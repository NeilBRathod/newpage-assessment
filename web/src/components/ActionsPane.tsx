import { useEffect, useState } from "react";
import { fetchActions, type ActionBoard } from "../api";
import { initials } from "../lib/answer";
import { GroundingMark } from "./GroundingMark";

/**
 * Every commitment across every meeting, grouped by who owns it.
 *
 * This is the view a chat interface is bad at. "What did I agree to?" is a
 * query, not a question — routing it through retrieval and generation would be
 * slower, less complete, and less trustworthy than reading the rows.
 */
export function ActionsPane({ onOpenMeeting }: { onOpenMeeting: (id: string) => void }) {
  const [board, setBoard] = useState<ActionBoard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchActions()
      .then(setBoard)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <div className="px-9 pt-[30px]">
        <p className="bg-flag-tint rounded-xl px-5 py-4 font-mono text-[10.5px] text-body">
          {error}
        </p>
      </div>
    );
  }

  if (!board) {
    return <p className="px-9 pt-[30px] font-mono text-[10.5px] text-faint">Loading…</p>;
  }

  if (board.total === 0) {
    return (
      <div className="px-9 pt-[30px] flex flex-col gap-3 max-w-[520px]">
        <h2 className="text-[23px] font-semibold tracking-[-0.02em]">No action items yet.</h2>
        <p className="font-text text-[15px] leading-[1.65] text-muted">
          Action items come from the per-meeting briefs, and briefs are extracted on first
          view. Open a meeting’s brief and its commitments appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="px-9 pt-[30px] pb-8 flex flex-col gap-6 overflow-y-auto scroll-quiet">
      <header className="flex flex-col gap-2">
        <h2 className="text-[23px] font-semibold tracking-[-0.02em]">Who owes what</h2>
        <div className="font-mono flex gap-2.5 text-[9.5px] text-faint">
          <span>{board.total} commitments</span>
          <span>·</span>
          <span>{board.owners.length} people</span>
          {board.ungrounded > 0 && (
            <>
              <span>·</span>
              <span className="text-flag">{board.ungrounded} unverified</span>
            </>
          )}
        </div>
      </header>

      <div className="flex flex-col gap-5 max-w-[680px]">
        {board.owners.map(({ owner, items }) => (
          <section key={owner} className="flex flex-col gap-2">
            <div className="flex items-center gap-2.5">
              <span className="w-[22px] h-[22px] rounded-full bg-brand-tint text-brand-dark
                               font-mono text-[8.5px] font-medium flex items-center justify-center">
                {initials(owner)}
              </span>
              <h3 className="text-[14px] font-semibold">{owner}</h3>
              <span className="font-mono text-[9px] text-faint">{items.length}</span>
            </div>

            <ul className="flex flex-col gap-1.5 pl-[32px]">
              {items.map((item) => (
                <li
                  key={item.id}
                  className="bg-white border border-line rounded-xl px-4 py-3 flex flex-col gap-2"
                >
                  <div className="flex justify-between items-baseline gap-3">
                    <p className="font-text text-[14px] leading-[1.55] text-body">
                      {item.description}
                    </p>
                    {item.due && (
                      <span className="font-mono text-[9px] text-brand-dark bg-brand-tint
                                       px-2 py-0.5 rounded-full shrink-0">
                        {item.due}
                      </span>
                    )}
                  </div>
                  <div className="flex items-baseline gap-2.5">
                    <button
                      type="button"
                      onClick={() => onOpenMeeting(item.meeting_id)}
                      className="font-mono text-[9px] text-soft hover:text-brand transition-colors"
                    >
                      {item.meeting_title}
                    </button>
                    <GroundingMark
                      speaker={item.speaker}
                      startS={item.start_s}
                      grounded={item.utterance_seq !== null}
                      omitSpeaker={item.speaker === item.owner}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
