#!/usr/bin/env python3
"""Manage the proxy gate in config/apps.toml."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import secrets
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = REPO_ROOT / "config/apps.toml"
DEFAULT_EXAMPLE_CONFIG = REPO_ROOT / "config/apps.example.toml"
GENERATOR = SCRIPT_DIR / "generate-caddy-config.py"
DEFAULT_TOKEN_HEADER = "X-Proxy-Token"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$")
HEADER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
PLUGIN_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9./_-]+(@[a-zA-Z0-9.]+)?$")
DETAILED_HELP = """Commands:
  init                         Create config/apps.toml from config/apps.example.toml.
  apply                        Regenerate .generated/Caddyfile, validate, and reload Caddy.
  list                         Show all configured apps and their access mode.
  add                          Add an app host/upstream to the config.
  enable / disable             Publish or unpublish an app without removing its config.
  remove                       Remove an app from the config.
  public enable|disable|list   Toggle or inspect no-auth public access for an app.
  token add|list|remove        Manage named X-Proxy-Token style app access tokens.
  trusted-ip add|list|remove   Manage IP/CIDR bypasses for an app.
  plugin add|list|remove       Manage additional Caddy plugins (xcaddy --with flags).
  plugin config                Open caddy/extra/global.caddy in $EDITOR for global plugin config.
  app <id> config              Open per-app Caddy extra directives in $EDITOR.
  completion bash|zsh          Print shell completion for tab completion.
  install                      Install gatectl globally and write completion files.
  help                         Show this detailed help.

Access order for protected apps:
  trusted_ips match -> reverse proxy directly
  token header match -> reverse proxy directly
  otherwise -> SSO

Public apps:
  public = true disables SSO, trusted IP checks, and token checks for that app.
  Existing token/trusted_ip config remains stored but is inactive until public is disabled.

Examples:
  gatectl add myapp "Your App" myapp.yourdomain.com http://my-app:3000
  gatectl public enable myapp
  gatectl token add myapp "CI deploy"
  gatectl trusted-ip add myapp 203.0.113.10
  gatectl apply
