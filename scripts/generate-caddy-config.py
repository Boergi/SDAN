#!/usr/bin/env python3
"""Generate the runtime Caddyfile from a template and app config."""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path("config/apps.toml")
DEFAULT_OUTPUT = Path(".generated/Caddyfile")
DEFAULT_TOKEN_HEADER = "X-Proxy-Token"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$")
HEADER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
VALID_PROVIDERS = {"azure", "authentik", "none"}


class ConfigError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--provider", choices=VALID_PROVIDERS, default="azure",
                        help="OIDC provider: azure, authentik, or none (default: azure)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def required_string(app: dict[str, Any], field: str, app_index: int) -> str:
    value = app.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"apps[{app_index}].{field} must be a non-empty string")
    return value.strip()


def validate_app(app: Any, app_index: int, seen_ids: set[str], seen_hosts: set[str]) -> dict[str, Any] | None:
    if not isinstance(app, dict):
        raise ConfigError(f"apps[{app_index}] must be a table")

    enabled = app.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(f"apps[{app_index}].enabled must be a boolean")
    if not enabled:
        return None

    app_id = required_string(app, "id", app_index)
    if not ID_PATTERN.fullmatch(app_id):
        raise ConfigError(f"apps[{app_index}].id must match {ID_PATTERN.pattern}")
    if app_id in seen_ids:
        raise ConfigError(f"Duplicate app id: {app_id}")
    seen_ids.add(app_id)

    title = required_string(app, "title", app_index)
    host = required_string(app, "host", app_index).lower()
    if "://" in host or "/" in host or not HOST_PATTERN.fullmatch(host):
        raise ConfigError(f"apps[{app_index}].host must be a bare hostname")
    if host in seen_hosts:
        raise ConfigError(f"Duplicate app host: {host}")
    seen_hosts.add(host)

    upstream = required_string(app, "upstream", app_index)
    if any(char.isspace() for char in upstream):
        raise ConfigError(f"apps[{app_index}].upstream must not contain whitespace")

    icon = app.get("icon", "las la-th-large")
    if not isinstance(icon, str) or not icon.strip():
        raise ConfigError(f"apps[{app_index}].icon must be a non-empty string")

    target_blank = app.get("target_blank", True)
    if not isinstance(target_blank, bool):
        raise ConfigError(f"apps[{app_index}].target_blank must be a boolean")

    portal = app.get("portal", True)
    if not isinstance(portal, bool):
        raise ConfigError(f"apps[{app_index}].portal must be a boolean")

    public = app.get("public", False)
    if not isinstance(public, bool):
        raise ConfigError(f"apps[{app_index}].public must be a boolean")

    token_header = app.get("token_header", DEFAULT_TOKEN_HEADER)
    if not isinstance(token_header, str) or not token_header.strip():
        raise ConfigError(f"apps[{app_index}].token_header must be a non-empty string")
    token_header = token_header.strip()
    if not HEADER_PATTERN.fullmatch(token_header):
        raise ConfigError(f"apps[{app_index}].token_header must be a valid HTTP header name")

    tokens = validate_tokens(app.get("tokens", []), app_index)
    trusted_ips = validate_trusted_ips(app.get("trusted_ips", []), app_index)

    return {
        "id": app_id,
        "policy": f"sso_policy_{app_id.replace('-', '_')}",
        "title": title,
        "host": host,
        "upstream": upstream,
        "icon": icon.strip(),
        "target_blank": target_blank,
        "portal": portal,
        "public": public,
        "token_header": token_header,
        "tokens": tokens,
        "trusted_ips": trusted_ips,
    }


