#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env}"

if [[ -f "${ENV_FILE}" ]]; then
  read -r -p ".env existiert bereits. Überschreiben? [y/N] " confirm
  if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    echo "Abgebrochen."
    exit 0
  fi
fi

echo "Microsoft Entra ID Werte eingeben (aus App Registration 'Caddy SSO Proxy'):"
read -r -p "Tenant ID: " tenant_id
read -r -p "Client ID: " client_id
read -r -s -p "Client Secret: " client_secret
echo
read -r -p "Auth Domain [auth.yourdomain.com]: " auth_domain
auth_domain="${auth_domain:-auth.yourdomain.com}"
read -r -p "Cookie Domain [yourdomain.com]: " cookie_domain
cookie_domain="${cookie_domain:-yourdomain.com}"
read -r -p "Proxy Network [proxy_net]: " proxy_network
proxy_network="${proxy_network:-proxy_net}"

cat > "${ENV_FILE}" <<EOF
# Microsoft Entra ID — Caddy SSO Proxy
AZURE_TENANT_ID=${tenant_id}
AZURE_CLIENT_ID=${client_id}
AZURE_CLIENT_SECRET=${client_secret}
AUTH_DOMAIN=${auth_domain}
COOKIE_DOMAIN=${cookie_domain}
PROXY_NETWORK=${proxy_network}
EOF

chmod 600 "${ENV_FILE}"
echo "Geschrieben: ${ENV_FILE}"
echo "Als Nächstes: docker compose up -d --force-recreate caddy"
