#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "WARN: scripts/apps.sh is deprecated. Use scripts/gatectl or gatectl instead." >&2
exec "${SCRIPT_DIR}/gatectl" "$@"
