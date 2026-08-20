# Meeting Intelligence System

A conversational assistant over meeting transcripts: ask questions about what was
discussed, what was decided, and who committed to what — with every answer citing
the speaker and timestamp it came from.

Built for the NewPage technical assessment (Option 3).

> **Status: in progress.** This README is a stub. The full write-up — setup,
> architecture, RAG decisions, guardrails, observability, AWS productionisation,
> and what I'd do differently — lands in the final phase.
>
> In the meantime, **[`docs/PLAN.md`](docs/PLAN.md)** is the real document: it
> records the design decisions, the reasoning behind them, and the phased build
> order, written before any code existed.

## Approach in one paragraph

Meeting transcripts aren't undifferentiated text — every line carries a speaker and
a timestamp, and that structure is the thing worth exploiting. Chunks follow speaker
turns rather than fixed token windows, retrieval fuses dense vectors with full-text
search so project codenames and ticket IDs aren't missed, and every answer is
traceable back to the exact utterance that supports it. Inference runs locally via
Ollama, which for meeting data is a product decision as much as a cost one.

## Stack

| Layer | Choice |
|---|---|
| API | Python, FastAPI, Pydantic, SQLAlchemy |
| Web | React, Vite, TypeScript, Tailwind |
| Store | Postgres 17 + pgvector |
| Models | `gemma4:12b` (generation), `embeddinggemma:300m` (embeddings), via Ollama |
| Orchestration | None — plain Python, deliberately |

## Build progress

- [x] Phase 0 — plan
- [x] Phase 1 — scaffold, compose, CI
- [x] Phase 2 — transcript corpus
- [x] Phase 3 — ingestion pipeline
- [x] Phase 4 — retrieval + RAG
- [x] Phase 5 — Ask UI (end-to-end demoable)
- [x] Phase 6 — extraction, Brief + Actions
- [x] Phase 7 — observability + evals
- [ ] Phase 8 — documentation
