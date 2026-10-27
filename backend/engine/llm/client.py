"""Provider-agnostic LLM client with structured JSON output.

Every role (see ROLES, plan.md section 3.3) gets its own provider/model from the environment so they can
be mixed freely:

    LLM_PROVIDER_<ROLE> = openai | anthropic | claude_cli | codex_cli | mock      (default mock)
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
  caller can fall back;
- a fallback chain per role (LLM_FALLBACK_<ROLE>, `fallback_clients`, `call_json_chain`): when a model times
  out or errors, the next one answers instead of the same one being asked again;
- token usage per call (`LLMResult.usage`, and the USAGE list a caller can collect a whole session into).

`claude_cli` and `codex_cli` answer through the local Claude Code and Codex command lines, on the user's own
subscription (selfplay.md §2). Each call runs in a fresh empty temporary directory with no tools, no project
or user settings, and a minimal environment, so the agent can read nothing of the repository or backend/.env
and an API key in the environment cannot switch it from the subscription to API billing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
from dotenv import load_dotenv

from engine.llm.cache import ResponseCache, cache_key

log = logging.getLogger("fragile.llm")

ROLES = ("review", "narrator", "guard", "tension", "scorer", "proposer", "options", "selfplay", "judge")

#: output budget per role. Generous on purpose: reasoning models spend part of it thinking, and a budget that
#: runs out returns an empty or cut-off reply. Only tokens actually produced are billed.
ROLE_MAX_TOKENS = {
    "review": 8000, "narrator": 8000, "guard": 8000, "tension": 4000, "scorer": 6000,
    "proposer": 8000, "options": 6000, "selfplay": 4000, "judge": 6000,
}

#: seconds before a request is abandoned (then retried once, then the role's fallback). The SDK's own default
#: is 600 s plus silent retries, which once froze a turn for ten minutes. LLM_TIMEOUT_<ROLE> overrides.
ROLE_TIMEOUT_S = {"narrator": 45.0, "proposer": 120.0, "judge": 120.0}
DEFAULT_TIMEOUT_S = 60.0
#: per call to a fallback model (LLM_TIMEOUT_<ROLE>_FALLBACK overrides)
FALLBACK_TIMEOUT_S = 30.0
#: a command-line call starts an agent process: slower than an HTTP request
CLI_TIMEOUT_S = 180.0
CLI_PROVIDERS = {"claude_cli": "claude", "codex_cli": "codex"}
#: the only environment a command-line provider sees: enough to find the binary and its login
_CLI_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "TMPDIR", "SHELL", "CLAUDE_CONFIG_DIR", "CODEX_HOME")

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_env_loaded = False

#: when set to a list, every finished call_json appends its LLMResult.meta() here: the turn loop collects the
#: provider, model, prompt version and latency of each call for the turn log
CALL_LOG: ContextVar[list[dict[str, Any]] | None] = ContextVar("llm_call_log", default=None)
#: when set to a list, every call a provider actually answered (not the mock, not a cache hit) appends
#: {role, provider, model, input_tokens, output_tokens} here: the self-play runner totals a session's cost
USAGE: ContextVar[list[dict[str, Any]] | None] = ContextVar("llm_usage", default=None)

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
    #: request timeout in seconds; None = the role's default (`LLMClient.timeout_s`)
    timeout: float | None = None

    @classmethod
    def for_role(cls, role: str, temperature: float, max_tokens: int = 1200, endpoint_of: str | None = None) -> LLMConfig:
        """`endpoint_of` borrows another role's provider, model, endpoint and key (a fallback model)."""
        if role.lower() not in ROLES:
            raise LLMError(f"unknown LLM role {role!r}; known roles: {', '.join(ROLES)}")
        if endpoint_of is not None and endpoint_of.lower() not in ROLES:
            raise LLMError(f"unknown LLM role {endpoint_of!r} in LLM_FALLBACK_{role.upper()}")
        load_env()
        key = (endpoint_of or role).upper()
        # empty values (as copied from .env.example) count as unset
        provider = (os.getenv(f"LLM_PROVIDER_{key}") or os.getenv("LLM_PROVIDER") or "mock").lower()
        model = os.getenv(f"LLM_MODEL_{key}") or os.getenv("LLM_MODEL") or "claude-sonnet-5"
        base_url = os.getenv(f"LLM_BASE_URL_{key}") or os.getenv("OPENAI_BASE_URL") or None
        api_key = os.getenv(f"LLM_API_KEY_{key}") or None
        # a fallback goes live together with the role it stands in for
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
        if self.provider in CLI_PROVIDERS:
            return shutil.which(CLI_PROVIDERS[self.provider]) is not None
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
    #: {input_tokens, output_tokens} of the provider calls behind this result; None for the mock and cache hits
    usage: dict[str, int] | None = None

    def meta(self) -> dict[str, Any]:
        out = {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "cached": self.cached,
            "attempts": self.attempts,
            "errors": self.errors,
            "latency_ms": round(self.latency_ms, 1),
        }
        if self.usage is not None:
            out["usage"] = self.usage
        return out


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


