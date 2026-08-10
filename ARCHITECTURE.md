# AI-Centric Interview Tracker & Resume Optimizer — Architecture

> A working reference for how this system is built and why, at a level useful
> for extending it. For step-by-step setup, see [README.md](README.md).
>
> **Status legend:** ✅ implemented and verified · 🟡 implemented, verification blocked · ⛔ not built

---

## Table of Contents

1. [What this project is](#1-what-this-project-is)
2. [System architecture](#2-system-architecture)
3. [Repository layout](#3-repository-layout)
4. [Data model](#4-data-model)
5. [The resume flow — upload, review, resolve, score](#5-the-resume-flow--upload-review-resolve-score)
6. [Template-preserving LaTeX tailoring](#6-template-preserving-latex-tailoring)
7. [Semantic matching](#7-semantic-matching)
8. [The LLM provider seam](#8-the-llm-provider-seam)
9. [Authentication, scope & moderation](#9-authentication-scope--moderation)
10. [Frontend design](#10-frontend-design)
11. [Testing strategy](#11-testing-strategy)
12. [Configuration reference](#12-configuration-reference)
13. [Design decisions & trade-offs](#13-design-decisions--trade-offs)
14. [Known gaps](#14-known-gaps)
15. [Extending the system](#15-extending-the-system)

---

## 1. What this project is

| Pain point | What this system does about it |
|---|---|
| Which companies should I even chase? | Embeds career goals and job descriptions into a shared vector space and ranks openings by semantic similarity, not keyword overlap. |
| Rewriting my resume for every role is soul-destroying. | One **master resume** plus AI-generated **tailored child versions**, each targeted at a specific job. |
| Every tailored version looks like a different resume. | The master's LaTeX is split into frozen template bytes and editable content slots. Tailoring rewrites only the slots, so every version is visually identical (§6). |
| I don't know why the ATS rejected me. | Produces a 0–100 match score, names missing keywords, and proposes verbatim line-level rewrites. |
| Did the tailoring actually help? | A tailored version is scored in its own right and the score is cached, so checking it is a database read. Reviewing it again is how the score gets raised — each round saved as a sibling version (§5). |

### Core design principle

> **Relational data stays relational. Documents stay documents. Vectors stay isolated.**

Companies, jobs, and their relationships use real foreign keys and CHECK
constraints, never JSON blobs. Resume *bodies* are documents (LaTeX), because
that's genuinely what they are. Vectors live in their own table so an optional
extension can't destabilize the core schema.

---

## 2. System architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│  Angular SPA  (standalone components, signals)                        │
│  Resumes · Jobs · Companies · Chase                                   │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ HTTP/JSON  (CORS-gated, bearer token)
                                ▼
┌───────────────────────────────────────────────────────────────────────┐
│  FastAPI  (fully async)                                               │
│                                                                       │
│  routers/ ──► crud/ ──► SQLModel ──► asyncpg ──► PostgreSQL           │
│      │                                                                │
│      ├──► services/matching     (pgvector cosine search)              │
│      ├──► embeddings/           (local | Voyage | OpenAI | Gemini)    │
│      ├──► services/latex/       (.tex span map → splice → HTTP call)  │
│      ├──► ai/provider.py        (Claude | Gemini selection)        │
│      ├──► ai/intake, review     (Pydantic AI → the chosen LLM)        │
│      ├──► ai/score.py           (score only — no patches, faster)     │
│      ├──► services/review.py    (propose → resolve → splice)         │
│      └──► services/scoring.py   (cache the verdict; label it stale)   │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
     ┌────────────────┐  ┌──────────────┐  ┌───────────────┐
     │  PostgreSQL    │  │  Gemini API  │  │  Embedding    │
     │  + pgvector    │  │      or      │  │  provider     │
     │  (Docker)      │  │  Claude API  │  │               │
     └────────────────┘  └──────────────┘  └───────────────┘
```

PDF compilation is a fourth external dependency, not shown above: a long-lived
LaTeX worker service that every engine (pdflatex, xelatex, lualatex, latexmk)
runs inside (§6.5).

### Why this stack

| Choice | Reasoning |
|---|---|
| FastAPI, all-async | The workload is I/O-bound end to end — DB round-trips, embedding calls, multi-second LLM calls. Async keeps one worker responsive while several reviews are in flight. |
| SQLModel | One class defines both the table and its Pydantic base. Distinct `Create`/`Update`/`Read` schemas are still hand-written so table models are never exposed on the wire. |
| PostgreSQL + pgvector | Relational integrity *and* vector search in one system — no separate vector DB to sync. |
| Pydantic AI | Turns "ask the LLM for JSON and pray" into a validated, typed object; schema violations retry at the library layer. |
| Angular standalone + signals | No NgModule ceremony. Signals give fine-grained reactivity without RxJS overhead a CRUD app doesn't need. |

---

## 3. Repository layout

```
Jarvis/
├── backend/
│   ├── app/
│   │   ├── main.py, deps.py        FastAPI app; SessionDep / CurrentUser / AdminUser
│   │   ├── core/                   config, Argon2 + JWT, login throttling, DB engine
│   │   ├── models/                 SQLModel tables
│   │   ├── schemas/                wire contracts (Create/Update/Read)
│   │   ├── crud/                   async data-access functions
│   │   ├── routers/                HTTP surface
│   │   ├── services/
│   │   │   ├── matching.py         embedding storage + cosine search
│   │   │   ├── slug.py             company-name normalization (the dedupe key)
│   │   │   ├── intake.py           correct → validate → compile an upload
│   │   │   ├── review.py           propose → resolve → splice
│   │   │   ├── scoring.py          cache a verdict; never refresh on read
│   │   │   └── latex/              span-map parser, splice renderer, safety
│   │   │                           allowlist, engine detection, worker HTTP client
│   │   ├── embeddings/             provider abstraction (local | Voyage | OpenAI | Gemini)
│   │   └── ai/                     intake / review / score / patch-revision agents,
│   │                               provider resolution, 429 retry handling
│   ├── alembic/versions/           migrations
│   └── tests/
├── frontend/
│   └── src/app/
│       ├── core/                   models, typed HTTP services, auth interceptor + guard
│       ├── auth/ profile/ admin/   sign-in, self-service account, moderation queue
│       ├── layout/                 dashboard shell
│       ├── companies/ jobs/        moderated shared data
│       ├── resumes/                detail screen, score panel, review panel, patch cards
│       └── matches/                "Companies to Chase"
└── latex-worker/                   the LaTeX engine image + its HTTP server (§6.5) —
                                     a peer service, not a backend subcomponent
```

**Layering rule:** `router → crud/services → models → database`. Routers
handle HTTP concerns only — validation, status codes, error translation. They
never build SQL. Services never raise `HTTPException`; they raise domain
errors (`PdfParseError`, `EmbeddingError`, `VectorSearchUnavailableError`) that
routers translate. This keeps services callable from tests and scripts without
dragging FastAPI along.

---

## 4. Data model

```
                          ┌──────────┐
                          │  users   │
                          └────┬─────┘
         ┌─────────────────────┴─────────────────────┐
         ▼                                           ▼
   ┌──────────┐                            ┌────────────────┐
   │ resumes  │◄───────────────────────────┤ resume_reviews │
   │ (master  │  source / child            └───────┬────────┘
   │  or      │◄───────┐                           ▼
   │  tailored│        │                  ┌────────────────┐
   │  child)  │        │                  │ resume_patches │
   └────┬─────┘        │                  └────────────────┘
        │         ┌─────┴──────┐
        └────────►│resume_     │
        (job) ────►│scores      │
                   └────────────┘
                        ▲
                        │
                ┌──────────────┐         ┌─────────────┐
                │ job_profiles │────────►│  companies  │
                └──────────────┘         └─────────────┘

        ┌────────────────────────────────────────────┐
        │ entity_embeddings   (pgvector — isolated)  │
        │ polymorphic: entity_type + entity_id       │
        └────────────────────────────────────────────┘
```

**`users`** is the account and the job seeker; `career_goals` doubles as the
embedding source for matching.

**`companies`** / **`job_profiles`** are public, community-contributed, and
admin-moderated (§9). Identity is derived, not asserted: companies dedupe on a
normalized `slug`, job profiles on `(company, external_job_id)` — see §9 for
why a plain `name`/`id` uniqueness rule doesn't hold.

**`resumes`** is the versioning model: a self-referencing `master_resume_id`
(`NULL` ⇒ this row *is* a master) keeps the tree exactly one level deep,
however many tailoring rounds a master goes through. Content is LaTeX by
construction — `.tex` is the only accepted upload format.

**`resume_reviews`** / **`resume_patches`** record one round of AI-proposed
edits against one resume and one job: one review, many patches, each `pending`
until accepted, rejected, or revised. Nothing is written to a resume until
every patch has a decision (§5).

**`resume_scores`** caches one ATS verdict per (resume, job) pair, fingerprinted
against the content it was computed from so a stale read is labeled rather than
silently served or silently refreshed (§5).

**`entity_embeddings`** stores vectors for users/jobs/companies/resumes in one
polymorphic table (`entity_type` + `entity_id`, no FK — see §7 for why),
keeping the optional pgvector dependency isolated from the core schema.

**`refresh_tokens`** / **`audit_logs`** support session rotation and
privileged-action logging (§9.5).

Migrations live in `backend/alembic/versions/`; run `alembic history` for the
current chain. Two revisions are pgvector-dependent and detect a missing
`vector` extension rather than aborting the chain (§7) — everything else in the
schema is unaffected either way.

---

## 5. The resume flow — upload, review, resolve, score

There is exactly one way a resume moves through this system:

```
   a .tex file
        │
        ▼
   POST /resumes/upload ──── 1 LLM call: {find,replace} corrections + slot vocabulary
        │  applied by exact match, then validated, parsed, and compiled
        ▼
   a stored master
        │
        ▼
   POST /resumes/{id}/reviews ──── 1 LLM call: ATS score + one patch per proposed edit
        │
        ▼
   a review — every patch starts `pending`
        │   accept / reject / revert  — free, no model call
        │   feedback                  — 1 LLM call, one patch only
        ▼
   pending_count == 0   ◄──── the gate: preview and finalize both 409 until this holds
        │
        ▼
   preview (free) ──► finalize ──► a tailored version (a sibling, never a grandchild)
                                          │
        ┌─────────────────────────────────┤
        ▼                                 ▼
   POST /resumes/{id}/scores       POST /resumes/{id}/reviews
   cheap: cached forever            the same call again — another round,
   after the first check            same master, next sibling version
```

The loop at the bottom is the point of the flow, not a footnote: a tailored
resume has an ATS score of its own, and raising it is another review round
against the same job, saved beside its predecessor.

**One call does two things, deliberately.** Upload returns corrections *and*
the slot vocabulary in one LLM call, because both need the same expensive
understanding of the specific template. Review returns the ATS score *and*
every proposed patch in one call, because scoring and tailoring are the same
judgment — asking twice invited the two answers to disagree, which used to
happen when they were separate endpoints.

**Corrections are scoped, never a rewrite.** The model returns `{find, replace,
reason}`, applied by exact, unique, non-overlapping match — never the whole
document back. A model that returns "here is your resume again, slightly
different everywhere" cannot be reviewed; a model that names one line can.

**The gate is enforced server-side, in one place**
(`services/review.spliced_source`), not by the client hiding a button. That is
what makes "the author reviewed this" a fact the server knows.

**Rejecting a patch is the absence of an edit**, not an edit that undoes one —
the renderer simply isn't given that slot, so the master's own bytes pass
through untouched.

**Scoring is deliberately not refreshed on read.** A `content_hash`
(content + slot config) is compared on every read; a mismatch is reported as
`stale: true` with the old number still attached, rather than spending a model
call every time a resume screen opens.

What each step costs, in LLM calls: upload 1, review 1, accept/reject/revert 0,
feedback 1 (one patch only), preview 0, finalize 0, score (cached & current) 0,
score (stale or uncached) 1.

---

## 6. Template-preserving LaTeX tailoring

### 6.1 Frozen bytes, not a re-rendered template

A master `.tex` is **never regenerated, only spliced**:

```
master.tex ──► parse ──► FROZEN spans (preamble, macros, geometry, fonts,
               │          employers, titles, dates, degrees)
               │
               │          EDITABLE spans (bullet bodies, opt-in marked regions)
               │          — the only thing an LLM ever sees or rewrites
               ▼
        render(): walk spans back-to-front, splice new text in place
               ▼
        tailored.tex ──► an engine (§6.5) ──► PDF
```

Because rendering copies every non-span byte through untouched, "same
template" is a structural guarantee, not a best effort — nothing in the
pipeline is *capable* of rewriting the preamble. A regression test pins this:
parsing and re-rendering with no edits must reproduce the input byte for byte.

### 6.2 What counts as editable

Four extraction strategies, cheapest/most-automatic first: bullets inside
list environments (covers stock LaTeX and the widely-copied "Jake's Résumé"
template with no configuration), standalone bullet macros, one named argument
of a multi-argument macro (e.g. the prose field of `\cventry{…}{…}{…}{prose}`),
and — the escape hatch for anything else — text between
`% jarvis:begin <label>` / `% jarvis:end` markers the author adds by hand.

Everything else is frozen **by design, not by accident**: employers, titles,
dates, and degrees are facts a tailoring pass must never be in a position to
rewrite. Truthfulness is enforced by the parser's structure, not just by
prompting the model nicely.

### 6.3 Two hashes keep the guarantee honest

- **`slot_hash`** (per editable slot) answers "is this edit still about the
  text it was written for?" — since slot ids are positional, a mismatch here
  (the master changed underneath a stale review) is a **409**, telling the
  caller to re-read the outline rather than splicing into the wrong bullet.
- **`template_hash`** (per document, over every frozen byte) is checked
  automatically after every render; a mismatch is a **500** (`TemplateDriftError`)
  and the output is discarded — reaching it means the splice logic itself is
  broken, not that the caller did anything wrong.

### 6.4 What the model is shown, and the safety net around it

Bullets go to the model as LaTeX (so a rewrite preserves the author's own
`\textbf{}`), which means model output gets injected into a document that then
compiles. `services/latex/safety.py` allowlists inline formatting commands
(never blocklists), validates brace balance, and degrades to plain text with
markup stripped rather than failing the whole render. Compilation also runs
`--untrusted`, since the document is user-supplied.

### 6.5 Engines run in one Docker image, per-document

`resumes.latex_engine` is chosen per document (auto-detected from the preamble
at upload — e.g. `\directlua` forces LuaLaTeX, `fontspec` forces a Unicode
engine — and only ever upgraded, never silently downgraded). Tailored children
inherit their master's engine, since they compile from the same template.

Every engine (pdflatex, xelatex, lualatex, latexmk) runs inside one curated
Docker image (`latex-worker/`) — a `scheme-basic` TeX Live install plus just
the collections resume templates actually need, not `scheme-full`'s ~4-5GB.
Nothing is installed on the host. Every invocation runs `-no-shell-escape`:
the document is untrusted (uploaded, then rewritten by an LLM), and LaTeX's
shell-escape feature is exactly the kind of thing that turns "compile a
resume" into command execution — the container boundary around the whole
service is belt-and-suspenders on top of this, not a substitute for it.

**The image runs as its own long-lived HTTP service, not something the backend
creates or execs into.** A small stdlib-only server (`latex-worker/server.py`)
wraps the engines behind three routes — `GET /health`, `GET /engines`,
`POST /compile` — and `services/latex/compiler.py` is nothing more than an
HTTP client for it, configured with `LATEX_WORKER_URL`. `docker-compose.yml`
runs it as the `latex-worker` service; for native development, start the image
once as a standalone container publishing port 8100 and the default URL finds
it unchanged.

This replaced an earlier design where the backend managed the worker
container's entire lifecycle itself — `docker run` to create it, `docker exec`
into it per compile, health-probing and recreating it on drift — which meant
the backend needed the same control over Docker an operator's own user account
has (a shared Docker socket, once the backend itself ran in a container).
Compiling untrusted `.tex` still happens in its own disposable process, exactly
as before; the backend just no longer needs the power to *create* containers
to make that happen, which is a much smaller thing to trust it with, and it
means one fewer host dependency (no `docker` CLI inside the backend image).
`GET /resumes/engine-status` reports what the worker says is actually
available.

---

## 7. Semantic matching

Deliberately independent of the resume flow: matching reads a user's career
goals and ranks job profiles against them by cosine similarity over pgvector —
it never touches a resume.

Embeddings go through a small provider interface
(`EmbeddingProvider.embed(texts) -> vectors`) rather than a hard-coded vendor,
because Anthropic has no embeddings endpoint of its own:

| Provider | Model | Dim | Key |
|---|---|---|---|
| `local` *(default)* | `BAAI/bge-small-en-v1.5` via fastembed (ONNX) | 384 | none |
| `voyage` | `voyage-3` | 1024 | `VOYAGE_API_KEY` |
| `openai` | `text-embedding-3-small` | 1536 | `OPENAI_API_KEY` |
| `gemini` | `gemini-embedding-2` | configurable | `GOOGLE_API_KEY` |

Vectors live in their own polymorphic table (`entity_embeddings`), not a column
on `users`/`job_profiles`, for four reasons: the optional pgvector extension
can't destabilize core queries; one table serves every embeddable entity type;
storing `source_text` alongside the vector makes re-indexing skip anything
unchanged; and a `provider`/`model` pair makes migrating vendors a targeted
re-embed rather than a full-table guess. The cost is one extra join and no
FK-enforced integrity on `entity_id` (orphaned vectors are skipped at read
time).

`ORDER BY embedding <=> :query` uses pgvector's HNSW index directly (ordering
by a computed similarity alias would defeat it). **Without pgvector installed,
`/matching/*` answers 503 naming exactly what's missing** — every other
endpoint is unaffected, by design (§13).

---

## 8. The LLM provider seam

`ai/provider.py` is the single place that resolves `LLM_PROVIDER` + `ATS_MODEL`
into a live Pydantic AI agent; the intake, review, and patch-revision agents
never name a vendor. Supporting Gemini alongside Claude meant adding one module
and two config mappings, not editing every agent.

Two details worth knowing if you touch this code:

- **The credential is passed explicitly**, not read from the process
  environment — `pydantic-settings` loads `backend/.env` into a `Settings`
  object without exporting it to `os.environ`, so the SDK's own env-var lookup
  silently misses a key configured exactly the way this README says to.
- **429s retry against the provider's own `RetryInfo`**, not a guessed
  backoff — Gemini's free tier is 5 requests/minute, tight enough that a
  single multi-call flow can exhaust it mid-request. Every other error
  propagates immediately, since retrying a bad key or schema violation only
  delays the failure.

This is not a rate limiter or a spend cap — see §14.

---

## 9. Authentication, scope & moderation

### 9.1 Ownership is derived, never supplied

`user_id` does not appear in any wire contract — no request body, no query
param. Every private row is resolved through the bearer token, not a
client-supplied id, because a field the client controls can't be an
authorization input (a validated copy would just be two sources of truth that
must agree forever).

### 9.2 404, not 403, for someone else's private data

Reaching for another user's resume returns **404**, identical to a
non-existent id — a 403 would confirm the id is real, turning the endpoint
into an existence oracle. **Admins are not exempt**: there is no role check on
resume ownership at all, because there is no administrative task that needs to
read someone's document. This is the one authorization rule in the app with no
override.

The same reasoning shows up at login: one message for "no such email" and
"wrong password," with a dummy hash verified on the unknown-email path so the
response isn't measurably faster.

### 9.3 Public data is moderated, not gated

Companies and job profiles are community-contributed and admin-approved, but a
contributor can use their own pending submission immediately — everyone else
sees nothing until it's approved. The alternative (hide until approved) makes
the feature useless: you add a company because you're about to track a job
there right now.

```sql
status = 'approved'  OR  created_by = me     -- admins see everything
```

Rejection keeps the row (with a reason the contributor can read) rather than
deleting it, so the same duplicate isn't re-proposed next week.

### 9.4 Identity is a database constraint

Companies dedupe on a normalized `slug` (accent-folded, lowercased, legal
suffixes stripped — `"Acme, Inc."` and `"ACME Incorporated"` both become
`acme`), not on `name`, because "one employer, several spellings" is a rule a
plain unique index can't express. Job profiles dedupe on
`(company, external_job_id)` via two **partial** unique indexes, because
Postgres treats NULLs as distinct and a plain unique constraint would admit
unlimited rows with no requisition id — exactly the common case.

### 9.5 Sessions

Argon2id passwords, HS256 JWTs, and a deliberate split: short-lived access
tokens (30 min, checked only against `is_active`) and long-lived refresh
tokens (14 days, single-use, validated against a `refresh_tokens` row).
Redeeming an already-used refresh token means two parties hold the same
credential, so the entire token family is revoked — a stolen refresh token
buys an attacker access only until the real user's next refresh, at which
point the theft announces itself. `users.token_version` gives "log out
everywhere" / revoke-on-password-change without a server-side session table.

`audit_logs` is append-only, has no API to read it (read it with `psql`), and
records only what can't be reconstructed from the rows themselves — role
grants, deactivations, deletions. Ordinary activity is not audited.

There is deliberately **no self-service password reset** — with no email
transport configured, that endpoint would be an unauthenticated account
takeover by anyone who knows an address. `app/cli.py` is the recovery path
(`uv run python -m app.cli reset-password you@example.com`), and
`BOOTSTRAP_ADMIN_EMAIL` promotes exactly one address at registration rather
than racing "first signup wins."

---

## 10. Frontend design

Angular, standalone components throughout, state in signals — no NgRx, since a
fetch-then-mutate CRUD app doesn't need a global store.

- **`AuthService`** owns the tokens and exposes `currentUser`,
  `isAuthenticated`, `isModerator`, `isAdmin` as signals.
- **`authInterceptor`** attaches the bearer token and, on a 401, refreshes
  once and replays the request — concurrent 401s share a single refresh
  through one `Subject`, because the server treats a re-redeemed refresh token
  as theft and would otherwise revoke the session three parallel requests were
  each trying to renew.
- **`authGuard`** sits on the parent route so a new page can't be added
  unprotected by forgetting a line. Guards are convenience, not security — the
  API enforces every rule independently regardless of what the client renders.
- The resume PDF download fetches a blob through `HttpClient` rather than a
  plain `<a href>`, since a bare link can't carry an `Authorization` header.

**One component renders the verdict everywhere.** `ScorePanel` and
`ReviewPanel` both show a 0–100 score, summary, and keyword gaps through one
shared `VerdictView`, so "your ATS score" can't mean something subtly
different on the two screens. A stale cached score is shown dimmed with a
banner explaining why — never hidden, never silently refreshed.

**Tailoring never auto-saves.** Nothing is written until every proposal has a
decision and the author presses save — the UI mirrors the server's gate (§5)
rather than pretending to be it, so the button being enabled and the request
succeeding can't disagree.

Type parity with the backend is manual: every Pydantic schema has a matching
TypeScript interface, including discriminated unions as literal unions. Real
maintenance cost — see §15 for the generated-client alternative.

---

## 11. Testing strategy

Backend tests hit real PostgreSQL and, where relevant, a real LaTeX
compile — mocks are reserved for the paid/keyed boundary (the LLM), where
Pydantic AI's `FunctionModel` drives scripted responses through the *real*
validation, prompt construction, and splice logic. `test_no_op_render_is_byte_
identical` is the load-bearing assertion for §6: every "the template is
preserved" claim reduces to that property plus the span map being correct.

A recurring category of test exists specifically to assert **503, not 500** on
every endpoint touching an optional dependency (pgvector, an LLM key) — this
was a real regression once, not a hypothetical. Authorization tests are
written from the attacker's side: a valid token for account A reaching for
account B's data, parametrized across the whole resume surface rather than
tested once, since the realistic failure mode is a new route that forgets the
check.

Frontend: `ng build` type-checks under `strict: true`.

---

## 12. Configuration reference

Full annotated list in `backend/.env.example`; the essentials:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://jarvis:…@localhost:5432/jarvis` | Must use the `asyncpg` driver |
| `JWT_SECRET_KEY` | random per process | **Set this.** ≥32 bytes (RFC 7518 §3.2) or refused |
| `BOOTSTRAP_ADMIN_EMAIL` | – | Promoted to admin at registration |
| `LLM_PROVIDER` / `ATS_MODEL` | `anthropic` / `claude-opus-5` | Changed together — see §8 |
| `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` | – | Whichever matches `LLM_PROVIDER` |
| `EMBEDDING_PROVIDER` / `EMBEDDING_DIM` | `local` / `384` | Dimension is baked into the pgvector column — changing it needs a migration + full re-index |
| `LATEX_DEFAULT_ENGINE` | `pdflatex` | Server default; per-resume overrides live in `resumes.latex_engine` |
| `LATEX_WORKER_URL` | `http://localhost:8100` | Where the LaTeX worker service listens — `docker-compose.yml` points this at the `latex-worker` service; the default is correct for a standalone worker container in native development. See §6.5 |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_SECONDS` | `10` / `900` | Credential-stuffing throttle, keyed per IP *and* per email |
| `JARVIS_TEST_DATABASE_URL` | – | Test-suite only |

---

## 13. Design decisions & trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Vector storage | Separate polymorphic table | Column on `users`/`job_profiles` | Isolates an optional extension; enables staleness detection and provider migration |
| Patch review | A table, one row per proposal | A draft the client carries | "Nothing renders until every patch is resolved" is only enforceable if the server knows what's outstanding |
| LaTeX tailoring | Splice byte spans in the original | Regenerate the `.tex` from a structured model | Splicing makes "same template" structural, not best-effort; regeneration would need to model every macro an author might use |
| Ownership | Derived from the token | `user_id` in the request | A client-supplied field can't be an authorization input |
| Another user's private row | 404 | 403 | 403 confirms the id exists — an existence oracle |
| Pending public data | Visible to its own contributor | Hidden until approved | You add a company because you're about to use it right now |
| Session revocation | `users.token_version` | A server-side session table | Password-change / logout-everywhere revocation with no extra table or per-request write |
| LLM output | Pydantic AI structured output | Prompt "return JSON," parse | Schema violations retry in-library, not in production |
| LaTeX engines | One curated Docker image, both engine families | Host-installed TeX Live, or `scheme-full` | Nothing on the host; `scheme-full` is ~4-5GB of subject areas no resume touches |

**The recurring theme is graceful degradation.** Three dependencies — pgvector,
an embedding provider, an LLM key — are each independently optional. Each is
checked at the boundary, each failure names the exact fix, and degradation is
itself tested so a refactor can't quietly turn a 503 into a 500.

---

## 14. Known gaps

| Gap | Impact |
|---|---|
| No self-service password reset | No email transport; recovery needs `app/cli.py` and shell access |
| No per-user cost ceiling | Every upload/review spends a model call; nothing caps how many an account can run |
| `to_markdown()` is heuristic | Multi-column or heavily-styled resumes extract imperfectly for ATS scoring |
| Tailoring reaches only bullets + marked regions | By design (§6.2) — a custom-macro skills line needs a `% jarvis:begin` marker added by hand |
| Sessions live in `localStorage` | Chosen over cookies since the API is cross-origin and cookie auth needs CSRF machinery; trade-off is XSS exposure |
| Gemini free tier caps at 20 requests/day | `ai/limits.py` waits out the per-minute limit but not the daily one — a paid key removes both |

---

## 15. Extending the system

**New embedding provider** — subclass `EmbeddingProvider`, register it in
`build_provider()`, set `EMBEDDING_DIM` (write a migration if it differs from
the current column).

**New embeddable entity** — widen the `entity_type` CHECK constraint, write a
`build_*_text()` function, extend `/matching/reindex`. No new table.

**Endpoint touching private data** — take `CurrentUser` as a dependency
(never a `user_id` param), resolve through `require_owned_resume`, add the
route to the parametrized isolation test in `tests/test_auth.py`.

**Highest-value next steps:** a generated API client from the OpenAPI schema
(removes the manual TS type-parity cost in §10), password reset by email,
moving upload/review off the request path into a background job, and per-user
cost guardrails now that every request is attributable to an account.
