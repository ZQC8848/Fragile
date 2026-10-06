"""Provider-agnostic LLM client with structured JSON output.

Every role (see ROLES, plan.md section 3.3) gets its own provider/model from the environment so they can
be mixed freely:

    LLM_PROVIDER_<ROLE> = openai | anthropic | mock      (default mock)
    LLM_MODEL_<ROLE>    = model id
    LLM_BASE_URL_<ROLE> = OpenAI-compatible endpoint, so one role can run on DeepSeek and another on Kimi
    LLM_API_KEY_<ROLE>  = key for that endpoint
    LLM_LIVE_ROLES      = comma list of roles allowed to leave their mock (see LLMConfig.live)

Configuration and keys come only from backend/.env, which git ignores (`load_env`).

`mock` returns deterministic canned JSON from the role's mock handler so the whole system runs offline
(tests, CI, frontend dev). On top of the providers this layer adds (plan.md section 3.2):

- a response cache, LLM_CACHE=1 (engine/llm/cache.py);
- prompt versions (engine/llm/prompts.py), carried on every call result so they reach the logs;
- JSON output validation against a JSON Schema with one corrective retry, then LLMOutputError so the
  caller can fall back.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
from dotenv import load_dotenv

from engine.llm.cache import ResponseCache, cache_key

log = logging.getLogger("fragile.llm")

ROLES = ("review", "narrator", "guard", "tension", "scorer", "proposer", "options", "selfplay", "judge")

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_env_loaded = False

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_RETRY_NOTE = (
    "\n\nYOUR PREVIOUS REPLY COULD NOT BE USED: {error}\n"
    "Reply again with ONLY the corrected JSON and nothing else."
)


def load_env() -> None:
    """Read backend/.env into the environment, once per process. Variables already set win."""
    global _env_loaded
    if not _env_loaded:
        load_dotenv(ENV_FILE, override=False)
        _env_loaded = True


class LLMError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    role: str
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 1200
    #: per-role endpoint, so one role can run on DeepSeek while another runs on Kimi
    base_url: str | None = None
    api_key: str | None = None
    #: when False the role answers from its mock handler no matter what `provider` says
    live: bool = False
    #: read and write the on-disk response cache (LLM_CACHE=1)
    cache: bool = False

    @classmethod
    def for_role(cls, role: str, temperature: float, max_tokens: int = 1200) -> LLMConfig:
        if role.lower() not in ROLES:
            raise LLMError(f"unknown LLM role {role!r}; known roles: {', '.join(ROLES)}")
        load_env()
        key = role.upper()
        # empty values (as copied from .env.example) count as unset
        provider = (os.getenv(f"LLM_PROVIDER_{key}") or os.getenv("LLM_PROVIDER") or "mock").lower()
        model = os.getenv(f"LLM_MODEL_{key}") or os.getenv("LLM_MODEL") or "claude-sonnet-5"
        base_url = os.getenv(f"LLM_BASE_URL_{key}") or os.getenv("OPENAI_BASE_URL") or None
        api_key = os.getenv(f"LLM_API_KEY_{key}") or None
        live = role.lower() in {r.strip().lower() for r in os.getenv("LLM_LIVE_ROLES", "").split(",") if r.strip()}
        cache = os.getenv("LLM_CACHE", "0").strip().lower() in ("1", "true", "yes", "on")
        return cls(
            role=role,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=base_url,
            api_key=api_key,
            live=live,
            cache=cache,
        )

    @property
    def effective_provider(self) -> str:
        """What will actually answer: `mock` until the role is switched live in the debug panel."""
        return self.provider if self.live else "mock"

    def can_go_live(self) -> bool:
        if self.provider == "mock":
            return False
        if self.provider == "openai":
            return bool(self.api_key or os.getenv("OPENAI_API_KEY"))
        if self.provider == "anthropic":
            return bool(self.api_key or os.getenv("ANTHROPIC_API_KEY"))
        return False


@dataclass
class LLMResult:
    """One finished call. `meta()` is what goes into the turn and decision logs."""

    role: str
    provider: str
    model: str
    prompt_version: int | None
    text: str = ""
    #: parsed (and validated) JSON for call_json; None for call_text
    data: Any = None
    #: the text came from the response cache, not the provider
    cached: bool = False
    attempts: int = 1
    #: why earlier attempts were rejected (parse or schema errors)
    errors: list[str] = field(default_factory=list)
    latency_ms: float = 0.0

    def meta(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "cached": self.cached,
            "attempts": self.attempts,
            "errors": self.errors,
            "latency_ms": round(self.latency_ms, 1),
        }


class LLMOutputError(LLMError):
    """The output was still not valid JSON for the schema after one retry. Callers fall back and log it."""

    def __init__(self, result: LLMResult):
        super().__init__(f"{result.role}: unusable output after {result.attempts} attempts: {result.errors[-1]}")
        self.result = result
        self.role = result.role
        self.errors = result.errors


def extract_json(text: str) -> Any:
    """Tolerant JSON extraction: fenced block, or first {...}/[...] span."""
    if text is None:
        raise LLMError("empty response")
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"could not parse JSON from model output: {text[:200]!r}")


def _parse_and_validate(text: str, validator: jsonschema.protocols.Validator | None) -> tuple[Any, str | None]:
    """(data, None) when usable, (None, error message) otherwise."""
    try:
        data = extract_json(text)
    except LLMError as e:
        return None, str(e)
    if validator is not None:
        problems = [f"{e.json_path}: {e.message}" for e in validator.iter_errors(data)]
        if problems:
            more = f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""
            return None, "output does not match the schema: " + "; ".join(problems[:3]) + more
    return data, None


class LLMClient:
    """One instance per role. `complete_json` returns parsed JSON; `stream_text` yields text deltas.

    `call_json` / `call_text` do the same work but return an LLMResult with the provider, model, prompt
    version, cache hit and attempt count for logging.
    """

    def __init__(self, config: LLMConfig, mock_handler=None, cache: ResponseCache | None = None):
        self.config = config
        self._mock_handler = mock_handler
        self.cache = cache if cache is not None else (ResponseCache() if config.cache else None)
        self._openai = None
        self._anthropic = None
        #: set once a model has told us it only accepts its default temperature (Kimi k2.6/k3, and the
        #: OpenAI reasoning models, answer 400 "only 1 is allowed for this model" otherwise)
        self._no_temperature = False

    # -- public --------------------------------------------------------------
    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        schema: dict[str, Any] | None = None,
        prompt_version: int | None = None,
    ) -> Any:
        """Parsed JSON, validated against `schema` when given. Raises LLMOutputError after one failed retry."""
        res = await self.call_json(system, user, temperature=temperature, schema=schema, prompt_version=prompt_version)
        return res.data

    async def complete_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        json_mode: bool = False,
        prompt_version: int | None = None,
    ) -> str:
        res = await self.call_text(system, user, temperature=temperature, json_mode=json_mode, prompt_version=prompt_version)
        return res.text

    async def call_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        schema: dict[str, Any] | None = None,
        prompt_version: int | None = None,
    ) -> LLMResult:
        """Parse (and validate) the reply. On failure ask once more with the error appended to the user
        prompt; if that also fails raise LLMOutputError, whose `.result` carries the log fields."""
        validator = None
        if schema is not None:
            jsonschema.Draft202012Validator.check_schema(schema)
            validator = jsonschema.Draft202012Validator(schema)
        errors: list[str] = []
        latency = 0.0
        prompt = user
        for attempt in (1, 2):
            res = await self.call_text(system, prompt, temperature=temperature, json_mode=True, prompt_version=prompt_version)
            latency += res.latency_ms
            res.attempts, res.errors, res.latency_ms = attempt, errors, latency
            data, error = _parse_and_validate(res.text, validator)
            if error is None:
                res.data = data
                return res
            errors.append(error)
            log.warning("llm %s attempt %d unusable: %s", self.config.role, attempt, error)
            prompt = user + _RETRY_NOTE.format(error=error)
        raise LLMOutputError(res)

    async def call_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        json_mode: bool = False,
        prompt_version: int | None = None,
    ) -> LLMResult:
        temp = self.config.temperature if temperature is None else temperature
        p = self.config.effective_provider
        res = LLMResult(
            role=self.config.role,
            provider=p,
            model="mock" if p == "mock" else self.config.model,
            prompt_version=prompt_version,
        )
        t0 = time.perf_counter()
        if p == "mock":
            # the mock is deterministic and free: it never reads or writes the cache
            res.text = self._mock(system, user)
        else:
            key = None
            if self.cache is not None:
                key = cache_key(self.config.role, self.config.model, prompt_version, system, user, temp)
                hit = self.cache.get(key)
                if hit is not None:
                    res.text, res.cached = hit, True
            if not res.cached:
                res.text = await self._provider_complete(p, system, user, temp, json_mode)
                if key is not None:
                    self.cache.put(key, res.text, role=self.config.role, model=self.config.model, prompt_version=prompt_version)
        res.latency_ms = (time.perf_counter() - t0) * 1000
        return res

    async def stream_text(self, system: str, user: str, *, temperature: float | None = None) -> AsyncIterator[str]:
        temp = self.config.temperature if temperature is None else temperature
        p = self.config.effective_provider
        if p == "mock":
            text = self._mock(system, user)
            for i in range(0, len(text), 24):
                yield text[i : i + 24]
            return
        if p == "openai":
            client = self._get_openai()
            stream = await client.chat.completions.create(
                model=self.config.model,
                temperature=temp,
                max_tokens=self.config.max_tokens,
                stream=True,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
            return
        if p == "anthropic":
            client = self._get_anthropic()
            async with client.messages.stream(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=temp,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                async for delta in stream.text_stream:
                    yield delta
            return
        raise LLMError(f"unknown provider {p!r}")

    # -- providers -------------------------------------------------------------
    async def _provider_complete(self, provider: str, system: str, user: str, temp: float, json_mode: bool) -> str:
        if provider == "openai":
            return await self._openai_complete(system, user, temp, json_mode)
        if provider == "anthropic":
            return await self._anthropic_complete(system, user, temp)
        raise LLMError(f"unknown provider {provider!r} for role {self.config.role}")

    def _get_openai(self):
        if self._openai is None:
            from openai import AsyncOpenAI

            kwargs: dict[str, Any] = {}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            self._openai = AsyncOpenAI(**kwargs)
        return self._openai

    def _get_anthropic(self):
        if self._anthropic is None:
            from anthropic import AsyncAnthropic

            kwargs: dict[str, Any] = {}
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            self._anthropic = AsyncAnthropic(**kwargs)
        return self._anthropic

    async def _openai_complete(self, system: str, user: str, temp: float, json_mode: bool) -> str:
        client = self._get_openai()
        kwargs: dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

        async def call(send_temperature: bool):
            return await client.chat.completions.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                messages=messages,
                **({"temperature": temp} if send_temperature else {}),
                **kwargs,
            )

        try:
            resp = await call(not self._no_temperature)
        except Exception as e:  # noqa: BLE001 - provider-specific 400, re-raised below if unrelated
            if self._no_temperature or "temperature" not in str(e).lower():
                raise
            # The model only accepts its default temperature. Drop the parameter for the rest of this
            # client's life; the role's temperature setting simply stops applying to it.
            self._no_temperature = True
            resp = await call(False)
        return resp.choices[0].message.content or ""

    async def _anthropic_complete(self, system: str, user: str, temp: float) -> str:
        client = self._get_anthropic()
        resp = await client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=temp,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")

    def _mock(self, system: str, user: str) -> str:
        if self._mock_handler is None:
            raise LLMError(f"mock provider for role {self.config.role} has no handler")
        out = self._mock_handler(system, user)
        return out if isinstance(out, str) else json.dumps(out)


_clients: dict[str, LLMClient] = {}


def get_client(role: str, temperature: float, mock_handler=None, max_tokens: int = 1200) -> LLMClient:
    """Cached per role. Mock handlers are attached by the role modules."""
    if role not in _clients:
        _clients[role] = LLMClient(LLMConfig.for_role(role, temperature, max_tokens), mock_handler)
    elif mock_handler is not None and _clients[role]._mock_handler is None:
        _clients[role]._mock_handler = mock_handler
    return _clients[role]


def llm_roles() -> list[dict[str, Any]]:
    """One row per role for the debug panel: what answers now, what it would switch to, and whether it can."""
    out = []
    for role, client in sorted(_clients.items()):
        c = client.config
        out.append(
            {
                "role": role,
                "live": c.live,
                "provider": c.provider,
                "effective_provider": c.effective_provider,
                "model": c.model,
                "base_url": c.base_url or "",
                "can_go_live": c.can_go_live(),
                "temperature": round(c.temperature, 2),
                "cache": client.cache is not None,
            }
        )
    return out


def set_llm_live(role: str, live: bool) -> bool:
    """Flip a role between its real provider and its mock. False when the role has no usable key."""
    client = _clients.get(role.lower())
    if client is None:
        return False
    if live and not client.config.can_go_live():
        return False
    client.config.live = live
    return True


def reset_clients() -> None:
    _clients.clear()
