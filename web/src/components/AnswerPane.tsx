import type { AskResult, Excerpt } from "../api";
import { inlineSegments, marginSources, parseAnswer } from "../lib/answer";

interface Props {
  question: string;
  answer: string;
  excerpts: Excerpt[];
  streaming: boolean;
  result: AskResult | null;
  activeChunkId: string | null;
  onSelectSource: (excerpt: Excerpt) => void;
}

export function AnswerPane({
  question, answer, excerpts, streaming, result, activeChunkId, onSelectSource,
}: Props) {
  const blocks = parseAnswer(answer);
  const refused = result?.refused ?? false;

  return (
    <div className="px-9 pt-[30px] flex flex-col gap-5 overflow-y-auto scroll-quiet">
      <header className="flex flex-col gap-2">
        <h2 className="text-[23px] font-semibold leading-[1.32] tracking-[-0.02em] max-w-[600px]">
          {question}
        </h2>
        <Meta streaming={streaming} result={result} excerptCount={excerpts.length} />
      </header>

      <hr className="border-0 h-px bg-line" />

      {refused ? (
        <RefusalBody answer={answer} />
      ) : (
        <div className="font-text flex flex-col gap-[17px] pb-8">
          {blocks.map((block, index) => {
            const sources = marginSources(block.citations, excerpts);
            const isActive = sources.some((s) =>
              s.excerpts.some((e) => e.chunk_id === activeChunkId),
            );
            // The lead sentence carries no citation and reads as a summary, so
            // it sits flush rather than pretending to be an evidenced claim.
            const isLead = index === 0 && block.citations.length === 0;

            return (
              <article key={index} className="flex gap-[18px]">
                <div className="w-[138px] shrink-0 flex flex-col gap-2 items-end text-right pt-[3px]">
                  {sources.map((source) => (
                    <button
                      key={source.meetingId}
                      type="button"
                      onClick={() => onSelectSource(source.excerpts[0])}
                      className="flex flex-col gap-[3px] items-end group cursor-pointer"
                    >
                      <span
                        title={source.meetingTitle}
                        className={`font-mono text-[9.5px] font-medium leading-[1.35] line-clamp-2 ${
                          isActive ? "text-brand" : "text-soft group-hover:text-brand"
                        }`}
                      >
                        {source.meetingTitle}
                      </span>
                      <span className="font-mono text-[9px] text-faint leading-[1.35]">
                        {source.speakers}
                      </span>
                      <span className="font-mono text-[9px] text-faint">{source.times}</span>
                    </button>
                  ))}
                  {streaming && sources.length === 0 && !isLead && (
                    <span className="w-[52px] h-[7px] rounded bg-line" aria-hidden />
                  )}
                </div>

                <p
                  className={`pl-4 border-l-2 max-w-[470px] ${
                    isLead
                      ? "border-transparent text-[16px] leading-[1.6] font-medium text-ink"
                      : "text-[15px] leading-[1.65] text-body"
                  } ${
                    isActive ? "border-brand" : isLead ? "" : "border-line"
                  } ${block.kind === "bullet" ? "before:content-['—'] before:mr-2 before:text-faint" : ""}`}
                >
                  {inlineSegments(block.text).map((segment, i) =>
                    segment.bold ? (
                      <strong key={i} className="font-medium text-ink">{segment.text}</strong>
                    ) : (
                      <span key={i}>{segment.text}</span>
                    ),
                  )}
                  {streaming && index === blocks.length - 1 && (
                    <span
                      className="caret inline-block w-[7px] h-4 bg-brand rounded-[1px] ml-[3px] -mb-[3px]"
                      aria-label="writing"
                    />
                  )}
                </p>
              </article>
            );
          })}

          {streaming && blocks.length === 0 && (
            <p className="pl-[156px] text-[15px] text-faint">Reading the excerpts…</p>
          )}
        </div>
      )}
    </div>
  );
}

function Meta({
  streaming, result, excerptCount,
}: {
  streaming: boolean;
  result: AskResult | null;
  excerptCount: number;
}) {
  if (streaming) {
    return (
      <div className="font-mono flex gap-2.5 items-center text-[9.5px] text-faint">
        <span className="flex gap-[3px]" aria-hidden>
          <span className="w-1 h-1 rounded-full bg-brand" />
          <span className="w-1 h-1 rounded-full bg-brand-mid" />
          <span className="w-1 h-1 rounded-full bg-line-strong" />
        </span>
        {excerptCount > 0 && (
          <span className="text-brand font-medium">{excerptCount} excerpts retrieved</span>
        )}
        <span>·</span>
        <span>writing…</span>
      </div>
    );
  }

  if (!result) return null;

  if (result.refused) {
    return (
      <div className="font-mono flex gap-2.5 text-[9.5px] text-faint">
        <span>0 excerpts</span>
        <span>·</span>
        <span>{result.retrieval_ms}ms</span>
        <span>·</span>
        <span className="text-flag font-medium">refused before generating</span>
      </div>
    );
  }

  const meetings = new Set(result.excerpts.map((e) => e.meeting_id)).size;
  return (
    <div className="font-mono flex gap-2.5 text-[9.5px] text-faint">
      <span>{meetings} meeting{meetings === 1 ? "" : "s"}</span>
      <span>·</span>
      <span>{result.excerpts.length} excerpts</span>
      <span>·</span>
      <span>{(result.generation_ms / 1000).toFixed(1)}s</span>
      <span>·</span>
      {/* Teal means "source" everywhere else here, so it would read as
          approval on an answer that cited nothing. */}
      <span
        className={
          result.citations.length > 0 ? "text-brand font-medium" : "text-soft"
        }
      >
        {result.citations.length > 0 ? "every claim sourced" : "no sources cited"}
      </span>
    </div>
  );
}

/** A refusal is the system working, so it is styled as an answer — not an error. */
function RefusalBody({ answer }: { answer: string }) {
  return (
    <div className="max-w-[626px] flex flex-col gap-[22px] pb-8">
      <div className="bg-flag-tint rounded-xl px-5 py-[17px] flex gap-3">
        <svg
          width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#ff7f1f"
          strokeWidth="1.8" strokeLinecap="round" className="shrink-0 mt-0.5" aria-hidden
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7.5v5" />
          <path d="M12 16.2v.2" />
        </svg>
        <p className="font-text text-[15px] leading-[1.6] text-body">{answer}</p>
      </div>
    </div>
  );
}
