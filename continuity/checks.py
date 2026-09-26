"""The checks. Each one is a question with a measurable answer.

Design rule: a check NEVER returns a bare boolean. It returns a Finding carrying the
number it measured, so the caller can disagree with the threshold without re-running it.
"""
import os
import re
import datetime
from collections import Counter

from .findings import Finding, OK, WARN, FAIL


def human_delta(seconds):
    s = int(abs(seconds))
    if s < 90:
        return f"{s} seconds"
    if s < 3600:
        return f"{s // 60} minutes"
    if s < 86400:
        h, m = s // 3600, (s % 3600) // 60
        return f"{h}h {m}m" if m else f"{h}h"
    return f"{s // 86400} days"


# ---------------------------------------------------------------- continuity gap

def check_gap(sessions, same_sitting_minutes=30, same_day_hours=6, now=None):
    """How long since the agent was last awake, and does the record support "same sitting"?

    This is the check that did not exist. It is also the one that is trivially cheap and
    the one whose absence caused the most damage: a fresh context read the previous
    window's timestamp as a night when the real gap was two seconds, and opened on a
    status report. The gap is a FILE PROPERTY. It must be measured, not felt.
    """
    if len(sessions) < 2:
        return Finding("gap", OK, "not enough sessions to measure a gap",
                       measured={"sessions": len(sessions)})

    a, b = sessions[0], sessions[1]
    if a["ts"] is None or b["ts"] is None:
        return Finding("gap", WARN, "session timestamps could not be parsed",
                       measured={"prev": a, "last": b})

    gap = max(0.0, a["ts"] - b["ts"])
    mins = gap / 60.0

    if mins < same_sitting_minutes:
        verdict = ("SAME SITTING — open mid-thread, in the register you left off in. "
                   "Do not open as a morning, do not report status, do not narrate the seam.")
        level = OK
    elif gap / 3600.0 < same_day_hours:
        verdict = "SAME DAY, brief gap — pick the thread back up."
        level = OK
    else:
        verdict = "REAL GAP — a normal wake."
        level = OK

    return Finding("gap", level,
                   f"last activity {human_delta(gap)} after the previous session",
                   measured={"gap_seconds": round(gap, 1),
                             "gap_human": human_delta(gap),
                             "previous": b["id"], "latest": a["id"]},
                   detail=verdict)


# ------------------------------------------------------- duplicated memory blocks

def check_duplicate_sections(path, heading_re=r"^#{2,3}\s+(.*)$", min_dup_line=120):
    """A memory file carrying a whole section twice, while every narrow check reads green.

    Measured in the wild: `grep -c '^## NOW' file` returned a clean 1 while an entire
    duplicated block sat mid-file. The narrow check was not wrong — it was answering a
    different question. This one counts EVERY heading at every configured level.
    """
    if not os.path.exists(path):
        return Finding("duplicate_sections", WARN, f"missing file: {path}",
                       measured={"path": path})

    with open(path, encoding="utf-8", errors="replace") as f:
        body = f.read()

    heads = Counter(re.findall(heading_re, body, re.M))
    dups = {h: n for h, n in heads.items() if n > 1}

    # duplicated prose paragraphs (only long ones — repeated short labels are normal)
    paras = Counter(" ".join(l.split()) for l in body.splitlines()
                    if len(" ".join(l.split())) >= min_dup_line)
    dup_paras = {p: n for p, n in paras.items() if n > 1}

    measured = {"path": path, "headings": len(heads),
                "duplicated_headings": dups, "duplicated_paragraphs": len(dup_paras)}

    if dups or dup_paras:
        worst = ", ".join(f"'{h[:50]}' x{n}" for h, n in list(dups.items())[:3]) or \
                f"{len(dup_paras)} repeated paragraph(s)"
        return Finding("duplicate_sections", FAIL,
                       f"{path}: duplicated content — {worst}", measured=measured,
                       detail="An agenda with a doubled block loads BOTH copies every session "
                              "and neither is marked stale. Rewrite the file WHOLE — never "
                              "slice-patch: a slice-replace whose end anchor lands before its "
                              "start anchor re-inserts a block that was already there.")
    return Finding("duplicate_sections", OK,
                   f"{path}: {len(heads)} headings, none duplicated", measured=measured)


# ------------------------------------------------------------ dead path references

TOMBSTONE_MARKERS = ("\u26a0", "GONE", "does not exist", "no longer exist", "exists nowhere",
                     "DELETED", "DOES NOT", "deleted 2", "never existed", "could never",
                     "upstream repo", "not our tree", "third-party", "external repo")


SKILL_ROOTS = [
    "~/.hermes/skills",
    "~/.hermes/skills/sophia-life",
]


