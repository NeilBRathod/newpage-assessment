/**
 * Whether an extracted item could be traced back to a real turn.
 *
 * Shown rather than hidden. An item whose quote does not appear anywhere in the
 * transcript is the one a reader should look at hardest, so it gets the loud
 * treatment — the same orange used for refusals, meaning "pay attention".
 */
export function GroundingMark({
  speaker, startS, grounded, omitSpeaker,
}: {
  speaker: string | null;
  startS: number | null;
  grounded: boolean;
  /** Set when the speaker is already shown alongside, e.g. an item's owner. */
  omitSpeaker?: boolean;
}) {
  if (!grounded) {
    return (
      <span
        className="font-mono text-[9px] text-flag bg-flag-tint px-1.5 py-0.5 rounded-full"
        title="The quote for this item does not appear in the transcript."
      >
        unverified
      </span>
    );
  }
  const clock =
    startS === null
      ? ""
      : `${String(Math.floor(startS / 60)).padStart(2, "0")}:${String(
          Math.floor(startS % 60),
        ).padStart(2, "0")}`;
  // Where the owner said the thing themselves, repeating the name twice on one
  // line is noise; the timestamp is the part that adds anything.
  if (omitSpeaker) {
    return <span className="font-mono text-[9px] text-faint">said this · {clock}</span>;
  }
  return (
    <span className="font-mono text-[9px] text-faint">
      {speaker}
      {clock && ` · ${clock}`}
    </span>
  );
}
