# Self-play round `r1-haosen`: 20 sessions, every role on Claude Sonnet

Haosen's share of the "20 sessions each" self-play round (agreed at the 11/4 meeting). Played with the
`selfplay` runner from `main` at `0afb2a9`, packed with `python -m selfplay pack`.

**This round is not the standard configuration.** Every engine role (review, narrator, guard, tension,
scorer, options, proposer, judge) and the player ran on Claude Sonnet through the `claude_cli` provider
(a Claude Max subscription, so the API cost is 0), not on DeepSeek/Kimi as in `selfplay/profiles.yaml`.
The exact change is in `profiles.diff` (also: `claude` concurrency 3). The runs used `--allow-dirty`, so
`python -m selfplay check` will flag these sessions as played on an uncommitted tree; keep the round
separate from the standard rounds when pooling data.

| | |
|---|---|
| Played | 2026-11-11 20:05 to 2026-11-12 03:09 PT (paused from about 20:35 to 02:20 by the subscription's 5-hour limit; the three sessions it interrupted were replayed with `--retry-errors`) |
| Manifest | `manifest-shard-01.json`: 20 sessions, 1 shard, persona seed 1794456376 (HEXACO generator, random personas) |
| Splits | train 13, dev 3, test 4 |
| DM policies | B 10, A 6, explore_hot 2, explore_random 2 |
| Result | 20/20 ended, 0 errors; 510 turns (10 to 42 per session); about 26.5M tokens |
| Endings | confession 5, open_it 5, bon_voyage 4, the_witness 4, second_crate 2 |

| session | split | DM policy | turns | ending |
|---|---|---|---|---|
| r1-haosen-0000 | train | A | 10 | bon_voyage |
| r1-haosen-0001 | train | A | 32 | confession |
| r1-haosen-0002 | train | explore_hot | 36 | the_witness |
| r1-haosen-0003 | dev | B | 42 | the_witness |
| r1-haosen-0004 | test | B | 21 | bon_voyage |
| r1-haosen-0005 | train | explore_hot | 23 | confession |
| r1-haosen-0006 | train | A | 29 | the_witness |
| r1-haosen-0007 | train | B | 20 | open_it |
| r1-haosen-0008 | train | explore_random | 15 | open_it |
| r1-haosen-0009 | test | A | 13 | open_it |
| r1-haosen-0010 | train | B | 24 | open_it |
| r1-haosen-0011 | test | B | 24 | open_it |
| r1-haosen-0012 | test | B | 25 | confession |
| r1-haosen-0013 | train | A | 29 | second_crate |
| r1-haosen-0014 | train | B | 21 | bon_voyage |
| r1-haosen-0015 | train | B | 37 | confession |
| r1-haosen-0016 | train | explore_random | 14 | bon_voyage |
| r1-haosen-0017 | train | B | 27 | confession |
| r1-haosen-0018 | dev | A | 33 | second_crate |
| r1-haosen-0019 | dev | B | 35 | the_witness |
