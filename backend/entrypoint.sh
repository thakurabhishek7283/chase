#!/bin/sh
# Container entrypoint: prepare configuration, migrate, then run the command
# (uvicorn by default — see the Dockerfile's CMD). Any other command runs in the
# same prepared environment, e.g.
#   docker compose exec backend python -m app.cli list-admins
set -eu

data_dir="${JARVIS_DATA_DIR:-/app/data}"

# No signing key configured: generate one once and keep it on the data volume,
# so sessions survive restarts without anyone having to invent a secret before
# the first `docker compose up`. Setting JWT_SECRET_KEY always wins.
if [ -z "${JWT_SECRET_KEY:-}" ]; then
    secret_file="$data_dir/jwt_secret"
    if [ ! -s "$secret_file" ]; then
        umask 077
        python -c "import secrets; print(secrets.token_urlsafe(48))" > "$secret_file"
        echo "entrypoint: generated a JWT signing key at $secret_file" >&2
    fi
    JWT_SECRET_KEY="$(cat "$secret_file")"
    export JWT_SECRET_KEY
fi

# Migrations run on every start; Alembic makes that a no-op when the schema is
# current. Disable when several replicas share a database and migrations are
# run as a separate release step instead.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    alembic upgrade head
fi

exec "$@"
