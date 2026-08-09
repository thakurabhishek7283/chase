# AI-Centric Interview Tracker & Resume Optimizer

An Angular + FastAPI system that semantically matches job openings to your career
goals, and uses Claude or Gemini to score your LaTeX resume against an ATS and
tailor it — repeatedly, one reviewed change at a time, without the template ever
moving.

> 📖 **[ARCHITECTURE.md](ARCHITECTURE.md)** — system design, data model, request
> flows, and known gaps.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Relational CRUD foundation | ✅ |
| 2 | Embedding engine + semantic matching | ✅ (needs pgvector) |
| 3–5 | ATS scoring, LaTeX masters, template-preserving tailoring, reviewed patches | ✅ |
| 6 | Authentication, owner-scoped data, moderated public data | ✅ |
| 7 | Cached ATS scores; tailored versions scored and re-reviewable | ✅ |

Pipeline/Kanban tracking was removed — that's what a spreadsheet is for. This
project optimizes resumes, not application tracking.

## Stack

- **Frontend** — Angular (standalone components, signals), `frontend/`
- **Backend** — FastAPI + SQLModel + Alembic, managed with [uv](https://docs.astral.sh/uv/), `backend/`
- **Database** — PostgreSQL + pgvector, run as a Docker container
- **PDF output** — Tectonic and a curated TeX Live install, bundled into one Docker image (`backend/docker/latex/`); nothing installed on the host
- **LLM** — Claude or Gemini, selected with `LLM_PROVIDER`

## Prerequisites

- Docker Desktop
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node.js LTS + npm

## Setup & running

```powershell
# 1. Postgres + pgvector (one-time container)
docker run -d --name jarvis-postgres -p 5432:5432 -v jarvis-pgdata:/var/lib/postgresql/data -e POSTGRES_USER=jarvis -e POSTGRES_PASSWORD=jarvis_dev_password -e POSTGRES_DB=jarvis pgvector/pgvector:pg18
docker exec jarvis-postgres psql -U jarvis -d jarvis -c "CREATE DATABASE jarvis_test;"

# 2. LaTeX engines (one-time image build; the app manages the worker container itself)
docker build -t jarvis-latex:latest backend/docker/latex

# 3. Backend
cd backend
uv sync
copy .env.example .env
# edit .env: set JWT_SECRET_KEY and BOOTSTRAP_ADMIN_EMAIL, plus an LLM key — see below
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 4. Frontend
cd ../frontend
npm install
npm start
```

- Backend: http://localhost:8000/docs
- Frontend: http://localhost:4200

Register at `/register` using the address you set as `BOOTSTRAP_ADMIN_EMAIL` to
get the admin account that clears the moderation queue.

Both containers started above (`jarvis-postgres` and the auto-managed
`jarvis-latex-worker`) just need to be running — restart them normally after a
reboot with `docker start jarvis-postgres`.

## Choosing an LLM provider

Upload intake, resume review, and patch revision all run through one seam, so
switching vendors is configuration, not code:

```ini
# backend/.env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ATS_MODEL=claude-opus-5
```

```ini
LLM_PROVIDER=google
GOOGLE_API_KEY=...
ATS_MODEL=gemini-3.5-flash
```

Only the active provider's key is required — a missing one produces a 503
naming the variable to set. Note Gemini's free tier is 5 requests/minute; the
app waits out the provider's own retry delay rather than failing.

An upload is not stored until an LLM call *and* a real compile both succeed, so
both an LLM key and the LaTeX image (step 2 above) are required before you can
use the app, not just before you can search or embed.

## Configuration

Every setting is an environment variable or a line in `backend/.env` — see
`backend/.env.example` for the full annotated list, and
[ARCHITECTURE.md §12](ARCHITECTURE.md#12-configuration-reference) for what each
one is for. The ones you must set yourself before first run:

| Variable | Why |
|---|---|
| `JWT_SECRET_KEY` | Unset ⇒ a random key per process — sessions die on every restart |
| `BOOTSTRAP_ADMIN_EMAIL` | The address promoted to admin at registration |
| `ANTHROPIC_API_KEY` or `GOOGLE_API_KEY` | Matching whichever `LLM_PROVIDER` you chose |

## Common issues

| Symptom | Fix |
|---|---|
| `503 … needs an Anthropic API key` | Set the key matching your `LLM_PROVIDER` |
| Every PDF compile fails / engine reports unavailable | `docker build -t jarvis-latex:latest backend/docker/latex`, and make sure Docker Desktop is running |
| `401` on every request after a restart | `JWT_SECRET_KEY` was unset and got regenerated — set it in `backend/.env` |
| No **Moderation** link in the sidebar | The signed-in account isn't an admin — register with `BOOTSTRAP_ADMIN_EMAIL` or `PATCH /users/{id}/role` |
| `/matching/*` returns 503 | The Postgres container is missing the `vector` extension — use the `pgvector/pgvector` image, not plain `postgres` |

More in [ARCHITECTURE.md, Appendix B](ARCHITECTURE.md#appendix-b--troubleshooting).
