"""The self-play runner (selfplay.md §7, §7.1, §9): manifest balance, shards, offline sessions with a mock
player, resume, the budget, refusals, pack and check, the report, and the command-line providers."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter

import pytest
import yaml

import selfplay.run as run_mod
from engine.llm import USAGE, LLMConfig
from engine.llm.cache import ResponseCache
from engine.llm.client import LLMClient, _codex_usage, _parse_claude_cli, _prune_nulls, _strict_schema
from selfplay import manifest
from selfplay.pack import check_round, pack_shard, read_pack
from selfplay.profiles import PROFILES_FILE, Profiles
from selfplay.run import Spend, run_shard
from tools.selfplay_report import build as build_report

GIT = {"commit": "c0ffee" * 6 + "abcd", "dirty": False}


def mock_profiles(**players) -> Profiles:
    data = yaml.safe_load(PROFILES_FILE.read_text(encoding="utf-8"))
    data["engine_roles"] = {r: "mock" for r in data["engine_roles"]}
    data["narrator_fallback"] = []
    data["players"] = {"shares": {"mock": 1.0}, "third": None, "test_only": [], "subscription": [], **players}
    return Profiles(data)


@pytest.fixture
def clean_git(monkeypatch):
    monkeypatch.setattr(run_mod, "git_info", lambda: dict(GIT))


# --------------------------------------------------------------------------- manifest
def test_manifest_is_balanced_and_test_only_models_stay_in_test():
    prof = Profiles()
    m = manifest.build("rtest", 60, subscription=3, profiles=prof)
    s = manifest.summary(m)
    assert s["sessions"] == 66
    assert s["player"] == manifest.quotas(60, prof.player_shares()) | {"claude": 3, "gpt": 3}
    test_only = set(prof.players["test_only"])
    assert all(x["split"] == "test" for x in m["sessions"] if x["player_profile"] in test_only)
    others = [x for x in m["sessions"] if x["player_profile"] not in test_only]
    assert Counter(x["split"] for x in others)["train"] >= 0.6 * len(others)
    # every player model shows up in both the tail and the population strata
    for model, n in s["player"].items():
        if n >= 6:
            strata = {manifest.stratum(x["persona"])[0] for x in m["sessions"] if x["player_profile"] == model}
            assert strata == {"tail", "population"}, model
    # DM policies spread within a player model
    flash = Counter(x["dm"]["policy"] for x in m["sessions"] if x["player_profile"] == "deepseek-flash")
    assert flash["B"] > flash["A"] > 0
    assert m["prompt_versions"]["selfplay"] == 2


def test_manifest_is_deterministic_per_round_and_rounds_differ():
    a, b, c = (manifest.build(r, 12, profiles=Profiles()) for r in ("r1", "r1", "r2"))
    assert a["sessions"] == b["sessions"]
    assert {x["persona"]["hexaco"]["H"] for x in a["sessions"]} != {x["persona"]["hexaco"]["H"] for x in c["sessions"]}
    assert len({x["seed"] for x in a["sessions"]}) == 12


def test_shards_partition_the_round_evenly(tmp_path):
    m = manifest.build("rshard", 37, subscription=2, profiles=Profiles())
    parts = manifest.shard(m, 6)
    ids = [x["id"] for p in parts for x in p["sessions"]]
    assert sorted(ids) == sorted(x["id"] for x in m["sessions"]) and len(set(ids)) == len(ids)
    for model in {x["player_profile"] for x in m["sessions"]}:
        per = [sum(x["player_profile"] == model for x in p["sessions"]) for p in parts]
        assert max(per) - min(per) <= 1, (model, per)
    paths = manifest.write(m, 6, tmp_path)
    assert [p.name for p in paths] == ["manifest.json", *(f"shard-{i:02d}.json" for i in range(1, 7))]
    with pytest.raises(FileExistsError):
        manifest.write(m, 6, tmp_path)


def test_profiles_resolve_the_third_share_and_the_narrator_fallback(monkeypatch):
    prof = Profiles()
    shares = prof.player_shares()
    assert shares["deepseek-flash"] == pytest.approx(0.475) and shares["deepseek-v4-pro"] == pytest.approx(0.375)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k-deepseek")
    prof.apply_engine_roles()
    assert os.environ["LLM_MODEL_NARRATOR"] == "deepseek-flash" and os.environ["LLM_API_KEY_NARRATOR"] == "k-deepseek"
    assert os.environ["LLM_FALLBACK_NARRATOR"] == "review:deepseek-flash,review:deepseek-flash"
    data = {**prof.data, "narrator_fallback": ["deepseek-v4-pro", "kimi-k2.6"]}
    assert Profiles(data)._fallback_items() == ["proposer:deepseek-v4-pro", "judge:kimi-k2.6"]
    assert "narrator" in os.environ["LLM_LIVE_ROLES"] and os.environ["LLM_CACHE"] == "1"


# --------------------------------------------------------------------------- offline sessions
async def test_three_offline_sessions_play_resume_pack_and_check(tmp_path, clean_git):
    prof = mock_profiles()
    m = manifest.build("roff", 3, profiles=prof)
    mdir = tmp_path / "manifests"
    manifest.write(m, 1, mdir)
    part = manifest.load(mdir / "roff" / "shard-01.json")
    raw, packs = tmp_path / "raw", tmp_path / "packs"

    res = await run_shard(part, raw_dir=raw, profiles=prof, progress=lambda _: None)
    assert res["played"] == 3 and set(res["statuses"]) <= {"ended", "max_turns"}
    d = raw / "roff" / "shard-01" / part["sessions"][0]["id"]
    for name in ("persona.json", "selfplay.json", "player.jsonl", "turns.jsonl", "decisions.jsonl"):
        assert (d / name).exists(), name
    info = json.loads((d / "selfplay.json").read_text())
    assert info["player"]["calls"] >= info["turns"] and info["prompt_versions"]["selfplay"] == 2
    first = json.loads((d / "player.jsonl").read_text().splitlines()[0])
    assert first["outcome"] == "played" and first["llm"]["prompt_version"] == 2

    again = await run_shard(part, raw_dir=raw, profiles=prof, progress=lambda _: None)
    assert again["played"] == 0 and again["skipped_done"] == 3

    out = pack_shard(part, raw_dir=raw, packs_dir=packs)
    assert out["packed"] == 3
    archive = packs / "roff" / "shard-01" / f"{part['sessions'][0]['id']}.tar.gz"
    before = archive.read_bytes()
    pack_shard(part, raw_dir=raw, packs_dir=packs)
    assert archive.read_bytes() == before  # reproducible: repacking changes nothing
    assert set(read_pack(archive)) >= {"persona.json", "selfplay.json", "turns.jsonl", "player.jsonl"}

    ok = check_round("roff", manifests_dir=mdir, packs_dir=packs, commit=GIT["commit"], complete=True)
    assert ok["ok"], ok["problems"]
    bad = check_round("roff", manifests_dir=mdir, packs_dir=packs, commit="f" * 40)
    assert not bad["ok"] and all("tag is" in p for p in bad["problems"])

    report = build_report([read_pack(p) for p in sorted((packs / "roff").glob("*/*.tar.gz"))])
    assert report["run"]["sessions"] == 3 and report["coverage"]["endings"] and "mock" in report["collapse"]


def test_check_finds_missing_misplaced_and_unexpected_sessions(tmp_path):
    prof = mock_profiles()
    m = manifest.build("rchk", 4, profiles=prof)
    mdir, packs = tmp_path / "manifests", tmp_path / "packs"
    manifest.write(m, 2, mdir)
    s1 = manifest.load(mdir / "rchk" / "shard-01.json")["sessions"]
    s2 = manifest.load(mdir / "rchk" / "shard-02.json")["sessions"]

    def fake(sid: str, shard: str, **info):
        src = tmp_path / "src" / sid
        src.mkdir(parents=True, exist_ok=True)
        (src / "selfplay.json").write_text(json.dumps({"status": "ended", "git": GIT, "prompt_versions": m["prompt_versions"],
                                                       "generator_version": m["generator_version"], **info}))
        from selfplay.pack import pack_session

        pack_session(src, packs / "rchk" / shard / f"{sid}.tar.gz")

    fake(s1[0]["id"], "shard-01")
    fake(s2[0]["id"], "shard-01")  # wrong shard
    fake(s1[1]["id"], "shard-01", prompt_versions={**m["prompt_versions"], "narrator": 99})
    fake("rchk-9999", "shard-02")  # not in the manifest
    r = check_round("rchk", manifests_dir=mdir, packs_dir=packs, commit=GIT["commit"], complete=True)
    text = "\n".join(r["problems"])
    assert "belongs to shard-02" in text and "prompt versions" in text and "not in the rchk manifest" in text
    assert r["missing"] == [s2[1]["id"]] and "1 sessions missing" in text


async def test_the_budget_stops_new_sessions(tmp_path, clean_git):
    prof = mock_profiles()
    part = manifest.shard(manifest.build("rbud", 2, profiles=prof), 1)[0]
    ledger = tmp_path / "raw" / "rbud" / "shard-01" / "_ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"session": "earlier", "status": "ended", "cost_usd": 5.0, "tokens": 10}) + "\n")
    res = await run_shard(part, raw_dir=tmp_path / "raw", profiles=prof, budget_usd=5.0, progress=lambda _: None)
    assert res["played"] == 0 and len(res["not_started_budget"]) == 2
    assert Spend(ledger, 6.0).total() == (5.0, 10)


async def test_a_refused_turn_is_written_again_with_the_reason(tmp_path, clean_git):
    calls: list[dict] = []

    def handler(system, user):
        seen = json.loads(user)
        calls.append(seen)
        if len(calls) == 1:  # the first player turn: an NPC's action in the action channel is refused
            return {"mode": "channels", "channels": {"speech": "", "action": "Julian pours me a glass.", "expression": "",
                                                     "addressee": None}, "deliberate_violation": "npc_action"}
        return run_mod.mock_player(system, user)

    prof = mock_profiles()
    prof.run["accept_rewrite"] = 0.0  # always write the turn again, never take the suggested rewrite
    part = manifest.shard(manifest.build("rref", 1, profiles=prof), 1)[0]
    res = await run_shard(part, raw_dir=tmp_path / "raw", profiles=prof, max_turns=3, mock_handler=handler,
                          progress=lambda _: None)
    assert res["played"] == 1
    lines = [json.loads(x) for x in (tmp_path / "raw" / "rref" / "shard-01" / part["sessions"][0]["id"] / "player.jsonl").read_text().splitlines()]
    turn1 = [x for x in lines if x["turn"] == 1]
    assert turn1[0]["outcome"] == "rejected" and turn1[0]["review"]["category"] == "npc_action"
    assert turn1[1]["refused"]["category"] == "npc_action" and calls[1]["refused"]["category"] == "npc_action"
    assert turn1[1]["outcome"] == "played"


def test_the_player_sees_the_stance_only_after_the_truth_is_out():
    prof = mock_profiles()
    entry = manifest.build("rview", 1, profiles=prof)["sessions"][0]
    from selfplay.persona import PersonaGenerator

    p = run_mod.Player(entry, prof["mock"], PersonaGenerator(), prof.run, log_path=None)

    class S:
        name, card, passages, phone = "Sam", {"identity": "old friend", "knows": ["x"]}, [{"text": "p"}] * 9, []
        state = {"player_room": "hall", "revealed": []}

        class world:
            @staticmethod
            def present(st):
                return ["mia"]

    before = p.view(S, None, None)
    S.state = {"player_room": "hall", "revealed": ["leo_dead"]}
    after = p.view(S, None, None)
    assert len(before["passages"]) == prof.run["passages"]
    assert after["card"][: len(before["card"])] == before["card"] and after["card"][-1].startswith("Now that you know")


# --------------------------------------------------------------------------- client: usage and the command lines
class Fake(LLMClient):
    async def _provider_complete(self, provider, system, user, temp, json_mode, schema=None):
        return '{"ok": true}', {"input_tokens": 11, "output_tokens": 3}


async def test_usage_is_collected_for_provider_calls_but_not_cache_hits(tmp_path):
    cache = ResponseCache(tmp_path / "c.sqlite3")
    client = Fake(LLMConfig(role="narrator", provider="openai", model="m", live=True), cache=cache)
    usage: list[dict] = []
    token = USAGE.set(usage)
    try:
        first = await client.call_json("sys", "user json")
        second = await client.call_json("sys", "user json")
    finally:
        USAGE.reset(token)
    assert usage == [{"role": "narrator", "provider": "openai", "model": "m", "input_tokens": 11, "output_tokens": 3}]
    assert first.meta()["usage"] == {"input_tokens": 11, "output_tokens": 3} and second.cached and "usage" not in second.meta()


def test_command_line_outputs_parse():
    text, usage = _parse_claude_cli(json.dumps({"result": "x", "structured_output": {"mode": "single", "text": "hi"}, "is_error": False,
                                                "usage": {"input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 9}}))
    assert json.loads(text) == {"mode": "single", "text": "hi"} and usage == {"input_tokens": 105, "output_tokens": 9}
    events = '{"type":"turn.started"}\nnot json\n{"type":"turn.completed","usage":{"input_tokens":12735,"output_tokens":270}}'
    assert _codex_usage(events) == {"input_tokens": 12735, "output_tokens": 270}


def test_codex_gets_a_strict_schema_and_the_nulls_are_pruned():
    strict = _strict_schema(run_mod.SCHEMA)
    assert strict["required"] == list(run_mod.SCHEMA["properties"]) and strict["additionalProperties"] is False
    ch = strict["properties"]["channels"]["anyOf"][0]
    assert ch["required"] == ["speech", "action", "expression", "addressee"]
    reply = {"mode": "single", "text": "I wave.", "channels": None, "deliberate_violation": None}
    assert _prune_nulls(reply, run_mod.SCHEMA) == {"mode": "single", "text": "I wave.", "deliberate_violation": None}


@pytest.mark.parametrize("provider", ["claude_cli", "codex_cli"])
async def test_command_line_calls_run_isolated(monkeypatch, provider):
    """Empty temp dir, minimal environment (no API key that could switch the CLI to API billing), no tools."""
    seen: dict = {}

    class Proc:
        returncode = 0

        async def communicate(self, data):
            seen["stdin"] = data.decode()
            if provider == "codex_cli":
                out = seen["cmd"][seen["cmd"].index("-o") + 1]
                open(out, "w").write('{"ok": true}')
                return b'{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}', b""
            return json.dumps({"result": '{"ok": true}', "usage": {}}).encode(), b""

    async def fake_exec(*cmd, cwd, env, **kw):
        seen.update(cmd=list(cmd), cwd=cwd, env=env, files=os.listdir(cwd))
        return Proc()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("LLM_API_KEY_NARRATOR", "sk-nor-this")
    monkeypatch.setattr("engine.llm.client.shutil.which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    client = LLMClient(LLMConfig(role="selfplay", provider=provider, model="sonnet", live=True))
    res = await client.call_json("SYSTEM", "the user turn", schema={"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"})
    assert res.data == {"ok": True}
    assert "ANTHROPIC_API_KEY" not in seen["env"] and not any(k.startswith("LLM_") for k in seen["env"])
    assert seen["files"] == [] and "fragile-llm-" in str(seen["cwd"])
    if provider == "claude_cli":
        assert seen["cmd"][seen["cmd"].index("--tools") + 1] == "" and "--json-schema" in seen["cmd"]
        assert "$schema" not in json.loads(seen["cmd"][seen["cmd"].index("--json-schema") + 1])
        assert seen["cmd"][seen["cmd"].index("--system-prompt") + 1] == "SYSTEM"
    else:
        assert "read-only" in seen["cmd"] and "--output-schema" in seen["cmd"] and seen["stdin"].startswith("SYSTEM")
