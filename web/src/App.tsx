import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  askStream, fetchHealth, fetchMeetings,
  type AskResult, type Excerpt, type Health, type Meeting,
} from "./api";
import { AnswerPane } from "./components/AnswerPane";
import { AskBar } from "./components/AskBar";
import { EmptyState } from "./components/EmptyState";
import { EvidencePanel } from "./components/EvidencePanel";
import { ActionsPane } from "./components/ActionsPane";
import { BriefPane } from "./components/BriefPane";
import { MeetingRail } from "./components/MeetingRail";

// Mirrors MEETINGIQ_MIN_RETRIEVAL_SCORE. Display only — the server owns the
// decision; this just labels the axis on the refusal chart.
const MIN_RETRIEVAL_SCORE = 0.2;

type View = "ask" | "brief" | "actions";

export default function App() {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [excerpts, setExcerpts] = useState<Excerpt[]>([]);
  const [result, setResult] = useState<AskResult | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  const [activeChunkId, setActiveChunkId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [filter, setFilter] = useState<"all" | "cited">("all");
  const [view, setView] = useState<View>("ask");
  const [briefMeetingId, setBriefMeetingId] = useState<string | null>(null);

  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    Promise.all([fetchMeetings(), fetchHealth()])
      .then(([m, h]) => {
        setMeetings(m);
        setHealth(h);
      })
      .catch((error) => setLoadError(error instanceof Error ? error.message : String(error)));
  }, []);

  // Abort an in-flight generation if the component goes away.
  useEffect(() => () => abortRef.current?.(), []);

  const ask = useCallback(
    (asked: string) => {
      setQuestion(asked);
      setAnswer("");
      setExcerpts([]);
      setResult(null);
      setAskError(null);
      setActiveChunkId(null);
      setStreaming(true);
      setFilter("all");
      setView("ask");

      abortRef.current = askStream(asked, selectedIds, {
        onExcerpts: (received) => {
          setExcerpts(received);
          // Pin the top excerpt immediately: the evidence panel should be
          // readable long before the answer finishes.
          setActiveChunkId(received[0]?.chunk_id ?? null);
        },
        onToken: (text) => setAnswer((current) => current + text),
        onRefusal: (payload) => setAnswer(payload.answer),
        onDone: (finished) => {
          // The streamed text is unaudited; the final payload has had invalid
          // citations stripped, so it replaces what was streamed.
          setAnswer(finished.answer);
          setResult(finished);
          setExcerpts(finished.excerpts);
          setStreaming(false);
          abortRef.current = null;
          if (finished.excerpts.length > 0) {
            const firstCited = finished.excerpts.find((e) =>
              finished.citations.includes(e.index),
            );
            setActiveChunkId((firstCited ?? finished.excerpts[0]).chunk_id);
          }
        },
        onError: (message) => {
          setAskError(message);
          setStreaming(false);
          abortRef.current = null;
        },
      });
    },
    [selectedIds],
  );

  const stop = useCallback(() => {
    abortRef.current?.();
    abortRef.current = null;
    setStreaming(false);
  }, []);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );
  }, []);

  const openBrief = useCallback((id: string) => {
    setBriefMeetingId(id);
    setView("brief");
  }, []);

  const { citedMeetingIds, citationCounts } = useMemo(() => {
    const ids = new Set<string>();
    const counts = new Map<string, number>();
    const cited = result?.citations ?? [];
    for (const excerpt of excerpts) {
      if (!cited.includes(excerpt.index)) continue;
      ids.add(excerpt.meeting_id);
      counts.set(excerpt.meeting_id, (counts.get(excerpt.meeting_id) ?? 0) + 1);
    }
    return { citedMeetingIds: ids, citationCounts: counts };
  }, [excerpts, result]);

  const totals = useMemo(() => {
    const list = meetings ?? [];
    return {
      utterances: list.reduce((sum, m) => sum + m.utterance_count, 0),
      speakers: new Set(list.flatMap((m) => m.participants)).size,
    };
  }, [meetings]);

  const degraded = useMemo(() => {
    if (!health || health.status === "ok") return null;
    return Object.entries(health.checks)
      .filter(([, check]) => !check.ok)
      .map(([name, check]) => `${name}: ${check.detail}`)
      .join("\n");
  }, [health]);

  if (loadError) {
    return (
      <main className="h-full flex items-center justify-center px-10">
        <div className="max-w-[460px] flex flex-col gap-3">
          <h1 className="text-[21px] font-semibold">The API isn’t reachable.</h1>
          <p className="font-text text-[15px] leading-relaxed text-muted">
            Nothing responded at <code className="font-mono text-[13px]">{loadError}</code>.
            Start it with <code className="font-mono text-[13px] text-brand-dark">make up</code>{" "}
            and <code className="font-mono text-[13px] text-brand-dark">make api</code>.
          </p>
        </div>
      </main>
    );
  }

  if (!meetings) {
    return (
      <main className="h-full flex items-center justify-center">
        <p className="font-mono text-[11px] text-faint">Loading…</p>
      </main>
    );
  }

  if (meetings.length === 0) return <EmptyState degraded={degraded} />;

  const asked = question !== "";

  return (
    <main className="h-full flex overflow-hidden">
      <MeetingRail
        meetings={meetings}
        citedMeetingIds={citedMeetingIds}
        citationCounts={citationCounts}
        selectedIds={selectedIds}
        filter={filter}
        onFilterChange={setFilter}
        onToggleSelect={toggleSelect}
        onOpenBrief={openBrief}
        totalUtterances={totals.utterances}
        totalSpeakers={totals.speakers}
      />

      <section className="flex-grow flex flex-col overflow-hidden">
        <Tabs
          view={view}
          onChange={setView}
          briefTitle={
            briefMeetingId
              ? (meetings.find((m) => m.id === briefMeetingId)?.title ?? null)
              : null
          }
        />

        {view === "actions" ? (
          <ActionsPane
            onOpenMeeting={(id) => {
              setBriefMeetingId(id);
              setView("brief");
            }}
          />
        ) : view === "brief" && briefMeetingId ? (
          <BriefPane meetingId={briefMeetingId} />
        ) : asked ? (
          <AnswerPane
            question={question}
            answer={answer}
            excerpts={excerpts}
            streaming={streaming}
            result={result}
            activeChunkId={activeChunkId}
            onSelectSource={(excerpt) => setActiveChunkId(excerpt.chunk_id)}
          />
        ) : (
          <Opening degraded={degraded} meetingCount={meetings.length} />
        )}

        {view === "ask" && askError && (
          <p className="mx-9 mb-2 bg-flag-tint rounded-xl px-4 py-3 font-mono
                        text-[10.5px] text-body">
            {askError}
          </p>
        )}

        {view === "ask" && (
          <AskBar
            streaming={streaming}
            disabled={Boolean(degraded) && !asked}
            selectedCount={selectedIds.length}
            onAsk={ask}
            onStop={stop}
          />
        )}
      </section>

      {view === "ask" && (
        <EvidencePanel
          excerpts={excerpts}
          citedIndices={result?.citations ?? []}
          activeChunkId={activeChunkId}
          onSelect={(excerpt) => setActiveChunkId(excerpt.chunk_id)}
          refused={result?.refused ?? false}
          topSimilarity={result?.top_similarity ?? null}
          minScore={MIN_RETRIEVAL_SCORE}
        />
      )}
    </main>
  );
}

