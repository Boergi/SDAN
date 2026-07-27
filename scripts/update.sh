#!/usr/bin/env bash
set -euo pipefail

# Secure Docker App Network - Update Script
# ==========================================
# Updates an existing installation with new files, config changes, and
# ensures all required directories and .env keys exist.
#
# Usage:
#   ./scripts/update.sh                         # Update locally
#   ./scripts/update.sh --dry-run               # Show what would change
#   ./scripts/update.sh --remote user@host:/srv/gateway  # Update remote via SSH

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

DRY_RUN=false
REMOTE_TARGET=""

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --remote)
            shift
            REMOTE_TARGET="$1"
            ;;
        --help|-h)
            echo "Usage: $0 [--dry-run] [--remote user@host:/path]"
            exit 0
            ;;
    esac
done

# If remote target is set, run update remotely via SSH
if [[ -n "$REMOTE_TARGET" ]]; then
    REMOTE_USER="${REMOTE_TARGET%%:*}"
    REMOTE_PATH="${REMOTE_TARGET#*:}"

    echo "==> Running update on remote: ${REMOTE_USER} ${REMOTE_PATH}"

    # Copy all project files except excluded ones
    rsync -avz --delete \
        --exclude '.git' \
        --exclude '.generated' \
        --exclude '.env' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude 'config/apps.toml' \
        --exclude 'caddy/jwt/*.pem' \
        --exclude 'caddy/jwt/*.key' \
        "${PROJECT_DIR}/" "${REMOTE_USER}:${REMOTE_PATH}/"

    # Run update.sh on remote (the newly copied version)
    ssh "${REMOTE_USER}" "cd ${REMOTE_PATH} && bash scripts/update.sh"

    echo "==> Remote update complete"
    exit 0
fi

echo "Secure Docker App Network - Update Script"
echo "=========================================="
echo ""

# ── 1. Check we're in the right directory ──
if [[ ! -f "$SCRIPT_DIR/generate-caddy-config.py" ]]; then
    log_error "Cannot find generate-caddy-config.py. Make sure you're in the project root."
    exit 1
fi

# ── 2. Ensure required directories exist ──
echo "=== Ensuring Required Directories ==="
mkdir -p "$PROJECT_DIR/caddy/extra/apps"
mkdir -p "$PROJECT_DIR/caddy/jwt"
mkdir -p "$PROJECT_DIR/.generated"
log_info "Directories checked/created: caddy/extra/apps, caddy/jwt, .generated"

# ── 3. Ensure .env has all required keys ──
echo ""
echo "=== Checking .env Configuration ==="
if [[ ! -f "$ENV_FILE" ]]; then
    log_error ".env file not found at $ENV_FILE."
    echo "Run 'scripts/setup.sh' first to create it."
    exit 1
fi

# List of default env vars that should exist
declare -A ENV_DEFAULTS
ENV_DEFAULTS["CADDY_PLUGINS"]=""
ENV_DEFAULTS["OIDC_PROVIDER"]="none"
ENV_DEFAULTS["AZURE_TENANT_ID"]=""
ENV_DEFAULTS["AZURE_CLIENT_ID"]=""
ENV_DEFAULTS["AZURE_CLIENT_SECRET"]=""
ENV_DEFAULTS["AUTHENTIK_ISSUER_URL"]=""
ENV_DEFAULTS["AUTHENTIK_CLIENT_ID"]=""
ENV_DEFAULTS["AUTHENTIK_CLIENT_SECRET"]=""
ENV_DEFAULTS["AUTH_DOMAIN"]=""
ENV_DEFAULTS["COOKIE_DOMAIN"]=""
ENV_DEFAULTS["PROXY_NETWORK"]="proxy_net"

UPDATED_ENV=false

for key in "${!ENV_DEFAULTS[@]}"; do
    # Check if key exists in .env
    if ! grep -q "^${key}=" "$ENV_FILE"; then
        default="${ENV_DEFAULTS[$key]}"
        if [[ -n "$default" ]]; then
            echo "$key=$default" >> "$ENV_FILE"
            log_warn "Added missing key '$key=$default' to .env"
        else
            echo "$key=" >> "$ENV_FILE"
            log_warn "Added missing empty key '$key' to .env"
        fi
        UPDATED_ENV=true
    fi
done

