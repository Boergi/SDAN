#!/usr/bin/env bash
set -euo pipefail

SERVER="${DEPLOY_SERVER:-user@yourserver.com}"
REMOTE_DIR="${DEPLOY_DIR:-/srv/gateway}"
APP_CONFIG_FILE="${APP_CONFIG_FILE:-config/apps.toml}"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Deploying to ${SERVER}:${REMOTE_DIR}"

ssh "${SERVER}" "mkdir -p ${REMOTE_DIR}"

rsync -avz --delete \
  --exclude '.git' \
  --exclude '.generated' \
  --exclude '.env' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'config/apps.toml' \
  --exclude 'caddy/jwt/*.pem' \
  --exclude 'caddy/jwt/*.key' \
  "${LOCAL_DIR}/" "${SERVER}:${REMOTE_DIR}/"

ssh "${SERVER}" bash -s <<EOF
set -euo pipefail
cd ${REMOTE_DIR}

if [[ ! -f .env ]]; then
  echo "ERROR: .env fehlt auf dem Server."
  echo "       Entra-Werte lokal anlegen: ./scripts/configure-env.sh"
  echo "       Dann .env auf den Server kopieren:"
  echo "       scp .env ${SERVER}:${REMOTE_DIR}/.env"
  exit 1
fi

if grep -q '^AZURE_TENANT_ID=$' .env || grep -q '^AZURE_CLIENT_ID=$' .env || grep -q '^AZURE_CLIENT_SECRET=$' .env || grep -q '^AUTH_DOMAIN=$' .env || grep -q '^COOKIE_DOMAIN=$' .env; then
  echo "ERROR: .env enthält leere Pflichtwerte. Bitte AZURE_*, AUTH_DOMAIN und COOKIE_DOMAIN eintragen."
  exit 1
fi

if ! grep -q '^AUTH_DOMAIN=' .env; then
  echo "ERROR: .env enthält keine AUTH_DOMAIN. Beispiel: AUTH_DOMAIN=auth.yourdomain.com"
  exit 1
fi

if ! grep -q '^COOKIE_DOMAIN=' .env; then
  echo "ERROR: .env enthält keine COOKIE_DOMAIN. Beispiel: COOKIE_DOMAIN=yourdomain.com"
  exit 1
fi

if [[ ! -f "${APP_CONFIG_FILE}" ]]; then
  echo "ERROR: App-Konfiguration fehlt: ${APP_CONFIG_FILE}"
  echo "       Einmalig anlegen: gatectl init"
  echo "       Danach Apps auf dem Server mit gatectl add|disable|enable|remove|public|token|trusted-ip|apply verwalten."
  exit 1
fi

if [[ ! -f caddy/jwt/sign_key1.pem ]]; then
  chmod +x scripts/generate-jwt-keys.sh
  ./scripts/generate-jwt-keys.sh
fi

# Read provider from .env
OIDC_PROVIDER="none"
if [[ -f .env ]]; then
  while IFS='=' read -r key value; do
    if [[ "$key" == "OIDC_PROVIDER" ]]; then
      OIDC_PROVIDER="${value//\"/}"
      OIDC_PROVIDER="${OIDC_PROVIDER//\'/}"
      break
    fi
  done < .env
fi

python3 scripts/generate-caddy-config.py --config "${APP_CONFIG_FILE}" --provider "${OIDC_PROVIDER}"
docker compose config --quiet
docker compose up -d --build --remove-orphans
docker compose ps
EOF

echo "==> Deploy complete"
