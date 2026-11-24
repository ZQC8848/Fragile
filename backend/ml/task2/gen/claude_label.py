"""Batch labelling through the local Claude Code command line (`claude -p`, the user's own subscription).

Jobs are written to an append-only JSONL file and skipped on restart, so a run can stop at any point.
When Claude reports its usage limit, the run stops with exit code 3; ml/task2/gen/label_supervise.sh then waits for
the limit to reset and starts it again.

    from ml.task2.gen.claude_label import run_jobs
    run_jobs(jobs, out_path, system=..., schema=..., model="sonnet", concurrency=3)
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

LIMIT_EXIT = 3
_LIMIT_WORDS = ("usage limit", "usage_limit", "limit reached", "rate limit", "reset at", "hit your limit")
_ENV_KEEP = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "SHELL", "TERM")


class UsageLimit(Exception):
    pass


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.add(json.loads(line)["id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return out


async def _call(system: str, user: str, schema: dict[str, Any] | None, model: str, timeout_s: float) -> tuple[Any, dict]:
    exe = shutil.which("claude")
    if exe is None:
        raise RuntimeError("claude is not installed")
    cmd = [exe, "-p", "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
           "--exclude-dynamic-system-prompt-sections", "--output-format", "json", "--system-prompt", system, "--model", model]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema)]
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    with tempfile.TemporaryDirectory(prefix="t2-label-") as tmp:
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=tmp, env=env, stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(user.encode("utf-8")), timeout_s)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
    text = out.decode("utf-8", "replace")
    blob = (text + err.decode("utf-8", "replace")).lower()
    if any(w in blob for w in _LIMIT_WORDS) and ('"is_error":true' in blob.replace(" ", "") or proc.returncode != 0):
        raise UsageLimit(text[-300:] or err.decode("utf-8", "replace")[-300:])
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {(err or out).decode('utf-8', 'replace')[-300:]}")
    d = json.loads(text)
    if d.get("is_error"):
        raise RuntimeError(f"claude error: {str(d.get('result'))[:300]}")
    data = d.get("structured_output")
    if data is None:
        data = json.loads(d.get("result") or "null")
    u = d.get("usage") or {}
    usage = {"in": int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0)),
             "out": int(u.get("output_tokens", 0))}
    return data, usage


def run_jobs(jobs: list[dict[str, Any]], out_path: Path, *, system: str, schema: dict[str, Any] | None, model: str = "sonnet",
             concurrency: int = 3, timeout_s: float = 300.0, retries: int = 2, check=None) -> int:
    """jobs: [{"id": str, "user": str, "meta": {...}}]. Appends {"id", "data", "meta", "usage", "model", "ts"} per job.
    check(job, data) -> str | None returns a reason to retry (e.g. a missing item). Returns the exit code."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen = done_ids(out_path)
    todo = [j for j in jobs if j["id"] not in seen]
    print(f"{len(jobs)} jobs, {len(seen)} done, {len(todo)} to run (model {model}, concurrency {concurrency})", flush=True)
    if not todo:
        return 0
    lock, stop = asyncio.Lock(), asyncio.Event()
    stats = {"ok": 0, "fail": 0, "in": 0, "out": 0, "t0": time.time()}

    async def one(job: dict[str, Any], sem: asyncio.Semaphore) -> None:
        async with sem:
            if stop.is_set():
                return
            for attempt in range(retries + 1):
                try:
                    data, usage = await _call(system, job["user"], schema, model, timeout_s)
                    why = check(job, data) if check else None
                    if why:
                        raise RuntimeError(why)
                except UsageLimit as e:
                    print(f"usage limit: {e}", flush=True)
                    stop.set()
                    return
                except Exception as e:  # noqa: BLE001
                    if attempt == retries:
                        stats["fail"] += 1
                        print(f"[fail] {job['id']}: {e}", flush=True)
                        return
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                async with lock:
                    with out_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"id": job["id"], "data": data, "meta": job.get("meta", {}), "usage": usage,
                                            "model": model, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
                    stats["ok"] += 1
                    stats["in"] += usage["in"]
                    stats["out"] += usage["out"]
                    if stats["ok"] % 10 == 0:
                        el = time.time() - stats["t0"]
                        print(f"{stats['ok']}/{len(todo)} done, {stats['fail']} failed, {el/60:.1f} min, "
                              f"tokens in {stats['in']:,} out {stats['out']:,}", flush=True)
                return

    async def main() -> None:
        sem = asyncio.Semaphore(concurrency)
        await asyncio.gather(*(one(j, sem) for j in todo))

    asyncio.run(main())
    print(f"finished: {stats['ok']} ok, {stats['fail']} failed, tokens in {stats['in']:,} out {stats['out']:,}", flush=True)
    if stop.is_set():
        return LIMIT_EXIT
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit("import run_jobs from this module")
