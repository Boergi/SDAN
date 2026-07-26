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