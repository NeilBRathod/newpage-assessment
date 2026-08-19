# Meeting Intelligence System — Implementation Plan

## Context

Technical assessment (Option 3): build a fullstack conversational AI assistant that analyses
meeting transcripts and answers questions about discussions, decisions, and action items.
The repo is currently empty (one commit, a stub README) — this is greenfield.

The grading criteria weight *how* it's built as heavily as *what* is built: chunking strategy,
model selection, retrieval approach, prompt engineering, context management, guardrails,
quality controls, observability, and a README that reads as human reasoning rather than
LLM output. The brief explicitly prefers "a solid & well-engineered basic solution" over an
over-engineered one.

**Decisions settled with the user:**
- Stack: Python FastAPI + React, Postgres + pgvector
- Models: local via Ollama — `gemma4:12b` generator (to pull), `embeddinggemma:300m` embeddings.
  `gemma4:e4b` already on disk, held for the audio bonus.
- Provider abstraction: local default, optional cloud adapter, fake for tests
- Seed data: synthetic corpus, authored as fixtures
- Deployment: runs locally; AWS productionisation is a written README deliverable.
  (Investigated reusing `ai-wedding-website` AWS — its VPC/RDS/ECR were decommissioned
  2026-08-09; only S3/Cognito/SES/SSM remain on an unmanaged 1GB Lightsail box. Not reusable.)
- Delivery: phase branches → PR → `main`. I open and merge each PR; merge commits, not squash.
  CI runs lint + tests on every PR.

**Intended outcome:** a running local app with a genuinely useful three-pane UI, a defensible
RAG pipeline, tests over the parts that matter, an eval harness, and a README that argues
its own decisions.

---

## The product idea

The thing that makes meeting transcripts different from generic document RAG is **structure**:
every line has a speaker and a timestamp. The design leans on that everywhere rather than
treating transcripts as undifferentiated text.

Three surfaces, not just a chat box:

1. **Ask** — chat with streaming answers; every claim cites `[Meeting · Speaker · 00:14:02]`.
   Clicking a citation opens the transcript at that moment with the turn highlighted.
   Verifiability is the whole point for meeting data.
2. **Brief** — per-meeting precomputed structure (summary, decisions, action items,
   participant talk-time). Not RAG; extracted once at ingest and read from SQL.
3. **Actions** — cross-meeting action-item board grouped by owner, each linked to the
   utterance where it was committed to.

---

## Architecture

```
React (Vite/TS/Tailwind) ──HTTP/SSE──▶ FastAPI ──▶ Postgres 17 + pgvector
     three panes                          │           meetings, utterances, chunks,
                                          │           decisions, action_items, query_traces
                                          ▼
                                 Ollama on HOST :11434
                                 gemma4:12b · embeddinggemma:300m
```

**Ollama runs on the host, not in Docker** — macOS containers get no Metal passthrough, so a
containerised model would be CPU-only and unusable. Containers reach it via
`host.docker.internal:11434`. This seam is deliberate and gets documented as such.

### Repo layout

```
api/src/meetingiq/
  config.py            pydantic-settings; validates num_ctx and model availability at startup
  models.py            SQLAlchemy tables
  ingest/parser.py     transcript text -> Utterance[]  (multiple formats)
  ingest/chunker.py    speaker-aware turn-group chunking       <- pure, heavily tested
  ingest/pipeline.py   parse -> chunk -> embed -> store -> extract
  retrieval/hybrid.py  vector + full-text, fused with RRF      <- pure fusion, tested
  retrieval/filters.py question -> metadata filters (speaker/meeting/date)
  llm/base.py          Protocol: LLMProvider, EmbeddingProvider
  llm/{ollama,openai,fake}.py
  rag/prompts.py       system prompt, context assembly, token budgeting
  rag/answer.py        orchestration
  rag/guardrails.py    score floor, citation validation, injection defence
  extraction/brief.py  per-meeting structured extraction
  observability/       structured JSON logs + query_traces writer
  routers/             meetings, chat, actions, traces, health
api/tests/             pytest, no network (FakeProvider)
api/evals/             golden_set.yaml + run_eval.py
web/src/components/    ChatPane, EvidencePanel, MeetingLibrary, BriefView, ActionBoard, TraceViewer
seed/transcripts/      synthetic corpus
```

