# AI-Centric Interview Tracker & Resume Optimizer — Architecture & Design

> A working reference for how this system is built, why it is built that way, and
> how to run and extend it.
>
> **Status legend used throughout:**
> ✅ Implemented and verified · 🟡 Implemented, verification blocked · ⛔ Not built yet

---

## Table of Contents

1. [What this project is](#1-what-this-project-is)
2. [System architecture](#2-system-architecture)
3. [Repository layout](#3-repository-layout)
4. [The data model](#4-the-data-model)
5. [Backend design](#5-backend-design)
6. [Phase 2 — PDF parsing & the embedding engine](#6-phase-2--pdf-parsing--the-embedding-engine)
7. [Phase 3 — ATS scoring with Pydantic AI](#7-phase-3--ats-scoring-with-pydantic-ai)
8. [Phase 4 — The LangGraph autofix loop](#8-phase-4--the-langgraph-autofix-loop)
8A. [Phase 5 — LaTeX masters & template-preserving tailoring](#8a-phase-5--latex-masters--template-preserving-tailoring-)
8B. [The LLM provider seam](#8b-the-llm-provider-seam-)
9. [Frontend design](#9-frontend-design)
10. [End-to-end request flows](#10-end-to-end-request-flows)
11. [Setup & running](#11-setup--running)
12. [Configuration reference](#12-configuration-reference)
13. [Testing strategy](#13-testing-strategy)
14. [Design decisions & trade-offs](#14-design-decisions--trade-offs)
15. [Known gaps & blockers](#15-known-gaps--blockers)
16. [Extending the system](#16-extending-the-system)

---

## 1. What this project is

A job seeker's problem is not "track my applications" — spreadsheets do that. The
real problems are:

| Pain point | What this system does about it |
|---|---|
| **Which companies should I even chase?** | Embeds career goals and job descriptions into a shared vector space and ranks openings by semantic similarity — not keyword overlap. |
| **Rewriting my resume for every role is soul-destroying.** | One **master resume** plus AI-generated **tailored child versions**, each targeted at a specific job profile. |
| **Every tailored version looks like a different resume.** | A LaTeX master is split into frozen template bytes and editable content slots. Tailoring rewrites only the slots, so a Python-flavoured and a Rust-flavoured version are visually identical (§8A). |
| **I don't know why the ATS rejected me.** | Parses the job description and resume, produces a 0–100 match score, names the missing keywords, and proposes verbatim line-level rewrites. |
| **Fixing the gaps is still manual.** | A state-machine loop that applies fixes, re-scores, and iterates until the score clears a target or stops improving. |

### Core design principle

> **Relational data stays relational. Documents stay documents. Vectors stay isolated.**

Companies, jobs, applications, and their relationships are modelled with real
foreign keys and CHECK constraints — never as JSON blobs. Resume *bodies* are
documents (Markdown), because that is genuinely what they are. Vectors live in
their own table so a single optional extension can't destabilise the core schema.

---

## 2. System architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│  Angular 22 SPA  (standalone components, signals, CDK drag-drop)      │
│  Board · Companies · Jobs · Resumes · Chase · ATS                     │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ HTTP/JSON  (CORS-gated)
                                ▼
┌───────────────────────────────────────────────────────────────────────┐
│  FastAPI  (fully async)                                               │
│                                                                       │
│  routers/ ──► crud/ ──► SQLModel ──► asyncpg ──► PostgreSQL           │
│      │                                                                │
│      ├──► services/pdf_parser   (pdfplumber → pypdf fallback)         │
│      ├──► services/matching     (pgvector cosine search)              │
│      ├──► embeddings/           (local | Voyage | OpenAI | Gemini)    │
│      ├──► services/latex/       (.tex span map → splice → Tectonic)   │
│      ├──► ai/provider.py        (Claude | Gemini selection)           │
│      ├──► ai/ats.py             (Pydantic AI → the chosen LLM)        │
│      ├──► ai/autofix.py         (LangGraph state machine)             │
│      └──► ai/tailor.py          (slot-scoped tailoring)               │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
     ┌────────────────┐  ┌──────────────┐  ┌───────────────┐
     │  PostgreSQL 16 │  │  Claude API  │  │  Embedding    │
     │  + pgvector    │  │      or      │  │  provider     │
     │                │  │  Gemini API  │  │               │
     └────────────────┘  └──────────────┘  └───────────────┘
```

### Why this stack

| Choice | Reasoning |
|---|---|
| **FastAPI, all-async** | The workload is I/O-bound end to end — DB round-trips, embedding calls, and multi-second LLM calls. Async keeps one worker responsive across many concurrent autofix loops. |
| **SQLModel** | One class defines both the table and its Pydantic base, halving CRUD boilerplate. Distinct `Create`/`Update`/`Read` schemas are still hand-written so table models are never exposed on the wire. |
| **PostgreSQL + pgvector** | Keeps relational integrity *and* vector search in one system. No separate vector DB to sync, no dual-write consistency problem. |
| **Pydantic AI** | Turns "ask the LLM for JSON and pray" into a validated, typed object. Schema violations are retried at the library layer, not discovered in production. |
| **LangGraph** | The autofix loop is genuinely cyclic (score → fix → score → …) with conditional exits. A graph models that honestly; a `while` loop would bury the control flow. |
| **Angular standalone + signals** | No NgModule ceremony. Signals give fine-grained reactivity without the RxJS overhead a CRUD app doesn't need. |

---

## 3. Repository layout

```
Jarvis/
├── backend/
│   ├── app/
│   │   ├── main.py               FastAPI app, CORS, router registration
│   │   ├── deps.py               SessionDep — the DI seam for the DB
│   │   ├── core/
│   │   │   ├── config.py         Pydantic Settings (env-driven)
│   │   │   └── db.py             Async engine + session factory
│   │   ├── models/               SQLModel tables (the schema)
│   │   ├── schemas/              Wire contracts (Create/Update/Read)
│   │   ├── crud/                 Async data-access functions
│   │   ├── routers/              HTTP surface
│   │   ├── services/
│   │   │   ├── pdf_parser.py     PDF → text → Markdown
│   │   │   ├── matching.py       Embedding storage + cosine search
│   │   │   ├── tailoring.py      parse → tailor → splice → score
│   │   │   └── latex/
│   │   │       ├── model.py      Span map: frozen vs editable
│   │   │       ├── parser.py     .tex → sections, bullets, marked regions
│   │   │       ├── renderer.py   Splice edits back into the master's bytes
│   │   │       ├── safety.py     Allowlist + brace validation for LLM output
│   │   │       ├── engines.py    Engine allowlist + per-document detection
│   │   │       ├── plain_text.py LaTeX → Markdown projection (one-way)
│   │   │       └── compiler.py   Tectonic subprocess → PDF
│   │   ├── embeddings/           Provider abstraction
│   │   │   ├── base.py           EmbeddingProvider ABC
│   │   │   ├── local.py          fastembed (ONNX, no API key)
│   │   │   └── remote.py         Voyage AI · OpenAI · Gemini
│   │   └── ai/
│   │       ├── schemas.py        ATSReport, AutofixResult, …
│   │       ├── ats.py            Pydantic AI agents + prompts
│   │       ├── autofix.py        LangGraph state machine
│   │       ├── tailor.py         Slot-scoped tailoring agent (Phase 5)
│   │       ├── provider.py       Anthropic | Google model resolution
│   │       └── limits.py         429 retry honouring the provider's RetryInfo
│   ├── alembic/versions/         5 migrations (see §4.5)
│   └── tests/                    118 tests
└── frontend/
    └── src/app/
        ├── core/models/          TS interfaces mirroring backend schemas
        ├── core/services/        Typed HttpClient wrappers
        ├── layout/               Dashboard shell + sidenav
        ├── kanban/               Board, column, card (CDK drag-drop)
        ├── companies/ jobs/ resumes/
        ├── matches/              "Companies to Chase"
        └── ats/                  ATS report + autofix panel
```

### The layering rule

```
router  →  crud / services  →  models  →  database
   ↑            ↑
schemas     embeddings / ai
```

Routers do HTTP concerns only: validation, status codes, error translation.
They never build SQL. Services never raise `HTTPException` — they raise domain
errors (`PdfParseError`, `EmbeddingError`, `VectorSearchUnavailableError`) that
routers translate. This keeps services callable from tests, scripts, and future
background workers without dragging FastAPI along.

---

## 4. The data model

### 4.1 Entity relationships

```
                    ┌──────────┐
                    │  users   │
                    └────┬─────┘
              ┌──────────┼──────────────┐
              ▼          ▼              │
        ┌──────────┐  ┌──────────────┐  │
        │ resumes  │  │ applications │◄─┘
        └────┬─────┘  └──┬───┬───┬───┘
             │           │   │   │
   self-FK   │           │   │   └──────────────┐
 (master ◄── │ tailored) │   │                  │
             └───────────┘   ▼                  ▼
                     ┌──────────────┐    ┌─────────────┐
                     │ job_profiles │───►│  companies  │
                     └──────┬───────┘    └──────┬──────┘
                            │                   │
                            ▼                   ▼
              ┌──────────────────────┐  ┌────────────────────┐
              │ job_profile_          │  │ company_           │
              │ technologies         │  │ technologies       │
              └──────────┬───────────┘  └─────────┬──────────┘
                         └────────┬───────────────┘
                                  ▼
                          ┌──────────────┐
                          │ technologies │
                          └──────────────┘

        ┌────────────────────────────────────────────┐
        │ entity_embeddings   (pgvector — isolated)   │
        │ polymorphic: entity_type + entity_id        │
        └────────────────────────────────────────────┘
```

### 4.2 Table reference

**`users`** — the job seeker.
`career_goals` is free text and doubles as the embedding source for matching.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, app-generated `uuid4()` |
| `full_name` | VARCHAR(255) | |
| `email` | VARCHAR(255) | UNIQUE, indexed |
| `career_goals` | TEXT | Embedded for semantic matching |
| `desired_salary_min/max` | NUMERIC(12,2) | |
| `salary_currency` | VARCHAR(3) | default `USD` |

**`companies`**

| Column | Type | Notes |
|---|---|---|
| `name` | VARCHAR(255) | UNIQUE, indexed |
| `growth_trajectory` | VARCHAR(20) | CHECK: `declining`/`stable`/`growing`/`hypergrowth` |

**`technologies`** + two join tables — the "no blobs" rule in practice.
A company's tech stack could have been `{"stack": ["python", "go"]}`. Instead it
is a lookup table plus join tables, which makes *"which of my target companies
use Python?"* a plain join instead of a JSON scan.

`job_profile_technologies` additionally carries `requirement_level`
(CHECK: `required` / `nice_to_have`) — an attribute of the *relationship*, which
is precisely what a join table is for.

**`resumes`** — the versioning model.

| Column | Notes |
|---|---|
| `master_resume_id` | Self-FK. `NULL` ⇒ this row **is** a master. Non-null ⇒ tailored child. |
| `content_format` | CHECK: `markdown` / `json` |
| `content` | TEXT — the document body |
| `version_label` | e.g. *"Tailored for Staff Platform Engineer"* |

The tree is deliberately kept **one level deep**: the autofix endpoint resolves
`resume.master_resume_id or resume.id` as the parent, so tailoring a tailored
resume still attaches to the original master rather than creating a chain.

**`applications`** — the Kanban pipeline.

| Column | Notes |
|---|---|
| `stage` | VARCHAR + CHECK: `applied`/`interviewing`/`offer`/`archive`. Indexed. |
| `board_position` | INTEGER — ordering *within* a column |
| `stage_updated_at` | Distinct from `updated_at`; tracks pipeline velocity |

**`entity_embeddings`** — vectors, polymorphic and isolated.

| Column | Notes |
|---|---|
| `entity_type` | CHECK: `user_career_goals`/`job_profile`/`company`/`resume` |
| `entity_id` | UUID of the owning row (no FK — polymorphic by design) |
| `source_text` | The exact text embedded — enables staleness detection |
| `provider` / `model` | Which provider produced this vector |
| `embedding` | `vector(N)`, N from `EMBEDDING_DIM` |

UNIQUE on `(entity_type, entity_id)` — one current vector per entity.

### 4.3 Why `stage` is a CHECK constraint, not a Postgres ENUM

Postgres `ENUM` types are painful to alter: `ALTER TYPE … ADD VALUE` cannot run
inside a transaction block in older versions and can't remove values at all. The
pipeline will realistically grow stages ("Phone Screen", "Onsite", "Final
Round"). A `VARCHAR` + CHECK is a one-line migration to widen. The same reasoning
applies to `experience_tier`, `growth_trajectory`, and `entity_type`.

### 4.4 Why embeddings are a separate table

The blueprint originally suggested adding `career_goals_embedding vector(1536)`
directly to `users`. A separate table was chosen instead, for four reasons:

1. **Isolation of an optional dependency.** `pgvector` is the one thing that
   can't be installed in the current environment. If the vector column lived on
   `users`, *every* user query would fail without the extension. Isolated, only
   the matching endpoints degrade.
2. **Polymorphism.** One table serves users, jobs, companies, and resumes. Adding
   a fifth embeddable entity is a CHECK-constraint widening, not a new column on
   a new table.
3. **Staleness detection.** Storing `source_text` alongside the vector means a
   re-index can skip anything unchanged — and embedding calls are the expensive
   step.
4. **Provider migration.** `provider` and `model` columns make it possible to
   find and re-embed only the vectors produced by an outgoing provider.

The trade-off: one extra join, and no FK-enforced referential integrity on
`entity_id` (the code tolerates orphaned vectors by skipping them at read time).

### 4.5 Migration chain

| Revision | Purpose | Applied? |
|---|---|---|
| `ca59c8073283` | `CREATE EXTENSION IF NOT EXISTS vector` | 🟡 stamped, not run |
| `eb33c6adc51f` | Phase 1 schema — 8 tables, FKs, CHECKs, indexes | ✅ applied & verified |
| `a89449bbaeeb` | `entity_embeddings` + HNSW index | ⛔ deferred (needs pgvector) |
| `c7d2f1a4b830` | Admit `'latex'` to the `resumes.content_format` CHECK | 🟡 applied by hand — see note |
| `d1e8b6c93f27` | `resumes.latex_engine` + its CHECK constraint | 🟡 applied by hand — see note |

> **Note on `c7d2f1a4b830` and `d1e8b6c93f27`.** They sit downstream of `a89449bbaeeb`, so
> `alembic upgrade head` cannot reach it on a Postgres without pgvector. The dev
> database has had the equivalent `ALTER TABLE … CHECK` applied directly, and the
> test database gets it from the model's `CheckConstraint` via `create_all`. On a
> pgvector-enabled instance the whole chain applies normally and no manual step
> is needed.

**HNSW over IVFFlat** for the vector index: IVFFlat requires a training step over
existing data and degrades as rows are added, while HNSW needs no training and
stays accurate for a small, continuously-updated corpus — exactly this workload.

---

## 5. Backend design

### 5.1 Configuration

`app/core/config.py` uses `pydantic-settings`, so every value is overridable by
environment variable or `backend/.env`. `get_settings()` is `@lru_cache`d — a
process-wide singleton parsed once.

### 5.2 Async session management

```python
engine = create_async_engine(settings.database_url)          # asyncpg driver
async_session_maker = async_sessionmaker(engine, class_=AsyncSession,
                                         expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
```

`expire_on_commit=False` matters: with the default, attribute access after
`commit()` triggers a *synchronous* lazy refresh, which raises under async.

`SessionDep = Annotated[AsyncSession, Depends(get_session)]` is the single DI
seam — tests override exactly one dependency to redirect the entire app at a
test database.

### 5.3 Timezone-aware datetimes — a bug worth documenting

The first implementation declared `created_at: datetime` and let SQLModel infer
the column type. SQLModel produced a **naive** `TIMESTAMP`, while the migration
created `TIMESTAMP WITH TIME ZONE`. Every insert then failed:

```
asyncpg.exceptions.DataError: invalid input for query argument $6:
can't subtract offset-naive and offset-aware datetimes
```

The fix is to state the type explicitly on every timestamp column:

```python
created_at: datetime = Field(default_factory=_utcnow,
                             sa_type=DateTime(timezone=True))
```

**Lesson:** when a migration and an ORM model can each independently decide a
column type, they will eventually disagree. Pin the type in the model.

### 5.4 Error translation

| Layer | Raises | Becomes |
|---|---|---|
| `pdf_parser` | `PdfParseError` | `422 Unprocessable Entity` |
| `embeddings` | `EmbeddingError` | `503 Service Unavailable` |
| `matching` | `VectorSearchUnavailableError` | `503 Service Unavailable` |
| `routers/ats` | missing API key | `503` with setup instructions |

Every 503 message tells the operator **exactly what to do**:

```json
{"detail": "Semantic search needs the pgvector extension and the
            'phase2 entity embeddings' migration. Run `alembic upgrade head`
            against a Postgres instance with pgvector installed."}
```

This is deliberate: an unconfigured optional dependency is an expected
operational state, not a crash. A regression test asserts these endpoints answer
**503, never 500**.

### 5.5 Complete API surface

**Phase 1 — CRUD**

```
GET    /api/v1/health

GET    /api/v1/users                          POST   /api/v1/users
GET    /api/v1/users/{id}                     PATCH  /api/v1/users/{id}
DELETE /api/v1/users/{id}

GET    /api/v1/companies                      POST   /api/v1/companies
GET    /api/v1/companies/{id}                 PATCH  /api/v1/companies/{id}
DELETE /api/v1/companies/{id}
POST   /api/v1/companies/{id}/technologies
DELETE /api/v1/companies/{id}/technologies/{tech_id}

GET    /api/v1/technologies                   POST   /api/v1/technologies

GET    /api/v1/job-profiles?company_id=       POST   /api/v1/job-profiles
GET    /api/v1/job-profiles/{id}              PATCH  /api/v1/job-profiles/{id}
DELETE /api/v1/job-profiles/{id}
POST   /api/v1/job-profiles/{id}/technologies
DELETE /api/v1/job-profiles/{id}/technologies/{tech_id}

GET    /api/v1/resumes?user_id=&master_only=  POST   /api/v1/resumes
GET    /api/v1/resumes/{id}                   PATCH  /api/v1/resumes/{id}
DELETE /api/v1/resumes/{id}
GET    /api/v1/resumes/{id}/versions

GET    /api/v1/applications?user_id=&stage=&company_id=
POST   /api/v1/applications
GET    /api/v1/applications/{id}              PATCH  /api/v1/applications/{id}
DELETE /api/v1/applications/{id}
PATCH  /api/v1/applications/{id}/stage        ← Kanban drag-drop
```

**Phases 2–4 — AI**

```
POST   /api/v1/resumes/parse-pdf              ← multipart PDF → Markdown
POST   /api/v1/matching/reindex               ← (re)embed jobs + goals
GET    /api/v1/users/{id}/job-matches?limit=  ← "companies to chase"
POST   /api/v1/ats/score                      ← structured ATS report
POST   /api/v1/ats/autofix                    ← LangGraph improvement loop
```

**Phase 5 — LaTeX**

```
GET    /api/v1/latex/status                        ← is a compiler installed?
POST   /api/v1/latex/resumes/upload                ← multipart .tex → master + outline
GET    /api/v1/latex/resumes/{id}/outline          ← what tailoring may change
PATCH  /api/v1/latex/resumes/{id}/engine           ← change the compile engine
GET    /api/v1/latex/resumes/{id}/render?output=   ← pdf | tex
POST   /api/v1/latex/resumes/{id}/preview?output=  ← apply a reviewed tailoring, no LLM
POST   /api/v1/latex/tailor                        ← LLM tailoring → child version
```

**Design note — the dedicated stage endpoint.** `PATCH /applications/{id}/stage`
exists alongside the general `PATCH /applications/{id}` because a Kanban drag is
a *distinct domain event*, not a generic field edit. It has its own narrow
payload (`{stage, board_position}`) and its own side effect (bumping
`stage_updated_at`). Squeezing it into the general PATCH would mean either
touching `stage_updated_at` on unrelated edits, or inferring intent from which
fields happen to be present.

---

## 6. Phase 2 — PDF parsing & the embedding engine

### 6.1 PDF extraction — dual-library strategy ✅

```
bytes ──► pdfplumber ──► empty? ──► pypdf ──► still empty? ──► PdfParseError
             │                        │
             └──────► _normalize() ◄──┘
                           │
                           ▼
                     to_markdown()
```

Two libraries because they fail differently. `pdfplumber` preserves
layout-derived spacing better on the multi-column layouts resumes love;
`pypdf` handles some malformed files `pdfplumber` refuses outright. Trying both
converts many hard failures into successes.

**Normalisation** collapses the ragged whitespace extraction produces:
runs of spaces/tabs → single space, 3+ newlines → paragraph break.

**`to_markdown()`** is deliberately conservative — it promotes `ALL CAPS` lines
to `## Headings` and normalises bullet glyphs (`•▪◦‣·-*` → `-`), and nothing
more. Aggressive layout reconstruction produces confident garbage; the user
reviews the extraction in a textarea before saving.

A scanned (image-only) PDF yields no text. Rather than saving an empty resume,
it raises with an actionable message naming OCR as the real requirement.

### 6.2 The embedding abstraction 🟡

**Anthropic does not offer an embeddings endpoint.** Claude handles reasoning;
embeddings must come from elsewhere. Rather than hard-coding a vendor, the system
defines an interface:

```python
class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_one(self, text: str) -> list[float]:      # shared default
        return (await self.embed([text]))[0]
```

| Provider | Model | Dim | Key | Notes |
|---|---|---|---|---|
| `local` *(default)* | `BAAI/bge-small-en-v1.5` | 384 | none | ONNX via fastembed; free, offline |
| `voyage` | `voyage-3` | 1024 | `VOYAGE_API_KEY` | Anthropic's recommended partner |
| `openai` | `text-embedding-3-small` | 1536 | `OPENAI_API_KEY` | Adds a second AI vendor |

Swapping providers is a config change:

```bash
EMBEDDING_PROVIDER=voyage
EMBEDDING_DIM=1024        # must match the model
VOYAGE_API_KEY=...
```

**Contracts every implementation must honour:**
- Output order matches input order (both remote providers sort by the API's
  `index` field — neither guarantees response ordering).
- An empty input list returns `[]` without a network call.
- Vector length equals `dimension`; the local provider asserts this and fails
  loudly on mismatch rather than writing bad rows.

The local provider is CPU-bound and synchronous, so it runs under
`asyncio.to_thread` — never blocking the event loop — and the model is
`@lru_cache`d so weights load once per process.

### 6.3 Embedding storage & staleness

`upsert_embedding()` skips the API call when the stored vector already came from
identical `source_text` on the same provider *and* model. Re-indexing an
unchanged corpus therefore costs zero embedding calls. Change any of the three
and it re-embeds.

### 6.4 Similarity search

```sql
SELECT entity_id, 1 - (embedding <=> CAST(:query AS vector)) AS similarity
FROM entity_embeddings
WHERE entity_type = :entity_type
ORDER BY embedding <=> CAST(:query AS vector)
LIMIT :limit
```

`<=>` is pgvector's **cosine distance**. Cosine (not L2) because it measures
*direction* — semantic topic — independent of magnitude, which for text
embeddings largely reflects document length. Distance is converted to
`1 - distance` so the API returns an intuitive 0–1 similarity.

`ORDER BY` uses the raw distance operator so the HNSW index is actually used;
ordering by the computed `similarity` alias would defeat it.

---

## 7. Phase 3 — ATS scoring with Pydantic AI

### 7.1 The structured output contract

The whole value of Pydantic AI here is that **the LLM cannot return malformed
data**. The schema is the contract:

```python
class ATSReport(BaseModel):
    match_score: int = Field(ge=0, le=100)
    summary: str
    matched_keywords: list[str]
    missing_keywords: list[MissingKeyword]
    suggestions:      list[PhrasingSuggestion]

class MissingKeyword(BaseModel):
    keyword:   str
    severity:  Literal["critical", "important", "nice_to_have"]
    rationale: str

class PhrasingSuggestion(BaseModel):
    original_text:  str   # verbatim from the resume — or "" for an addition
    suggested_text: str
    reason:         str
    severity:       Severity
```

`match_score` is range-constrained at the schema level, so a hallucinated `150`
is rejected and retried by the library — not caught downstream.

### 7.2 The `original_text` invariant

`original_text` **must be copied verbatim from the resume**. This is what makes
suggestions *applyable*: the client can locate the exact string, show a
before/after diff, and let the user accept it individually. A paraphrase would
make the suggestion un-locatable. Empty string signals an addition rather than a
rewrite.

### 7.3 Anti-fabrication as a safety property

Both system prompts carry an explicit rule:

> *Never fabricate experience the candidate does not have. Rewrites may surface,
> reword, or re-emphasise what is already there; they may not claim new skills,
> employers, or dates.*

An ATS optimiser that invents credentials generates **résumé fraud**. This is a
safety property, not a style preference — so a unit test asserts the rule
survives future prompt edits:

```python
def test_system_prompt_forbids_fabrication() -> None:
    assert "Never fabricate" in SCORING_SYSTEM_PROMPT
```

### 7.4 Model and injection

Model: **`claude-opus-5`** (configurable via `ATS_MODEL`), resolved as the
identifier string `anthropic:claude-opus-5` so the API key is read at call time —
the app imports cleanly with no credentials present.

`score_resume(..., agent=None)` accepts an injected agent. Production passes
nothing and gets the cached real agent; tests pass a `FunctionModel`-backed one.
This is what makes the LLM logic testable without a key or network.

---

## 8. Phase 4 — The LangGraph autofix loop

### 8.1 The graph

```
              ┌──────────────────┐
   START ────►│   score_node     │◄─────────────┐
              │  (Claude call)   │              │
              └────────┬─────────┘              │
                       │                        │
                       ▼                        │
                 ┌───────────┐                  │
                 │  decide   │                  │
                 └─┬───────┬─┘                  │
       stop_reason │       │ keep going         │
          is set   │       │                    │
                   ▼       ▼                    │
                 END   ┌──────────────┐         │
                       │ rewrite_node │─────────┘
                       │(Claude call) │
                       └──────────────┘
```

### 8.2 Termination — three distinct exits

| `stopped_because` | Condition |
|---|---|
| `target_reached` | `match_score >= target_score` |
| `max_iterations` | Iteration budget exhausted |
| `no_further_gains` | Report returned zero suggestions — another rewrite would only churn |

Reporting *why* it stopped is as important as the score: a run that hit
`max_iterations` at 71 means "keep going", while `no_further_gains` at 71 means
"this resume genuinely doesn't fit this role."

### 8.3 A real bug: LangGraph state is copy-on-write

The first implementation set the termination reason inside the conditional edge:

```python
def decide(state):
    if report.match_score >= state["target_score"]:
        state["stopped_because"] = "target_reached"   # ← silently discarded
        return END
```

Tests failed with every run reporting `max_iterations`. **LangGraph passes edge
functions a copy of state; only node return values are merged.** The fix moves
the decision into the node and leaves the edge as pure routing:

```python
async def score_node(state):
    ...
    if report.match_score >= state["target_score"]:
        update["stopped_because"] = "target_reached"
    elif iterations >= state["max_iterations"]:
        update["stopped_because"] = "max_iterations"
    elif not report.suggestions:
        update["stopped_because"] = "no_further_gains"
    return update

def decide(state):
    return END if state.get("stopped_because") else "rewrite"
```

**Lesson:** in a state-graph framework, *only nodes mutate state*. Edges route.
This bug was invisible to type checking and only surfaced through tests that
asserted on the reason rather than just the score.

### 8.4 Budget discipline

Every iteration is **two** Claude calls (rewrite + re-score), so cost grows
linearly with iterations. Controls:

- `ats_max_autofix_iterations` (default **3**) — the hard ceiling.
- `target_score` (default **85**) — early exit once good enough.
- `no_further_gains` — stops a loop that isn't improving.
- The rewrite prioritises `critical`/`important` suggestions, falling back to all
  only if none are in those tiers — so each expensive call targets the gaps that
  actually move the score.

### 8.5 Persisting the result

With `save_as_tailored_version: true`, the improved resume is written as a new
`Resume` row whose `master_resume_id` points at the original master. This is the
blueprint's "dynamic resume versioning" realised: one master, many AI-generated,
job-targeted children — with the original never mutated.

---

## 8B. The LLM provider seam ✅

### 8B.1 Why there is a seam at all

The ATS scorer, the autofix graph, and the LaTeX tailoring agent never name a
vendor — each takes an injectable `Agent` and works with whatever it is given.
`ai/provider.py` is the single place that decides who those agents talk to, so
supporting a second vendor meant adding one module and two mappings in
`core/config.py`, not editing every agent.

```
LLM_PROVIDER=anthropic  ──►  anthropic:claude-opus-5      ──┐
                                                            ├──►  Agent(...)
LLM_PROVIDER=google     ──►  google-gla:gemini-3.5-flash  ──┘
```

`ATS_MODEL` is the model id *within* the active provider, so the two are changed
together — a Claude id under `google` will not resolve. Pydantic AI addresses
the Gemini API as `google-gla` (Google Generative Language API), not `google`;
`google-vertex` is the separate Vertex AI path.

### 8B.2 The credential had to stop going through the environment

The original code returned a bare `"anthropic:{model}"` identifier and let the
SDK read `ANTHROPIC_API_KEY` from the process environment. That is a latent bug:
**`pydantic-settings` loads `backend/.env` into the `Settings` object without
exporting anything to `os.environ`**, so a key configured exactly the way the
README says to configure it was invisible to the SDK. It only ever worked when
the key was a real environment variable.

`resolve_model()` now hands the credential to the provider explicitly, and keeps
the bare-identifier path for deployments that genuinely do use environment
variables:

```python
GoogleModel(model, provider=GoogleProvider(api_key=key))    # key configured
"google-gla:gemini-3.5-flash"                               # no key: SDK reads env
```

The 503 guard follows the same principle — `require_llm_key()` names the
*active* provider's variable, so switching to Google does not send users hunting
for an Anthropic key.

### 8B.3 Rate limits are a correctness concern, not just a nuisance

Gemini's free tier allows **5 requests per minute per model**. One
`/latex/tailor` with scoring spends 3 calls; a 3-iteration autofix spends 6. A
single request can therefore exhaust a minute's budget and 429 *partway through*
— throwing away the calls already paid for.

`ai/limits.py` retries only on 429, and waits the interval the provider itself
asks for:

```
429 body → error.details[].retryDelay = "46s" → sleep(47) → retry
```

Honouring the server's own `RetryInfo` beats a guessed backoff: it is the API
telling us exactly when the window reopens. Exponential backoff is the fallback
for providers that give no hint. Every non-429 — a bad key, a schema violation,
a missing model — propagates immediately, because retrying those only delays the
error.

For the same reason, the two before/after scoring calls in `tailor_latex_resume`
were changed from `asyncio.gather` to sequential. Firing both at once doubles
the instantaneous request rate against a 5/min budget and reliably triggers a
throttle that then has to be waited out anyway; serialising costs one round trip
on an operation that already takes tens of seconds.

> This is **not** a rate limiter. Per-user spend ceilings remain an open gap
> (§15) — this only stops the app falling over when the provider pushes back.

---

## 8A. Phase 5 — LaTeX masters & template-preserving tailoring ✅

### 8A.1 The problem this solves

Phase 4 tailors a Markdown resume by asking the model to return a whole new
document. That works for content and is hopeless for *presentation*: the layout
is whatever the model decides to emit, and two tailored versions of the same
resume can look like two different resumes.

The requirement is the opposite: **one master template, many contentful
variants** — a Python-heavy version and a Rust-heavy version that are visually
indistinguishable side by side.

### 8A.2 Frozen bytes, not a re-rendered template

The design decision that makes this work is that a master `.tex` is **never
regenerated, only spliced**.

```
master.tex ──► parse ──► ┌─────────────────────────┐
                         │ FROZEN (byte spans)     │  documentclass, packages,
                         │                         │  \newcommand macros, geometry,
                         │                         │  fonts, section scaffolding,
                         │                         │  employers, titles, dates,
                         │                         │  degrees
                         ├─────────────────────────┤
                         │ EDITABLE (byte spans)   │  \item bodies
                         │  g1-b1, g1-b2 …         │  % jarvis:begin regions
                         │  r1, r2 …               │
                         └─────────────────────────┘
                                    │
             LLM sees ONLY the editable spans, keyed by id
                                    │
                                    ▼
        render(): walk spans back-to-front, splice new text in place
                                    │
                                    ▼
                            tailored.tex ──► tectonic ──► PDF
```

Because rendering copies every non-span byte through untouched, "same template"
is a **structural guarantee rather than a best effort**. Nothing in the pipeline
is capable of rewriting the preamble, so the preamble cannot drift. The test
`test_no_op_render_is_byte_identical` pins this: parsing and re-rendering with no
edits must reproduce the input byte for byte.

Working back to front matters — it means earlier offsets stay valid while later
ones are being rewritten, so the span map needs no re-basing mid-render.

### 8A.3 What counts as editable

Two extraction strategies, mirroring the dual-library philosophy of
`pdf_parser`: cover the common case automatically, and give the author an escape
hatch for the rest.

| Strategy | Finds | Why |
|---|---|---|
| **Bullets, automatic** | `\item` bodies in `itemize`/`enumerate`; `\resumeItem{…}` bodies between `\resumeItemListStart`/`End` | Covers stock LaTeX and the widely-copied "Jake's resume" template without configuration |
| **Marked regions, opt-in** | Anything between `% jarvis:begin <label>` and `% jarvis:end` | A skills line built from custom macros is not something a parser should guess at. The author widens the editable surface themselves |

**Everything else is frozen, and that boundary is a content decision, not a
parsing convenience.** Bullets and skill lines are what *should* differ between a
Python role and a Rust one. Employers, job titles, dates, and degrees are facts —
a tailoring pass must never be in a position to rewrite them. Truthfulness is
enforced by the parser's structure, not only by asking the model nicely.

Sections with no editable slots are reported back as `frozen_sections` in the
outline, which is how an author discovers they need to add a marker.

### 8A.4 Why the model is shown LaTeX, and what that costs

Bullets go to the model as LaTeX so a rewrite preserves the `\textbf{}` the
author already had. The cost is that model output is injected into a document we
then compile, so `services/latex/safety.py` sits in between:

- **Allowlist, never blocklist.** Only inline formatting commands a resume bullet
  legitimately needs are permitted, so a command nobody anticipated is refused by
  default rather than by omission.
- **Balanced braces.** An unbalanced fragment does not fail locally — it swallows
  the rest of the document and corrupts the very layout this feature protects.
- **Degrade, don't fail.** `coerce_fragment()` falls back to the model's words
  with markup stripped. Losing a `\textbf` in one bullet beats refusing to render
  the resume.

Compilation additionally runs `--untrusted`, because the document is
user-supplied and `\write18` would otherwise turn a resume upload into command
execution.

### 8A.5 Reusing the ATS scorer

`services/latex/plain_text.py` flattens a parsed resume to Markdown so Phases 2–4
work unchanged on LaTeX resumes — no second scorer, no LaTeX-aware embeddings.
The projection is deliberately lossy and one-way: it approximates what an ATS
extracts from the compiled PDF, which is exactly the right input for scoring, and
is never parsed back into LaTeX.

With `score: true`, `/latex/tailor` scores the master and the tailored version
concurrently so the caller can show the lift.

### 8A.6 Storage — no new table

A LaTeX master needs no table of its own:

- The **template is the master's `.tex`**, already in `resumes.content`, with
  `content_format = 'latex'` (migration `c7d2f1a4b830` widens the CHECK).
- The **master↔child link** is the existing `master_resume_id` self-reference.
- The **span map is derived** from the source on every request. Persisting it
  would only create a cache that can fall out of step with the document it
  describes.

Tailored children store their full rendered `.tex`, so every version compiles
standalone and diffs cleanly against its master.

### 8A.7 Human in the loop

`POST /latex/resumes/{id}/preview` applies an *already-reviewed* tailoring
without calling the model. It is deterministic and free, which is what makes
hand-editing practical: the client can take the `tailoring` object from a tailor
response, let the user fix a bullet, and re-render after every tweak.

### 8A.8 The engine belongs to the document

A resume that loads `fontspec` cannot compile under pdfLaTeX; one that calls
`\directlua` needs LuaLaTeX. With a single server-wide engine those masters
cannot coexist, so `resumes.latex_engine` stores it per document (NULL = follow
the server default).

**The engine is auto-detected at upload**, by scanning the preamble for packages
that pin the document to a family. Detection only ever *upgrades* — a document
with no special requirements keeps whatever the operator configured, because
second-guessing a deliberate choice for no reason is worse than doing nothing.
An explicit `latex_engine` on the upload always wins over detection.

| Document loads | Result |
|---|---|
| `luacode`, `luatexbase`, `\directlua` | `lualatex` — nothing else can run it |
| `fontspec`, `unicode-math`, `polyglossia`, `xeCJK` | Unicode engine required; `pdflatex` is lifted to `xelatex`, but `tectonic` is left alone because it is XeTeX-based and already handles them |
| Nothing special | The server default, unchanged |

A known-bad pairing is caught **before** the engine runs, both in the outline
(`engine_warning`) and at render time (a 422 naming the package). A one-line
"this needs XeLaTeX" beats a hundred lines of TeX log.

**Tailored children inherit their master's engine.** A child renders from the
master's template, so it has to compile the same way — inheriting the engine is
part of what keeps the two visually identical.

#### The allowlist is a security boundary

The stored value becomes `argv[0]` of a subprocess, so it is constrained at
three layers, and widening the set of engines means widening all three:

```
Pydantic Literal  ──►  ENGINE_NAMES frozenset  ──►  ck_resumes_latex_engine
(rejects at the        (validate_engine, before      (the database refuses
 wire boundary)         shutil.which)                 anything else)
```

A caller-supplied **path** is never executed. Pointing at a binary somewhere
unusual stays `LATEX_ENGINE_PATH` — operator configuration, not user data.

### 8A.9 Engine choice

Tectonic — one self-contained binary that fetches the packages a document needs
on first compile, rather than a multi-gigabyte TeX distribution or a Docker image
(blocked on this machine; see §15). The first compile on a new machine is slow
and needs network; afterwards it works from its local cache. `GET /latex/status`
reports availability and install instructions, and is advisory rather than a
gate — parsing and tailoring work fine without an engine, only the PDF step
needs one.

`LATEX_ENGINE_PATH` also accepts `latexmk`, `xelatex`, `lualatex` or
`pdflatex`; the compiler builds the right argument list per engine. It sets the
*default* — per-resume overrides live in `resumes.latex_engine` (§8A.8).

---

## 9. Frontend design

### 9.1 Structure

Angular 22, standalone components throughout — no NgModules. State lives in
signals; there is no NgRx, because a fetch-then-mutate CRUD app doesn't need a
global store and the ceremony would outweigh the benefit.

```
core/models/     TS interfaces mirroring backend schemas 1:1
core/services/   Typed HttpClient wrappers, one per resource
layout/          Dashboard shell (sidenav + router-outlet)
kanban/          board → column → card
matches/         "Companies to Chase"
ats/             ATS report + autofix panel
```

### 9.2 Type parity as the contract

Every backend Pydantic schema has a matching TypeScript interface. Discriminated
unions are mirrored as literal unions, so a typo is a compile error:

```typescript
export type Severity = 'critical' | 'important' | 'nice_to_have';
export type StoppedBecause = 'target_reached' | 'no_further_gains' | 'max_iterations';
```

This parity is manual and therefore a real maintenance cost — see
[§16](#16-extending-the-system) for the generated-client alternative.

### 9.3 Kanban drag-and-drop

Angular CDK. Each column is a `cdkDropList` connected to the other three. On drop:

1. **Optimistic update** — `transferArrayItem` moves the card immediately.
2. **Persist** — `PATCH /applications/{id}/stage`.
3. **Revert on failure** — restore prior stage/position and re-fetch.

Optimistic-then-reconcile keeps dragging responsive; the revert path means a
failed write never leaves the UI lying about persisted state.

### 9.4 The ATS panel

The interactive loop from the blueprint:

- **Score badge** colour-coded by band (`strong` ≥85, `moderate` ≥65, `weak`).
- **Keyword chips** — matched (green) vs missing, tinted by severity.
- **Suggestion list** with per-item checkboxes and a strikethrough before/after
  diff, so a user can accept rewrites individually rather than all-or-nothing.
- **Autofix** runs the LangGraph loop and reports the score delta, iteration
  count, and termination reason.

---

## 10. End-to-end request flows

### 10.1 Resume PDF upload ✅

```
User picks PDF
  → POST /api/v1/resumes/parse-pdf   (multipart, 10 MB cap)
      → pdfplumber → (fallback) pypdf
      → _normalize() → to_markdown()
  → {filename, character_count, content_markdown}
  → Angular fills the content textarea (title auto-derived if blank)
  → user REVIEWS and edits
  → POST /api/v1/resumes             (normal CRUD create)
```

Parsing and persistence are separate steps on purpose — extraction is imperfect,
so a human checkpoint sits between them.

### 10.2 Semantic job matching 🟡

```
POST /api/v1/matching/reindex
  → for each job_profile: build text → embed → upsert (skip if unchanged)
  → for each user with career_goals: embed → upsert

GET /api/v1/users/{id}/job-matches?limit=10
  → load user; 400 if no career_goals
  → embed career_goals
  → cosine search over entity_type='job_profile'
  → batch-load JobProfiles + Companies (no N+1)
  → [{similarity, job_profile, company}, …] ordered best-first
```

### 10.3 ATS scoring 🟡

```
POST /api/v1/ats/score {resume_id, job_profile_id}
  → 503 early if no ANTHROPIC_API_KEY
  → load resume + job (404 if either missing)
  → Pydantic AI agent → Claude → validated ATSReport
  → render score, keywords, suggestions
```

### 10.4 Autofix loop 🟡

```
POST /api/v1/ats/autofix {resume_id, job_profile_id,
                          target_score, save_as_tailored_version}
  → LangGraph:
        score  →  decide  →  rewrite  →  score  →  decide  →  END
  → optionally persist as tailored child of the master
  → {original_score, final_score, iterations, stopped_because,
     revised_resume_markdown, applied_suggestions, final_report}
```

---

## 11. Setup & running

### 11.1 Prerequisites

| Tool | Purpose |
|---|---|
| Python 3.12 + [uv](https://docs.astral.sh/uv/) | Backend |
| Node.js LTS + npm | Frontend |
| PostgreSQL 16 | Database — installed natively, no container |

### 11.2 Postgres

```powershell
winget install PostgreSQL.PostgreSQL.16
psql -U postgres -h 127.0.0.1 -c "CREATE ROLE jarvis LOGIN PASSWORD 'jarvis_dev_password';"
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE jarvis      OWNER jarvis;"
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE jarvis_test OWNER jarvis;"
```

### 11.3 Backend

```powershell
cd backend
uv sync
copy .env.example .env
uv run alembic upgrade head          # every migration, pgvector or not
uv run uvicorn app.main:app --reload
```

`upgrade head` applies cleanly on a Postgres without pgvector: the two
vector-dependent revisions detect the missing extension and skip their DDL
(§4.5), leaving the relational schema complete. Semantic matching is the only
thing that degrades, and it answers 503 rather than failing obscurely.

### 11.4 Frontend

```powershell
cd frontend
npm install
npm start                            # http://localhost:4200
```

### 11.5 Optional capabilities

```powershell
# Local embeddings (no API key, ~offline)
cd backend && uv sync --extra local-embeddings

# ATS + autofix
#   backend/.env:
#   ANTHROPIC_API_KEY=sk-ant-...
```

---

## 12. Configuration reference

All values are settable via environment variable or `backend/.env`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://jarvis:…@localhost:5432/jarvis` | Must use the `asyncpg` driver |
| `CORS_ORIGINS` | `http://localhost:4200` | Comma-separated |
| `EMBEDDING_PROVIDER` | `local` | `local` · `voyage` · `openai` · `gemini` |
| `EMBEDDING_DIM` | `384` | **Must match the model**; baked into the migration |
| `LOCAL_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model id |
| `VOYAGE_API_KEY` / `VOYAGE_MODEL` | – / `voyage-3` | |
| `OPENAI_API_KEY` / `OPENAI_EMBEDDING_MODEL` | – / `text-embedding-3-small` | |
| `LLM_PROVIDER` | `anthropic` | `anthropic` · `google`. Selects the vendor for ATS scoring, autofix, and tailoring |
| `ANTHROPIC_API_KEY` | – | Required when `LLM_PROVIDER=anthropic` |
| `GOOGLE_API_KEY` | – | Required when `LLM_PROVIDER=google` |
| `LLM_MAX_RETRIES` | `3` | 429 retries; Gemini's free tier is 5 req/min |
| `LLM_RETRY_MAX_WAIT_SECONDS` | `65` | Ceiling on a single backoff wait |
| `JARVIS_ENV_FILE` | `.env` | Which env file to load. The test suite points this at nothing to stay hermetic |
| `ATS_MODEL` | `claude-opus-5` | Model id *within* the active provider — change it together with `LLM_PROVIDER` |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | Used when `EMBEDDING_PROVIDER=gemini` |
| `ATS_MAX_AUTOFIX_ITERATIONS` | `3` | Cost ceiling — each iteration is 2 LLM calls |
| `LATEX_ENGINE_PATH` | `tectonic` | Server **default** only; binary name or absolute path. Per-resume overrides live in `resumes.latex_engine` |
| `LATEX_COMPILE_TIMEOUT_SECONDS` | `120` | Tectonic's *first* run downloads packages and may need more |
| `LATEX_MAX_UPLOAD_BYTES` | `2097152` | Upload ceiling for a `.tex` master |
| `LATEX_SECTION_MACROS` | `section,subsection,cvsection,resumeSection,heading` | Extend when your resume class defines its own section macro |

> ⚠️ **`EMBEDDING_DIM` is not runtime-tunable.** It is compiled into the
> `vector(N)` column by migration `a89449bbaeeb`. Changing providers to one with
> a different dimension requires a new migration plus a full re-index.

---

## 13. Testing strategy

**118 backend tests, all passing.**

| File | Covers | Approach |
|---|---|---|
| `test_applications.py` | Company CRUD, application lifecycle, stage moves | Real Postgres |
| `test_pdf_parser.py` | Extraction, Markdown conversion, error paths | **Real PDFs** generated with reportlab |
| `test_embeddings.py` | Provider interface contract, factory validation | Stub provider |
| `test_ai.py` | ATS scoring, all 4 autofix exit paths | Pydantic AI `FunctionModel` |
| `test_matching.py` | 503 degradation contract, validation | Real Postgres, no pgvector |
| `test_latex.py` | Parsing, splice rendering, safety allowlist, projection, tailoring | Real `.tex` documents; `FunctionModel` for the LLM |
| `test_latex_api.py` | Upload/outline/render/preview/engine endpoints, format, key and allowlist guards | Real Postgres; **real Tectonic** for the PDF test |
| `test_latex_engines.py` | Engine detection, compatibility warnings, allowlist rejection | Pure functions over real `.tex` preambles |
| `test_ai_provider.py` | Provider selection, credential plumbing, 429 retry, Gemini embedding normalisation | Fake agents; `asyncio.sleep` patched so backoff is instant |

The LaTeX suite's load-bearing assertion is
`test_no_op_render_is_byte_identical` — parse-then-render with no edits must
reproduce the input exactly. Every "the template is preserved" claim in §8A
reduces to that property plus the span map being correct.

`test_render_produces_a_pdf` compiles with a real engine and is skipped
(not failed) when none is installed, so the suite stays green on a machine
without Tectonic while still proving the path where one exists.

### Principles

**Test against real infrastructure where possible.** DB tests hit real
PostgreSQL, PDF tests parse real generated PDFs. Mocks are reserved for the
paid/keyed boundary (the LLM).

**Mock at the model layer, not the function layer.** `FunctionModel` lets tests
drive scores per call while the *real* Pydantic AI validation, the *real*
LangGraph traversal, and the *real* prompt construction all execute:

```python
def _scoring_model(scores: list[int]) -> FunctionModel:
    """Returns each score in turn, then repeats the last."""
```

`_scoring_model([60, 90])` proves the loop exits on `target_reached` after
exactly one iteration.

**Assert the degradation contract.** Several tests exist purely to ensure
unconfigured optional dependencies produce **503, not 500** — the regression that
was actually found and fixed during development.

**Windows/asyncpg gotcha:** `pyproject.toml` pins
`asyncio_default_fixture_loop_scope = "session"`. Without it, pytest-asyncio
creates a fresh event loop per test while the engine stays bound to the first —
producing `RuntimeError: Event loop is closed` under `ProactorEventLoop`.

### Frontend

`ng build` type-checks under `strict: true`. Kanban drag-and-drop persistence was
verified live with Playwright: dragged a card across columns, confirmed the PATCH
fired, reloaded the page, and confirmed the card stayed put.

---

## 14. Design decisions & trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Vector storage | Separate polymorphic table | Column on `users`/`job_profiles` | Isolates an optional extension; enables staleness detection and provider migration. **Cost:** an extra join, no FK on `entity_id`. |
| Stage representation | VARCHAR + CHECK | Postgres ENUM | Pipeline stages will grow; widening a CHECK is one line. |
| Tech stack | Lookup + join tables | JSON array column | Makes "which companies use Python?" a join, not a scan. **Cost:** more tables, more joins. |
| Embeddings | Provider interface | Hard-code one vendor | Anthropic has no embeddings API; local default means zero keys to start. **Cost:** an abstraction layer. |
| Autofix control flow | LangGraph | `while` loop | Cyclic flow with conditional exits is what a graph is for; nodes stay independently testable. **Cost:** a dependency and its state-copy semantics. |
| LLM provider | A seam in `ai/provider.py` | Hard-code one vendor | The agents already took an injectable `Agent`; one module and two mappings made a second vendor a config change rather than a refactor. |
| Provider credential | Passed explicitly to the provider | Let the SDK read the environment | `pydantic-settings` never exports `.env` to `os.environ`, so the documented way to configure a key silently did not reach the SDK. |
| Rate limits | Retry on the provider's own `RetryInfo` | Fixed backoff, or surface the 429 | The API states when the window reopens; guessing is either too slow or too eager. A partial failure would discard calls already paid for. |
| LLM output | Pydantic AI structured output | Prompt "return JSON" + parse | Schema violations are retried in-library, not debugged in prod. |
| Frontend state | Signals | NgRx | Fetch-then-mutate CRUD doesn't justify a global store. |
| PDF parsing | pdfplumber → pypdf | Either alone | They fail on different malformed files; trying both raises the success rate. |
| LaTeX tailoring | Splice byte spans in the original | Regenerate the .tex from a structured model | Splicing makes "same template" a structural guarantee. Regeneration means every macro the author used has to be modelled — and anything unmodelled silently changes the layout. |
| LaTeX editable surface | Bullets + opt-in markers | Extract every text run | Employers, titles, and dates must be *unreachable*, not merely discouraged. Narrowing the surface enforces truthfulness in the parser rather than in the prompt. |
| LLM sees bullets as | LaTeX, then validated | Plain text, then escaped | Escaping everything would strip the author's own `\textbf` on each pass. Validation preserves it; `coerce_fragment()` falls back to escaped plain text when a fragment fails. |
| LaTeX engine | Tectonic | MiKTeX / TeX Live | One ~50 MB binary that fetches packages on demand, versus multi-GB installs. |
| API key handling | Read at call time | Client at import | The app must import and serve CRUD with no credentials configured. |

### The recurring theme: graceful degradation

Three optional dependencies — pgvector, an embedding provider, an Anthropic key —
are each independently absent-able. The design consequence:

- Missing dependencies are **checked at the boundary**, not deep in a call stack.
- Every failure message is **actionable** — it names the exact command to run.
- Degradation is **tested**, so a refactor can't silently turn a 503 into a 500.
- Core CRUD stays **fully functional** regardless.

---

## 15. Known gaps & blockers

### Environment blockers (not code defects)

| Blocker | Cause | Unblock |
|---|---|---|
| **pgvector unavailable** | A stock Postgres install ships no `vector` extension, and pgvector publishes no prebuilt Windows binary. | Build pgvector against the local Postgres with an MSVC toolchain, or move vector storage off Postgres entirely. |
| **No live LLM verification** | No `ANTHROPIC_API_KEY` configured. | Set the key; the code path is unchanged. |
| **Local embeddings uninstalled** | `fastembed` is an optional extra. | `uv sync --extra local-embeddings` |

Migration `a89449bbaeeb` has therefore **never created its table** here — it
detects the absent extension and skips. Its `CREATE TABLE` is reviewed but
unproven; expect to debug it the first time it runs against a real pgvector.

### Functional gaps ⛔

| Gap | Impact |
|---|---|
| **No "create application" UI** | Kanban cards can only be created via the API (`/docs`). The board displays and moves them, but a user can't start tracking a job from the browser alone. **This is the largest usability gap.** |
| **No authentication** | Single-user assumption. `user_id` is passed explicitly; there is no session, no authorization, no multi-tenancy. |
| **Free-tier rate limits bite** | Gemini's free tier is 5 requests/minute. `ai/limits.py` waits these out, so a scored `/latex/tailor` (3 calls) or a 3-iteration autofix (6 calls) *succeeds but is slow*. A paid key or a lighter model removes the stall. |
| **Suggestion checkboxes are display-only** | The ATS panel lets a user tick individual suggestions, but "apply selected" isn't wired — autofix currently applies its own prioritisation. |
| **No LaTeX UI** | Phase 5 is API-only. Upload, outline review, bullet editing, and PDF preview all work through `/docs`, not the browser app. |
| **Markdown resumes still have no PDF export** | Phase 5 gives PDF output to *LaTeX* masters. A Markdown resume has no template to compile, so `PDF in → optimised → PDF out` is closed only for the LaTeX path. |
| **Tailoring only reaches bullets and marked regions** | By design (§8A.3), but it means a resume whose skills line is built from custom macros needs a `% jarvis:begin` marker added by hand before that line can be tailored. |
| **No user CRUD UI** | Users must be created via the API. |
| **`to_markdown()` is heuristic** | Multi-column and heavily-styled resumes will extract imperfectly. |
| **Cost is unbounded per request** | Nothing rate-limits autofix. A user can spend real money in a loop. |

---

## 16. Extending the system

### Adding a new embedding provider

1. Subclass `EmbeddingProvider` in `app/embeddings/remote.py`.
2. Add the name to `EmbeddingProviderName` in `core/config.py`.
3. Register it in `build_provider()`.
4. Set `EMBEDDING_DIM` to the model's dimension — **and write a migration** if it
   differs from the current column.

### Adding a new embeddable entity

1. Add the name to `EMBEDDABLE_ENTITIES` and the CHECK constraint.
2. Widen the constraint in a migration.
3. Write a `build_*_text()` function to define what gets embedded.
4. Extend `/matching/reindex`.

No new table, no new column.

### Adding a pipeline stage

1. Widen the `applications.stage` CHECK constraint (one-line migration).
2. Add it to `Stage` in `app/schemas/application.py`.
3. Add it to `STAGES` / `STAGE_LABELS` in `application.model.ts`.

The Kanban board renders columns from `STAGES`, so the UI follows automatically.

### High-value next steps

1. **"New Application" form** — closes the biggest usability gap.
2. **Apply-selected-suggestions** — wire the existing checkboxes to a targeted
   rewrite; cheaper and more controllable than a full autofix.
3. **PDF export** — completes the round trip (PDF in → optimised → PDF out).
4. **Generated API client** — replace hand-maintained TS interfaces with a client
   generated from the OpenAPI schema, eliminating drift.
5. **Authentication** — required before this is anything but single-user.
6. **Background jobs** — move autofix to a task queue; multi-iteration loops are
   too slow for a synchronous HTTP request.
7. **Cost guardrails** — per-user rate limits and a spend ceiling.

---

## Appendix A — Command reference

```powershell
# Backend
cd backend
uv sync                                   # install
uv sync --extra local-embeddings          # + local embeddings
uv run uvicorn app.main:app --reload      # serve → :8000
uv run pytest -q                          # test  (28 passing)
uv run alembic upgrade head               # migrate
uv run alembic history                    # migration chain
uv run alembic downgrade base             # reset

# Frontend
cd frontend
npm install
npm start                                 # serve → :4200
ng build                                  # type-check + bundle
ng test --watch=false                     # unit tests
```

## Appendix B — Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `can't subtract offset-naive and offset-aware datetimes` | Model/migration timezone mismatch | Add `sa_type=DateTime(timezone=True)` |
| `RuntimeError: Event loop is closed` in tests | Per-test event loops vs a session engine | `asyncio_default_fixture_loop_scope = "session"` |
| `relation "entity_embeddings" does not exist` | Vector migration skipped — no pgvector on this server | Install pgvector, then create the table; `alembic upgrade head` won't replay a stamped revision |
| `503 … requires fastembed` | Optional extra not installed | `uv sync --extra local-embeddings` |
| `503 … needs an Anthropic API key` | No key configured | Set `ANTHROPIC_API_KEY` |
| `WSL2 is unable to start… virtualization is not enabled` | BIOS setting | Enable VT-x / AMD-V in firmware |
| Angular can't reach the API | CORS | Add the origin to `CORS_ORIGINS` |
