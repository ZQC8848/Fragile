"""Model profiles for self-play (selfplay.md §2, §7.1): selfplay/profiles.yaml, read once per run.

    profile          provider, endpoint, model, where its key comes from, an estimated price
    engine roles     which profile each engine role uses; `apply_engine_roles` writes them into the
                     environment (overriding backend/.env) before any role client exists
    players          player clients built straight from a profile, one per session
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.llm import ROLES, LLMClient, LLMConfig, load_env, reset_clients
from engine.llm.client import CLI_PROVIDERS, ROLE_MAX_TOKENS

PROFILES_FILE = Path(__file__).resolve().parent / "profiles.yaml"


@dataclass
class Profile:
    name: str
    provider: str
    model: str = ""
    base_url: str | None = None
    key_env: list[str] = field(default_factory=list)
    #: USD per million tokens, {input, output}
    price: dict[str, float] = field(default_factory=dict)
    #: sessions of this player model at once (None = the run's concurrency)
    concurrency: int | None = None

    @property
    def is_cli(self) -> bool:
        return self.provider in CLI_PROVIDERS

    def key(self) -> str | None:
        load_env()
        return next((os.environ[k] for k in self.key_env if os.environ.get(k)), None)

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * float(self.price.get("input", 0)) + output_tokens * float(self.price.get("output", 0))) / 1e6

    def config(self, role: str, temperature: float, *, cache: bool = False) -> LLMConfig:
        return LLMConfig(
            role=role, provider=self.provider, model=self.model or "default", temperature=temperature,
            max_tokens=ROLE_MAX_TOKENS.get(role, 1200), base_url=self.base_url, api_key=self.key(),
            live=self.provider != "mock", cache=cache,
        )

    def client(self, role: str, temperature: float, *, cache: bool = False, mock_handler=None) -> LLMClient:
        return LLMClient(self.config(role, temperature, cache=cache), mock_handler)


class Profiles:
    def __init__(self, data: dict[str, Any] | None = None, path: Path = PROFILES_FILE):
        raw = path.read_text(encoding="utf-8") if data is None else None
        self.data: dict[str, Any] = data if data is not None else yaml.safe_load(raw)
        self.hash = hashlib.sha256((raw or json.dumps(self.data, sort_keys=True)).encode("utf-8")).hexdigest()[:12]
        self.profiles = {name: Profile(name, **spec) for name, spec in (self.data.get("profiles") or {}).items()}
        self.profiles.setdefault("mock", Profile("mock", "mock", "mock"))
        self.engine_roles: dict[str, str] = self.data.get("engine_roles") or {}
        self.players: dict[str, Any] = self.data.get("players") or {}
        self.dm: list[dict[str, Any]] = self.data.get("dm") or []
        self.splits: dict[str, float] = self.data.get("splits") or {"train": 1.0}
        self.run: dict[str, Any] = self.data.get("run") or {}
        for role, name in self.engine_roles.items():
            if role not in ROLES:
                raise ValueError(f"profiles.yaml: unknown engine role {role!r}")
            self[name]
        for name in self.data.get("narrator_fallback") or []:
            self[name]

    def __getitem__(self, name: str) -> Profile:
        if name not in self.profiles:
            raise KeyError(f"profiles.yaml has no profile {name!r}")
        return self.profiles[name]

    def player_shares(self) -> dict[str, float]:
        """The API players' shares with `third` resolved: its share goes to the named profile, or is split
        evenly between the first two profiles when none is named yet."""
        shares = dict(self.players.get("shares") or {})
        third = self.players.get("third")
        t = shares.pop("third", 0.0)
        if third:
            shares[third] = shares.get(third, 0.0) + t
        elif t:
            first = list(shares)[:2]
            for name in first:
                shares[name] += t / len(first)
        for name in shares:
            self[name]
        total = sum(shares.values())
        return {k: v / total for k, v in shares.items()}

    def apply_engine_roles(self, *, cache: bool = True) -> None:
        """Point every engine role at its profile through the environment the role clients read, and switch
        them live. Roles mapped to `mock` stay on their mock. Clears the role clients built so far."""
        env: dict[str, str] = {}
        live = []
        for role, name in self.engine_roles.items():
            p = self[name]
            key = role.upper()
            env[f"LLM_PROVIDER_{key}"] = p.provider
            env[f"LLM_MODEL_{key}"] = p.model or "default"
            env[f"LLM_BASE_URL_{key}"] = p.base_url or ""
            env[f"LLM_API_KEY_{key}"] = p.key() or ""
            if p.provider != "mock":
                live.append(role)
        env["LLM_LIVE_ROLES"] = ",".join(live)
        env["LLM_CACHE"] = "1" if cache else "0"
        env["LLM_FALLBACK_NARRATOR"] = ",".join(self._fallback_items())
        for k in [k for k in os.environ if k.startswith(("LLM_PROVIDER_", "LLM_MODEL_", "LLM_BASE_URL_", "LLM_API_KEY_", "LLM_FALLBACK_"))]:
            del os.environ[k]
        os.environ.update(env)
        reset_clients()

    def _fallback_items(self) -> list[str]:
        """LLM_FALLBACK_NARRATOR borrows other roles' endpoints: each fallback profile is named through an
        engine role on the same endpoint and key, with its own model."""
        out = []
        for name in self.data.get("narrator_fallback") or []:
            p = self[name]
            role = next((r for r, n in self.engine_roles.items()
                         if self[n].provider == p.provider and self[n].base_url == p.base_url and self[n].key_env == p.key_env), None)
            if role is None:
                role = next((r for r, n in self.engine_roles.items() if self[n].provider == p.provider and self[n].base_url == p.base_url), None)
            if role is not None:
                out.append(f"{role}:{p.model}")
        return out

    def price_of(self, provider: str, model: str) -> Profile | None:
        return next((p for p in self.profiles.values() if p.provider == provider and (p.model or "default") == model), None) or next(
            (p for p in self.profiles.values() if p.provider == provider and p.is_cli), None
        )
