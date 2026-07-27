#!/usr/bin/env bash
set -euo pipefail

# Secure Docker App Network - Setup Script
# ========================================
# This script guides you through setting up the gateway with your preferred
# OpenID provider (Azure AD, Authentik, or none for IP+Token only).
#
# Usage:
#   ./scripts/setup.sh                    # interactive mode
#   ./scripts/setup.sh --provider none    # non-interactive, no SSO

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"
GENERATED_DIR="$PROJECT_DIR/.generated"
CADDY_TEMPLATE_DIR="$PROJECT_DIR/caddy/templates"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Parse arguments
PROVIDER_FLAG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --provider)
            PROVIDER_FLAG="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Usage: $0 [--provider azure|authentik|none]"
            exit 1
            ;;
    esac
done

# Check prerequisites
check_prerequisites() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    if ! command -v docker compose &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi

    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed. Please install Python 3 first."
        exit 1
    fi
}

# Create .env file
create_env_file() {
    if [[ -f "$ENV_FILE" ]]; then
        if [[ -n "$PROVIDER_FLAG" ]]; then
            # Non-interactive: keep existing .env
            log_info ".env file already exists."
            return 0
        fi
        log_info ".env file already exists."
        read -r -p "Do you want to overwrite it? [y/N] " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            log_info "Keeping existing .env file."
            return 0
        fi
    fi

    if [[ -n "$PROVIDER_FLAG" ]]; then
        # Non-interactive mode
        OIDC_PROVIDER="$PROVIDER_FLAG"
        AZURE_TENANT_ID=""
        AZURE_CLIENT_ID=""
        AZURE_CLIENT_SECRET=""
        AUTHENTIK_ISSUER_URL=""
        AUTHENTIK_CLIENT_ID=""
        AUTHENTIK_CLIENT_SECRET=""
        AUTH_DOMAIN=""
        COOKIE_DOMAIN=""
        PROXY_NETWORK="proxy_net"
        CADDY_PLUGINS=""
    else
        # Interactive mode
        echo ""
        echo "=== OpenID Provider Selection ==="
        echo ""
        echo "Choose your authentication provider:"
        echo "1) Azure AD (Microsoft Entra ID)"
        echo "2) Authentik (self-hosted OIDC)"
        echo "3) No SSO (IP + Token authentication only)"
        echo ""

        read -r -p "Your choice [1-3]: " provider_choice

        case "$provider_choice" in
            1)
                OIDC_PROVIDER="azure"
                echo ""
                echo "=== Azure AD Configuration ==="
                echo ""
                read -r -p "Azure Tenant ID: " AZURE_TENANT_ID
                read -r -p "Azure Client ID: " AZURE_CLIENT_ID
                read -r -s -p "Azure Client Secret: " AZURE_CLIENT_SECRET
                echo ""
                AUTHENTIK_ISSUER_URL=""
                AUTHENTIK_CLIENT_ID=""
                AUTHENTIK_CLIENT_SECRET=""
                ;;
            2)
                OIDC_PROVIDER="authentik"
                echo ""
                echo "=== Authentik Configuration ==="
                echo ""
                echo "Important: You need to create an OpenID Connect provider in Authentik first."
                echo "The redirect URI should be: https://YOUR_AUTH_DOMAIN/proxy/auth/oauth2/authentik/authorization-code-callback"
                read -r -p "Authentik Issuer URL: " AUTHENTIK_ISSUER_URL
                read -r -p "Authentik Client ID: " AUTHENTIK_CLIENT_ID
                read -r -s -p "Authentik Client Secret: " AUTHENTIK_CLIENT_SECRET
                echo ""
                AZURE_TENANT_ID=""
                AZURE_CLIENT_ID=""
                AZURE_CLIENT_SECRET=""
                ;;
            3)
                OIDC_PROVIDER="none"
                echo ""
                echo "=== No SSO Mode (IP + Token only) ==="
                echo ""
                echo "In this mode, apps are only accessible via:"
                echo "- Trusted IP addresses (CIDR ranges)"
                echo "- Token headers (X-Proxy-Token by default)"
                echo "- No SSO portal will be shown."
                AZURE_TENANT_ID=""
                AZURE_CLIENT_ID=""
                AZURE_CLIENT_SECRET=""
                AUTHENTIK_ISSUER_URL=""
                AUTHENTIK_CLIENT_ID=""
                AUTHENTIK_CLIENT_SECRET=""
                ;;
            *)
                log_error "Invalid choice. Please run the script again."
                exit 1
                ;;
        esac

        # Common settings
        echo ""
        echo "=== Common Settings ==="
        echo ""

        if [[ "$OIDC_PROVIDER" != "none" ]]; then
            read -r -p "Auth Domain (e.g., auth.yourdomain.com): " AUTH_DOMAIN
            read -r -p "Cookie Domain (e.g., yourdomain.com): " COOKIE_DOMAIN
        else
            AUTH_DOMAIN=""
            COOKIE_DOMAIN=""
        fi
        read -r -p "Proxy Network Name [proxy_net]: " PROXY_NETWORK
        PROXY_NETWORK="${PROXY_NETWORK:-proxy_net}"

        # Additional Caddy plugins
        echo ""
        echo "=== Additional Caddy Plugins (optional) ==="
        echo ""
        echo "You can install extra Caddy plugins (e.g., for rate limiting, caching, etc.)."
        echo "Enter them as space-separated --with flags, or leave empty to skip."
        echo ""
        echo "Examples:"
        echo "  --with github.com/mholt/caddy-ratelimit"
        echo "  --with github.com/caddyserver/transform-encoder --with github.com/mholt/caddy-ratelimit"
        echo ""
        read -r -p "Additional plugins: " CADDY_PLUGINS
        CADDY_PLUGINS="${CADDY_PLUGINS:-}"
    fi

    # Generate .env file
    cat > "$ENV_FILE" <<EOF
