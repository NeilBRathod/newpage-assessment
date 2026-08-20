export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Check {
  ok: boolean;
  detail: string;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  checks: Record<string, Check>;
}

export interface Meeting {
  id: string;
  title: string;
  meeting_date: string | null;
  participants: string[];
  duration_s: number | null;
  utterance_count: number;
  chunk_count: number;
  source_format: string;
}

export interface Utterance {
  seq: number;
  speaker: string;
  start_s: number;
  end_s: number;
  text: string;
}

export interface Transcript {
  meeting: Meeting;
  utterances: Utterance[];
}

export interface Excerpt {
  index: number;
  chunk_id: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string | null;
  speakers: string[];
  start_s: number;
  end_s: number;
  utterance_seqs: number[];
  text: string;
  vector_rank: number | null;
  text_rank: number | null;
  vector_similarity: number | null;
  rrf_score: number;
}

export interface AskResult {
  question: string;
  answer: string;
  refused: boolean;
  refusal_reason: string | null;
  citations: number[];
  excerpts: Excerpt[];
  filters_applied: string;
  top_similarity: number | null;
  retrieval_ms: number;
  generation_ms: number;
}

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return (await response.json()) as T;
}

export const fetchHealth = () => getJSON<Health>("/health");
export const fetchMeetings = () => getJSON<Meeting[]>("/meetings");
export const fetchTranscript = (id: string) => getJSON<Transcript>(`/meetings/${id}/transcript`);

export interface AskHandlers {
  onExcerpts: (excerpts: Excerpt[]) => void;
  onToken: (text: string) => void;
  onRefusal: (payload: { answer: string; reason: string }) => void;
  onDone: (result: AskResult) => void;
  onError: (message: string) => void;
}

/**
 * Stream an answer over Server-Sent Events.
 *
 * Hand-rolled rather than using EventSource because that API is GET-only and
 * the question goes in a POST body. The parsing below is the SSE framing we
 * actually emit — blank-line-delimited `event:`/`data:` pairs — not the full
 * specification.
 *
 * Returns an abort function: a 40-second local generation the user cannot
 * cancel is a trap.
 */
export function askStream(
  question: string,
  meetingIds: string[],
  handlers: AskHandlers,
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, meeting_ids: meetingIds, stream: true }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        throw new Error(`${response.status} ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // A chunk can split mid-event, so only whole blocks are consumed and
        // the remainder is left in the buffer.
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";

        for (const block of blocks) {
          if (!block.trim()) continue;
          const lines = block.split("\n");
          const event = lines.find((l) => l.startsWith("event: "))?.slice(7);
          const data = lines.find((l) => l.startsWith("data: "))?.slice(6);
          if (!event || !data) continue;

          const payload = JSON.parse(data);
          switch (event) {
            case "excerpts":
              handlers.onExcerpts(payload as Excerpt[]);
              break;
            case "token":
              handlers.onToken((payload as { text: string }).text);
              break;
            case "refusal":
              handlers.onRefusal(payload as { answer: string; reason: string });
              break;
            case "done":
              handlers.onDone(payload as AskResult);
              break;
            case "error":
              handlers.onError((payload as { message: string }).message);
              break;
          }
        }
      }
    } catch (error) {
      // Aborting is a user action, not a failure to report.
      if (error instanceof DOMException && error.name === "AbortError") return;
      handlers.onError(error instanceof Error ? error.message : String(error));
    }
  })();

  return () => controller.abort();
}