"""


class AppConfigError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gatectl",
        description=__doc__,
        epilog=DETAILED_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to apps.toml")
    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="Do not regenerate .generated/Caddyfile after a write operation",
    )

    subcommands = parser.add_subparsers(dest="command", required=True)

    init = subcommands.add_parser("init", help="Create config/apps.toml from the example config")
    init.add_argument("--force", action="store_true", help="Overwrite an existing app config")

    apply = subcommands.add_parser("apply", help="Regenerate config and reload Caddy")
    apply.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the image and force-recreate Docker containers instead of only reloading Caddy",
    )
    apply.add_argument(
        "--no-reload",
        "--no-restart",
        dest="no_reload",
        action="store_true",
        help="Generate and validate, but do not reload or rebuild/restart containers",
    )
    apply.add_argument("--skip-compose-check", action="store_true", help="Skip Docker Compose config validation")

    subcommands.add_parser("help", help="Show detailed command help")

    subcommands.add_parser("list", help="List configured apps")

    add = subcommands.add_parser("add", help="Add a new app")
    add.add_argument("id", help="Stable app id, e.g. myapp")
    add.add_argument("title", help="Portal title")
    add.add_argument("host", help="Public host, e.g. myapp.yourdomain.com")
    add.add_argument("upstream", help="Caddy upstream, e.g. http://my-app:3000")
    add.add_argument("--icon", default="las la-th-large", help="Line Awesome icon class")
    add.add_argument("--same-tab", action="store_true", help="Do not open the portal link in a new tab")
    add.add_argument("--disabled", action="store_true", help="Create the app as disabled")
    add.add_argument("--no-portal", action="store_true", help="Publish the host without a portal tile")
    add.add_argument("--public", action="store_true", help="Publish without SSO, tokens, or trusted IP checks")
    add.add_argument("--token-header", default=DEFAULT_TOKEN_HEADER, help="Header used for app access tokens")
    add.add_argument(
        "--trusted-ip",
        action="append",
        default=[],
        help="IP address or CIDR range that bypasses SSO and token checks; can be repeated",
    )

    enable = subcommands.add_parser("enable", help="Enable an app")
    enable.add_argument("id")

    disable = subcommands.add_parser("disable", help="Disable an app")
    disable.add_argument("id")

    remove = subcommands.add_parser("remove", help="Remove an app from config")
    remove.add_argument("id")

    public = subcommands.add_parser("public", help="Manage app public access")
    public_commands = public.add_subparsers(dest="public_command", required=True)

    public_list = public_commands.add_parser("list", help="Show whether an app is public")
    public_list.add_argument("id")

    public_enable = public_commands.add_parser("enable", help="Make an app public")
    public_enable.add_argument("id")

    public_disable = public_commands.add_parser("disable", help="Require auth rules for an app again")
    public_disable.add_argument("id")

    token = subcommands.add_parser("token", help="Manage app access tokens")
    token_commands = token.add_subparsers(dest="token_command", required=True)

    token_list = token_commands.add_parser("list", help="List token names for an app")
    token_list.add_argument("id")

    token_add = token_commands.add_parser("add", help="Add a named token to an app")
    token_add.add_argument("id")
    token_add.add_argument("name", help="Human-readable token purpose, e.g. ci")
    token_add.add_argument("--token", help="Use a provided token value instead of generating one")
    token_add.add_argument("--header", dest="token_header", help="Set/override the app token header")

    token_remove = token_commands.add_parser("remove", help="Remove a named token from an app")
    token_remove.add_argument("id")
    token_remove.add_argument("name")

    trusted_ip = subcommands.add_parser("trusted-ip", help="Manage app trusted IP bypasses")
    trusted_ip_commands = trusted_ip.add_subparsers(dest="trusted_ip_command", required=True)

    trusted_ip_list = trusted_ip_commands.add_parser("list", help="List trusted IPs for an app")
    trusted_ip_list.add_argument("id")

    trusted_ip_add = trusted_ip_commands.add_parser("add", help="Add a trusted IP/CIDR to an app")
    trusted_ip_add.add_argument("id")
    trusted_ip_add.add_argument("ip", help="IP address or CIDR range, e.g. 203.0.113.10 or 198.51.100.0/24")

    trusted_ip_remove = trusted_ip_commands.add_parser("remove", help="Remove a trusted IP/CIDR from an app")
    trusted_ip_remove.add_argument("id")
    trusted_ip_remove.add_argument("ip")

    completion = subcommands.add_parser("completion", help="Print shell completion script")
    completion.add_argument("shell", choices=("bash", "zsh"), help="Shell to generate completion for")

    install = subcommands.add_parser("install", help="Install gatectl globally for the current user")
    install.add_argument(
        "--prefix",
        type=Path,
        default=Path(os.environ.get("PREFIX", "~/.local")),
        help="Install prefix, defaults to ~/.local or PREFIX",
    )
    install.add_argument(
        "--completion",
        choices=("both", "bash", "zsh", "none"),
        default="both",
        help="Completion files to install",
    )
    install.add_argument("--force", action="store_true", help="Overwrite an existing non-gatectl launcher")

    # Plugin management
    plugin = subcommands.add_parser("plugin", help="Manage additional Caddy plugins")
    plugin_commands = plugin.add_subparsers(dest="plugin_command", required=True)

    plugin_add = plugin_commands.add_parser("add", help="Add a Caddy plugin (e.g. github.com/caddy-dns/hetzner/v2@v2.0.1)")
    plugin_add.add_argument("import_path", help="Go import path with optional @version suffix")

    plugin_list = plugin_commands.add_parser("list", help="List installed Caddy plugins")

    plugin_remove = plugin_commands.add_parser("remove", help="Remove a Caddy plugin")
    plugin_remove.add_argument("import_path", help="Go import path to remove")

    plugin_config = plugin_commands.add_parser("config", help="Open caddy/extra/global.caddy in $EDITOR")

    # App extra config
    app = subcommands.add_parser("app", help="Manage per-app Caddy extra directives")
    app_commands = app.add_subparsers(dest="app_command", required=True)

    app_config = app_commands.add_parser("config", help="Open per-app Caddy extra directives in $EDITOR")
    app_config.add_argument("id", help="App id")

    return parser.parse_args()


def resolve_config(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def load_apps(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except FileNotFoundError as exc:
        raise AppConfigError(
            f"Config file not found: {path}. Run 'gatectl init' first."
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise AppConfigError(f"Invalid TOML in {path}: {exc}") from exc

    raw_apps = config.get("apps", [])
    if not isinstance(raw_apps, list):
        raise AppConfigError("Config must contain an apps array")

    apps: list[dict[str, Any]] = []
    for index, raw_app in enumerate(raw_apps):
        if not isinstance(raw_app, dict):
            raise AppConfigError(f"apps[{index}] must be a table")
        apps.append(normalize_app(raw_app, index))
    validate_unique(apps)
    return apps


def normalize_app(raw_app: dict[str, Any], index: int) -> dict[str, Any]:
    app_id = required_string(raw_app, "id", index)
    if not ID_PATTERN.fullmatch(app_id):
        raise AppConfigError(f"apps[{index}].id must match {ID_PATTERN.pattern}")

    title = required_string(raw_app, "title", index)
    host = required_string(raw_app, "host", index).lower()
    if "://" in host or "/" in host or not HOST_PATTERN.fullmatch(host):
        raise AppConfigError(f"apps[{index}].host must be a bare hostname")

    upstream = required_string(raw_app, "upstream", index)
    if any(char.isspace() for char in upstream):
        raise AppConfigError(f"apps[{index}].upstream must not contain whitespace")

    icon = raw_app.get("icon", "las la-th-large")
    if not isinstance(icon, str) or not icon.strip():
        raise AppConfigError(f"apps[{index}].icon must be a non-empty string")

    enabled = raw_app.get("enabled", True)
    if not isinstance(enabled, bool):
        raise AppConfigError(f"apps[{index}].enabled must be a boolean")

    target_blank = raw_app.get("target_blank", True)
    if not isinstance(target_blank, bool):
        raise AppConfigError(f"apps[{index}].target_blank must be a boolean")

    portal = raw_app.get("portal", True)
    if not isinstance(portal, bool):
        raise AppConfigError(f"apps[{index}].portal must be a boolean")

    public = raw_app.get("public", False)
    if not isinstance(public, bool):
        raise AppConfigError(f"apps[{index}].public must be a boolean")

    token_header = validate_token_header(raw_app.get("token_header", DEFAULT_TOKEN_HEADER), index)
    tokens = normalize_tokens(raw_app.get("tokens", []), index)
    trusted_ips = normalize_trusted_ips(raw_app.get("trusted_ips", []), index)

    return {
        "id": app_id,
        "title": title,
        "host": host,
        "upstream": upstream,
        "icon": icon.strip(),
        "target_blank": target_blank,
        "enabled": enabled,
        "portal": portal,
        "public": public,
        "token_header": token_header,
        "tokens": tokens,
        "trusted_ips": trusted_ips,
    }


def required_string(app: dict[str, Any], field: str, index: int) -> str:
    value = app.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AppConfigError(f"apps[{index}].{field} must be a non-empty string")
    return value.strip()


def validate_token_header(value: Any, index: int | str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppConfigError(f"{app_context(index)}.token_header must be a non-empty string")
    value = value.strip()
    if not HEADER_PATTERN.fullmatch(value):
        raise AppConfigError(f"{app_context(index)}.token_header must be a valid HTTP header name")
    return value


def validate_token_name(value: Any, index: int | str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppConfigError(f"{app_context(index)}.name must be a non-empty string")
    return value.strip()


def validate_token_value(value: Any, index: int | str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppConfigError(f"{app_context(index)}.token must be a non-empty string")
    value = value.strip()
    if any(char.isspace() for char in value) or "*" in value:
        raise AppConfigError(f"{app_context(index)}.token must not contain whitespace or '*'")
    return value


def app_context(index: int | str) -> str:
    if isinstance(index, int):
        return f"apps[{index}]"
    return index


def normalize_tokens(tokens: Any, index: int) -> list[dict[str, str]]:
    if tokens is None:
        return []
    if not isinstance(tokens, list):
        raise AppConfigError(f"apps[{index}].tokens must be an array")

    seen_names: set[str] = set()
    seen_values: set[str] = set()
    normalized: list[dict[str, str]] = []
    for token_index, token in enumerate(tokens):
        if not isinstance(token, dict):
            raise AppConfigError(f"apps[{index}].tokens[{token_index}] must be a table")

        token_context = f"apps[{index}].tokens[{token_index}]"
        name = validate_token_name(token.get("name"), token_context)
        if name in seen_names:
            raise AppConfigError(f"Duplicate token name for apps[{index}]: {name}")
        seen_names.add(name)

        value = validate_token_value(token.get("token"), token_context)
        if value in seen_values:
            raise AppConfigError(f"Duplicate token value for apps[{index}]")
        seen_values.add(value)

        normalized.append({"name": name, "token": value})
    return normalized


def validate_trusted_ip(value: Any, index: int | str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppConfigError(f"{app_context(index)}.trusted_ips must be a non-empty string")
    value = value.strip()
    if any(char.isspace() for char in value):
        raise AppConfigError(f"{app_context(index)}.trusted_ips must not contain whitespace")
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise AppConfigError(f"{app_context(index)}.trusted_ips must be an IP address or CIDR range") from exc
    return value


def normalize_trusted_ips(trusted_ips: Any, index: int) -> list[str]:
    if trusted_ips is None:
        return []
    if not isinstance(trusted_ips, list):
        raise AppConfigError(f"apps[{index}].trusted_ips must be an array")

    seen_ips: set[str] = set()
    normalized: list[str] = []
    for trusted_ip_index, trusted_ip in enumerate(trusted_ips):
        trusted_ip_context = f"apps[{index}].trusted_ips[{trusted_ip_index}]"
        value = validate_trusted_ip(trusted_ip, trusted_ip_context)
        if value in seen_ips:
            raise AppConfigError(f"Duplicate trusted IP for apps[{index}]: {value}")
        seen_ips.add(value)
        normalized.append(value)
    return normalized


def validate_unique(apps: list[dict[str, Any]]) -> None:
    ids: set[str] = set()
    hosts: set[str] = set()
    for app in apps:
        if app["id"] in ids:
            raise AppConfigError(f"Duplicate app id: {app['id']}")
        ids.add(app["id"])

        if app["host"] in hosts:
            raise AppConfigError(f"Duplicate app host: {app['host']}")
        hosts.add(app["host"])


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_apps(apps: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for app in apps:
        lines = [
            "[[apps]]",
            f"id = {quote(app['id'])}",
            f"title = {quote(app['title'])}",
            f"host = {quote(app['host'])}",
            f"upstream = {quote(app['upstream'])}",
            f"icon = {quote(app['icon'])}",
            f"target_blank = {str(app['target_blank']).lower()}",
            f"enabled = {str(app['enabled']).lower()}",
        ]
        if app["portal"] is not True:
            lines.append(f"portal = {str(app['portal']).lower()}")
        if app["public"] is True:
            lines.append("public = true")
        if app["token_header"] != DEFAULT_TOKEN_HEADER:
            lines.append(f"token_header = {quote(app['token_header'])}")
        if app["trusted_ips"]:
            lines.append("trusted_ips = [")
            for trusted_ip in app["trusted_ips"]:
                lines.append(f"  {quote(trusted_ip)},")
            lines.append("]")
        for token in app["tokens"]:
            lines.extend(
                [
                    "",
                    "[[apps.tokens]]",
                    f"name = {quote(token['name'])}",
                    f"token = {quote(token['token'])}",
                ]
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def write_apps(path: Path, apps: list[dict[str, Any]]) -> None:
    validate_unique(apps)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_apps(apps), encoding="utf-8")


def find_app(apps: list[dict[str, Any]], app_id: str) -> dict[str, Any]:
    for app in apps:
        if app["id"] == app_id:
            return app
    raise AppConfigError(f"App not found: {app_id}")


def print_apps(apps: list[dict[str, Any]]) -> None:
    if not apps:
        print("No apps configured")
        return

    id_width = max(len("ID"), *(len(app["id"]) for app in apps))
    state_width = len("STATE")
    access_width = max(len("ACCESS"), *(len("public" if app["public"] else "protected") for app in apps))
    host_width = max(len("HOST"), *(len(app["host"]) for app in apps))

    print(
        f"{'ID':<{id_width}}  {'STATE':<{state_width}}  {'ACCESS':<{access_width}}  "
        f"{'PORTAL':<6}  {'TOKENS':<6}  {'IPS':<3}  {'HOST':<{host_width}}  UPSTREAM"
    )
    for app in apps:
        state = "enabled" if app["enabled"] else "disabled"
        access = "public" if app["public"] else "protected"
        portal = "yes" if app["portal"] else "no"
        tokens = str(len(app["tokens"]))
        trusted_ips = str(len(app["trusted_ips"]))
        print(
            f"{app['id']:<{id_width}}  {state:<{state_width}}  {access:<{access_width}}  "
            f"{portal:<6}  {tokens:<6}  {trusted_ips:<3}  "
            f"{app['host']:<{host_width}}  {app['upstream']}"
        )


def print_tokens(app: dict[str, Any]) -> None:
    print(f"App: {app['id']}")
    print(f"Header: {app['token_header']}")
    if not app["tokens"]:
        print("No tokens configured")
        return

    name_width = max(len("NAME"), *(len(token["name"]) for token in app["tokens"]))
    print(f"{'NAME':<{name_width}}")
    for token in app["tokens"]:
        print(f"{token['name']:<{name_width}}")


def print_trusted_ips(app: dict[str, Any]) -> None:
    print(f"App: {app['id']}")
    if not app["trusted_ips"]:
        print("No trusted IPs configured")
        return

    print("TRUSTED_IP")
    for trusted_ip in app["trusted_ips"]:
        print(trusted_ip)


def print_public(app: dict[str, Any]) -> None:
    state = "public" if app["public"] else "protected"
    print(f"App: {app['id']}")
    print(f"Access: {state}")


def regenerate(config_path: Path) -> None:
    env_path = REPO_ROOT / ".env"
    provider = "none"  # Default fallback
    if env_path.exists():
        with env_path.open("r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("OIDC_PROVIDER="):
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    if val in ("azure", "authentik", "none"):
                        provider = val
                    break
    subprocess.run(
        [sys.executable, str(GENERATOR), "--config", str(config_path), "--provider", provider],
        cwd=REPO_ROOT,
        check=True,
    )


def run_compose(args: list[str]) -> None:
    errors: list[str] = []
    for command in (["docker", "compose"], ["docker-compose"]):
        full_command = command + args
        try:
            subprocess.run(full_command, cwd=REPO_ROOT, check=True, capture_output=True, text=True)
            return
        except FileNotFoundError as exc:
            errors.append(f"{' '.join(full_command)}: {exc}")
            continue
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or "").strip()
            if details:
                errors.append(f"{' '.join(full_command)}: {details}")
            else:
                errors.append(f"{' '.join(full_command)} exited with {exc.returncode}")
            continue

    raise AppConfigError("Docker Compose command failed. " + " | ".join(errors))


def apply_config(config_path: Path, reload_caddy: bool, rebuild_containers: bool, compose_check: bool) -> None:
    regenerate(config_path)
    if compose_check:
        run_compose(["config", "--quiet"])
        print("Docker Compose config is valid")

    if rebuild_containers:
        run_compose(["up", "-d", "--build", "--force-recreate", "--remove-orphans"])
        run_compose(["exec", "-T", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile"])
        print("Docker containers rebuilt and restarted")
    elif reload_caddy:
        run_compose(["exec", "-T", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile"])
        run_compose(["exec", "-T", "caddy", "caddy", "reload", "--config", "/etc/caddy/Caddyfile"])
        print("Caddy config reloaded")


def render_bash_completion() -> str:
    return r'''# bash completion for gatectl
_gatectl_app_ids() {
  gatectl list 2>/dev/null | awk 'NR > 1 {print $1}'
}

_gatectl() {
  local cur prev cmd
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"

  local commands="init apply help list add enable disable remove public token trusted-ip completion install"
  local global_options="--help --config --no-generate"

  case "$prev" in
    --config|--prefix)
      compopt -o default 2>/dev/null
      return 0
      ;;
    --completion)
      COMPREPLY=( $(compgen -W "both bash zsh none" -- "$cur") )
      return 0
      ;;
  esac

  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "$commands $global_options" -- "$cur") )
    return 0
  fi

  cmd="${COMP_WORDS[1]}"
  case "$cmd" in
    apply)
      COMPREPLY=( $(compgen -W "--rebuild --no-reload --no-restart --skip-compose-check --help" -- "$cur") )
      ;;
    add)
      COMPREPLY=( $(compgen -W "--icon --same-tab --disabled --no-portal --public --token-header --trusted-ip --help" -- "$cur") )
      ;;
    enable|disable|remove)
      COMPREPLY=( $(compgen -W "$(_gatectl_app_ids)" -- "$cur") )
      ;;
    public)
      if [[ $COMP_CWORD -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "enable disable list" -- "$cur") )
      else
        COMPREPLY=( $(compgen -W "$(_gatectl_app_ids)" -- "$cur") )
      fi
      ;;
    token)
      if [[ $COMP_CWORD -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "add list remove" -- "$cur") )
      elif [[ $COMP_CWORD -eq 3 ]]; then
        COMPREPLY=( $(compgen -W "$(_gatectl_app_ids)" -- "$cur") )
      else
        COMPREPLY=( $(compgen -W "--token --header --help" -- "$cur") )
      fi
      ;;
    trusted-ip)
      if [[ $COMP_CWORD -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "add list remove" -- "$cur") )
      elif [[ $COMP_CWORD -eq 3 ]]; then
        COMPREPLY=( $(compgen -W "$(_gatectl_app_ids)" -- "$cur") )
      fi
      ;;
    completion)
      COMPREPLY=( $(compgen -W "bash zsh" -- "$cur") )
      ;;
    install)
      COMPREPLY=( $(compgen -W "--prefix --completion --force --help" -- "$cur") )
      ;;
  esac
}

complete -F _gatectl gatectl
'''


def render_zsh_completion() -> str:
    return r'''#compdef gatectl
# zsh completion for gatectl

_gatectl_app_ids() {
  local -a ids
  ids=("${(@f)$(gatectl list 2>/dev/null | awk 'NR > 1 {print $1}')}")
  _describe 'app id' ids
}

_gatectl() {
  local -a commands
  commands=(
    'init:Create config/apps.toml from the example config'
    'apply:Regenerate config and reload Caddy'
    'help:Show detailed command help'
    'list:List configured apps'
    'add:Add a new app'
    'enable:Enable an app'
    'disable:Disable an app'
    'remove:Remove an app'
    'public:Manage public access'
    'token:Manage access tokens'
    'trusted-ip:Manage trusted IP bypasses'
    'completion:Print shell completion'
    'install:Install gatectl globally'
  )

  if (( CURRENT == 2 )); then
    _describe -t commands 'gatectl command' commands
    return
  fi

  case "${words[2]}" in
    apply)
      compadd -- --rebuild --no-reload --no-restart --skip-compose-check --help
      ;;
    add)
      compadd -- --icon --same-tab --disabled --no-portal --public --token-header --trusted-ip --help
      ;;
    enable|disable|remove)
      _gatectl_app_ids
      ;;
    public)
      if (( CURRENT == 3 )); then
        compadd -- enable disable list
      else
        _gatectl_app_ids
      fi
      ;;
    token)
      if (( CURRENT == 3 )); then
        compadd -- add list remove
      elif (( CURRENT == 4 )); then
        _gatectl_app_ids
      else
        compadd -- --token --header --help
      fi
      ;;
    trusted-ip)
      if (( CURRENT == 3 )); then
        compadd -- add list remove
      elif (( CURRENT == 4 )); then
        _gatectl_app_ids
      fi
      ;;
    completion)
      compadd -- bash zsh
      ;;
    install)
      compadd -- --prefix --completion --force --help
      ;;
  esac
}

_gatectl "$@"
'''


def render_completion(shell: str) -> str:
    if shell == "bash":
        return render_bash_completion()
    if shell == "zsh":
        return render_zsh_completion()
    raise AppConfigError(f"Unsupported shell: {shell}")


def write_install_file(path: Path, content: str, mode: int | None, force: bool) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != content and not force:
        raise AppConfigError(f"Refusing to overwrite {path}. Use --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)


def install_gatectl(prefix: Path, completion: str, force: bool) -> None:
    prefix = prefix.expanduser().resolve()
    launcher_path = prefix / "bin" / "gatectl"
    script_path = (SCRIPT_DIR / "gatectl").resolve()
    launcher = f"#!/usr/bin/env bash\nexec {shlex.quote(str(script_path))} \"$@\"\n"
    write_install_file(launcher_path, launcher, 0o755, force)

    installed_completion_paths: list[Path] = []
    if completion in ("both", "bash"):
        bash_path = prefix / "share" / "bash-completion" / "completions" / "gatectl"
        write_install_file(bash_path, render_bash_completion(), None, force=True)
        installed_completion_paths.append(bash_path)
    if completion in ("both", "zsh"):
        zsh_path = prefix / "share" / "zsh" / "site-functions" / "_gatectl"
        write_install_file(zsh_path, render_zsh_completion(), None, force=True)
        installed_completion_paths.append(zsh_path)

    print(f"Installed gatectl: {launcher_path}")
    for path in installed_completion_paths:
        print(f"Installed completion: {path}")
    print()
    print("Make sure this is in your PATH:")
    print(f"  {prefix / 'bin'}")
    if completion in ("both", "bash"):
        print()
        print("Bash completion can be loaded with:")
        print(f"  source {prefix / 'share' / 'bash-completion' / 'completions' / 'gatectl'}")
    if completion in ("both", "zsh"):
        print()
        print("For zsh, add this directory to fpath before compinit:")
        print(f"  fpath=({prefix / 'share' / 'zsh' / 'site-functions'} $fpath)")
        print("  autoload -Uz compinit && compinit")


def init_config(config_path: Path, force: bool) -> None:
    if config_path.exists() and not force:
        raise AppConfigError(f"Config already exists: {config_path}. Use --force to overwrite it.")
    try:
        content = DEFAULT_EXAMPLE_CONFIG.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AppConfigError(f"Example config not found: {DEFAULT_EXAMPLE_CONFIG}") from exc

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content, encoding="utf-8")
    print(f"Created {config_path} from {DEFAULT_EXAMPLE_CONFIG}")


def add_app(apps: list[dict[str, Any]], args: argparse.Namespace) -> None:
    new_app = normalize_app(
        {
            "id": args.id,
            "title": args.title,
            "host": args.host,
            "upstream": args.upstream,
            "icon": args.icon,
            "target_blank": not args.same_tab,
            "enabled": not args.disabled,
            "portal": not args.no_portal,
            "public": args.public,
            "token_header": args.token_header,
            "tokens": [],
            "trusted_ips": args.trusted_ip,
        },
        len(apps),
    )

    apps.append(new_app)
    validate_unique(apps)


def add_token(app: dict[str, Any], args: argparse.Namespace) -> str:
    if args.token_header:
        app["token_header"] = validate_token_header(args.token_header, app["id"])

    name = validate_token_name(args.name, app["id"])
    token_value = validate_token_value(args.token or secrets.token_urlsafe(32), app["id"])

    if any(token["name"] == name for token in app["tokens"]):
        raise AppConfigError(f"Token already exists for app {app['id']}: {name}")
    if any(token["token"] == token_value for token in app["tokens"]):
        raise AppConfigError(f"Token value already exists for app {app['id']}")

    app["tokens"].append({"name": name, "token": token_value})
    return token_value


def remove_token(app: dict[str, Any], token_name: str) -> None:
    find_token_name = validate_token_name(token_name, app["id"])
    original_count = len(app["tokens"])
    app["tokens"] = [token for token in app["tokens"] if token["name"] != find_token_name]
    if len(app["tokens"]) == original_count:
        raise AppConfigError(f"Token not found for app {app['id']}: {find_token_name}")


def add_trusted_ip(app: dict[str, Any], trusted_ip: str) -> str:
    value = validate_trusted_ip(trusted_ip, app["id"])
    if value in app["trusted_ips"]:
        raise AppConfigError(f"Trusted IP already exists for app {app['id']}: {value}")
    app["trusted_ips"].append(value)
    return value


def remove_trusted_ip(app: dict[str, Any], trusted_ip: str) -> str:
    value = validate_trusted_ip(trusted_ip, app["id"])
    if value not in app["trusted_ips"]:
        raise AppConfigError(f"Trusted IP not found for app {app['id']}: {value}")
    app["trusted_ips"] = [existing_ip for existing_ip in app["trusted_ips"] if existing_ip != value]
    return value


def set_public(app: dict[str, Any], public: bool) -> None:
    app["public"] = public


# ── Plugin management (.env helpers) ──────────────────────────────────────────

def _env_path() -> Path:
    return REPO_ROOT / ".env"


def read_env(key: str) -> str | None:
    """Read a single key from .env file. Returns None if key not found."""
    env_path = _env_path()
    if not env_path.exists():
        return None
    with env_path.open("r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return None


def write_env(key: str, value: str) -> None:
    """Update or add a key=value in .env file, preserving other entries."""
    env_path = _env_path()
    if not env_path.exists():
        raise AppConfigError(f".env file not found at {env_path}. Run 'setup.sh' first.")

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"#{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}\n")

    env_path.write_text("".join(new_lines), encoding="utf-8")


def load_plugins() -> list[str]:
    """Parse CADDY_PLUGINS from .env into a list of import paths."""
    raw = read_env("CADDY_PLUGINS") or ""
    # Parse --with github.com/foo/bar@v1.0.0 into ["github.com/foo/bar@v1.0.0", ...]
    plugins: list[str] = []
    for part in shlex.split(raw):
        if part.startswith("--with "):
            part = part[7:]
        if part.startswith("--with"):
            part = part[6:]
        part = part.strip()
        if part:
            plugins.append(part)
    return plugins


def save_plugins(plugins: list[str]) -> None:
    """Save a list of import paths as CADDY_PLUGINS in .env."""
    if plugins:
        value = " ".join(f"--with {p}" for p in plugins)
        write_env("CADDY_PLUGINS", value)
    else:
        write_env("CADDY_PLUGINS", "")


def validate_plugin_import(import_path: str) -> str:
    """Validate and normalize a Go import path."""
    # Strip any --with prefix the user might have included
    path = import_path.strip()
    if path.startswith("--with "):
        path = path[7:]
    elif path.startswith("--with"):
        path = path[6:]
    path = path.strip()

    if not PLUGIN_PATTERN.fullmatch(path):
        raise AppConfigError(
            f"Invalid plugin import path: {path}. Expected format: github.com/user/repo or github.com/user/repo/v2@v1.0.0"
        )
    return path


def open_editor(file_path: Path) -> None:
    """Open a file in the user's $EDITOR and wait for it to close."""
    editor = os.environ.get("EDITOR", "")
    if not editor:
        # Try common editors
        for candidate in ("nano", "vim", "vi", "code", "emacs", "subl"):
            if subprocess.run(["which", candidate], capture_output=True, text=True).returncode == 0:
                editor = candidate
                break
    if not editor:
        raise AppConfigError(
            "No editor found. Set $EDITOR (e.g. EDITOR=nano) or use one of: nano, vim, vi, code"
        )

    if not file_path.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("# Caddy extra directives\n# Add your plugin configuration here.\n", encoding="utf-8")

    subprocess.run(shlex.split(editor) + [str(file_path)], check=True)


