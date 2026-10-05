# Frontend

The Angular single-page app for Chase —
standalone components, state in signals. See the root [README](../README.md)
for running the whole stack and [ARCHITECTURE.md §10](../ARCHITECTURE.md#10-frontend-design)
for how it is put together.

## Development

Requires Node.js 24 (or ≥ 22.22) and a backend on `localhost:8000`
(`make dev-infra` and `make backend-dev` from the repository root).

```bash
npm ci
npm start          # http://localhost:4200, reloads on save
```

The app calls the API on its own origin (`/api/v1`). `npm start` forwards
`/api`, `/docs` and `/openapi.json` to the backend through
[`proxy.conf.json`](proxy.conf.json); the Docker image's nginx does the same
in production.

## Scripts

| Command | What |
|---|---|
| `npm start` | Dev server with live reload |
| `npm run build` | Production bundle in `dist/frontend/browser` |
| `npm run test:ci` | Unit tests once (Vitest); `npm test` watches |
| `npm run format` / `format:check` | Prettier write / verify |

## Layout

```
src/app/
├── core/        models, typed HTTP services, auth interceptor + guards
├── auth/        sign-in and registration
├── layout/      dashboard shell (sidebar navigation)
├── resumes/     upload, detail, score panel, review panel, patch cards
├── jobs/        job profiles (moderated, shared)
├── companies/   companies (moderated, shared)
├── matches/     "Companies to Chase" — semantic matches
├── profile/     self-service account settings
├── admin/       moderation queue
└── users/       user management (admin)
```

## Container image

[`Dockerfile`](Dockerfile) builds the production bundle and serves it with
unprivileged nginx on port 8080 ([`nginx/default.conf.template`](nginx/default.conf.template)).
`BACKEND_URL` (default `http://backend:8000`) sets where `/api` is proxied.
