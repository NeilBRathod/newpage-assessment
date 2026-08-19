# Seed corpus

Eight meetings from a fictional payments company, **Kestrel**, building an
instant-settlement product called **Relay** over roughly three months.

The corpus is synthetic on purpose — real meeting transcripts cannot be
committed to a public repo — but it is not filler. A retrieval system
demonstrated against bland, self-contained documents proves nothing, because
every question has its answer sitting in one obvious place. These were written
so that the interesting questions genuinely require retrieval to answer.

See [FORMAT.md](FORMAT.md) for the three transcript formats and what the parser
guarantees about them.

## The meetings

| Date | Meeting | Format | Why it exists |
|---|---|---|---|
| 2026-04-07 | Relay Kickoff | A | Sets the scope and makes an architecture decision *provisionally* |
| 2026-04-14 | Architecture Review | A | **Reverses** that decision on evidence |
| 2026-04-28 | Sprint 3 Planning | A | Routine delivery detail: ticket IDs, a blocker, a design question |
| 2026-05-12 | Meridian Advisory Call | **B** | External voice; contradicts an internal assumption about pricing |
| 2026-05-26 | Q2 Budget Review | A | Money and headcount; a different vocabulary from the engineering meetings |
| 2026-06-09 | Incident Postmortem | A | Dense with causes, owners and dated commitments |
| 2026-06-23 | Dashboard Design Review | **C (WebVTT)** | A disagreement that gets resolved; accessibility detail |
| 2026-07-07 | Beta Go/No-Go | A | Pulls every earlier thread together into one decision |

Recurring people: Priya Raman (VP Eng), Marcus Webb (Product), Dana Osei (Staff
Eng), Jamie Fox (QA), Sofia Reyes (Customer Success), Tom Lindqvist (Sales),
Aisha Khan (Design), Ben Cutler (CFO). Guests appear once or twice — Rafael
Ortiz, Nadia Haddad, and Elena Vasquez from the customer side.

## Threads that span meetings

These are the point of the corpus. Each requires pulling from two or more
meetings, so a system that only does single-document lookup will answer them
incompletely — which is exactly what should be visible in a demo.

1. **The ledger decision, made and then reversed.** 07 Apr provisionally decides
   to extend the existing ledger. 14 Apr reverses it after Dana's benchmark.
   07 Jul notes the reversal paid off for a reason nobody predicted. A question
   like *"what did we decide about the ledger?"* has a wrong answer that is
   easy to retrieve and a right answer that requires noticing the reversal.
2. **Meridian's webhook complaint.** Raised 12 May as mattering *more* than the
   product being built. Still unresolved on 07 Jul, where it is escalated and
   queued. Tests whether the system tracks an unresolved thread across time.
3. **The 5 June incident.** Caused by a query regression invisible at staging
   scale (09 Jun), which then becomes Jamie's condition for beta on 07 Jul.
   Cause and consequence sit seven weeks apart.
4. **Reconciliation (PAY-1042).** Flagged as important 14 Apr, nearly dropped
   28 Apr, and on 09 Jun it is the thing that proves no money was lost.
5. **Pricing.** 30 basis points per transaction (07 Apr) → rejected by the
   customer (12 May) → remodelled as tiered per-event (26 May) → accepted
   (07 Jul).
6. **Dates slipping honestly.** GA of 1 Sept survives three meetings before
   being given up on 07 Jul. Every slip is stated out loud when it happens.

## Deliberate awkwardness

Real transcripts are messy, and a parser that only handles tidy input is not
finished. So the corpus includes: an utterance wrapping across lines, `MM:SS`
timestamps alongside `HH:MM:SS`, a speaker who appears in only one meeting, an
em-dash-heavy speaking style, disagreements that are not resolved, and one
meeting where somebody is corrected and says so.

## Questions that should be refused

Nothing in these transcripts answers the following, and a system that produces a
confident answer to any of them is hallucinating. They are the basis of the
refusal cases in the eval set:

- *"What did we decide about the Frankfurt data centre?"* — never mentioned
- *"What is Priya's salary?"* — headcount is discussed; compensation is not
- *"What happened in the August board meeting?"* — outside the corpus range
- *"How many customers churned in Q1?"* — plausible, adjacent, absent