# Secure Docker App Network - Environment Configuration
# ======================================================

# OpenID Provider: azure, authentik, or none
OIDC_PROVIDER=$OIDC_PROVIDER

# Azure AD (Microsoft Entra ID)
AZURE_TENANT_ID=$AZURE_TENANT_ID
AZURE_CLIENT_ID=$AZURE_CLIENT_ID
AZURE_CLIENT_SECRET=$AZURE_CLIENT_SECRET

# Authentik
AUTHENTIK_ISSUER_URL=$AUTHENTIK_ISSUER_URL
AUTHENTIK_CLIENT_ID=$AUTHENTIK_CLIENT_ID
AUTHENTIK_CLIENT_SECRET=$AUTHENTIK_CLIENT_SECRET

# Common settings
AUTH_DOMAIN=$AUTH_DOMAIN
COOKIE_DOMAIN=$COOKIE_DOMAIN
PROXY_NETWORK=$PROXY_NETWORK

# Additional Caddy plugins (space-separated --with flags for xcaddy build)
CADDY_PLUGINS=$CADDY_PLUGINS
EOF

    chmod 600 "$ENV_FILE"
    log_info ".env file created: $ENV_FILE"
}

# Ensure apps config exists
ensure_apps_config() {
    APPS_CONFIG="$PROJECT_DIR/config/apps.toml"

    if [[ -f "$APPS_CONFIG" ]]; then
        log_info "Apps config found: $APPS_CONFIG"
        return 0
    fi

    echo ""
    echo "=== Apps Configuration ==="
    echo ""
    log_warn "No apps config found at config/apps.toml"

    # Create an empty config via gatectl init
    if [[ -x "$SCRIPT_DIR/gatectl" ]]; then
        python3 "$SCRIPT_DIR/gatectl.py" --config "$APPS_CONFIG" init
        log_info "Created empty apps config: $APPS_CONFIG"
    else
        # Fallback: create minimal empty config
        cat > "$APPS_CONFIG" <<EOF
# App configuration
# Add your apps using: gatectl add <id> <title> <host> <upstream>
EOF
        log_info "Created empty apps config: $APPS_CONFIG"
    fi
}

