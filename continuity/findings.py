"""Findings — the only output type. Nothing here is a boolean."""
from dataclasses import dataclass, field
from typing import Any

OK, WARN, FAIL = "ok", "warn", "fail"

_ORDER = {OK: 0, WARN: 1, FAIL: 2}


@dataclass
class Finding:
    """One observation about one thing.

    `level` is a judgement call and is meant to be argued with. `measured` is the raw
    thing a command returned — keep it, because a finding without its measurement is
    an opinion wearing a number.
    """
    check: str
    level: str
    message: str
    measured: dict = field(default_factory=dict)
    detail: str = ""

    def worse_than(self, other):
        return _ORDER[self.level] > _ORDER[other.level]


@dataclass
class Report:
    findings: list = field(default_factory=list)

    def add(self, f: Finding):
        self.findings.append(f)
        return f

    @property
    def level(self):
        lv = OK
        for f in self.findings:
            if _ORDER[f.level] > _ORDER[lv]:
                lv = f.level
        return lv

    @property
    def exit_code(self):
        return {OK: 0, WARN: 0, FAIL: 1}[self.level]

    def by_check(self):
        out = {}
        for f in self.findings:
            out.setdefault(f.check, []).append(f)
        return out
