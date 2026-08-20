import type { Excerpt } from "../api";

/**
 * The model writes citations inline — "the decision was reversed [2]" — but the
 * design puts provenance in the margin beside each claim. This module is the
 * bridge: it splits an answer into blocks, lifts each block's citations out of
 * the prose, and hands back the sources that belong next to it.
 *
 * Doing this in the client rather than asking the model for structured output
 * is deliberate. A 12B model emits prose with brackets far more reliably than
 * it emits well-formed JSON, and a parse failure here degrades to "no margin
 * entry" rather than to a failed answer.
 */

export interface AnswerBlock {
  kind: "paragraph" | "bullet";
  text: string;
  /** Citation indices, in the order the model wrote them. */
  citations: number[];
}

// Matches "[2]", "[1, 4]" and "[1,4]" — models group references interchangeably.
const CITATION = /\[\s*(\d{1,2}(?:\s*,\s*\d{1,2})*)\s*\]/g;
const BULLET = /^\s*[*-]\s+/;

export function parseAnswer(answer: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];

  for (const raw of answer.split(/\n{2,}|\n(?=\s*[*-]\s)/)) {
    const line = raw.trim();
    if (!line) continue;

    const citations: number[] = [];
    for (const match of line.matchAll(CITATION)) {
      for (const part of match[1].split(",")) {
        const index = Number(part.trim());
        if (!citations.includes(index)) citations.push(index);
      }
    }

    const kind = BULLET.test(line) ? "bullet" : "paragraph";
    const text = line
      .replace(CITATION, "")
      .replace(BULLET, "")
      // Removing a marker leaves a space before the full stop it preceded.
      .replace(/\s+([.,;:])/g, "$1")
      .replace(/[ \t]{2,}/g, " ")
      .trim();

    if (text) blocks.push({ kind, text, citations });
  }

  return blocks;
}

export interface MarginSource {
  meetingTitle: string;
  meetingId: string;
  speakers: string;
  times: string;
  excerpts: Excerpt[];
}

/**
 * Collapse a block's citations into one margin entry per meeting.
 *
 * Two citations from the same meeting read as one source with two timestamps,
 * not two sources — which is both truer and shorter.
 */
export function marginSources(
  citations: number[],
  excerpts: Excerpt[],
): MarginSource[] {
  const byMeeting = new Map<string, Excerpt[]>();

  for (const index of citations) {
    // Citations are 1-based and validated server-side, but a stray index must
    // not throw here.
    const excerpt = excerpts[index - 1];
    if (!excerpt) continue;
    const existing = byMeeting.get(excerpt.meeting_id);
    if (existing) existing.push(excerpt);
    else byMeeting.set(excerpt.meeting_id, [excerpt]);
  }

  return [...byMeeting.values()].map((group) => ({
    meetingTitle: group[0].meeting_title,
    meetingId: group[0].meeting_id,
    speakers: speakerLabel(group),
    times: group.map((e) => formatClock(e.start_s)).join(" · "),
    excerpts: group,
  }));
}

/**
 * A name here, or an honest count.
 *
 * An excerpt spans several turns, so its speaker list is who was present in the
 * passage — not who made the claim being cited. Printing "Marcus Webb +4"
 * beside a sentence reads as attribution, and attributing a statement to
 * someone who did not make it is the worst failure this product can have. A
 * name is therefore shown only when the excerpt has exactly one speaker, where
 * the attribution is unambiguous; otherwise it degrades to a count.
 */
function speakerLabel(excerpts: Excerpt[]): string {
  const names = [...new Set(excerpts.flatMap((e) => e.speakers))];
  if (names.length === 1) return names[0];
  return `${names.length} speakers`;
}

/** mm:ss, or h:mm:ss past an hour. */
export function formatClock(seconds: number): string {
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

/** Initials for the participant chips in the meeting rail. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Minimal inline formatting: **bold** only.
 *
 * Returns segments rather than HTML so React renders them as elements — model
 * output never reaches dangerouslySetInnerHTML.
 */
export function inlineSegments(text: string): { bold: boolean; text: string }[] {
  const segments: { bold: boolean; text: string }[] = [];
  const pattern = /\*\*([^*]+)\*\*/g;
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > cursor) segments.push({ bold: false, text: text.slice(cursor, start) });
    segments.push({ bold: true, text: match[1] });
    cursor = start + match[0].length;
  }
  if (cursor < text.length) segments.push({ bold: false, text: text.slice(cursor) });

  return segments.length ? segments : [{ bold: false, text }];
}