def handle_plugin(args: argparse.Namespace) -> int:
    """Handle plugin subcommands."""
    if args.plugin_command == "config":
        global_path = REPO_ROOT / "caddy" / "extra" / "global.caddy"
        open_editor(global_path)
        print("Plugin config saved. Run 'gatectl apply' to reload Caddy.")
        return 0

    if args.plugin_command == "list":
        plugins = load_plugins()
        if not plugins:
            print("No plugins configured. Use 'gatectl plugin add <import-path>' to add one.")
            return 0
        print("Installed Caddy plugins:")
        for plugin in plugins:
            print(f"  {plugin}")
        return 0

    if args.plugin_command == "add":
        plugin = validate_plugin_import(args.import_path)
        plugins = load_plugins()
        if plugin in plugins:
            print(f"Plugin already installed: {plugin}")
            return 0
        plugins.append(plugin)
        save_plugins(plugins)
        print(f"Added plugin: {plugin}")
        print("Run 'gatectl apply --rebuild' to rebuild the Caddy image and restart.")
        return 0

    if args.plugin_command == "remove":
        plugin = validate_plugin_import(args.import_path)
        plugins = load_plugins()
        if plugin not in plugins:
            raise AppConfigError(f"Plugin not found: {plugin}")
        plugins.remove(plugin)
        save_plugins(plugins)
        print(f"Removed plugin: {plugin}")
        print("Run 'gatectl apply --rebuild' to rebuild the Caddy image and restart.")
        return 0

    raise AppConfigError(f"Unsupported plugin command: {args.plugin_command}")


