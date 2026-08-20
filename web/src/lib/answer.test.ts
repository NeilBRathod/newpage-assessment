import { describe, expect, it } from "vitest";
import type { Excerpt } from "../api";
import {
  formatClock, initials, inlineSegments, marginSources, parseAnswer,
} from "./answer";

function excerpt(overrides: Partial<Excerpt> & { index: number }): Excerpt {
  return {
    chunk_id: `c${overrides.index}`,
    meeting_id: "m1",
    meeting_title: "Architecture Review",
    meeting_date: "2026-04-14",
    speakers: ["Dana Osei"],
    start_s: 25,
    end_s: 60,
    utterance_seqs: [1, 2],
    text: "Dana Osei: the p99 was four point two seconds.",
    vector_rank: 1,
    text_rank: null,
    vector_similarity: 0.45,
    rrf_score: 0.016,
    ...overrides,
  };
}

describe("parseAnswer", () => {
  it("lifts citations out of the prose", () => {
    const [block] = parseAnswer("The decision was reversed [2].");

    expect(block.text).toBe("The decision was reversed.");
    expect(block.citations).toEqual([2]);
  });

  it("parses grouped citations, which models write interchangeably", () => {
    expect(parseAnswer("Reversed [1, 4].")[0].citations).toEqual([1, 4]);
    expect(parseAnswer("Reversed [1,4].")[0].citations).toEqual([1, 4]);
  });

  it("does not leave a gap before punctuation", () => {
    expect(parseAnswer("Reversed [2] .")[0].text).toBe("Reversed.");
  });

  it("splits on blank lines", () => {
    const blocks = parseAnswer("First claim [1].\n\nSecond claim [2].");

    expect(blocks).toHaveLength(2);
    expect(blocks[1].citations).toEqual([2]);
  });

  it("treats markdown list items as their own blocks", () => {
    const blocks = parseAnswer("Timeline:\n* Decided [1]\n* Reversed [2]");

    expect(blocks).toHaveLength(3);
    expect(blocks[1].kind).toBe("bullet");
    expect(blocks[1].text).toBe("Decided");
  });

  it("keeps a block that cites nothing", () => {
    // The lead sentence is usually an uncited summary; dropping it would lose
    // the answer's opening line.
    const [block] = parseAnswer("Yes — the decision was reversed a week later.");

    expect(block.citations).toEqual([]);
    expect(block.text).toContain("Yes");
  });

  it("de-duplicates a citation repeated in one block", () => {
    expect(parseAnswer("Both [3] and again [3].")[0].citations).toEqual([3]);
  });

  it("returns nothing for an empty answer", () => {
    expect(parseAnswer("")).toEqual([]);
    expect(parseAnswer("   \n\n  ")).toEqual([]);
  });
});

describe("marginSources", () => {
  it("collapses two citations from one meeting into a single source", () => {
    const sources = marginSources(
      [1, 2],
      [excerpt({ index: 1, start_s: 25 }), excerpt({ index: 2, start_s: 215 })],
    );

    expect(sources).toHaveLength(1);
    expect(sources[0].times).toBe("00:25 · 03:35");
  });

  it("keeps separate meetings separate", () => {
    const sources = marginSources(
      [1, 2],
      [
        excerpt({ index: 1 }),
        excerpt({ index: 2, meeting_id: "m2", meeting_title: "Beta Go/No-Go" }),
      ],
    );

    expect(sources.map((s) => s.meetingTitle)).toEqual([
      "Architecture Review",
      "Beta Go/No-Go",
    ]);
  });

  it("names a speaker only when the excerpt has exactly one", () => {
    const sources = marginSources([1], [excerpt({ index: 1, speakers: ["Dana Osei"] })]);

    expect(sources[0].speakers).toBe("Dana Osei");
  });

  it("degrades to a count rather than implying who made the claim", () => {
    // An excerpt spans several turns; naming one of its speakers beside a
    // sentence reads as an attribution that was never established.
    const sources = marginSources(
      [1],
      [excerpt({ index: 1, speakers: ["Dana Osei", "Priya Raman", "Marcus Webb"] })],
    );

    expect(sources[0].speakers).toBe("3 speakers");
  });

  it("ignores a citation with no matching excerpt rather than throwing", () => {
    expect(marginSources([9], [excerpt({ index: 1 })])).toEqual([]);
  });
});

describe("formatClock", () => {
  it.each([
    [25, "00:25"],
    [215, "03:35"],
    [3725, "1:02:05"],
    [0, "00:00"],
  ])("formats %i as %s", (seconds, expected) => {
    expect(formatClock(seconds)).toBe(expected);
  });
});

describe("initials", () => {
  it("takes first and last initial", () => {
    expect(initials("Dana Osei")).toBe("DO");
    expect(initials("Elena Vasquez")).toBe("EV");
  });

  it("falls back to two letters for a single name", () => {
    expect(initials("Rafael")).toBe("RA");
  });
});

describe("inlineSegments", () => {
  it("splits bold runs out of plain text", () => {
    expect(inlineSegments("A **bold** claim")).toEqual([
      { bold: false, text: "A " },
      { bold: true, text: "bold" },
      { bold: false, text: " claim" },
    ]);
  });

  it("returns a single plain segment when there is no markup", () => {
    expect(inlineSegments("plain")).toEqual([{ bold: false, text: "plain" }]);
  });
});