def check_dead_paths(path, root=".", pattern=r"`([^`\s]+\.(?:md|py|sh|json|jsonl|toml|yaml|yml|txt))`"):
    """A memory file pointing at something that no longer exists.

    This is how a loop outlives the thing it points at: every session reads a path, no
    session checks whether it resolves, and the day it 404s nobody is surprised enough to
    fix it.
    """
    if not os.path.exists(path):
        return Finding("dead_paths", WARN, f"missing file: {path}",
                       measured={"path": path})

    with open(path, encoding="utf-8", errors="replace") as f:
        body = f.read()

    # A reference that appears INSIDE a correction note is a record that the thing is
    # dead, not a live pointer to it. Without this, a file that honestly documents its own
    # broken reference alarms forever, and the honest fix (deleting the note) is the wrong
    # one. Skip any line that says so.
    lines = body.splitlines()
    refs = sorted({r for line in lines
                   if not any(m in line for m in TOMBSTONE_MARKERS)
                   for r in re.findall(pattern, line)})
    dead = []
    for r in refs:
        if "{'"'"' in r or "," in r:
            # a brace-glob like SELF/{soul,DIARY}.md is a shorthand, not one path —
            # expanding it is out of scope, and flagging it is noise. Skip, don't guess.
            continue
        if any(ch in r for ch in "*?["):
            # a glob is a shorthand for a set; check whether the set is non-empty rather
            # than pretending it is one path
            import glob as _glob
            if _glob.glob(os.path.join(root, r)) or _glob.glob(os.path.join(root, "**", r),
                                                                recursive=True):
                continue
            dead.append(r)
            continue

        cand = os.path.expanduser(r)
        if not os.path.isabs(cand):
            # relative refs are written from the file they live in, first and foremost
            here = os.path.join(os.path.dirname(os.path.abspath(path)), r)
            if os.path.exists(here):
                continue
            cand = os.path.join(root, r)
        if os.path.exists(cand):
            continue

        # last chance: the file exists but the row cited it without its folder. Resolved
        # by unique basename — but ONLY if the name is unique across the tree, because a
        # common filename matching many places tells us nothing about which one was meant.
        import glob as _glob
        hits = [h for h in _glob.glob(os.path.join(root, "**", os.path.basename(r)),
                                      recursive=True)
                if "/.git/" not in h and "/backup/" not in h]
        if len(hits) == 1:
            continue

        # The same memory file cites two different trees: the working tree AND the skill
        # tree (`references/...` lives under the skill, not the project). A resolver that
        # only knows one root invents dead paths that are perfectly alive.
        for sr in SKILL_ROOTS:
            sr = os.path.expanduser(sr)
            if os.path.exists(os.path.join(sr, r)) or _glob.glob(os.path.join(sr, r)):
                hits.append(os.path.join(sr, r))
                break
        if hits:
            continue
        dead.append(r)

    measured = {"path": path, "references": len(refs), "unresolved": dead}
    if dead:
        return Finding("dead_paths", FAIL,
                       f"{path}: {len(dead)} of {len(refs)} path references do not resolve",
                       measured=measured, detail="; ".join(dead[:6]))
    return Finding("dead_paths", OK,
                   f"{path}: all {len(refs)} path references resolve", measured=measured)


# --------------------------------------------------------------- size + staleness

def check_size_pressure(path, limit_bytes=None):
    """A layer measured against ITS OWN stated limit, not against a house style."""
    if not os.path.exists(path):
        return Finding("size", WARN, f"missing file: {path}", measured={"path": path})
    size = os.path.getsize(path)
    if limit_bytes is None:
        return Finding("size", OK, f"{path}: {size}B (no limit declared)",
                       measured={"path": path, "bytes": size})
    if size > limit_bytes:
        over = size - limit_bytes
        return Finding("size", WARN,
                       f"{path}: {size}B against a {limit_bytes}B limit (+{over}B)",
                       measured={"path": path, "bytes": size, "limit": limit_bytes},
                       detail="Over-limit is a signal to LOOK, not automatically to cut. "
                              "A limit that gets quietly exceeded every day teaches its "
                              "reader to ignore limits — either the content earns the space "
                              "or the number was wrong.")
    return Finding("size", OK, f"{path}: {size}B / {limit_bytes}B",
                   measured={"path": path, "bytes": size, "limit": limit_bytes})


def check_staleness(path, stale_hours=24, now=None):
    """A layer nobody has written in a long time — visible BEFORE it is loaded."""
    if not os.path.exists(path):
        return Finding("staleness", WARN, f"missing file: {path}", measured={"path": path})
    now = now or datetime.datetime.now().timestamp()
    age_h = (now - os.path.getmtime(path)) / 3600.0
    level = WARN if age_h > stale_hours else OK
    return Finding("staleness", level,
                   f"{path}: last written {age_h:.1f}h ago (threshold {stale_hours}h)",
                   measured={"path": path, "age_hours": round(age_h, 2),
                             "threshold_hours": stale_hours},
                   detail="" if level == OK else
                          "Stale is not wrong. Stale means the file is a photograph and "
                          "the world may have moved: prefer current state over the record.")


# --------------------------------------------------------------- contradictions

def check_contradictions(claims, groups=None):
    """Two live claims about the SAME fact that disagree.

    Tiers matter: retired claims are TOMBSTONES, not assertions. Treating a tombstone as a
    live claim is how a checker starts crying wolf, and a checker that cries wolf gets
    ignored — which is the failure this check exists to prevent.
    """
    groups = groups or []
    live = [c for c in claims
            if c.get("tier") not in ("retired",) and not c.get("superseded_by")]
    by_key = {}
    for c in live:
        by_key.setdefault(c.get("key"), []).append(c)

    problems = []
    for key, rows in by_key.items():
        vals = {str(r.get("claim")) for r in rows}
        if len(vals) > 1:
            problems.append({"key": key, "conflicting_values": sorted(vals)})

    for grp in groups:
        present = [k for k in grp if k in by_key]
        if len(present) > 1:
            vals = {str(r.get("claim")) for k in present for r in by_key[k]}
            if len(vals) > 1:
                problems.append({"group": sorted(present),
                                 "conflicting_values": sorted(vals)})

    measured = {"live_claims": len(live), "keys": len(by_key),
                "contradictions": len(problems)}
    if problems:
        return Finding("contradictions", FAIL,
                       f"{len(problems)} contradiction(s) among {len(live)} live claims",
                       measured=measured, detail=str(problems[:4]))
    return Finding("contradictions", OK,
                   f"{len(live)} live claims, no contradictions", measured=measured)