def _log_call(res: LLMResult) -> None:
    log_list = CALL_LOG.get()
    if log_list is not None:
        log_list.append(res.meta())


def _log_usage(res: LLMResult) -> None:
    usage = USAGE.get()
    if usage is not None:
        usage.append({"role": res.role, "provider": res.provider, "model": res.model, **(res.usage or {"input_tokens": 0, "output_tokens": 0})})


def _parse_claude_cli(stdout: str) -> tuple[str, dict[str, int] | None]:
    """`claude -p --output-format json`: one result object; `structured_output` when a schema was given."""
    try:
        d = json.loads(stdout)
    except json.JSONDecodeError:
        raise LLMError(f"claude printed no JSON result: {stdout[:200]!r}") from None
    if d.get("is_error"):
        raise LLMError(f"claude reported an error: {str(d.get('result'))[:300]}")
    u = d.get("usage") or {}
    usage = {
        "input_tokens": int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)),
        "output_tokens": int(u.get("output_tokens", 0)),
    }
    if d.get("structured_output") is not None:
        return json.dumps(d["structured_output"], ensure_ascii=False), usage
    return str(d.get("result") or ""), usage


def _allows_null(schema: dict[str, Any]) -> bool:
    t = schema.get("type")
    return t == "null" or (isinstance(t, list) and "null" in t) or any(_allows_null(x) for x in schema.get("anyOf", []))


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI's strict structured outputs (codex --output-schema): every object lists all its properties as
    required and allows no others; a property that was optional becomes nullable instead."""
    if not isinstance(schema, dict):
        return schema
    out = {k: _strict_schema(v) if isinstance(v, dict) else [_strict_schema(x) for x in v] if isinstance(v, list) and k == "anyOf" else v
           for k, v in schema.items()}
    if out.get("type") == "object" and "properties" in out:
        required = set(schema.get("required", []))
        props = {}
        for name, sub in out["properties"].items():
            props[name] = sub if name in required or _allows_null(sub) else {"anyOf": [sub, {"type": "null"}]}
        out["properties"] = props
        out["required"] = list(props)
        out["additionalProperties"] = False
    return out


def _prune_nulls(data: Any, schema: dict[str, Any]) -> Any:
    """Undo _strict_schema on a reply: drop the nulls it forced into properties that were only optional."""
    if not isinstance(data, dict) or not isinstance(schema, dict):
        return data
    props = schema.get("properties") or {}
    out = {}
    for k, v in data.items():
        sub = props.get(k, {})
        if v is None and not _allows_null(sub):
            continue
        out[k] = _prune_nulls(v, sub)
    return out


def _codex_error(stdout: str) -> str | None:
    """The message of the last `error` event of `codex exec --json`."""
    msg = None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "error":
            msg = str(ev.get("message"))
            try:
                msg = json.loads(msg)["error"]["message"]
            except (ValueError, KeyError, TypeError):
                pass
    return msg[:300] if msg else None


def _codex_usage(stdout: str) -> dict[str, int] | None:
    """The `turn.completed` event of `codex exec --json` carries the token counts."""
    usage = None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
            u = ev["usage"]
            usage = {"input_tokens": int(u.get("input_tokens", 0)), "output_tokens": int(u.get("output_tokens", 0))}
    return usage


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
        provider_retry: bool = True,
    ) -> LLMResult:
        """Parse (and validate) the reply. On failure ask once more with the error appended to the user
        prompt; if that also fails raise LLMOutputError, whose `.result` carries the log fields.
        `provider_retry=False`: a provider error (timeout, 4xx, 5xx) is not retried, so a chain moves on."""
        validator = None
        if schema is not None:
            jsonschema.Draft202012Validator.check_schema(schema)
            validator = jsonschema.Draft202012Validator(schema)
        errors: list[str] = []
        latency = 0.0
        # some OpenAI-compatible endpoints (DeepSeek) refuse JSON mode unless the user turn says "json"
        if "json" not in user and self.config.effective_provider != "mock":
            user += "\n\nReply in json."
        prompt = user
        for attempt in (1, 2):
            t0 = time.perf_counter()
            try:
                res = await self.call_text(system, prompt, temperature=temperature, json_mode=True, prompt_version=prompt_version, schema=schema)
            except Exception as e:  # noqa: BLE001 - a provider error (4xx, 5xx, timeout) gets the same retry, then the fallback
                p = self.config.effective_provider
                res = LLMResult(self.config.role, p, "mock" if p == "mock" else self.config.model, prompt_version)
                res.latency_ms = (time.perf_counter() - t0) * 1000
                error = f"provider error: {e.__class__.__name__}: {str(e)[:300]}"
                latency += res.latency_ms
                res.attempts, res.errors, res.latency_ms = attempt, errors, latency
                errors.append(error)
                log.warning("llm %s attempt %d failed: %s", self.config.role, attempt, error)
                if not provider_retry:
                    break
                continue
            latency += res.latency_ms
            res.attempts, res.errors, res.latency_ms = attempt, errors, latency
            data, error = _parse_and_validate(res.text, validator)
            if error is None:
                res.data = data
                _log_call(res)
                return res
            errors.append(error)
            log.warning("llm %s attempt %d unusable: %s", self.config.role, attempt, error)
            prompt = user + _RETRY_NOTE.format(error=error)
        _log_call(res)
        raise LLMOutputError(res)

    async def call_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        json_mode: bool = False,
        prompt_version: int | None = None,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        """`schema` only reaches the command-line providers, which can enforce it; the others are asked for
        JSON mode and validated afterwards (call_json)."""
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
                res.text, res.usage = await self._provider_complete(p, system, user, temp, json_mode, schema)
                _log_usage(res)
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
    async def _provider_complete(
        self, provider: str, system: str, user: str, temp: float, json_mode: bool, schema: dict[str, Any] | None = None
    ) -> tuple[str, dict[str, int] | None]:
        """(text, usage)."""
        if provider == "openai":
            return await self._openai_complete(system, user, temp, json_mode)
        if provider == "anthropic":
            return await self._anthropic_complete(system, user, temp)
        if provider in CLI_PROVIDERS:
            return await self._cli_complete(provider, system, user, schema)
        raise LLMError(f"unknown provider {provider!r} for role {self.config.role}")

    def timeout_s(self) -> float:
        if self.config.timeout is not None:
            return self.config.timeout
        raw = os.getenv(f"LLM_TIMEOUT_{self.config.role.upper()}")
        if raw:
            return float(raw)
        if self.config.provider in CLI_PROVIDERS:
            return CLI_TIMEOUT_S
        return ROLE_TIMEOUT_S.get(self.config.role, DEFAULT_TIMEOUT_S)

    def _get_openai(self):
        if self._openai is None:
            from openai import AsyncOpenAI

            kwargs: dict[str, Any] = {"timeout": self.timeout_s(), "max_retries": 0}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            self._openai = AsyncOpenAI(**kwargs)
        return self._openai

    def _get_anthropic(self):
        if self._anthropic is None:
            from anthropic import AsyncAnthropic

            kwargs: dict[str, Any] = {"timeout": self.timeout_s(), "max_retries": 0}
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
        u = getattr(resp, "usage", None)
        usage = {"input_tokens": u.prompt_tokens or 0, "output_tokens": u.completion_tokens or 0} if u else None
        return resp.choices[0].message.content or "", usage

    async def _anthropic_complete(self, system: str, user: str, temp: float) -> str:
        client = self._get_anthropic()
        resp = await client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=temp,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        u = getattr(resp, "usage", None)
        usage = {"input_tokens": u.input_tokens or 0, "output_tokens": u.output_tokens or 0} if u else None
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text"), usage

    async def _cli_complete(self, provider: str, system: str, user: str, schema: dict[str, Any] | None) -> tuple[str, dict[str, int] | None]:
        """One call through the Claude Code (`claude -p`) or Codex (`codex exec`) command line."""
        exe = shutil.which(CLI_PROVIDERS[provider])
        if exe is None:
            raise LLMError(f"{CLI_PROVIDERS[provider]} is not installed (provider {provider} for role {self.config.role})")
        env = {k: os.environ[k] for k in _CLI_ENV if k in os.environ}
        # both command lines refuse a schema that names its draft ($schema) or carries an $id
        schema = {k: v for k, v in schema.items() if k not in ("$schema", "$id")} if schema is not None else None
        with tempfile.TemporaryDirectory(prefix="fragile-llm-") as tmp:
            work = Path(tmp) / "work"
            work.mkdir()
            if provider == "claude_cli":
                cmd = [exe, "-p", "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
                       "--exclude-dynamic-system-prompt-sections", "--output-format", "json", "--system-prompt", system]
                if self.config.model not in ("", "default"):
                    cmd += ["--model", self.config.model]
                if schema is not None:
                    cmd += ["--json-schema", json.dumps(schema)]
                stdin = user
            else:
                last = Path(tmp) / "last.txt"
                cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules",
                       "-s", "read-only", "-C", str(work), "--json", "-o", str(last)]
                if self.config.model not in ("", "default"):
                    cmd += ["-m", self.config.model]
                if schema is not None:
                    (Path(tmp) / "schema.json").write_text(json.dumps(_strict_schema(schema)), encoding="utf-8")
                    cmd += ["--output-schema", str(Path(tmp) / "schema.json")]
                # codex exec has no system prompt option: the instructions go first in the one prompt
                stdin = f"{system}\n\nDo not run commands or use tools; answer directly.\n\n{user}"
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=work, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(stdin.encode("utf-8")), self.timeout_s())
            except BaseException:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
                raise
            if proc.returncode != 0:
                tail = _codex_error(out.decode("utf-8", "replace")) or (err or out).decode("utf-8", "replace").strip()[-300:]
                raise LLMError(f"{CLI_PROVIDERS[provider]} exited with {proc.returncode}: {tail}")
            if provider == "claude_cli":
                return _parse_claude_cli(out.decode("utf-8", "replace"))
            text = last.read_text(encoding="utf-8") if last.exists() else ""
            if schema is not None:
                try:
                    text = json.dumps(_prune_nulls(json.loads(text), schema), ensure_ascii=False)
                except json.JSONDecodeError:
                    pass  # call_json reports the unusable reply
            return text, _codex_usage(out.decode("utf-8", "replace"))

    def _mock(self, system: str, user: str) -> str:
        if self._mock_handler is None:
            raise LLMError(f"mock provider for role {self.config.role} has no handler")
        out = self._mock_handler(system, user)
        return out if isinstance(out, str) else json.dumps(out)


_clients: dict[str, LLMClient] = {}


def get_client(role: str, temperature: float, mock_handler=None, max_tokens: int | None = None) -> LLMClient:
    """Cached per role. Mock handlers are attached by the role modules."""
    if role not in _clients:
        budget = max_tokens or ROLE_MAX_TOKENS.get(role, 1200)
        _clients[role] = LLMClient(LLMConfig.for_role(role, temperature, budget), mock_handler)
    elif mock_handler is not None and _clients[role]._mock_handler is None:
        _clients[role]._mock_handler = mock_handler
    return _clients[role]


def fallback_clients(role: str, temperature: float, mock_handler=None) -> list[LLMClient]:
    """The role's fallback models, in order, from LLM_FALLBACK_<ROLE>: a comma list of other roles whose
    endpoint to borrow, each optionally with its own model ("guard, proposer:deepseek-v4-pro"). Keys stay
    in one place per endpoint. Every fallback keeps this role's prompt budget and its own short timeout."""
    load_env()
    raw = os.getenv(f"LLM_FALLBACK_{role.upper()}", "")
    timeout = float(os.getenv(f"LLM_TIMEOUT_{role.upper()}_FALLBACK") or FALLBACK_TIMEOUT_S)
    out = []
    for item in (x.strip() for x in raw.split(",")):
        if not item:
            continue
        other, _, model = item.partition(":")
        config = LLMConfig.for_role(role, temperature, ROLE_MAX_TOKENS.get(role, 1200), endpoint_of=other.strip())
        if model.strip():
            config.model = model.strip()
        config.timeout = timeout
        out.append(LLMClient(config, mock_handler))
    return out


