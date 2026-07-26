#!/usr/bin/env bash
set -euo pipefail

echo "==> Updating system packages"
apt update && apt upgrade -y

echo "==> Configuring UFW"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status

echo "==> Installing Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

if id -nG "${SUDO_USER:-$USER}" 2>/dev/null | grep -qw docker; then
  echo "User already in docker group"
else
  usermod -aG docker "${SUDO_USER:-$USER}" || true
fi

apt install -y docker-compose-plugin

echo "==> Docker version"
docker --version
docker compose version

echo "==> Server setup complete"
