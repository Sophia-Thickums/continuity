"""Load a config, run every check, print a report. No hidden state, no writes."""
import os
import sys
import datetime

from . import checks, store
from .findings import Report, Finding, OK, WARN, FAIL

DEFAULT_FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "examples")


def _read_toml(path):
    """Parse the tiny subset of TOML we need, without a dependency.

    Supports [sections], key = value (string/int/bool/float), and inline string lists.
    Deliberately narrow: a config parser that silently mis-reads a file is the same class
    of bug as the checks themselves exist to catch.
    """
    out, section = {}, None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[[") and line.endswith("]]"):
                # array-of-tables: append a fresh dict, and remember we are inside it
                name = line[2:-2].strip()
                out.setdefault(name, [])
                if not isinstance(out[name], list):
                    raise ValueError(f"'{name}' used as both table and array-of-tables")
                out[name].append({})
                section = f"{name}[{len(out[name]) - 1}]"
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                out.setdefault(section, {})
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if v.startswith("[") and v.endswith("]"):
                items = [i.strip().strip('"\'') for i in v[1:-1].split(",") if i.strip()]
                val = items
            elif v.startswith('"') and v.endswith('"'):
                val = v[1:-1]
            elif v.lower() in ("true", "false"):
                val = v.lower() == "true"
            else:
                try:
                    val = int(v)
                except ValueError:
                    try:
                        val = float(v)
                    except ValueError:
                        val = v
            if section is None:
                out[k] = val
            elif "[" in section and section.endswith("]"):
                name, idx = section[:-1].split("[")
                out[name][int(idx)][k] = val
            else:
                out.setdefault(section, {})[k] = val
    return out


def run(cfg_path=None, sessions=None, use_fixtures=False):
    report = Report()

    if use_fixtures or cfg_path is None:
        # ---- self-contained demo: no user data needed
        import json
        sp = os.path.join(DEFAULT_FIXTURES, "sessions.jsonl")
        if os.path.exists(sp):
            st = store.JsonlSessions(sp)
            sessions = st.sessions()
        for fx in ("memory_clean.md", "memory_doubled.md", "memory_deadpaths.md"):
            p = os.path.join(DEFAULT_FIXTURES, fx)
            if os.path.exists(p):
                report.add(checks.check_duplicate_sections(p))
                report.add(checks.check_dead_paths(p, root=DEFAULT_FIXTURES))
                report.add(checks.check_size_pressure(p, limit_bytes=2400))
                report.add(checks.check_staleness(p, stale_hours=24 * 365))
        if sessions:
            report.add(checks.check_gap(sessions))
        return report

    cfg = _read_toml(cfg_path)

    s = cfg.get("sessions", {})
    if s:
        try:
            st = store.open_store(s)
            sessions = st.sessions(limit=s.get("limit", 200))
            report.add(checks.check_gap(
                sessions,
                same_sitting_minutes=s.get("same_sitting_minutes", 30),
                same_day_hours=s.get("same_day_hours", 6),
            ))
        except store.StoreError as e:
            report.add(Finding("gap", WARN, f"session store unavailable: {e}"))
    elif sessions:
        report.add(checks.check_gap(sessions))

    layers = cfg.get("layers", [])
    if not layers:
        # A config that DECLARES layers but yields none is not a clean run — it is a run
        # that looked at nothing. Reporting OK here is the exact failure this kit exists
        # to catch, so it refuses to.
        raw_has = "layers" in open(cfg_path, encoding="utf-8").read()
        report.add(Finding("config", FAIL,
                           "config declares layers but none parsed — refusing to report OK",
                           measured={"config": cfg_path, "layers_declared": raw_has},
                           detail="A check that cannot observe must never report absence. "
                                  "This was hit for real: the parser silently ignored "
                                  "[[layers]] array-of-tables and the run returned OK "
                                  "without opening a single file."))

    for layer in layers:
        if isinstance(layer, str):
            layer = {"path": layer}
        p = os.path.expanduser(layer["path"])
        if not os.path.isabs(p):
            p = os.path.join(os.getcwd(), p)
        report.add(checks.check_duplicate_sections(p))
        report.add(checks.check_dead_paths(p, root=layer.get("root", os.getcwd())))
        report.add(checks.check_size_pressure(p, limit_bytes=layer.get("limit_bytes")))
        report.add(checks.check_staleness(p, stale_hours=layer.get("stale_hours", 24)))

    claims_path = cfg.get("claims", {}).get("path")
    if claims_path:
        import json
        claims = []
        cp = os.path.expanduser(claims_path)
        if os.path.exists(cp):
            with open(cp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            claims.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        report.add(checks.check_contradictions(claims))

    return report


ICONS = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}


def render(report):
    print("=" * 74)
    print(f"CONTINUITY CHECK — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 74)
    for f in report.findings:
        print(f"\n[{ICONS[f.level]}] {f.check}")
        print(f"        {f.message}")
        if f.detail:
            print(f"        -> {f.detail}")
    level = report.level
    print("\n" + "-" * 74)
    n = {l: sum(1 for f in report.findings if f.level == l) for l in (FAIL, WARN, OK)}
    print(f"RESULT: {level.upper()}   ({n[FAIL]} failing, {n[WARN]} warning, {n[OK]} ok)")
    if level == FAIL:
        print("Exit 1 — a real contradiction or duplication. Not a style opinion.")
    print("-" * 74)
    return report.exit_code


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__ if __doc__ else "usage: python3 -m continuity [demo|check <config.toml>]")
        return 0
    if not argv or argv[0] == "demo":
        return render(run(use_fixtures=True))
    if argv[0] == "check":
        if len(argv) < 2:
            print("usage: python3 -m continuity check <config.toml>")
            return 2
        return render(run(cfg_path=argv[1]))
    print(f"unknown command: {argv[0]}")
    return 2
