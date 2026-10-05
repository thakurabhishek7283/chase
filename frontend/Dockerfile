# syntax=docker/dockerfile:1.7
#
# Production image for the Angular frontend.
#
#   build    compiles the app with the Angular CLI (optimised, hashed assets)
#   runtime  serves the static files from unprivileged nginx, and reverse-
#            proxies /api, /docs and /openapi.json to the backend
#
# For live reload during development, use `npm start` instead (README).

ARG NODE_VERSION=24

FROM node:${NODE_VERSION}-slim AS build
WORKDIR /app

# Dependencies in their own layer so editing app code doesn't bust the
# (slow) npm-install cache.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY . .
RUN npx ng build --configuration production


FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime

LABEL org.opencontainers.image.title="jarvis-frontend" \
      org.opencontainers.image.description="Angular UI for the AI interview tracker and resume optimizer, served by nginx" \
      org.opencontainers.image.source="https://github.com/thakurabhishek7283/chase"

# Where nginx forwards API calls. The compose service name by default;
# override at run time for any other topology.
ENV BACKEND_URL=http://backend:8000

COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
