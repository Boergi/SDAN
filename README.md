# Secure Docker App Network User Manual

This repository runs a Caddy-based gateway for publishing Docker apps behind SSO,
token access, trusted IP bypasses, or public access. The operational CLI is `gatectl`.

The goal is simple: app projects stay in their own repositories and Docker Compose
stacks. Only the public app container joins the shared proxy network. This repository
owns the gateway, the auth portal, and the generated Caddy config.

## Quick Start

On the server:

```bash
cd /srv/gateway
gatectl list
gatectl apply
```

Common workflow after changing app config:

```bash
gatectl add myapp "Your App" myapp.yourdomain.com http://my-app:3000
gatectl apply
```

Use a full rebuild only when the Caddy image or container definition changed:

```bash
gatectl apply --rebuild
```

## Core Concepts

- `config/apps.toml` is the source of truth for published apps.
- `config/apps.toml` is intentionally ignored by Git, like `.env`.
- `gatectl` edits `config/apps.toml` and regenerates `.generated/Caddyfile`.
- Caddy serves the auth portal and app hostnames.
- Docker apps connect their public web container to `proxy_net`.
- The app itself usually lives in a separate repository and Compose stack.

Request handling for protected apps:

1. Trusted IP match: directly proxy to the app.
2. Token header match: directly proxy to the app.
3. Otherwise: require SSO.

For public apps, Caddy skips SSO, token checks, and trusted IP checks.

## Repository Layout

```text
.
├── apps/                       Example app stacks only
├── caddy/
│   ├── templates/              Caddyfile templates (azure, authentik, none)
│   ├── snippets/               Caddy snippets
│   ├── ui/                     Portal UI assets
│   └── jwt/                    JWT key material
├── config/
│   ├── apps.example.toml       Example app config tracked by Git
│   └── apps.toml               Real app config, ignored by Git
├── scripts/
│   ├── setup.sh                Interactive setup script
│   ├── gatectl                 CLI wrapper
│   ├── gatectl.py              CLI implementation
│   ├── deploy.sh               Deploys code to the server
│   └── generate-caddy-config.py
├── .generated/                 Generated Caddyfile (ignored by Git)
├── docker-compose.yml          Gateway stack
├── .env                        Environment variables (ignored by Git)
└── .env.example                Example environment file
```

## Installing Gatectl

From the repo:

```bash
./scripts/gatectl install
```

Default install target:

```text
~/.local/bin/gatectl
~/.local/share/bash-completion/completions/gatectl
~/.local/share/zsh/site-functions/_gatectl
```

