#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JWT_DIR="${SCRIPT_DIR}/../caddy/jwt"

mkdir -p "${JWT_DIR}"

openssl genrsa -out "${JWT_DIR}/sign_key1.pem" 4096
openssl rsa -in "${JWT_DIR}/sign_key1.pem" -pubout -out "${JWT_DIR}/verify_key1.pem"

chmod 600 "${JWT_DIR}/sign_key1.pem"
chmod 644 "${JWT_DIR}/verify_key1.pem"

echo "JWT keys written to ${JWT_DIR}"
