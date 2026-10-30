#!/bin/sh
# One-command setup: start every service (from empty volumes on the first run)
# and import the WordPress content and users. Safe to run again: the imports
# only write what changed.
#
#   ./setup.sh
set -eu
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (development values)."
fi

run() { echo "+ $*"; "$@"; }

# wp-db (WordPress MariaDB, loads the dump), main + main-db, auth + auth-db,
# and the one-off jwt-keys and assets jobs.
run docker compose up -d --build

# Each import waits for its databases to be healthy (the first WordPress dump
# load takes ~20 s), runs migrations, then imports in one transaction.
run docker compose run --rm main-wp-import
run docker compose run --rm auth-wp-import

port() { value=$(grep -E "^$1=" .env | tail -n 1 | cut -d= -f2); echo "${value:-$2}"; }
cat <<MSG

Ready:
  Django site     http://localhost:$(port MAIN_PORT 8000)/   (brand list: /brand/)
  Brand API       http://localhost:$(port MAIN_PORT 8000)/api/brands/
  Auth service    http://localhost:$(port AUTH_PORT 8001)/api/token/   (users: admin = editor, reviewers = readers;
                  password: AUTH_IMPORT_PASSWORD in .env)
  Original WP     docker compose --profile wordpress up -d wordpress  ->  http://localhost:$(port WP_PORT 8080)/
MSG