Make sure this is in your shell `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Print completion manually:

```bash
gatectl completion bash
gatectl completion zsh
```

The old `./scripts/apps.sh` wrapper still works, but it is deprecated.

## Initial Setup

The easiest way to get started is to run the interactive setup script:

```bash
./scripts/setup.sh
```

This script will:
- Ask you to choose your authentication provider (Azure AD, Authentik, or none)
- Collect all necessary credentials
- Generate the `.env` file
- Create the Caddy configuration
- Build and start the Docker containers

### Supported Providers

#### Azure AD (Microsoft Entra ID)
- Best for: Organizations already using Microsoft 365
- Requires: Azure subscription with Entra ID

#### Authentik
- Best for: Self-hosted identity management
- Requires: Running Authentik instance with OpenID Connect provider configured

#### No SSO (IP + Token only)
- Best for: Internal networks where IP-based access control is sufficient
- Features: Trusted IP ranges and token headers still work

### Manual Setup (Advanced)

If you prefer to configure manually:

1. Copy `.env.example` to `.env` and fill in the values:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

2. Generate the Caddyfile:
   ```bash
   ./scripts/generate-caddy-config.py --provider azure
   ```

3. Start the containers:
   ```bash
   docker compose up -d
   ```

## Gatectl Command Reference

Show all commands:

```bash
gatectl help
```

List configured apps:

```bash
gatectl list
```

Add an app:

```bash
gatectl add myapp "Your App" myapp.yourdomain.com http://my-app:3000
```

Add an app without a portal tile:

```bash
gatectl add api "Internal API" api.yourdomain.com http://api-app:8080 --no-portal
```

Disable or enable an app:

```bash
gatectl disable myapp
gatectl enable myapp
```

Remove an app from config:

```bash
gatectl remove myapp
```

Apply config:

```bash
gatectl apply
```

Apply with container rebuild:

```bash
gatectl apply --rebuild
```

Only regenerate and validate:

```bash
gatectl apply --no-reload
```

## Access Modes

### Protected SSO

Default mode. If no trusted IP or token matches, the user is sent through SSO.

```toml
[[apps]]
id = "myapp"
title = "Your App"
host = "myapp.yourdomain.com"
upstream = "http://my-app:3000"
enabled = true
```

### Token Access

Create a named token:

```bash
gatectl token add myapp "CI deploy"
```

Use it:

```bash
curl -H "X-Proxy-Token: <token>" https://myapp.yourdomain.com/
```

List token names:

```bash
gatectl token list myapp
```

Remove a token:

```bash
gatectl token remove myapp "CI deploy"
```

Token values live in `config/apps.toml` and are not committed. `token list` shows names,
not secret values.

### Trusted IP Bypass

Allow one IP or CIDR range to bypass SSO and token checks:

```bash
gatectl trusted-ip add myapp 203.0.113.10
gatectl trusted-ip add myapp 198.51.100.0/24
```

List and remove:

```bash
gatectl trusted-ip list myapp
gatectl trusted-ip remove myapp 203.0.113.10
```

Important: trusted IP matching uses the client IP Caddy sees. If Cloudflare, a load
balancer, or another reverse proxy is in front of Caddy, configure forwarded headers
and trusted proxies first.

### Public Apps

Make an app public:

```bash
gatectl public enable myapp
```

Disable public access:

```bash
gatectl public disable myapp
```

Check public state:

```bash
gatectl public list myapp
```

`public = true` means no SSO, no token check, and no trusted IP check. Existing tokens
and trusted IPs stay in config but are inactive until public mode is disabled again.

## Config File

The live file is:

```text
config/apps.toml
```

Example:

```toml
[[apps]]
id = "myapp"
title = "Your App"
host = "myapp.yourdomain.com"
upstream = "http://my-app:3000"
icon = "las la-clock"
target_blank = true
enabled = true

trusted_ips = [
  "203.0.113.10",
]

[[apps.tokens]]
name = "CI deploy"
token = "generated-secret-token"
```

`[[apps.tokens]]` belongs to the most recent `[[apps]]` block above it. The helper
writes tokens directly below their owning app block to keep that relationship obvious.

Useful fields:

- `id`: stable lowercase app id.
- `title`: portal label.
- `host`: public hostname.
- `upstream`: Caddy upstream, usually a Docker network alias.
- `icon`: portal icon class.
- `enabled`: publish or unpublish the app.
- `portal`: show or hide the portal tile.
- `public`: publish without auth checks.
- `token_header`: defaults to `X-Proxy-Token`.
- `trusted_ips`: IP/CIDR bypass list.

## App Compose Pattern

Real apps should live outside this repo. Only the public app service joins
`proxy_net`.

```yaml
services:
  app:
    image: example/app:latest
    networks:
      app_net:
      proxy_net:
        aliases:
          - my-app

  database:
    image: postgres:16
    networks:
      - app_net

networks:
  app_net:
    driver: bridge

  proxy_net:
    external: true
    name: proxy_net
