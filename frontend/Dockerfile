# Dev-mode image: runs the Angular dev server with live reload, so a clone-
# and-`docker compose up` gives the same experience as `npm start` without
# installing Node locally. There is no production/nginx build here yet — see
# ARCHITECTURE.md if you need one.
FROM node:24-slim

WORKDIR /app

# Dependencies in their own layer so editing app code doesn't bust the
# (slow) npm-install cache.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 4200

# --host so the dev server accepts connections from outside the container;
# --poll because inotify file events don't cross a bind mount reliably on
# Docker Desktop (Windows/Mac).
CMD ["npx", "ng", "serve", "--host", "0.0.0.0", "--poll", "1000"]