# Also check for commented-out keys (e.g. #CADDY_PLUGINS=)
for key in "${!ENV_DEFAULTS[@]}"; do
    if grep -q "^#${key}=" "$ENV_FILE"; then
        default="${ENV_DEFAULTS[$key]}"
        # Uncomment it by replacing the commented line
        if [[ "$DRY_RUN" == true ]]; then
            log_warn "[DRY-RUN] Would uncomment key '#${key}=...'"
        else
            sed -i.bak "s/^#${key}=/${key}=/" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
            log_warn "Uncommented key '$key' in .env"
            UPDATED_ENV=true
        fi
    fi
done

if [[ "$UPDATED_ENV" == false ]]; then
    log_info "All required .env keys are present."
fi

# ── 4. Check docker-compose.yml has extra volume ──
echo ""
echo "=== Checking docker-compose.yml ==="
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
EXTRA_VOLUME_MISSING=false
if [[ -f "$COMPOSE_FILE" ]]; then
    if ! grep -q "./caddy/extra" "$COMPOSE_FILE"; then
        log_warn "docker-compose.yml is missing the 'caddy/extra' volume mount."
        log_warn "Please update manually or re-pull the latest docker-compose.yml."
        EXTRA_VOLUME_MISSING=true
    else
        log_info "docker-compose.yml has the 'caddy/extra' volume mount."
    fi
fi

# ── 5. Check templates have import extra/global.caddy ──
echo ""
echo "=== Checking Caddy Templates ==="
for tmpl in "$PROJECT_DIR/caddy/templates/azure.tmpl" "$PROJECT_DIR/caddy/templates/authentik.tmpl" "$PROJECT_DIR/caddy/templates/none.tmpl"; do
    TMPL_NAME="$(basename "$tmpl")"
    if [[ -f "$tmpl" ]]; then
        if grep -q "import extra/global.caddy" "$tmpl"; then
            log_info "Template $TMPL_NAME: import extra/global.caddy found."
        else
            log_warn "Template $TMPL_NAME: missing import extra/global.caddy. Run 'git pull' to get the latest templates."
        fi
    fi
done

# ── 6. Create default global.caddy if missing ──
echo ""
echo "=== Checking Plugin Config Files ==="
GLOBAL_EXTRA="$PROJECT_DIR/caddy/extra/global.caddy"
if [[ ! -f "$GLOBAL_EXTRA" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        log_warn "[DRY-RUN] Would create $GLOBAL_EXTRA"
    else
        cat > "$GLOBAL_EXTRA" <<'EOF'
# Global Caddy extra directives
# Add plugin-specific configuration here.
# This file is imported into the global block of the Caddyfile.
#
# Example:
#   tls {
#     dns hetzner {env.HETZNER_API_TOKEN}
#   }
EOF
        log_info "Created default: $GLOBAL_EXTRA"
    fi
else
    log_info "Plugin config exists: $GLOBAL_EXTRA"
fi

# ── 7. Rebuild and restart Caddy ──
echo ""
echo "=== Rebuilding and Restarting Caddy ==="
if [[ "$DRY_RUN" == true ]]; then
    log_warn "[DRY-RUN] Would rebuild Caddy image and restart containers."
    log_warn "[DRY-RUN] Would run: docker compose up -d --build --remove-orphans"
else
    cd "$PROJECT_DIR"

    # Generate Caddyfile
    if command -v python3 &> /dev/null; then
        if [[ -f "$PROJECT_DIR/config/apps.toml" ]]; then
            python3 "$SCRIPT_DIR/generate-caddy-config.py" --config "$PROJECT_DIR/config/apps.toml"
        else
            log_warn "No apps.toml found. Caddyfile generation skipped."
        fi
    fi

    # Rebuild and restart
    if command -v docker &> /dev/null; then
        echo ""
        echo "Building Caddy image (this may take a while if plugins changed)..."
        docker compose build caddy 2>&1 || {
            log_warn "docker compose build failed. Trying 'docker compose build --no-cache'..."
            docker compose build --no-cache caddy
        }

        echo ""
        echo "Starting containers..."
        docker compose up -d --remove-orphans

        echo ""
        echo "=== Status ==="
        docker compose ps
    else
        log_warn "Docker not found. Skipping container rebuild."
    fi
fi

echo ""
if [[ "$DRY_RUN" == true ]]; then
    echo "Dry-run complete. Run without --dry-run to apply changes."
else
    echo "=== Update Complete ==="
    echo ""
    echo "Your gateway has been updated. If you added new plugins,"
    echo "the changes are now compiled into the Caddy image."
    echo ""
    echo "Next steps:"
    echo "1. Add plugin config to 'gatectl plugin config' if needed"
    echo "2. Add per-app directives via 'gatectl app <id> config'"
    echo "3. Run 'gatectl apply' to reload Caddy after config changes"
fi