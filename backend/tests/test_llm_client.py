import os

import pytest

import engine.llm.client as client_mod
from engine.llm import (
    ROLES,
    LLMClient,
    LLMConfig,
    LLMError,
    LLMOutputError,
    ResponseCache,
    get_client,
    load_prompt,
    prompt_versions,
    reset_clients,
)

VERDICT_SCHEMA = {
    "type": "object",
    "required": ["verdict"],
    "properties": {"verdict": {"enum": ["ok", "rejected"]}},
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Never read a developer's backend/.env here, and start every test from the defaults."""
    monkeypatch.setattr(client_mod, "_env_loaded", True)
    for k in list(os.environ):
        if k.startswith(("LLM_", "PROMPT_VERSION_")):
            monkeypatch.delenv(k)
    reset_clients()
    yield
    reset_clients()


class FakeProvider(LLMClient):
    """A live, non-mock role whose provider is scripted: returns `replies` in order, records each prompt."""

    def __init__(self, replies: list[str], cache: ResponseCache | None = None):
        super().__init__(LLMConfig(role="narrator", provider="openai", model="fake-model", live=True), cache=cache)
        self.replies = replies
        self.prompts: list[tuple[str, str]] = []

    async def _provider_complete(self, provider, system, user, temp, json_mode):
        self.prompts.append((system, user))
        return self.replies[min(len(self.prompts), len(self.replies)) - 1]


def scripted(replies):
    """Mock handler returning `replies` in order (the last one repeats); records the user prompts."""
    seen: list[str] = []

    def handler(system, user):
        seen.append(user)
        return replies[min(len(seen), len(replies)) - 1]

    return handler, seen


# -- configuration ------------------------------------------------------------
def test_every_role_defaults_to_mock_without_cache():
    for role in ROLES:
        cfg = LLMConfig.for_role(role, 0.5)
        assert cfg.provider == "mock"
        assert cfg.effective_provider == "mock"
        assert cfg.cache is False


def test_per_role_env_vars(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_NARRATOR", "openai")
    monkeypatch.setenv("LLM_MODEL_NARRATOR", "test-model")
    monkeypatch.setenv("LLM_BASE_URL_NARRATOR", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY_NARRATOR", "test-key")
    monkeypatch.setenv("LLM_LIVE_ROLES", "narrator")
    monkeypatch.setenv("LLM_CACHE", "1")
    cfg = LLMConfig.for_role("narrator", 0.9)
    assert (cfg.provider, cfg.model, cfg.base_url, cfg.api_key) == (
        "openai",
        "test-model",
        "https://example.invalid/v1",
        "test-key",
    )
    assert cfg.effective_provider == "openai"
    assert cfg.can_go_live()
    assert cfg.cache is True
    assert LLMConfig.for_role("review", 0.2).effective_provider == "mock"


def test_unknown_role_is_rejected():
    with pytest.raises(LLMError):
        LLMConfig.for_role("performer", 0.5)
    with pytest.raises(LLMError):
        get_client("tts", 0.5)


# -- cache --------------------------------------------------------------------
async def test_cache_miss_then_hit(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite3")
    llm = FakeProvider(['{"text": "one"}'], cache=cache)

    first = await llm.call_json("sys", "user", prompt_version=1)
    assert first.cached is False
    assert first.data == {"text": "one"}
    assert len(llm.prompts) == 1

    second = await llm.call_json("sys", "user", prompt_version=1)
    assert second.cached is True
    assert second.data == {"text": "one"}
    assert len(llm.prompts) == 1  # served from disk, provider not called
    assert second.meta()["prompt_version"] == 1

    # every part of the key matters: prompt version, temperature, system, user
    await llm.call_json("sys", "user", prompt_version=2)
    await llm.call_json("sys", "user", temperature=0.1, prompt_version=1)
    await llm.call_json("sys2", "user", prompt_version=1)
    await llm.call_json("sys", "user2", prompt_version=1)
    assert len(llm.prompts) == 5
    assert cache.count() == 5


async def test_cache_off_by_default(tmp_path):
    llm = FakeProvider(['{"text": "one"}'])
    assert llm.cache is None
    await llm.call_json("sys", "user")
    await llm.call_json("sys", "user")
    assert len(llm.prompts) == 2


async def test_mock_bypasses_cache(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite3")
    handler, seen = scripted([{"ok": True}])
    llm = LLMClient(LLMConfig(role="guard", provider="mock", model="m", cache=True), handler, cache=cache)
    r1 = await llm.call_json("sys", "user")
    r2 = await llm.call_json("sys", "user")
    assert (r1.cached, r2.cached) == (False, False)
    assert r1.provider == "mock"
    assert len(seen) == 2
    assert cache.count() == 0


# -- prompt files -------------------------------------------------------------
def test_prompt_loader_version_selection(tmp_path, monkeypatch):
    for name, text in {
        "review_v1.md": "review one",
        "review_v2.md": "review two",
        "review_v10.md": "review ten",
        "review_notes.md": "not a version",
        "narrator_v5.md": "narrator five",
    }.items():
        (tmp_path / name).write_text(text, encoding="utf-8")

    assert set(prompt_versions("review", tmp_path)) == {1, 2, 10}
    text, version = load_prompt("review", tmp_path)
    assert (text, version) == ("review ten", 10)  # numeric, not lexicographic
    assert load_prompt("narrator", tmp_path).version == 5

    monkeypatch.setenv("PROMPT_VERSION_REVIEW", "2")
    assert load_prompt("review", tmp_path) == ("review two", 2)
    monkeypatch.setenv("PROMPT_VERSION_REVIEW", "v1")
    assert load_prompt("review", tmp_path).version == 1
    monkeypatch.setenv("PROMPT_VERSION_REVIEW", "7")
    with pytest.raises(FileNotFoundError):
        load_prompt("review", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_prompt("guard", tmp_path)


# -- JSON validation and retry ------------------------------------------------
async def test_unparseable_then_valid_retries_once():
    handler, seen = scripted(["I think the answer is yes.", '{"verdict": "ok"}'])
    llm = LLMClient(LLMConfig(role="review", provider="mock", model="m"), handler)
    res = await llm.call_json("sys", "the input", schema=VERDICT_SCHEMA, prompt_version=3)
    assert res.data == {"verdict": "ok"}
    assert res.attempts == 2
    assert len(res.errors) == 1
    assert res.meta()["prompt_version"] == 3
    assert seen[0] == "the input"
    assert seen[1].startswith("the input") and "could not parse JSON" in seen[1]


async def test_schema_invalid_then_valid_retries_once():
    llm = FakeProvider(['{"verdict": "maybe"}', '```json\n{"verdict": "rejected"}\n```'])
    data = await llm.complete_json("sys", "the input", schema=VERDICT_SCHEMA)
    assert data == {"verdict": "rejected"}
    assert len(llm.prompts) == 2
    retry_user = llm.prompts[1][1]
    assert "does not match the schema" in retry_user and "$.verdict" in retry_user


async def test_retry_then_raise():
    handler, seen = scripted([{"verdict": 42}])
    llm = LLMClient(LLMConfig(role="guard", provider="mock", model="m"), handler)
    with pytest.raises(LLMOutputError) as exc:
        await llm.complete_json("sys", "u", schema=VERDICT_SCHEMA, prompt_version=1)
    assert len(seen) == 2  # one retry, no more
    err = exc.value
    assert isinstance(err, LLMError)
    assert err.role == "guard"
    assert err.result.attempts == 2
    assert len(err.errors) == 2
    assert err.result.meta()["prompt_version"] == 1


async def test_without_schema_any_json_passes():
    handler, _ = scripted(['Sure: {"offsets": []}'])
    llm = get_client("scorer", 0.2, mock_handler=handler)
    assert await llm.complete_json("sys", "u") == {"offsets": []}


async def test_provider_errors_get_one_retry_then_the_fallback_error():
    class Flaky(FakeProvider):
        async def _provider_complete(self, provider, system, user, temp, json_mode):
            self.prompts.append((system, user))
            if len(self.prompts) == 1:
                raise RuntimeError("503 overloaded")
            return self.replies[0]

    ok = Flaky(['{"verdict": "ok"}'])
    res = await ok.call_json("sys", "the input", schema=VERDICT_SCHEMA)
    assert res.data == {"verdict": "ok"} and res.attempts == 2 and "provider error" in res.errors[0]
    assert ok.prompts[0][1].endswith("Reply in json.")  # JSON mode needs the word for some endpoints

    class Down(FakeProvider):
        async def _provider_complete(self, provider, system, user, temp, json_mode):
            raise RuntimeError("connection refused")

    with pytest.raises(LLMOutputError) as e:
        await Down([]).call_json("sys", "the input", schema=VERDICT_SCHEMA)
    assert e.value.result.attempts == 2