### Schema (the parts that matter)

- `utterances` — `(meeting_id, seq, speaker, ts_start_s, ts_end_s, text)`. Ground truth for
  the evidence panel; chunks reference these rather than duplicating text.
- `chunks` — `text`, `context_header`, `speakers[]`, time range, `utterance_ids[]`,
  `embedding vector(768)`, `tsv tsvector`. HNSW index (`vector_cosine_ops`) + GIN on `tsv`.
- `query_traces` — question, filters, retrieved chunk ids + scores, token counts,
  latency split retrieve/generate, answer, citations, refusal reason.

---

## Key technical decisions

**Chunking — speaker-aware turn groups, not fixed windows.** Group consecutive utterances into
~350-token chunks (hard max 500), **never splitting mid-utterance**, with one turn of overlap so
pronouns resolve ("he said we should…" needs the prior turn). Each chunk is prefixed before
embedding with a synthetic header — `Meeting: Q3 Planning | 2026-03-12 | Speakers: Alice, Bob |
00:14:02–00:17:45` — so the vector captures who and when, not just what.

**Hybrid retrieval with Reciprocal Rank Fusion.** Meetings are dense with proper nouns, project
codenames and ticket IDs that dense vectors miss. Top-20 pgvector + top-20 Postgres full-text,
fused via RRF (k=60), take top 6–8. RRF is ~20 lines, needs no reranker model, and needs no
score normalisation between two incomparable scoring systems.

**No orchestration framework.** Plain Python. LangChain/LlamaIndex would hide exactly the
decisions being graded and add indirection over ~200 lines of explicit pipeline. This is a
stated position in the README, not an omission.

**pgvector over Chroma/Qdrant.** One datastore for vectors *and* relational data means metadata
filtering and hybrid search happen in a single SQL query, and action-item tracking is just SQL.
Also the cleanest AWS path (RDS/Aurora, no code change).

**Guardrails enforced in code, not just prompts** — local models follow instructions less
reliably than frontier ones, so:
- retrieval score floor: below threshold, refuse *without* calling the LLM
- citation validation: parse cited chunk ids, reject any not in the retrieved set
- transcripts wrapped in delimiters, declared as data-never-instructions (someone genuinely
  might say "ignore previous instructions" in a meeting)
- hard context token budget enforced before the call

**The `num_ctx` trap.** Ollama defaults to 2048 tokens regardless of the model's real window —
retrieved context gets silently truncated and answers are grounded on nothing. Set explicitly
per request and asserted at startup.

---

## Delivery workflow

`main` is the trunk. Its first commit is this plan, committed as `docs/PLAN.md` so the repo
opens with the reasoning that produced it. Every phase after that is a branch → PR → merge.

- Branch naming: `phase/NN-slug`
- PR body: what it delivers, what it deliberately leaves out, how to verify it
- Merge commits (not squash) so the incremental commits stay visible on `main`
- CI (lint + tests) must be green before merge, from phase 1 onward
- **Every phase leaves `main` in a runnable state** — no phase depends on a later one to boot

### Sequencing rationale

The ordering is a **vertical slice first, then breadth**. Phases 1–5 build the narrowest path
that goes all the way from a transcript file to a cited answer on screen. Only once that loop
works end-to-end do the later phases widen it (extraction, boards, evals, polish).

The alternative — all backend first, UI last — front-loads the interesting engineering but
carries a bad failure mode: if time runs out, there is no application to show, against a brief
that explicitly expects "a well designed application". Slicing vertically means the worst case
is a working app with fewer features rather than a feature-rich API with no app.

---

## Phases

