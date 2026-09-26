# continuity

**Does your agent stay itself?**

A small, dependency-free test suite for the layer almost nobody instruments: whether a
long-running agent is still continuous with the agent it was — across sessions, windows,
restarts and gaps.

```
python3 -m continuity demo
```

Zero setup. Runs against fixtures included in this repo and prints a report.

Then point it at your own records:

```
cp continuity.toml my-agent.toml     # edit the paths
python3 -m continuity check my-agent.toml
```

## Why this exists

Everyone building long-running agents worries about the same thing, and almost nobody can
measure it. The failure is not that the agent forgets — it is that **the machinery meant to
prevent forgetting reports success while the forgetting happens.**

Every check in this repo came out of a failure that shipped silently against a real system:

| check | the failure it catches |
|---|---|
| `gap` | A fresh context read a two-second window boundary as a night, and opened on a status report. Continuity is a **file property** — it must be measured, not felt. |
| `duplicate_sections` | A memory file carried an entire section **twice** while `grep -c '^## NOW'` returned a clean `1`. The narrow check was not wrong; it was answering a different question. |
| `dead_paths` | An agenda pointed at a path that had not existed for weeks. Every session read it; no session checked whether it resolved. |
| `size` | A layer at 3.5× its own stated limit, which teaches its reader that limits are decorative. |
| `staleness` | A layer nobody had written in days, loaded as if it were current. |
| `contradictions` | Two live claims about the same fact, disagreeing for a month — with **retired rows correctly ignored as tombstones**, because a checker that cries wolf gets ignored. |

## Design rules

1. **No bare booleans.** Every finding carries the number it measured. You can disagree
   with a threshold without re-running the check.
2. **Read-only, always.** Looking at a live system must not change it.
3. **Exit 1 means a real contradiction or duplication** — not a style opinion. Warnings are
   warnings.
4. **No dependencies.** Standard library only. A measurement tool you cannot install is a
   measurement tool nobody runs.
5. **Over-limit is a signal, not a verdict.** The `size` check tells you to look. It never
   tells you to delete. Pruning a living fact to satisfy a counter is a documented failure
   mode of this exact system — the number is a fact about the store, not an instruction.

## What this does not do

It does not tell you whether your agent is *conscious*, *aligned*, or *the same entity in
any philosophical sense*. It measures **continuity of record**: whether the things an agent
relies on to be itself are internally consistent, current, and actually reachable. That is a
much smaller claim, and it is the one that can be verified.

## Dogfood receipt — what it caught on the system it came from

Run against the real memory layers of the system that produced it (`dogfood-ours.toml`), on
its first honest run, it found:

1. **Its own worst bug.** The first run returned `RESULT: OK` having opened **zero files** —
   the config parser ignored `[[layers]]`, so every declared layer vanished and the tool
   reported green about nothing. Fixed, and a guard added: *a config that declares layers
   but yields none now exits FAIL and says so.* `tests/test_runner.py` holds the regression.
2. **A registry row pointing at a directory deleted that day** — a live project row citing a
   design folder (and three files inside it) that had been removed hours earlier at the
   owner's order. Every session read that row; no session checked it.
3. **A citation to a file that never existed under that name.**
4. **Three more unresolved references** — corrected in place, with the correction itself
   marked so the checker does not alarm on its own record.

Then it went green, honestly — 14 checks, one file still carrying 25 resolvable path
references. **A suite whose first run found nothing is a suite nobody has tested.**

## Provenance

Extracted from a live system that has been running continuously since August 2026 — with its
failures kept. The negative results are the point: a suite of checks that has never caught
its own operator lying to itself is a suite nobody has tested.

Version 0.1.0 · MIT
