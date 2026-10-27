"""`python -m selfplay doctor`: can this machine run self-play, and which sessions (selfplay.md §7.1)?

Checks the Python packages, git, each profile's key and endpoint (a free GET /models), and whether the
claude and codex command lines are installed. `--probe` also asks each command line for one tiny JSON
answer, which proves the login works (a few seconds and a sliver of the subscription quota each).
"""

from __future__ import annotations

import asyncio
import importlib
import shutil
import subprocess
from typing import Any

from engine.paths import REPO_ROOT

from .profiles import Profile, Profiles

PACKAGES = ("openai", "jsonschema", "yaml", "dotenv", "httpx")
PROBE_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def _endpoint(p: Profile) -> tuple[bool, str]:
    import httpx

    key = p.key()
    if not key:
        return False, f"no key: set {p.key_env[0]} in backend/.env"
    try:
        r = httpx.get(f"{(p.base_url or 'https://api.openai.com/v1').rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
    except httpx.HTTPError as e:
        return False, f"{p.base_url} unreachable ({e.__class__.__name__})"
    if r.status_code in (401, 403):
        return False, f"{p.base_url} refused the key ({r.status_code})"
    if r.status_code >= 400:
        return False, f"{p.base_url} answered {r.status_code}"
    ids = {m.get("id") for m in (r.json().get("data") or []) if isinstance(m, dict)}
    if ids and p.model not in ids:
        return True, f"reachable, but {p.model!r} is not in its model list"
    return True, "reachable, key accepted"


def _cli(p: Profile, probe: bool) -> tuple[bool, str]:
    exe = "claude" if p.provider == "claude_cli" else "codex"
    path = shutil.which(exe)
    if path is None:
        return False, f"{exe} not installed"
    version = subprocess.run([exe, "--version"], capture_output=True, text=True, check=False).stdout.strip()
    if not probe:
        return True, f"{version or exe} installed (login not checked; --probe checks it)"
    client = p.client("selfplay", 1.0)
    try:
        res = asyncio.run(client.call_json("Reply with JSON only.", 'Reply {"ok": true}.', schema=PROBE_SCHEMA))
    except Exception as e:  # noqa: BLE001 - report whatever went wrong
        return False, f"{exe} did not answer: {str(e)[:200]}"
    return bool(res.data.get("ok")), f"{version} answered in {res.latency_ms / 1000:.0f}s"


def check(probe: bool = False, profiles: Profiles | None = None) -> dict[str, Any]:
    prof = profiles or Profiles()
    rows: list[tuple[str, bool, str]] = []
    for name in PACKAGES:
        try:
            importlib.import_module(name)
            rows.append((f"python: {name}", True, "ok"))
        except ImportError:
            rows.append((f"python: {name}", False, "missing: run `uv sync` in backend/"))
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    rows.append(("git", git.returncode == 0, git.stdout.strip()[:10] or "not a git checkout"))

    status: dict[str, tuple[bool, str]] = {}
    needed = set(prof.engine_roles.values()) | set(prof.player_shares()) | set(prof.players.get("subscription") or [])
    for name in sorted(needed):
        p = prof[name]
        if p.provider == "mock":
            status[name] = (True, "mock")
        elif p.is_cli:
            status[name] = _cli(p, probe)
        else:
            status[name] = _endpoint(p)
        rows.append((f"profile: {name}", *status[name]))

    engine_ok = all(status[n][0] for n in set(prof.engine_roles.values()))
    players = {n: status[n][0] and engine_ok for n in sorted(set(prof.player_shares()) | set(prof.players.get("subscription") or []))}
    return {"rows": rows, "engine_ok": engine_ok, "players": players}


def report(result: dict[str, Any]) -> str:
    lines = []
    for what, ok, note in result["rows"]:
        lines.append(f"  {'ok ' if ok else 'NO '} {what:<26} {note}")
    lines.append("")
    if not result["engine_ok"]:
        lines.append("The engine roles cannot run here, so no session can: fix the profiles marked NO above.")
    else:
        can = [n for n, ok in result["players"].items() if ok]
        cannot = [n for n, ok in result["players"].items() if not ok]
        lines.append(f"This machine can play sessions whose player is: {', '.join(can) or 'none'}.")
        if cannot:
            lines.append(f"It skips sessions played by: {', '.join(cannot)} (the runner reports them as unavailable).")
    return "\n".join(lines)