async def call_json_chain(
    clients: list[LLMClient],
    system: str,
    user: str,
    *,
    schema: dict[str, Any] | None = None,
    prompt_version: int | None = None,
    deadline: float | None = None,
) -> LLMResult:
    """Ask each client in turn until one returns usable JSON. A provider error moves straight to the next
    model; an unusable reply still gets that model's one corrective retry. `deadline` (time.monotonic())
    caps the whole chain: a model is skipped when too little time is left, and a call is cut at the
    deadline. Raises LLMOutputError (the last attempt's result, with every model's errors) when all fail."""
    errors: list[str] = []
    last: LLMResult | None = None
    for i, client in enumerate(clients):
        if i:
            client.config.live = clients[0].config.live  # the Console's live switch covers the whole chain
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining < 3:
            errors.append(f"{client.config.model}: skipped, turn budget spent")
            break
        try:
            call = client.call_json(system, user, schema=schema, prompt_version=prompt_version, provider_retry=False)
            res = await (call if remaining is None else asyncio.wait_for(call, remaining))
            res.errors = errors + res.errors
            if i:
                res.errors.append(f"answered by fallback {i}")
            return res
        except LLMOutputError as e:
            last = e.result
            errors += [f"{client.config.model}: {x}" for x in e.result.errors]
        except TimeoutError:
            c = client.config
            last = LLMResult(c.role, c.effective_provider, c.model, prompt_version, errors=[])
            errors.append(f"{c.model}: cut at the turn deadline")
            _log_call(last)
    if last is None:
        c = clients[0].config
        last = LLMResult(c.role, c.effective_provider, c.model, prompt_version)
    last.errors = errors
    raise LLMOutputError(last)


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