def validate_tokens(tokens: Any, app_index: int) -> list[dict[str, str]]:
    if tokens is None:
        return []
    if not isinstance(tokens, list):
        raise ConfigError(f"apps[{app_index}].tokens must be an array")

    seen_names: set[str] = set()
    seen_values: set[str] = set()
    validated: list[dict[str, str]] = []
    for token_index, token in enumerate(tokens):
        if not isinstance(token, dict):
            raise ConfigError(f"apps[{app_index}].tokens[{token_index}] must be a table")

        name = token.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"apps[{app_index}].tokens[{token_index}].name must be a non-empty string")
        name = name.strip()
        if name in seen_names:
            raise ConfigError(f"Duplicate token name for apps[{app_index}]: {name}")
        seen_names.add(name)

        value = token.get("token")
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"apps[{app_index}].tokens[{token_index}].token must be a non-empty string")
        value = value.strip()
        if any(char.isspace() for char in value) or "*" in value:
            raise ConfigError(f"apps[{app_index}].tokens[{token_index}].token must not contain whitespace or '*'")
        if value in seen_values:
            raise ConfigError(f"Duplicate token value for apps[{app_index}]")
        seen_values.add(value)

        validated.append({"name": name, "token": value})
    return validated


def validate_trusted_ips(trusted_ips: Any, app_index: int) -> list[str]:
    if trusted_ips is None:
        return []
    if not isinstance(trusted_ips, list):
        raise ConfigError(f"apps[{app_index}].trusted_ips must be an array")

    seen_ips: set[str] = set()
    validated: list[str] = []
    for trusted_ip_index, trusted_ip in enumerate(trusted_ips):
        if not isinstance(trusted_ip, str) or not trusted_ip.strip():
            raise ConfigError(
                f"apps[{app_index}].trusted_ips[{trusted_ip_index}] must be a non-empty string"
            )
        trusted_ip = trusted_ip.strip()
        if any(char.isspace() for char in trusted_ip):
            raise ConfigError(
                f"apps[{app_index}].trusted_ips[{trusted_ip_index}] must not contain whitespace"
            )
        try:
            ipaddress.ip_network(trusted_ip, strict=False)
        except ValueError as exc:
            raise ConfigError(
                f"apps[{app_index}].trusted_ips[{trusted_ip_index}] must be an IP address or CIDR range"
            ) from exc
        if trusted_ip in seen_ips:
            raise ConfigError(f"Duplicate trusted IP for apps[{app_index}]: {trusted_ip}")
        seen_ips.add(trusted_ip)
        validated.append(trusted_ip)
    return validated


