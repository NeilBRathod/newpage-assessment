import { useEffect, useRef, useState } from "react";
import { fetchTranscript, type Excerpt, type Transcript } from "../api";
import { formatClock } from "../lib/answer";

interface Props {
  excerpts: Excerpt[];
  citedIndices: number[];
  activeChunkId: string | null;
  onSelect: (excerpt: Excerpt) => void;
  refused: boolean;
  topSimilarity: number | null;
  minScore: number;
}

/**
 * Shows every excerpt the retriever returned, not just the cited one.
 *
 * Seeing what was retrieved and *not* used is most of what auditing an answer
 * means — it is the difference between "the model found nothing better" and
 * "the model ignored something better".
 */
export function EvidencePanel({
  excerpts, citedIndices, activeChunkId, onSelect, refused, topSimilarity, minScore,
}: Props) {
  const active = excerpts.find((e) => e.chunk_id === activeChunkId) ?? null;
  const others = excerpts.filter((e) => e.chunk_id !== active?.chunk_id);

  return (
    <aside className="w-[396px] shrink-0 bg-white border-l border-line flex flex-col overflow-hidden">
      <header className="px-[18px] pt-[18px] pb-3 flex justify-between items-baseline">
        <h2 className="text-[13px] font-semibold">Evidence</h2>
        <span className="font-mono text-[9.5px] text-faint">
          {refused ? "none above floor" : `${excerpts.length} retrieved`}
        </span>
      </header>

      {refused ? (
        <RefusalEvidence topSimilarity={topSimilarity} minScore={minScore} />
      ) : excerpts.length === 0 ? (
        <p className="px-[18px] py-8 text-[13px] text-faint leading-relaxed">
          Ask a question and the excerpts behind the answer appear here.
        </p>
      ) : (
        <div className="flex flex-col overflow-y-auto scroll-quiet pb-4">
          {active && (
            <div className="px-3.5 pb-3">
              <PinnedExcerpt
                excerpt={active}
                cited={citedIndices.includes(active.index)}
              />
            </div>
          )}

          {others.length > 0 && (
            <>
              <p className="px-[18px] pb-[7px] font-mono text-[8.5px] font-medium
                            tracking-[0.09em] uppercase text-faint">
                {citedIndices.length > 0 ? "Also retrieved" : "Retrieved"}
              </p>
              <div className="px-3.5 flex flex-col gap-1">
                {others.map((excerpt) => (
                  <CompactExcerpt
                    key={excerpt.chunk_id}
                    excerpt={excerpt}
                    cited={citedIndices.includes(excerpt.index)}
                    onClick={() => onSelect(excerpt)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </aside>
  );
}

function PinnedExcerpt({ excerpt, cited }: { excerpt: Excerpt; cited: boolean }) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const firstCitedTurn = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTranscript(null);
    fetchTranscript(excerpt.meeting_id)
      .then((t) => !cancelled && setTranscript(t))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [excerpt.meeting_id]);

  // Land on the turn the excerpt starts at rather than the context line above it.
  useEffect(() => {
    firstCitedTurn.current?.scrollIntoView({ block: "start" });
  }, [transcript, excerpt.chunk_id]);

  // The turns this excerpt was built from, plus one either side for context —
  // a quoted line reads differently without what prompted it.
  const seqs = excerpt.utterance_seqs;
  const turns = transcript?.utterances.filter(
    (u) => u.seq >= Math.min(...seqs) - 1 && u.seq <= Math.max(...seqs) + 1,
  );

  return (
    <div className="border-[1.5px] border-brand rounded-xl overflow-hidden">
      <div className="bg-brand-tint px-3.5 py-2.5 flex flex-col gap-1">
        <div className="flex justify-between items-baseline">
          <span className="font-mono text-[8.5px] font-medium tracking-[0.08em] uppercase text-brand-dark">
            {cited ? "Cited above" : "Selected"}
          </span>
          <span className="font-mono text-[9px] text-brand-dark/70">
            rank {excerpt.vector_rank ?? excerpt.text_rank ?? "—"}
            {excerpt.vector_similarity !== null &&
              ` · ${excerpt.vector_similarity.toFixed(2)}`}
          </span>
        </div>
        <p className="text-[13px] font-semibold text-ink">{excerpt.meeting_title}</p>
        <p className="font-mono text-[9px] text-brand-dark/70">
          {excerpt.meeting_date ?? "undated"} · {formatClock(excerpt.start_s)}–
          {formatClock(excerpt.end_s)}
        </p>
      </div>

      {/* Chunks run to a median of 12 turns, which would push the rest of the
          retrieved stack far below the fold. Capped and scrolled to the excerpt
          itself, so nothing is hidden but the list below stays reachable. */}
      <div className="flex flex-col max-h-[330px] overflow-y-auto scroll-quiet">
        {turns
          ? turns.map((turn) => {
              const inExcerpt = seqs.includes(turn.seq);
              return (
                <div
                  key={turn.seq}
                  ref={inExcerpt && turn.seq === seqs[0] ? firstCitedTurn : undefined}
                  className={`px-3.5 py-2.5 flex flex-col gap-1 ${
                    inExcerpt ? "bg-brand-wash" : "bg-white"
                  }`}
                >
                  <div className="flex gap-2 items-baseline">
                    <span
                      className={`text-[10.5px] font-semibold ${
                        inExcerpt ? "text-brand" : "text-faint"
                      }`}
                    >
                      {turn.speaker}
                    </span>
                    <span className="font-mono text-[8.5px] text-faint">
                      {formatClock(turn.start_s)}
                    </span>
                  </div>
                  <p
                    className={`font-text text-[12.5px] leading-[1.5] ${
                      inExcerpt ? "text-ink" : "text-soft"
                    }`}
                  >
                    {turn.text}
                  </p>
                </div>
              );
            })
          : // Falls back to the excerpt's own text if the transcript is still
            // loading, so the panel is never empty.
            excerpt.text.split("\n").map((line, i) => (
              <p key={i} className="px-3.5 py-1.5 font-text text-[12.5px] leading-[1.5] text-soft">
                {line}
              </p>
            ))}
      </div>
    </div>
  );
}

function CompactExcerpt({
  excerpt, cited, onClick,
}: {
  excerpt: Excerpt;
  cited: boolean;
  onClick: () => void;
}) {
  const similarity = excerpt.vector_similarity;
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left px-3 py-2.5 rounded-[10px] bg-raised hover:bg-line/60
                 transition-colors flex flex-col gap-1.5"
    >
      <div className="flex justify-between items-baseline gap-2">
        <span className="text-[11.5px] font-medium text-body">{excerpt.meeting_title}</span>
        <span className="font-mono text-[8.5px] text-faint shrink-0">
          {cited && <span className="text-flag mr-1">cited</span>}
          {excerpt.index} · {similarity !== null ? similarity.toFixed(2) : "—"}
        </span>
      </div>
      <p className="font-text text-[11.5px] leading-[1.45] text-soft line-clamp-2">
        {excerpt.text.replace(/\n/g, " ")}
      </p>
      <div className="h-[2px] bg-line rounded-sm overflow-hidden">
        <div
          className="h-[2px] bg-brand-mid"
          style={{ width: `${Math.round((similarity ?? 0) * 100)}%` }}
        />
      </div>
    </button>
  );
}

function RefusalEvidence({
  topSimilarity, minScore,
}: {
  topSimilarity: number | null;
  minScore: number;
}) {
  const best = topSimilarity ?? 0;
  return (
    <div className="px-[22px] py-6 flex flex-col gap-[15px] items-start">
      <svg
        width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#c8c8c8"
        strokeWidth="1.5" strokeLinecap="round" aria-hidden
      >
        <circle cx="11" cy="11" r="7" />
        <path d="M16 16l4.5 4.5" />
        <path d="M8.4 11h5.2" />
      </svg>
      <p className="font-text text-[14px] leading-[1.55] text-muted">
        Nothing cleared the relevance floor, so there is no source to show.
      </p>

      <div className="w-full bg-raised rounded-[10px] px-3.5 py-3 flex flex-col gap-2">
        <div className="font-mono flex justify-between text-[9.5px] text-soft">
          <span>best match</span>
          <span className="text-flag font-medium">{best.toFixed(2)}</span>
        </div>
        <div className="relative h-[3px] bg-line rounded-sm">
          <div
            className="h-[3px] bg-flag-mid rounded-sm"
            style={{ width: `${Math.min(100, best * 100)}%` }}
          />
          <span
            className="absolute -top-[3px] w-[1.5px] h-[9px] bg-body"
            style={{ left: `${Math.min(100, minScore * 100)}%` }}
            aria-label={`floor ${minScore}`}
          />
        </div>
        <div className="font-mono flex justify-between text-[9.5px] text-soft">
          <span>floor</span>
          <span>{minScore.toFixed(2)}</span>
        </div>
      </div>

      <p className="font-mono text-[9px] leading-[1.6] text-faint">
        The model was never called.
        <br />
        The refusal is deterministic.
      </p>
    </div>
  );
}
