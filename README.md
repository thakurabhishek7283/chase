# Chase — AI resume tailoring & job matching

[![CI](https://github.com/thakurabhishek7283/chase/actions/workflows/ci.yml/badge.svg)](https://github.com/thakurabhishek7283/chase/actions/workflows/ci.yml)
[![MIT licence](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

An Angular + FastAPI system that semantically matches job openings to your career
goals, and uses Gemini to score your LaTeX resume against an ATS and tailor it —
repeatedly, one reviewed change at a time, without the template ever moving.

> The services, database and containers still carry the project's earlier
> codename, `jarvis` (for example `jarvis-postgres`, `JARVIS_TEST_DATABASE_URL`).

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
- **PDF output** — a curated TeX Live install (pdflatex, xelatex, lualatex, latexmk), bundled into one Docker image (`latex-worker/`) and run as its own HTTP service; nothing installed on the host
- **LLM** — Google Gemini (`gemini-3.5-flash`), reached through Pydantic AI

## Prerequisites

- Docker Desktop (or the Docker Engine + Compose plugin) — this is the only
  requirement for the Docker Compose path below
- For the native path instead: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node.js LTS + npm

## Setup & running — Docker Compose (easiest)

Everything (Postgres, backend, frontend) runs in containers; nothing but
Docker is installed on your machine.

```powershell
# 1. Configure secrets — required even in Docker, since these aren't guessable
copy backend\.env.example backend\.env
# edit backend/.env: set JWT_SECRET_KEY, BOOTSTRAP_ADMIN_EMAIL and
# GOOGLE_API_KEY — see "The LLM key" below

# 2. Everything, including the LaTeX engines
docker compose up --build
```

- Backend: http://localhost:8000/docs
- Frontend: http://localhost:4200

Register at `/register` using the address you set as `BOOTSTRAP_ADMIN_EMAIL`
to get the admin account that clears the moderation queue. Code is baked into
the images at build time — after changing `backend/` or `frontend/`, re-run
with `--build` to pick it up; this path favors "just run it" over a live
reload loop.

If port 5432 is already taken by a Postgres you're running natively, either
stop it first or edit the `postgres:` port mapping in `docker-compose.yml`.

## Setup & running — native (for active development)

Runs Postgres and the LaTeX engines in containers, but the backend and
frontend directly on your machine, with reload-on-save.

```powershell
# 1. Postgres + pgvector (one-time container)
docker run -d --name jarvis-postgres -p 5432:5432 -v jarvis-pgdata:/var/lib/postgresql -e POSTGRES_USER=jarvis -e POSTGRES_PASSWORD=jarvis_dev_password -e POSTGRES_DB=jarvis pgvector/pgvector:pg18
docker exec jarvis-postgres psql -U jarvis -d jarvis -c "CREATE DATABASE jarvis_test;"

# 2. LaTeX engines (one-time image build, then run it as a standalone service —
# the backend only ever talks to it over HTTP, on port 8100)
docker build -t jarvis-latex:latest latex-worker
docker run -d --name jarvis-latex-worker -p 8100:8100 --restart unless-stopped jarvis-latex:latest

# 3. Backend
cd backend
uv sync --extra local-embeddings   # the extra is the local embedding model for matching
copy .env.example .env
# edit .env: set JWT_SECRET_KEY, BOOTSTRAP_ADMIN_EMAIL and GOOGLE_API_KEY — see below
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 4. Frontend
cd ../frontend
npm install
npm start
```

- Backend: http://localhost:8000/docs
- Frontend: http://localhost:4200

Both containers started above just need to be running — restart them after a
reboot with `docker start jarvis-postgres jarvis-latex-worker`.

## The LLM key

Upload intake, resume review, and patch revision all run on Gemini. Get a key
from [Google AI Studio](https://aistudio.google.com/apikey) and put it in
`backend/.env`:

```ini
# backend/.env
GOOGLE_API_KEY=...
ATS_MODEL=gemini-3.5-flash   # gemini-2.5-pro and gemini-3.1-pro-preview also work
```

Without it the LLM-backed routes answer 503 naming the variable to set. Note
the free tier is 5 requests/minute and 20/day; the app waits out the per-minute
limit using the delay the API itself asks for, rather than failing.

An upload is not stored until an LLM call *and* a real compile both succeed, so
both the key and a running LaTeX worker are required before you can use the
app, not just before you can search or embed.

Semantic matching does *not* use this key — embeddings run on your machine
(fastembed/ONNX, 384-dim), so re-indexing costs nothing and sends nothing.

## Configuration

Every setting is an environment variable or a line in `backend/.env` — see
`backend/.env.example` for the full annotated list, and
[ARCHITECTURE.md §12](ARCHITECTURE.md#12-configuration-reference) for what each
one is for. The ones you must set yourself before first run:

| Variable | Why |
|---|---|
| `JWT_SECRET_KEY` | Unset ⇒ a random key per process — sessions die on every restart |
| `BOOTSTRAP_ADMIN_EMAIL` | The address promoted to admin at registration |
| `GOOGLE_API_KEY` | Gemini powers intake, review and tailoring — nothing works without it |

## Tests

```bash
# Backend: 270 tests against a real Postgres + pgvector (the jarvis_test
# database from step 1) and the LaTeX worker on :8100
cd backend
uv run pytest

# Frontend
cd frontend
npm test -- --watch=false
```

[CI](.github/workflows/ci.yml) runs both on every push, with Postgres as a
service container and the LaTeX worker started from `latex-worker/server.py`.

## Common issues

| Symptom | Fix |
|---|---|
| `503 … needs a Gemini API key` | Set `GOOGLE_API_KEY` in `backend/.env` and restart |
| Every PDF compile fails / engine reports unavailable | Check the LaTeX worker is actually running (`docker ps`) and `LATEX_WORKER_URL` points at it — `docker logs jarvis-latex-worker` (native) or `docker compose logs latex-worker` (Compose) |
| `401` on every request after a restart | `JWT_SECRET_KEY` was unset and got regenerated — set it in `backend/.env` |
| No **Moderation** link in the sidebar | The signed-in account isn't an admin — register with `BOOTSTRAP_ADMIN_EMAIL` or `PATCH /users/{id}/role` |
| `/matching/*` returns 503 | The Postgres container is missing the `vector` extension — use the `pgvector/pgvector` image, not plain `postgres` |
| `docker compose up` fails with "port is already allocated" on 5432 | You already have a Postgres (container or native) bound to that port — stop it, or remap `postgres:`'s port in `docker-compose.yml` |
| `env_file backend/.env not found` from `docker compose up` | Missed step 1 — `copy backend\.env.example backend\.env`, then fill in the required values |

More in [ARCHITECTURE.md, Appendix B](ARCHITECTURE.md#appendix-b--troubleshooting).