# Generate JWT signing keys
generate_jwt_keys() {
    echo ""
    echo "=== Generating JWT Signing Keys ==="
    echo ""

    if [[ -f "$PROJECT_DIR/caddy/jwt/sign_key1.pem" ]]; then
        log_info "JWT signing keys already exist."
        return 0
    fi

    mkdir -p "$PROJECT_DIR/caddy/jwt"
    "$SCRIPT_DIR/generate-jwt-keys.sh"
    log_info "JWT signing keys generated."
}

# Generate Caddyfile from template
generate_caddyfile() {
    echo ""
    echo "=== Generating Caddyfile ==="
    echo ""

    APPS_CONFIG="$PROJECT_DIR/config/apps.toml"
    if [[ ! -f "$APPS_CONFIG" ]]; then
        log_warn "Skipping Caddyfile generation: no apps config found."
        echo "Run 'scripts/gatectl apply' after creating your app entries."
        return 0
    fi

    # Determine provider from .env
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    else
        log_error ".env file not found. Please run the script again."
        exit 1
    fi

    # Determine template based on provider
    case "$OIDC_PROVIDER" in
        azure|authentik|none)
            TEMPLATE_FILE="$CADDY_TEMPLATE_DIR/$OIDC_PROVIDER.tmpl"
            ;;
        *)
            log_error "Invalid OIDC_PROVIDER in .env: $OIDC_PROVIDER"
            exit 1
            ;;
    esac

    if [[ ! -f "$TEMPLATE_FILE" ]]; then
        log_error "Template file not found: $TEMPLATE_FILE"
        exit 1
    fi

    # Create generated directory
    mkdir -p "$GENERATED_DIR"

    # Generate Caddyfile using Python script
    python3 "$SCRIPT_DIR/generate-caddy-config.py" \
        --config "$APPS_CONFIG" \
        --provider "$OIDC_PROVIDER" \
        --output "$GENERATED_DIR/Caddyfile"

    log_info "Caddyfile generated: $GENERATED_DIR/Caddyfile"
}

# Build and start Docker containers
build_and_start() {
    echo ""
    echo "=== Building and Starting Docker Containers ==="
    echo ""

    cd "$PROJECT_DIR"

    # Build the Caddy image
    docker compose build caddy

    log_info "Caddy image built successfully."

    # Start the containers
    docker compose up -d caddy

    log_info "Caddy container started successfully."

    # Show status
    echo ""
    echo "=== Status ==="
    docker compose ps
}

# Install gatectl CLI
install_gatectl() {
    echo ""
    echo "=== Installing gatectl CLI ==="
    echo ""

    if "$SCRIPT_DIR/gatectl" install; then
        log_info "gatectl installed successfully."
    else
        log_warn "gatectl installation failed. You can install it later with: ./scripts/gatectl install"
    fi
}

# Main execution
main() {
    echo "Secure Docker App Network - Setup Script"
    echo "========================================="
    echo ""

    check_prerequisites
    create_env_file
    ensure_apps_config
    generate_jwt_keys
    generate_caddyfile
    build_and_start
    install_gatectl

    echo ""
    echo "=== Setup Complete ==="
    echo ""
    echo "Your gateway is now running!"
    echo ""
    echo "Next steps:"
    echo "1. Add your apps using 'gatectl add'"
    echo "2. Run 'gatectl apply' to apply changes"
    echo "3. Make sure your apps are connected to the '$PROXY_NETWORK' network"
    echo ""
    echo "Documentation: https://github.com/Boergi/SDAN"
}

main "$@"