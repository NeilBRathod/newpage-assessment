import { useEffect, useState } from "react";
import { fetchBrief, type Brief } from "../api";
import { GroundingMark } from "./GroundingMark";

/**
 * A meeting's brief: summary, decisions, action items.
 *
 * Not RAG — this is read from Postgres, extracted once by a constrained
 * decoding pass. Questions that have a structured answer should not be routed
 * through retrieval and generation every time they are asked.
 */
export function BriefPane({ meetingId }: { meetingId: string }) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBrief(null);
    setError(null);
    fetchBrief(meetingId)
      .then((b) => !cancelled && setBrief(b))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [meetingId]);

  if (error) {
    return (
      <div className="px-9 pt-[30px]">
        <p className="bg-flag-tint rounded-xl px-5 py-4 font-mono text-[10.5px] text-body">
          {error}
        </p>
      </div>
    );
  }

  if (!brief) {
    return (
      <div className="px-9 pt-[30px] flex flex-col gap-3">
        <p className="font-mono text-[10.5px] text-faint">Reading the transcript…</p>
        <p className="font-text text-[13px] text-faint max-w-[420px] leading-relaxed">
          The first brief for a meeting runs the model over the whole transcript, which takes
          about a minute locally. It is cached afterwards.
        </p>
      </div>
    );
  }

  return (
    <div className="px-9 pt-[30px] pb-8 flex flex-col gap-6 overflow-y-auto scroll-quiet">
      <header className="flex flex-col gap-2">
        <h2 className="text-[23px] font-semibold leading-[1.3] tracking-[-0.02em] max-w-[600px]">
          {brief.meeting.title}
        </h2>
        <div className="font-mono flex gap-2.5 text-[9.5px] text-faint">
          <span>{brief.meeting.meeting_date ?? "undated"}</span>
          <span>·</span>
          <span>{brief.meeting.participants.length} participants</span>
          <span>·</span>
          <span>{brief.meeting.utterance_count} turns</span>
          <span>·</span>
          <span className={brief.grounded_count === brief.total_count ? "text-brand" : "text-flag"}>
            {brief.grounded_count}/{brief.total_count} traced to a turn
          </span>
        </div>
      </header>

      <p className="font-text text-[15px] leading-[1.68] text-body max-w-[640px]">
        {brief.summary}
      </p>

      <Section title="Decisions" count={brief.decisions.length} empty="Nothing was settled.">
        {brief.decisions.map((decision) => (
          <li
            key={decision.id}
            className="bg-white border border-line rounded-xl px-4 py-3 flex flex-col gap-2"
          >
            <p className="font-text text-[14px] leading-[1.55] text-body">{decision.text}</p>
            <div className="flex items-baseline gap-2">
              <GroundingMark
                speaker={decision.speaker}
                startS={decision.start_s}
                grounded={decision.utterance_seq !== null}
              />
              {decision.quote && (
                <p className="font-text text-[11.5px] text-faint italic truncate">
                  “{decision.quote}”
                </p>
              )}
            </div>
          </li>
        ))}
      </Section>

      <Section
        title="Action items"
        count={brief.action_items.length}
        empty="Nobody committed to anything."
      >
        {brief.action_items.map((item) => (
          <li
            key={item.id}
            className="bg-white border border-line rounded-xl px-4 py-3 flex flex-col gap-2"
          >
            <div className="flex justify-between items-baseline gap-3">
              <p className="font-text text-[14px] leading-[1.55] text-body">{item.description}</p>
              {item.due && (
                <span className="font-mono text-[9px] text-brand-dark bg-brand-tint
                                 px-2 py-0.5 rounded-full shrink-0">
                  {item.due}
                </span>
              )}
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-[11.5px] font-semibold text-ink">{item.owner}</span>
              <GroundingMark
                speaker={item.speaker}
                startS={item.start_s}
                grounded={item.utterance_seq !== null}
                omitSpeaker={item.speaker === item.owner}
              />
            </div>
          </li>
        ))}
      </Section>
    </div>
  );
}

function Section({
  title, count, empty, children,
}: {
  title: string;
  count: number;
  empty: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2.5 max-w-[640px]">
      <h3 className="font-mono text-[9.5px] font-medium tracking-[0.09em] uppercase text-faint">
        {title} {count > 0 && `· ${count}`}
      </h3>
      {count === 0 ? (
        // An empty section is a real finding, not a gap to apologise for.
        <p className="font-text text-[13px] text-faint">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-2">{children}</ul>
      )}
    </section>
  );
}