```

Then route to the alias:

```bash
gatectl add myapp "Your App" myapp.yourdomain.com http://my-app:3000
gatectl apply
```

### Securing Apps Behind the Proxy (No Direct Access)

When an app is integrated with the proxy, it is **critical that the app container does not expose ports directly to the host**. Otherwise, clients could bypass the proxy (and its SSO, token checks, and IP filtering) by connecting directly to the host IP and port.

Follow these rules to ensure an app is only reachable through the gateway:

1. **Do not add `ports:` to the app service.**  
   The proxy accesses the app via Docker's internal network (`proxy_net`), not through published host ports.

   ```yaml
   # ❌ BAD – exposes the app directly on the host
   services:
     app:
       ports:
         - "3000:3000"

   # ✅ GOOD – only reachable through the proxy
   services:
     app:
       networks:
         proxy_net:
           aliases:
             - my-app
   ```

2. **Attach only the public web container to `proxy_net`.**  
   Backend services like databases, caches, or internal APIs should stay on an isolated internal network (`app_net`) and must **not** be attached to `proxy_net`. This prevents accidental exposure of internal services.

3. **Do not publish ports on the proxy network.**  
   The `proxy_net` network is created externally by the gateway stack. App stacks consume it with `external: true`. No app should define or publish host ports on this network.

4. **Verify the app is not directly reachable.**  
   After starting the app stack, check that no host ports are listening for the app:

   ```bash
   docker compose ps
   ```

   The `PORTS` column should be empty for the app container. If it shows a mapped port like `0.0.0.0:3000->3000/tcp`, the app is directly reachable on the host and bypasses the proxy.

5. **For apps that must listen on a specific port internally** (e.g., port `3000`), the port is only relevant within the Docker network. The proxy upstream will use `http://my-app:3000` internally — no host port mapping is required.

This pattern applies to all apps integrated with the gateway, whether they are example apps in this repo or real applications in external repositories.

## Deployment

Local-to-server code deployment:

```bash
./scripts/deploy.sh
```

Default target:

```text
user@yourserver.com:/srv/gateway
```

Override target:

```bash
DEPLOY_SERVER=user@example.com DEPLOY_DIR=/srv/gateway ./scripts/deploy.sh
```

`deploy.sh` preserves these server-side files:

- `.env`
- `config/apps.toml`
- generated JWT key material

Normal production app config changes should be done on the server:

```bash
ssh user@yourserver.com
cd /srv/gateway
gatectl add myapp "Your App" myapp.yourdomain.com http://my-app:3000
gatectl apply
```

## Operational Checks

Gateway status:

```bash
docker compose ps
```

Validate generated Caddy config without reload:

```bash
gatectl apply --no-reload
```

Rebuild and recreate the gateway container:

```bash
gatectl apply --rebuild
```

Check SSO redirect:

```bash
curl -I https://w1.yourdomain.com/
```

Check token access:

```bash
curl -H "X-Proxy-Token: <token>" https://w1.yourdomain.com/
```

## Troubleshooting

`gatectl: command not found`

Add `~/.local/bin` to `PATH` or run the repo wrapper:

```bash
./scripts/gatectl list
```

Completion does not work

Load the generated completion file:

```bash
source ~/.local/share/bash-completion/completions/gatectl
```

For zsh, add the completion folder to `fpath` before `compinit`:

```bash
fpath=(~/.local/share/zsh/site-functions $fpath)
autoload -Uz compinit && compinit
```

Caddy does not see the app

Check that the app container is attached to `proxy_net` and has the alias used by
`upstream`.

```bash
docker network inspect proxy_net
```

Config changed but behavior did not

Run:

```bash
gatectl apply
```

If the Caddy image or Compose definition changed, use:

```bash
gatectl apply --rebuild
```

## Security Notes

- Treat Docker group access as root-equivalent.
- Keep `config/apps.toml` private; it may contain token secrets.
- Prefer SSO by default.
- Use public mode only for intentionally public services.
- Use trusted IP bypasses only when Caddy sees the real client IP.
- Rotate tokens by adding a new named token, updating clients, then removing the old one.