def load_apps(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_apps = config.get("apps", [])
    if not isinstance(raw_apps, list):
        raise ConfigError("Config must contain an apps array")

    seen_ids: set[str] = set()
    seen_hosts: set[str] = set()
    apps: list[dict[str, Any]] = []
    for index, raw_app in enumerate(raw_apps):
        app = validate_app(raw_app, index, seen_ids, seen_hosts)
        if app:
            apps.append(app)
    return apps


def render_portal_links(apps: list[dict[str, Any]]) -> str:
    portal_apps = [app for app in apps if app["portal"]]
    if not portal_apps:
        return ""

    lines = ["        links {"]
    for app in portal_apps:
        target = " target_blank" if app["target_blank"] else ""
        lines.append(
            f"          {quote(app['title'])} https://{app['host']}/{target} icon {quote(app['icon'])}"
        )
    lines.append("        }")
    return "\n".join(lines)


def render_authorization_policies(apps: list[dict[str, Any]], provider: str) -> str:
    # No authorization policies for "none" provider
    if provider == "none":
        return ""
    
    blocks: list[str] = []
    provider_lower = provider.lower()
    for app in apps:
        if app["public"]:
            continue
        blocks.append(
            f"""
    authorization policy {app['policy']} {{
      crypto key key1 sign from file /etc/caddy/jwt/sign_key1.pem
      crypto key key1 verify from file /etc/caddy/jwt/verify_key1.pem
      set auth url https://{{$AUTH_DOMAIN}}/proxy/auth/oauth2/{provider_lower}/
      allow roles authp/user
      validate bearer header
    }}"""
        )
    return "".join(blocks)


def render_app_sites(apps: list[dict[str, Any]], provider: str) -> str:
    blocks: list[str] = []
    for app in apps:
        if app["public"]:
            blocks.append(
                f"""

{app['host']} {{
  import security_baseline

  reverse_proxy {app['upstream']}
}}"""
            )
            continue

        # For "none" provider: no SSO, just IP and token auth
        if provider == "none":
            trusted_ip_matcher = ""
            trusted_ip_handle = ""
            token_matchers: list[str] = []
            token_handles: list[str] = []
            matcher_prefix = app["id"].replace("-", "_")
            if app["trusted_ips"]:
                trusted_ip_matcher = f"""

  @trusted_ip_{matcher_prefix} {{
    remote_ip {' '.join(app['trusted_ips'])}
  }}"""
                trusted_ip_handle = f"""

  handle @trusted_ip_{matcher_prefix} {{
    reverse_proxy {app['upstream']}
  }}"""

            for index, token in enumerate(app["tokens"]):
                matcher = f"token_{matcher_prefix}_{index}"
                token_matchers.append(
                    f"""

  @{matcher} {{
    header {app['token_header']} {quote(token["token"])}
  }}"""
                )
                token_handles.append(
                    f"""

  handle @{matcher} {{
    reverse_proxy {app['upstream']}
  }}"""
                )

            blocks.append(
                f"""

{app['host']} {{
  import security_baseline

{trusted_ip_matcher}
{''.join(token_matchers)}
{trusted_ip_handle}
{''.join(token_handles)}

  handle {{
    respond "Forbidden" 403
  }}
}}"""
            )
            continue

        # For providers with SSO: central auth redirect + authorization
        trusted_ip_matcher = ""
        trusted_ip_handle = ""
        token_matchers: list[str] = []
        token_handles: list[str] = []
        matcher_prefix = app["id"].replace("-", "_")
        if app["trusted_ips"]:
            trusted_ip_matcher = f"""

  @trusted_ip_{matcher_prefix} {{
    remote_ip {' '.join(app['trusted_ips'])}
  }}"""
            trusted_ip_handle = f"""

  handle @trusted_ip_{matcher_prefix} {{
    reverse_proxy {app['upstream']}
  }}"""

        for index, token in enumerate(app["tokens"]):
            matcher = f"token_{matcher_prefix}_{index}"
            token_matchers.append(
                f"""

  @{matcher} {{
    header {app['token_header']} {quote(token["token"])}
  }}"""
            )
            token_handles.append(
                f"""

  handle @{matcher} {{
    reverse_proxy {app['upstream']}
  }}"""
            )

        blocks.append(
            f"""

{app['host']} {{
  import security_baseline

  @centralAuth path /proxy/auth*
{trusted_ip_matcher}
{''.join(token_matchers)}
{trusted_ip_handle}
{''.join(token_handles)}

  handle @centralAuth {{
    redir https://{{$AUTH_DOMAIN}}{{uri}} 302
  }}

  handle {{
    authorize with {app['policy']}
    reverse_proxy {app['upstream']}
  }}
}}"""
        )
    return "".join(blocks)


def main() -> int:
    args = parse_args()
    
    # Determine template path based on provider
    script_dir = Path(__file__).parent.resolve()
    template_path = script_dir.parent / "caddy" / "templates" / f"{args.provider}.tmpl"
    
    try:
        config = load_toml(args.config)
        apps = load_apps(config)
        template = template_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        print(f"ERROR: Template file not found: {template_path}", file=sys.stderr)
        return 1
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rendered = template
    rendered = rendered.replace("{{PORTAL_LINKS_BLOCK}}", render_portal_links(apps))
    rendered = rendered.replace("{{AUTHORIZATION_POLICIES}}", render_authorization_policies(apps, args.provider))
    rendered = rendered.replace("{{APP_SITE_BLOCKS}}", render_app_sites(apps, args.provider))

    unresolved = sorted(set(re.findall(r"{{[A-Z_]+}}", rendered)))
    if unresolved:
        print(f"ERROR: Unresolved template placeholders: {', '.join(unresolved)}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(f"Generated {args.output} from {template_path} ({len(apps)} app(s), provider: {args.provider})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
