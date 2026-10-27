"""Pack a shard's finished sessions into the repository, and check a round (selfplay.md §7.1).

    data/selfplay/<round>/<shard>/<session>.tar.gz    one per finished session (plain git, not LFS)

The archives are byte-for-byte reproducible (sorted members, zeroed times and owners), so packing again after
a resume rewrites only the new sessions' files and git sees no change in the others.

`check` accepts a round only when every archive belongs to its manifest and to the shard it sits in, appears
once, and was played at the round's tag (the git commit of `selfplay-<round>`, clean tree) with the
manifest's prompt and generator versions. Missing sessions are listed; `--complete` makes them an error.
"""

from __future__ import annotations

import gzip
import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from engine.paths import DATA_DIR, REPO_ROOT

from .manifest import MANIFESTS_DIR, load
from .run import FINAL, RAW_DIR, session_status

PACKS_DIR = DATA_DIR / "selfplay"
MEMBERS = ("persona.json", "selfplay.json", "player.jsonl", "turns.jsonl", "decisions.jsonl", "events.jsonl", "session.json")


def pack_session(src: Path, dest: Path) -> Path:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in MEMBERS:
            f = src / name
            if not f.exists():
                continue
            data = f.read_bytes()
            ti = tarfile.TarInfo(f"{src.name}/{name}")
            ti.size, ti.mtime, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = len(data), 0, 0o644, 0, 0, "", ""
            tar.addfile(ti, io.BytesIO(data))
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0, compresslevel=9) as gz:
        gz.write(buf.getvalue())
    if not dest.exists() or dest.read_bytes() != out.getvalue():
        dest.write_bytes(out.getvalue())
    return dest


def pack_shard(manifest: dict[str, Any], *, raw_dir: Path = RAW_DIR, packs_dir: Path = PACKS_DIR) -> dict[str, Any]:
    shard = manifest.get("shard") or "all"
    src_root = Path(raw_dir) / manifest["round"] / shard
    dest_root = Path(packs_dir) / manifest["round"] / shard
    packed, unfinished = [], []
    for entry in manifest["sessions"]:
        src = src_root / entry["id"]
        if session_status(src) in FINAL:
            pack_session(src, dest_root / f"{entry['id']}.tar.gz")
            packed.append(entry["id"])
        else:
            unfinished.append(entry["id"])
    return {"dir": str(dest_root), "packed": len(packed), "unfinished": unfinished}


def read_pack(path: Path) -> dict[str, Any]:
    """{member name: parsed content}; .jsonl members become lists."""
    out: dict[str, Any] = {}
    with tarfile.open(path, "r:gz") as tar:
        for m in tar.getmembers():
            f = tar.extractfile(m)
            if f is None:
                continue
            name = m.name.split("/", 1)[-1]
            text = f.read().decode("utf-8")
            out[name] = [json.loads(x) for x in text.splitlines() if x.strip()] if name.endswith(".jsonl") else json.loads(text)
    return out


def tag_commit(tag: str) -> str | None:
    r = subprocess.run(["git", "rev-list", "-n", "1", tag], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return r.stdout.strip() or None


def check_round(round_name: str, *, manifests_dir: Path = MANIFESTS_DIR, packs_dir: Path = PACKS_DIR, complete: bool = False,
                commit: str | None = None) -> dict[str, Any]:
    """`commit` overrides the tag's commit (tests); without either, the commit check is skipped with a warning."""
    mdir = Path(manifests_dir) / round_name
    manifest = load(mdir / "manifest.json")
    shard_of = {}
    for f in sorted(mdir.glob("shard-*.json")):
        for s in load(f)["sessions"]:
            shard_of[s["id"]] = f.stem
    expected = commit or tag_commit(manifest["tag"])
    problems: list[str] = []
    warnings: list[str] = []
    if expected is None:
        warnings.append(f"no git tag {manifest['tag']}: commits not checked")
    seen: dict[str, Path] = {}
    statuses: dict[str, int] = {}
    for path in sorted((Path(packs_dir) / round_name).glob("*/*.tar.gz")):
        sid = path.name.removesuffix(".tar.gz")
        if sid in seen:
            problems.append(f"{sid}: packed twice ({seen[sid].parent.name}, {path.parent.name})")
            continue
        seen[sid] = path
        if sid not in shard_of:
            problems.append(f"{sid}: not in the {round_name} manifest")
            continue
        if path.parent.name != shard_of[sid]:
            problems.append(f"{sid}: in {path.parent.name}, belongs to {shard_of[sid]}")
        try:
            info = read_pack(path).get("selfplay.json") or {}
        except (tarfile.TarError, OSError, json.JSONDecodeError) as e:
            problems.append(f"{sid}: unreadable archive ({e})")
            continue
        statuses[info.get("status", "?")] = statuses.get(info.get("status", "?"), 0) + 1
        if info.get("status") not in FINAL:
            problems.append(f"{sid}: status {info.get('status')!r} is not final")
        git = info.get("git") or {}
        if expected is not None and git.get("commit") != expected:
            problems.append(f"{sid}: played at {str(git.get('commit'))[:10]}, the round's tag is {expected[:10]}")
        if git.get("dirty"):
            problems.append(f"{sid}: played on a working tree with uncommitted changes")
        if info.get("prompt_versions") != manifest["prompt_versions"]:
            problems.append(f"{sid}: prompt versions {info.get('prompt_versions')} differ from the manifest's")
        if info.get("generator_version") != manifest["generator_version"]:
            problems.append(f"{sid}: persona generator v{info.get('generator_version')}, manifest v{manifest['generator_version']}")
    missing = sorted(set(shard_of) - set(seen))
    if complete and missing:
        problems.append(f"{len(missing)} sessions missing")
    by_shard: dict[str, int] = {}
    for sid in missing:
        by_shard[shard_of[sid]] = by_shard.get(shard_of[sid], 0) + 1
    return {"round": round_name, "ok": not problems, "packed": len(seen), "expected": len(shard_of), "statuses": statuses,
            "missing": missing, "missing_by_shard": by_shard, "problems": problems, "warnings": warnings}
