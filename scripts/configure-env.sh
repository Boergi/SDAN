#!/usr/bin/env bash
set -euo pipefail

# ============================================
# DEPRECATED: Use scripts/setup.sh instead
# ============================================
# This script is kept for backwards compatibility.
# It only supports Azure AD configuration.
# For Authentik or "No SSO" mode, use scripts/setup.sh

echo "WARN: scripts/configure-env.sh is deprecated. Use scripts/setup.sh instead." >&2
echo "      scripts/setup.sh supports Azure AD, Authentik, and No SSO mode." >&2
echo "" >&2

ENV_FILE="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env}"

if [[ -f "${ENV_FILE}" ]]; then
  read -r -p ".env existiert bereits. Überschreiben? [y/N] " confirm
  if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    echo "Abgebrochen."
    exit 0
  fi
fi

echo "OpenID Provider Auswahl:"
echo "1) Azure AD (Microsoft Entra ID)"
echo "2) Authentik (self-hosted OIDC)"
echo "3) No SSO (IP + Token authentication only)"
read -r -p "Your choice [1-3]: " provider_choice

case "$provider_choice" in
  1)
    OIDC_PROVIDER="azure"
    echo ""
    echo "Microsoft Entra ID Werte eingeben (aus App Registration 'Caddy SSO Proxy'):"
    read -r -p "Tenant ID: " tenant_id
    read -r -p "Client ID: " client_id
    read -r -s -p "Client Secret: " client_secret
    echo
    AZURE_TENANT_ID="${tenant_id}"
    AZURE_CLIENT_ID="${client_id}"
    AZURE_CLIENT_SECRET="${client_secret}"
    AUTHENTIK_ISSUER_URL=""
    AUTHENTIK_CLIENT_ID=""
    AUTHENTIK_CLIENT_SECRET=""
    ;;
  2)
    OIDC_PROVIDER="authentik"
    echo ""
    echo "Authentik Configuration:"
    read -r -p "Issuer URL: " AUTHENTIK_ISSUER_URL
    read -r -p "Client ID: " AUTHENTIK_CLIENT_ID
    read -r -s -p "Client Secret: " AUTHENTIK_CLIENT_SECRET
    echo
    AZURE_TENANT_ID=""
    AZURE_CLIENT_ID=""
    AZURE_CLIENT_SECRET=""
    ;;
  3)
    OIDC_PROVIDER="none"
    echo ""
    echo "No SSO mode selected."
    AZURE_TENANT_ID=""
    AZURE_CLIENT_ID=""
    AZURE_CLIENT_SECRET=""
    AUTHENTIK_ISSUER_URL=""
    AUTHENTIK_CLIENT_ID=""
    AUTHENTIK_CLIENT_SECRET=""
    ;;
  *)
    echo "Invalid choice."
    exit 1
    ;;
esac

read -r -p "Auth Domain [auth.yourdomain.com]: " auth_domain
auth_domain="${auth_domain:-auth.yourdomain.com}"
read -r -p "Cookie Domain [yourdomain.com]: " cookie_domain
cookie_domain="${cookie_domain:-yourdomain.com}"
read -r -p "Proxy Network [proxy_net]: " proxy_network
proxy_network="${proxy_network:-proxy_net}"

cat > "${ENV_FILE}" <<EOF
# Secure Docker App Network - Environment Configuration
# ======================================================

# OpenID Provider: azure, authentik, or none
OIDC_PROVIDER=${OIDC_PROVIDER}

# Azure AD (Microsoft Entra ID)
AZURE_TENANT_ID=${AZURE_TENANT_ID}
AZURE_CLIENT_ID=${AZURE_CLIENT_ID}
AZURE_CLIENT_SECRET=${AZURE_CLIENT_SECRET}

# Authentik
AUTHENTIK_ISSUER_URL=${AUTHENTIK_ISSUER_URL}
AUTHENTIK_CLIENT_ID=${AUTHENTIK_CLIENT_ID}
AUTHENTIK_CLIENT_SECRET=${AUTHENTIK_CLIENT_SECRET}

# Common settings
AUTH_DOMAIN=${auth_domain}
COOKIE_DOMAIN=${cookie_domain}
PROXY_NETWORK=${proxy_network}
EOF

chmod 600 "${ENV_FILE}"
echo "Geschrieben: ${ENV_FILE}"
echo "Als Nächstes: docker compose up -d --force-recreate caddy"