/** Meetings are loaded but nothing has been asked yet. */
function Opening({ degraded, meetingCount }: { degraded: string | null; meetingCount: number }) {
  return (
    <div className="px-9 pt-[30px] flex flex-col gap-5 overflow-y-auto scroll-quiet">
      <h2 className="text-[26px] font-semibold tracking-[-0.02em] leading-[1.25] max-w-[560px]">
        {meetingCount} meetings, indexed and ready.
      </h2>
      <p className="font-text text-[15px] leading-[1.65] text-muted max-w-[520px]">
        Every answer cites the speaker and timestamp it came from. Ask something that spans
        meetings — the interesting questions usually do.
      </p>

      <div className="flex flex-col gap-2 max-w-[560px]">
        <p className="font-mono text-[9.5px] font-medium tracking-[0.09em] uppercase text-faint">
          Try
        </p>
        {[
          "Did we change our mind about building on the existing ledger?",
          "What caused the June incident and what did we commit to fixing?",
          "What has Meridian asked for that we still haven’t built?",
        ].map((example) => (
          <p
            key={example}
            className="font-text text-[14px] text-body bg-white border border-line
                       rounded-[10px] px-3.5 py-2.5"
          >
            {example}
          </p>
        ))}
      </div>

      {degraded && (
        <pre className="bg-flag-tint rounded-xl px-5 py-4 font-mono text-[10.5px]
                        leading-[1.6] text-body whitespace-pre-wrap max-w-[560px]">
          {degraded}
        </pre>
      )}
    </div>
  );
}

/** Ask, Brief, Actions. The brief tab only exists once a meeting is chosen. */
function Tabs({
  view, onChange, briefTitle,
}: {
  view: View;
  onChange: (view: View) => void;
  briefTitle: string | null;
}) {
  const tabs: { id: View; label: string; enabled: boolean }[] = [
    { id: "ask", label: "Ask", enabled: true },
    { id: "brief", label: briefTitle ? "Brief" : "Brief", enabled: briefTitle !== null },
    { id: "actions", label: "Actions", enabled: true },
  ];

  return (
    <nav className="px-9 pt-5 flex gap-1 border-b border-line -mb-px">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          disabled={!tab.enabled}
          onClick={() => onChange(tab.id)}
          title={tab.id === "brief" && briefTitle ? briefTitle : undefined}
          className={`text-[12.5px] font-medium px-3 py-2 border-b-2 -mb-px transition-colors ${
            view === tab.id
              ? "border-brand text-ink"
              : tab.enabled
                ? "border-transparent text-soft hover:text-body"
                : "border-transparent text-line-strong cursor-not-allowed"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
