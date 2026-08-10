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
- **PDF output** — a curated TeX Live install (pdflatex, xelatex, lualatex, latexmk), bundled into one Docker image (`latex-worker/`) and run as its own HTTP service; nothing installed on the host
- **LLM** — Llama 3.3 70B on NVIDIA NIM, or Claude, selected with `LLM_PROVIDER`

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
# edit backend/.env: set JWT_SECRET_KEY and BOOTSTRAP_ADMIN_EMAIL, plus an LLM
# key (NVIDIA_API_KEY or ANTHROPIC_API_KEY) — see "Choosing an LLM provider" below

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

Both containers started above just need to be running — restart them after a
reboot with `docker start jarvis-postgres jarvis-latex-worker`.

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
both an LLM key and a running LaTeX worker are required before you can use the
app, not just before you can search or embed.

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
| Every PDF compile fails / engine reports unavailable | Check the LaTeX worker is actually running (`docker ps`) and `LATEX_WORKER_URL` points at it — `docker logs jarvis-latex-worker` (native) or `docker compose logs latex-worker` (Compose) |
| `401` on every request after a restart | `JWT_SECRET_KEY` was unset and got regenerated — set it in `backend/.env` |
| No **Moderation** link in the sidebar | The signed-in account isn't an admin — register with `BOOTSTRAP_ADMIN_EMAIL` or `PATCH /users/{id}/role` |
| `/matching/*` returns 503 | The Postgres container is missing the `vector` extension — use the `pgvector/pgvector` image, not plain `postgres` |
| `docker compose up` fails with "port is already allocated" on 5432 | You already have a Postgres (container or native) bound to that port — stop it, or remap `postgres:`'s port in `docker-compose.yml` |
| `env_file backend/.env not found` from `docker compose up` | Missed step 1 — `copy backend\.env.example backend\.env`, then fill in the required values |

More in [ARCHITECTURE.md, Appendix B](ARCHITECTURE.md#appendix-b--troubleshooting).
