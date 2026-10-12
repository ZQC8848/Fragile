"""tools/play_cli.py drives a whole game from scripted keyboard input (plan.md M3 acceptance)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from play_cli import Cli  # noqa: E402


async def test_cli_plays_from_the_opening_to_an_ending():
    out: list[str] = []
    script = iter([
        '"Hi Mia."', "",              # single box: review, then Enter sends the draft
        "Mia confesses.", "",        # rejected: Enter takes the one-click rewrite
        "/options", "2",             # pick the probe option
        "/phone", "/state", "/trace",
        "/channels", "Good to see you, Julian.", "", "", "julian",  # fill the channels
        "/channels",
    ])

    async def read(prompt: str) -> str | None:
        line = next(script, None)
        if line is not None:
            return line
        if not prompt.lstrip().startswith(">"):
            return ""  # Enter at every follow-up prompt: send the draft
        # then keep walking out until the story ends
        return "I walk out the front door." if cli.session.state["player_room"] == "hall" else "I go to the hall."

    cli = Cli(read, out.append, seed=3, save_generated=False)
    await cli.run("Sam", "nonbinary")
    text = " ".join(" ".join(out).split())
    assert "I ring the bell." in text and "— the end —" in text
    assert "[npc_action]" in text and "voicemail · Leo" in text and "story_min=" in text and "latency ms" in text
    assert cli.session.state["ending"] == "bon_voyage"
    sources = [t["input"]["source"] for t in cli.session.traces[1:4]]
    assert sources == ["typed_accepted", "typed_edited", "option"]
