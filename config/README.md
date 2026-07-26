# Gatectl Proxy Config

`apps.toml` is the source of truth for portal entries and protected reverse proxy hosts.
It is intentionally ignored by Git. The repository only ships `apps.example.toml`.

Create a local/server config once:

```bash
./scripts/gatectl init
```

Use `gatectl` for routine changes:

```bash
./scripts/gatectl help
./scripts/gatectl list
./scripts/gatectl add myapp "Your App" myapp.yourdomain.com http://my-app:3000 --icon "las la-clock"
./scripts/gatectl disable myapp
./scripts/gatectl enable myapp
./scripts/gatectl remove myapp
./scripts/gatectl public enable myapp
./scripts/gatectl public list myapp
./scripts/gatectl public disable myapp
./scripts/gatectl token add myapp "CI deploy"
./scripts/gatectl token list myapp
./scripts/gatectl token remove myapp "CI deploy"
./scripts/gatectl trusted-ip add myapp 203.0.113.10
./scripts/gatectl trusted-ip list myapp
./scripts/gatectl trusted-ip remove myapp 203.0.113.10
./scripts/gatectl apply
./scripts/deploy.sh
```

The helper updates `apps.toml` and regenerates `.generated/Caddyfile`. Deploy remains a
separate step on purpose. `deploy.sh` preserves the server-side `config/apps.toml` like
`.env`, so manage app config on the server or copy it there intentionally.
Run config commands against the config you want to change; for production changes this
usually means SSHing into the server and running `gatectl ...` there. After
server-side config changes, run `gatectl apply` to reload Caddy with the
new config.

## Updating an Existing Installation

When pulling new changes from Git, use the update script to ensure everything is
properly migrated:

```bash
# Update locally (adds missing directories, .env keys, rebuilds Caddy)
./scripts/update.sh

# Preview what would change without applying anything
./scripts/update.sh --dry-run

# Update a remote server (syncs files and runs update remotely)
./scripts/update.sh --remote user@yourserver.com:/srv/gateway
```

The update script:
1. Creates any missing directories (`caddy/extra/apps`, etc.)
2. Adds missing `.env` keys with sensible defaults
3. Uncomments commented-out keys in `.env`
4. Checks that `docker-compose.yml` has the required volume mounts
5. Verifies Caddy templates have the `import extra/global.caddy` directive
6. Creates a default `caddy/extra/global.caddy` if missing
7. Rebuilds the Caddy image and restarts containers

## Caddy Plugin Management

Gatectl supports installing additional Caddy modules via xcaddy. Plugins are compiled
into the Caddy image at build time.

```bash
# Add a plugin (e.g., Hetzner DNS challenge)
gatectl plugin add github.com/caddy-dns/hetzner/v2@v2.0.1

# List installed plugins
gatectl plugin list

# Remove a plugin
gatectl plugin remove github.com/caddy-dns/hetzner/v2@v2.0.1

# After adding/removing plugins, rebuild the image:
gatectl apply --rebuild
```

### Global Plugin Configuration (`caddy/extra/global.caddy`)

Some plugins need configuration in the global Caddy block (e.g., DNS tokens for ACME).
Create or edit the global config file:

```bash
gatectl plugin config
```

This opens `caddy/extra/global.caddy` in your `$EDITOR`. The content is imported
into the global block of the generated Caddyfile.

Example `caddy/extra/global.caddy`:
```caddy
# Hetzner DNS for ACME DNS-01 challenge
tls {
  dns hetzner {env.HETZNER_API_TOKEN}
}
```

Place secrets like `HETZNER_API_TOKEN` in `.env` – they are automatically available
as environment variables in the Caddy container.

### Per-App Extra Directives (`caddy/extra/apps/<id>.caddy`)

Add Caddy directives specific to a single app without modifying `apps.toml`:

```bash
gatectl app w1 config
```

This opens `caddy/extra/apps/w1.caddy` in your `$EDITOR`. The content is injected
into the site block for `w1` when the Caddyfile is generated.

Example `caddy/extra/apps/w1.caddy`:
```caddy
# Rate-limit for w1
rate_limit {
  zone dynamic 10r/s
}
```

When Caddyfile is regenerated, it produces:
```caddy
w1.yourdomain.com {
  # --- extra/apps/w1.caddy ---
  # Rate-limit for w1
  rate_limit {
    zone dynamic 10r/s
  }

  reverse_proxy http://w1-app:80
}
```

Install `gatectl` globally for your user:

```bash
./scripts/gatectl install
```

By default this writes a launcher to `~/.local/bin/gatectl` and completion files below
`~/.local/share`. Ensure `~/.local/bin` is in your `PATH`. You can also print completion
scripts directly:

```bash
gatectl completion bash
gatectl completion zsh
```

You can still run the generator directly:

```bash
python3 scripts/generate-caddy-config.py --config config/apps.toml
```

Fields:

- `id`: stable lowercase id, used for generated Caddy policy names.
- `title`: label shown in the portal.
- `host`: public hostname served by Caddy.
- `upstream`: Caddy upstream, usually an alias on `proxy_net`.
- `icon`: Line Awesome icon class for the portal tile.
- `target_blank`: open portal link in a new tab.
- `enabled`: set `false` to keep an app in config without publishing it.
- `portal`: set `false` to publish the host without showing a portal tile.
- `public`: set `true` to publish the app without SSO, token, or trusted IP checks.
- `token_header`: optional header name for token access, defaults to `X-Proxy-Token`.
- `tokens`: optional named access tokens for this app. Requests with a matching token
  header bypass SSO and are proxied directly to the app.
- `trusted_ips`: optional IP addresses or CIDR ranges that bypass SSO and token checks
  for this app.

Public app example:

```toml
[[apps]]
id = "status"
title = "Status"
host = "status.yourdomain.com"
upstream = "http://status-app:3000"
public = true
```

For public apps, Caddy only imports the security baseline and reverse proxies to the
upstream. Existing `tokens` or `trusted_ips` in the app config remain stored, but are
inactive until `public` is set back to `false`.

Trusted IP example in `config/apps.toml`:

```toml
trusted_ips = [
  "203.0.113.10",
  "198.51.100.0/24",
]
```

Token example in `config/apps.toml`:

```toml
[[apps]]
id = "myapp"
title = "Your App"
host = "myapp.yourdomain.com"
upstream = "http://my-app:3000"

[[apps.tokens]]
name = "CI deploy"
token = "generated-secret-token"
```

`[[apps.tokens]]` is a nested TOML table and belongs to the most recent `[[apps]]`
table above it. In the example above, the token belongs to the `myapp` app. The helper
scripts always write tokens directly below their owning app block.

Use a token like this:

```bash
curl -H "X-Proxy-Token: <token>" https://myapp.yourdomain.com/
```

Trusted IPs are based on the client IP Caddy sees. If Caddy is behind Cloudflare, a
load balancer, or another reverse proxy, configure trusted forwarded headers first;
otherwise the matcher will see the proxy IP instead of the real client IP.

Apply config:

```bash
gatectl apply
```

`apply` validates `apps.toml`, regenerates `.generated/Caddyfile`, runs Docker Compose
config validation, validates the running Caddy config in the container, and reloads
Caddy. Use `--rebuild` to rebuild the Caddy image and force-recreate containers. Use
`--no-reload` to generate and validate without touching running containers, or
`--skip-compose-check` to skip the Compose config validation. For a pure Caddyfile
regeneration, combine `--no-reload` and `--skip-compose-check`.