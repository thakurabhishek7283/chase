# AI-Centric Interview Tracker & Resume Optimizer

An Angular + FastAPI system that tracks interview pipelines, semantically matches
job openings to your career goals, and uses Claude or Gemini to score and
auto-optimize resumes against ATS screens.

> 📖 **[ARCHITECTURE.md](ARCHITECTURE.md)** — full design documentation: data model,
> request flows, design trade-offs, setup paths, testing strategy, and known gaps.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Relational CRUD foundation + Kanban board | ✅ verified end-to-end |
| 2 | PDF parsing + embedding engine + semantic matching | ✅ PDF parsing verified · 🟡 vectors need pgvector |
| 3 | ATS scoring via Pydantic AI | ✅ verified live against Gemini |
| 4 | LangGraph autofix loop | ✅ verified live against Gemini |
| 5 | LaTeX masters + template-preserving tailoring + PDF export | ✅ verified end-to-end (API-only, no UI) |

## Stack

- **Frontend**: Angular (`frontend/`), npm
- **Backend**: FastAPI + SQLModel + Alembic (`backend/`), managed with [uv](https://docs.astral.sh/uv/)
- **Database**: PostgreSQL 16, installed natively — no containers anywhere in the stack
- **PDF output**: [Tectonic](https://tectonic-typesetting.github.io/) — one self-contained LaTeX binary
- **LLM**: Claude *or* Gemini, selected with `LLM_PROVIDER`

## Choosing an LLM provider

The ATS scorer, the autofix loop, and LaTeX tailoring all run through one seam,
so switching vendors is configuration rather than code. Set both variables
together — `ATS_MODEL` is the model id *within* the chosen provider:

```ini
# backend/.env
LLM_PROVIDER=google
GOOGLE_API_KEY=...            # from https://aistudio.google.com/apikey
ATS_MODEL=gemini-3.5-flash    # or gemini-2.5-pro, gemini-3.1-pro-preview
```

```ini
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
ATS_MODEL=claude-opus-5
```

Only the active provider's key is needed. A missing one produces a 503 that
names the variable you actually have to set.

> **Gemini free tier is 5 requests/minute.** One scored `/latex/tailor` spends 3
> calls and a 3-iteration autofix spends 6, so requests will pause and retry
> rather than fail — the app waits out the interval Google asks for. A paid key
> or a `-flash-lite` model removes the stall.

## Writing resumes in LaTeX

Upload your own `.tex` master and every tailored version compiles from *its*
template, so the variants differ in wording but not in look.

```powershell
# 1. Install the LaTeX engine (one-time). No winget package exists; grab the release binary:
$dest = "$env:LOCALAPPDATA\Programs\tectonic"
New-Item -ItemType Directory -Force -Path $dest
Invoke-WebRequest -Uri "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-x86_64-pc-windows-msvc.zip" -OutFile "$env:TEMP\tectonic.zip"
Expand-Archive "$env:TEMP\tectonic.zip" -DestinationPath $dest -Force
# add $dest to PATH, or set LATEX_ENGINE_PATH to "$dest\tectonic.exe"

# 2. Confirm the API can see it
curl http://localhost:8000/api/v1/latex/status

# 3. Upload your master .tex
curl -F "user_id=<uuid>" -F "title=My Master" -F "file=@resume.tex" `
     http://localhost:8000/api/v1/latex/resumes/upload

# 4. Tailor it for a job, then download the PDF
curl -X POST http://localhost:8000/api/v1/latex/tailor `
     -H "Content-Type: application/json" `
     -d '{"resume_id":"<uuid>","job_profile_id":"<uuid>","score":true}'
curl -o tailored.pdf "http://localhost:8000/api/v1/latex/resumes/<child-uuid>/render?output=pdf"
```

### What tailoring is allowed to change

| Changed | Frozen |
|---|---|
| `\item` bullet text — reworded, reordered, dropped | Preamble, packages, `\newcommand` macros, geometry, fonts |
| Anything between `% jarvis:begin <label>` and `% jarvis:end` | Employers, job titles, dates, degrees, section headings |

### Engines are per-resume

The engine is detected from your preamble at upload, so a `fontspec` master and a
plain pdfLaTeX one can coexist. Detection only upgrades — pass `latex_engine` on
the upload to override it, or change it later:

```powershell
curl -X PATCH http://localhost:8000/api/v1/latex/resumes/<uuid>/engine `
     -H "Content-Type: application/json" -d '{"latex_engine":"xelatex"}'
```

Allowed: `tectonic`, `latexmk`, `pdflatex`, `xelatex`, `lualatex` — a fixed
allowlist, because the value is executed. Tailored versions inherit their
master's engine. `GET /latex/status` reports which ones are actually installed.

The upload response lists every editable slot plus a `frozen_sections` array. If
a section you *want* tailored shows up as frozen — a skills line built from
custom macros, say — wrap it in markers:

```latex
\section{Skills}
% jarvis:begin skills
\textbf{Languages}: Python, Go, Rust
% jarvis:end
```

Everything outside those spans is copied through byte for byte, which is what
makes the template preservation a guarantee rather than a hope. See
[ARCHITECTURE.md §8A](ARCHITECTURE.md) for the design.

## Prerequisites

- PostgreSQL 16, installed natively
- Node.js LTS + npm
- `uv` (Python package/env manager)

## Local development

```powershell
# 1. Postgres — create the dev role and databases (one-time)
winget install PostgreSQL.PostgreSQL.16
psql -U postgres -h 127.0.0.1 -c "CREATE ROLE jarvis LOGIN PASSWORD 'jarvis_dev_password';"
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE jarvis      OWNER jarvis;"
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE jarvis_test OWNER jarvis;"

# 2. Backend (from backend/)
cd backend
uv sync
copy .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 3. Frontend (from frontend/)
cd ../frontend
npm install
npm start
```

- Backend: http://localhost:8000/docs
- Frontend: http://localhost:4200

`.env.example` already points `DATABASE_URL` at `localhost:5432`, so it needs no
editing unless your Postgres listens elsewhere. If you run more than one
Postgres instance, check which one owns 5432 — a second install typically takes
5433.

### Semantic matching needs pgvector

`alembic upgrade head` applies end-to-end on a stock Postgres. The two
vector-dependent revisions detect that the `vector` extension is absent and skip
their DDL instead of aborting the chain, so the relational schema — every phase
except semantic matching — is complete either way.

Until pgvector is installed, `/matching/*` answers **503** with a message naming
what's missing. Nothing else is affected. Note that a stock Postgres has no
`vector` extension and pgvector publishes no prebuilt Windows binary, so
enabling it means building the extension against your Postgres install with an
MSVC toolchain.