| # | Branch | Delivers | Done when |
|---|---|---|---|
| 0 | `main` | This plan as `docs/PLAN.md`, `.gitignore`, README stub | Committed directly to `main` |
| 1 | `phase/01-scaffold` | Compose (Postgres+pgvector, api, web), Makefile, `.env.example`, FastAPI app, pydantic-settings config, structured JSON logging, `/health`, GitHub Actions CI, pytest wired up | `make up` boots; `/health` reports DB + Ollama reachability and model presence; CI green on the PR |
| 2 | `phase/02-corpus` | Transcript format spec + 6–8 synthetic transcripts: recurring participants, decisions revisited across meetings, deliberate cross-meeting references | Corpus committed under `seed/`; format documented before any parser exists to write against it |
| 3 | `phase/03-ingestion` | Alembic migrations, SQLAlchemy models, parser, speaker-aware chunker, embedding provider (Protocol + Ollama + Fake), storage, content-hash idempotency, `make seed` | `make seed` ingests the corpus; re-running is a no-op; chunker/parser tests green — invariants: no mid-utterance splits, token budget respected, overlap present |
| 4 | `phase/04-retrieval-rag` | Hybrid retrieval (pgvector + FTS + RRF), metadata filter extraction, prompt assembly with token budgeting, guardrails, citation validation, streaming `/chat` endpoint | Cited answers over the corpus via curl / OpenAPI docs; an unanswerable question refuses without calling the LLM; fusion + guardrail tests green |
| 5 | `phase/05-ask-ui` | React + Vite + TS + Tailwind app shell, meeting library, **Ask** pane with streaming answers and citation chips, evidence panel deep-linking to the cited utterance | **End-to-end demoable.** Upload → ask → click a citation → land on the right turn in the transcript |
| 6 | `phase/06-extraction` | Per-meeting structured extraction (summary, decisions, action items with owner/due/quote), **Brief** pane, cross-meeting **Actions** board grouped by owner | Brief renders per meeting; action items link back to source utterances; extraction runs at ingest and is idempotent |
| 7 | `phase/07-observability-evals` | `query_traces` writer, trace viewer page, golden set (~25 Q&A incl. adversarial/unanswerable), `make eval` reporting recall@5, citation validity, refusal accuracy, p50/p95 latency | `make eval` prints the scorecard; every query is inspectable in the trace viewer |
| 8 | `phase/08-docs` | README: setup, architecture diagram, RAG/LLM decisions, guardrails, observability, AWS productionisation, standards followed *and skipped*, AI-tooling approach, what I'd do differently. Screenshots | README is the actual submission artefact and reads as reasoning, not output |

**Stretch, only if 1–8 are solid:**

| # | Branch | Delivers |
|---|---|---|
| 9 | `phase/09-audio` | Audio upload → transcript via `gemma4:e4b`'s native audio input, feeding the same ingestion pipeline (no separate Whisper) |
| 10 | `phase/10-terraform` | Unapplied `terraform/` skeleton for the documented AWS target, `terraform validate` in CI, never applied |

### Scope guards

Phases 6–8 are where scope creep would bite. If the schedule slips, the cut order is:
**10 → 9 → 7's trace viewer UI (keep the traces table and `make eval`) → 6's Actions board
(keep Brief)**. Phases 1–5 and 8 are non-negotiable — they are the working product and the
document that explains it.

---

## Verification

- `make up` → compose starts; `/health` reports DB reachable, Ollama reachable, both models
  present, `num_ctx` correct
- `make seed` → ingests the corpus; re-running is a no-op (content hash)
- `make test` → pytest green, no network calls (FakeProvider), covering: parser across formats,
  chunker invariants, RRF fusion, citation validator, filter extraction, ingestion idempotency,
  API routes
- `make eval` → recall@5, citation validity rate, refusal accuracy, p50/p95 latency
- Manual: upload a transcript, ask a cross-meeting question, click a citation and confirm it
  lands on the right utterance; ask an unanswerable question and confirm it refuses rather
  than invents
