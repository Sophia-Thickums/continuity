"""Session stores — read the raw record of when an agent was awake, and what it said.

Two shapes are supported because those are the two that exist in the wild:

  sqlite  a sessions table (one row per session, with a timestamp) — the shape used by
          Hermes and by most home-grown agent harnesses
  jsonl   one JSON object per line, each with a timestamp — the shape you get from
          anything that appends turns to a file

Nothing here writes. Every reader opens read-only, because the first rule of looking
at a live system is that looking must not change it.
"""
import json
import os
import sqlite3


class StoreError(Exception):
    pass


def _expand(p):
    return os.path.expanduser(p)


class SqliteSessions:
    """One row per session. Column names are configurable — no schema is assumed."""

    def __init__(self, path, table="sessions", time_col="last_activity_at",
                 id_col="id", title_col="title", messages_col="message_count",
                 source_col=None, source_value=None):
        self.path = _expand(path)
        self.table, self.time_col = table, time_col
        self.id_col, self.title_col = id_col, title_col
        self.messages_col = messages_col
        self.source_col, self.source_value = source_col, source_value

        if not os.path.exists(self.path):
            raise StoreError(f"no session store at {self.path}")

    def _connect(self):
        return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)

    def sessions(self, limit=200):
        """Most recent first. Ordered by the configured time column."""
        cols = [self.id_col, self.time_col, self.title_col, self.messages_col]
        where, params = "", []
        if self.source_col and self.source_value is not None:
            where = f"WHERE {self.source_col} = ?"
            params = [self.source_value]
        sql = (f"SELECT {', '.join(cols)} FROM {self.table} {where} "
               f"ORDER BY {self.time_col} DESC LIMIT ?")
        con = self._connect()
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(sql, params + [limit]).fetchall()
        except sqlite3.Error as e:
            raise StoreError(f"{self.table}: {e}")
        finally:
            con.close()
        return [self._row(r) for r in rows]

    def _row(self, r):
        return {
            "id": r[self.id_col],
            "ts": r[self.time_col],
            "title": r[self.title_col] if self.title_col in r.keys() else "",
            "messages": r[self.messages_col] if self.messages_col in r.keys() else None,
        }


class JsonlSessions:
    """One JSON object per line. Fields: ts (epoch seconds or ISO8601), and anything else."""

    def __init__(self, path, ts_field="ts", id_field="id"):
        self.path = _expand(path)
        self.ts_field, self.id_field = ts_field, id_field
        if not os.path.exists(self.path):
            raise StoreError(f"no session log at {self.path}")

    def sessions(self, limit=200):
        out = []
        with open(self.path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out.append({
                    "id": rec.get(self.id_field, ""),
                    "ts": normalize_ts(rec.get(self.ts_field)),
                    "title": rec.get("title", ""),
                    "messages": rec.get("messages"),
                })
        out = [r for r in out if r["ts"] is not None]
        out.sort(key=lambda r: r["ts"], reverse=True)
        return out[:limit]


def normalize_ts(v):
    """Accept epoch seconds, epoch millis, or ISO8601. Return epoch seconds or None.

    Guessing wrong here shifts every gap by decades, so the thresholds are explicit
    rather than clever: a number above 1e11 is millis, ISO strings are parsed as UTC
    unless they carry an offset.
    """
    import datetime
    if v is None:
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        if x > 1e11:            # milliseconds
            x /= 1000.0
        return x
    if isinstance(v, str):
        s = v.strip().replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    return None


def open_store(cfg):
    """Build a reader from a config dict."""
    kind = cfg.get("type", "sqlite")
    if kind == "sqlite":
        return SqliteSessions(
            cfg["path"],
            table=cfg.get("table", "sessions"),
            time_col=cfg.get("time_col", "last_activity_at"),
            id_col=cfg.get("id_col", "id"),
            title_col=cfg.get("title_col", "title"),
            messages_col=cfg.get("messages_col", "message_count"),
            source_col=cfg.get("source_col"),
            source_value=cfg.get("source_value"),
        )
    if kind == "jsonl":
        return JsonlSessions(cfg["path"],
                             ts_field=cfg.get("ts_field", "ts"),
                             id_field=cfg.get("id_field", "id"))
    raise StoreError(f"unknown store type: {kind}")