def handle_app(args: argparse.Namespace) -> int:
    """Handle app subcommands."""
    if args.app_command == "config":
        extra_path = REPO_ROOT / "caddy" / "extra" / "apps" / f"{args.id}.caddy"
        if not extra_path.parent.exists():
            extra_path.parent.mkdir(parents=True, exist_ok=True)
        open_editor(extra_path)
        print(f"Updated extra directives for app '{args.id}'.")
        print("Run 'gatectl apply' to regenerate the Caddyfile and reload.")
        return 0

    raise AppConfigError(f"Unsupported app command: {args.app_command}")


def main() -> int:
    args = parse_args()
    config_path = resolve_config(args.config)

    try:
        if args.command == "help":
            print(DETAILED_HELP)
            return 0

        if args.command == "completion":
            print(render_completion(args.shell), end="")
            return 0

        if args.command == "install":
            install_gatectl(args.prefix, args.completion, args.force)
            return 0

        if args.command == "init":
            init_config(config_path, args.force)
            if not args.no_generate:
                regenerate(config_path)
            return 0

        apps = load_apps(config_path)

        if args.command == "apply":
            if args.rebuild and args.no_reload:
                raise AppConfigError("Use either --rebuild or --no-reload, not both")
            apply_config(
                config_path,
                reload_caddy=not args.no_reload,
                rebuild_containers=args.rebuild,
                compose_check=not args.skip_compose_check,
            )
            return 0

        if args.command == "list":
            print_apps(apps)
            return 0

        if args.command == "add":
            add_app(apps, args)
            action = f"Added app: {args.id}"
        elif args.command == "public":
            app = find_app(apps, args.id)
            if args.public_command == "list":
                print_public(app)
                return 0
            if args.public_command == "enable":
                set_public(app, True)
                action = f"Enabled public access for app: {args.id}"
            elif args.public_command == "disable":
                set_public(app, False)
                action = f"Disabled public access for app: {args.id}"
            else:
                raise AppConfigError(f"Unsupported public command: {args.public_command}")
        elif args.command == "token":
            app = find_app(apps, args.id)
            if args.token_command == "list":
                print_tokens(app)
                return 0
            if args.token_command == "add":
                token_value = add_token(app, args)
                action = (
                    f"Added token '{args.name}' to app: {args.id}\n"
                    f"Header: {app['token_header']}\n"
                    f"Token: {token_value}"
                )
            elif args.token_command == "remove":
                remove_token(app, args.name)
                action = f"Removed token '{args.name}' from app: {args.id}"
            else:
                raise AppConfigError(f"Unsupported token command: {args.token_command}")
        elif args.command == "trusted-ip":
            app = find_app(apps, args.id)
            if args.trusted_ip_command == "list":
                print_trusted_ips(app)
                return 0
            if args.trusted_ip_command == "add":
                trusted_ip = add_trusted_ip(app, args.ip)
                action = f"Added trusted IP '{trusted_ip}' to app: {args.id}"
            elif args.trusted_ip_command == "remove":
                trusted_ip = remove_trusted_ip(app, args.ip)
                action = f"Removed trusted IP '{trusted_ip}' from app: {args.id}"
            else:
                raise AppConfigError(f"Unsupported trusted-ip command: {args.trusted_ip_command}")
        elif args.command == "enable":
            app = find_app(apps, args.id)
            app["enabled"] = True
            action = f"Enabled app: {args.id}"
        elif args.command == "disable":
            app = find_app(apps, args.id)
            app["enabled"] = False
            action = f"Disabled app: {args.id}"
        elif args.command == "remove":
            find_app(apps, args.id)
            apps = [app for app in apps if app["id"] != args.id]
            action = f"Removed app: {args.id}"
        elif args.command == "plugin":
            return handle_plugin(args)
        elif args.command == "app":
            return handle_app(args)
        else:
            raise AppConfigError(f"Unsupported command: {args.command}")

        write_apps(config_path, apps)
        print(action)

        if not args.no_generate:
            regenerate(config_path)
        return 0
    except (AppConfigError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
