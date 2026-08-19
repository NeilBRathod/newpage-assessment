# Transcript formats

The parser accepts three formats. Supporting more than one is deliberate: real
transcripts arrive from Zoom, Google Meet, Otter, Fireflies and hand-typed
notes, and each has its own idea of how to write a timestamp. Committing to a
single house format would push that mess onto whoever is uploading.

Every format must yield the same thing — an ordered list of utterances, each
with a **speaker**, a **start time in seconds**, and **text** — because that
triple is what the chunker, the citations and the evidence panel all depend on.

---

## Format A — bracketed timestamp (primary)

Used by most of the seed corpus. A metadata header, then one utterance per line.

```
# Meeting: Relay Kickoff
# Date: 2026-04-07
# Duration: 00:52:10
# Participants: Priya Raman, Marcus Webb, Dana Osei

[00:00:04] Priya Raman: Right, let's get started.
[00:00:31] Marcus Webb: Thanks. So the goal today is to agree scope.
```

- Header lines begin `# Key: value` and are optional except `Meeting`.
  Missing `Date` falls back to the file's modification date; missing
  `Participants` is derived from the speakers actually present.
- Timestamps are `HH:MM:SS` or `MM:SS`.
- An utterance may wrap onto following lines; continuation lines carry no
  timestamp and are appended to the utterance above.

## Format B — parenthesised timestamp after the speaker

Common in exports that treat the speaker as the primary key.

```
Priya Raman (00:00:04): Right, let's get started.
Marcus Webb (0:31): Thanks. So the goal today is to agree scope.
```

No header block, so the meeting title comes from the filename and the date from
a `YYYY-MM-DD` prefix in it if present.

## Format C — WebVTT

The subtitle format Zoom and Meet both export. Speaker is encoded as a `Name:`
prefix inside the cue text.

```
WEBVTT

1
00:00:04.000 --> 00:00:29.500
Priya Raman: Right, let's get started.
```

The cue *end* time is kept — it is the only format that carries one, and it
makes the evidence panel's highlight range exact rather than inferred.

---

## What the parser guarantees

- Utterances come out in chronological order, renumbered from 0.
- Speaker names are trimmed and normalised for casing, but not otherwise
  altered — `Dana Osei` and `dana osei` collapse; `Dana` and `Dana Osei` do not,
  because guessing that they are the same person is a judgement the system
  should not silently make.
- Where a format has no end time, an utterance's end is the next utterance's
  start (and the last one gets the meeting duration, or its start plus a
  default).
- Anything unparseable raises rather than being skipped. A transcript that
  silently loses a third of its lines is worse than one that fails to load.
