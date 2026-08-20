import { useEffect, useState } from "react";
import { fetchTraces, type Trace, type TraceList } from "../api";

/**
 * Every question the system has answered, and the retrieval behind it.
 *
 * A RAG system fails in ways that look identical from outside — the retriever
 * missed it, the context was truncated, the model ignored what it was given.
 * Expanding a trace shows which of those happened.
 */
export function TracesPane() {
  const [data, setData] = useState<TraceList | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    fetchTraces().then(setData).catch(() => setData(null));
  }, []);

  if (!data) {
    return <p className="px-9 pt-[30px] font-mono text-[10.5px] text-faint">Loading…</p>;
  }

  if (data.stats.total === 0) {
    return (
      <div className="px-9 pt-[30px] max-w-[520px] flex flex-col gap-3">
        <h2 className="text-[23px] font-semibold tracking-[-0.02em]">No queries yet.</h2>
        <p className="font-text text-[15px] leading-[1.65] text-muted">
          Every question is recorded here with the excerpts that were retrieved, their scores,
          and how long each stage took.
        </p>
      </div>
    );
  }

  const { stats } = data;
  return (
    <div className="px-9 pt-[30px] pb-8 flex flex-col gap-5 overflow-y-auto scroll-quiet">
      <header className="flex flex-col gap-2">
        <h2 className="text-[23px] font-semibold tracking-[-0.02em]">Queries</h2>
        <div className="font-mono flex gap-2.5 text-[9.5px] text-faint">
          <span>{stats.total} answered</span>
          <span>·</span>
          <span>{stats.refused} refused</span>
          <span>·</span>
          <span className={stats.with_invalid_citations > 0 ? "text-flag" : ""}>
            {stats.with_invalid_citations} with fabricated citations
          </span>
          {stats.p50_generation_ms !== null && (
            <>
              <span>·</span>
              <span>
                p50 {(stats.p50_generation_ms / 1000).toFixed(1)}s / p95{" "}
                {((stats.p95_generation_ms ?? 0) / 1000).toFixed(1)}s
              </span>
            </>
          )}
        </div>
      </header>

      <ul className="flex flex-col gap-1.5 max-w-[720px]">
        {data.traces.map((trace) => (
          <TraceRow
            key={trace.id}
            trace={trace}
            open={expanded === trace.id}
            onToggle={() => setExpanded(expanded === trace.id ? null : trace.id)}
          />
        ))}
      </ul>
    </div>
  );
}

function TraceRow({
  trace, open, onToggle,
}: {
  trace: Trace;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <li className="bg-white border border-line rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left px-4 py-3 flex flex-col gap-1.5 hover:bg-raised transition-colors"
      >
        <div className="flex justify-between items-baseline gap-3">
          <span className="font-text text-[14px] text-body leading-snug">{trace.question}</span>
          <span className="font-mono text-[9px] text-faint shrink-0">
            {trace.refused ? (
              <span className="text-flag">refused</span>
            ) : (
              `${(trace.generation_ms / 1000).toFixed(1)}s`
            )}
          </span>
        </div>
        <div className="font-mono flex gap-2 text-[9px] text-faint">
          <span>{trace.excerpt_count} excerpts</span>
          <span>·</span>
          <span>retrieve {trace.retrieval_ms}ms</span>
          {trace.top_similarity !== null && (
            <>
              <span>·</span>
              <span>top {trace.top_similarity.toFixed(2)}</span>
            </>
          )}
          {trace.filters_applied !== "none" && (
            <>
              <span>·</span>
              <span className="text-brand">{trace.filters_applied}</span>
            </>
          )}
          {trace.invalid_citations.length > 0 && (
            <>
              <span>·</span>
              <span className="text-flag">
                fabricated {trace.invalid_citations.join(", ")}
              </span>
            </>
          )}
        </div>
      </button>

      {open && (
        <div className="border-t border-line px-4 py-3 flex flex-col gap-3 bg-raised">
          <p className="font-text text-[13px] leading-[1.6] text-muted">{trace.answer}</p>

          {trace.retrieved.length > 0 && (
            <table className="w-full font-mono text-[9.5px]">
              <thead>
                <tr className="text-faint text-left">
                  <th className="font-medium pb-1">#</th>
                  <th className="font-medium pb-1">meeting</th>
                  <th className="font-medium pb-1 text-right">vec</th>
                  <th className="font-medium pb-1 text-right">txt</th>
                  <th className="font-medium pb-1 text-right">sim</th>
                  <th className="font-medium pb-1 text-right">rrf</th>
                </tr>
              </thead>
              <tbody>
                {trace.retrieved.map((row) => (
                  <tr
                    key={row.chunk_id}
                    className={row.cited ? "text-brand-dark" : "text-soft"}
                  >
                    <td className="py-0.5">{row.index}</td>
                    <td className="py-0.5 truncate max-w-[220px]">{row.meeting}</td>
                    <td className="py-0.5 text-right">{row.vector_rank ?? "—"}</td>
                    <td className="py-0.5 text-right">{row.text_rank ?? "—"}</td>
                    <td className="py-0.5 text-right">{row.similarity?.toFixed(3) ?? "—"}</td>
                    <td className="py-0.5 text-right">{row.rrf.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <p className="font-mono text-[9px] text-faint">
            {trace.generation_model} · {trace.context_tokens} context tokens ·{" "}
            {new Date(trace.created_at).toLocaleString("en-GB")}
          </p>
        </div>
      )}
    </li>
  );
}
