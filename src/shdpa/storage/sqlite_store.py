"""SQLite-backed persistence + immutable audit log.

Schema is deliberately tiny (3 tables) because every column the agent
might want to slice on already lives inside the JSON blob — we just
denormalize the few we need to index (class, resolved, created_at,
cost). The full Incident object is round-tripped via Pydantic.

Audit log:
  Every insert into `incidents` also writes an append-only row to
  `audit_log` keyed by `(incident_id, sha256(json))`. The hash is the
  evidence trail — if a row is later tampered, the hash will not match
  the JSON.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from shdpa.models import Incident

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id           TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    source       TEXT NOT NULL,
    dag_id       TEXT,
    task_id      TEXT,
    predicted_class TEXT,
    resolved     INTEGER NOT NULL DEFAULT 0,
    resolution_kind TEXT,
    total_cost_usd REAL NOT NULL DEFAULT 0,
    total_latency_s REAL NOT NULL DEFAULT 0,
    error        TEXT,
    raw_json     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at);
CREATE INDEX IF NOT EXISTS idx_incidents_class   ON incidents(predicted_class);
CREATE INDEX IF NOT EXISTS idx_incidents_dag     ON incidents(dag_id);

CREATE TABLE IF NOT EXISTS llm_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     TEXT NOT NULL,
    purpose         TEXT NOT NULL,
    model           TEXT,
    provider        TEXT,
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (incident_id) REFERENCES incidents(id)
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_incident ON llm_calls(incident_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    written_at   TEXT NOT NULL,
    incident_id  TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    operation    TEXT NOT NULL  -- 'insert' (we never update — append-only)
);

CREATE INDEX IF NOT EXISTS idx_audit_incident ON audit_log(incident_id);
"""


class SQLiteStore:
    """Thread-safe SQLite persistence + audit log.

    Use as a context manager OR call .close() explicitly. The store is
    safe to share across threads because sqlite3.connect with
    check_same_thread=False + an explicit lock is used.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---------- context manager ----------

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------- writes ----------

    def save_incident(self, incident: Incident) -> str:
        """Persist a finished incident. Returns the incident id (string).

        Idempotent: if an incident with the same id already exists, the
        row is REPLACED but the audit_log gets a fresh 'insert' row so
        the history of mutations is preserved.
        """
        raw = incident.model_dump_json()
        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        iid = str(incident.id)
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO incidents
                   (id, created_at, source, dag_id, task_id, predicted_class,
                    resolved, resolution_kind, total_cost_usd, total_latency_s,
                    error, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    iid,
                    incident.created_at.isoformat(),
                    incident.source,
                    incident.dag_id,
                    incident.task_id,
                    incident.predicted_class,
                    int(incident.resolved),
                    incident.resolution_kind,
                    incident.total_cost_usd,
                    incident.total_latency_s,
                    incident.error,
                    raw,
                ),
            )
            # Denormalize LLM calls so SQL `sum(cost)` over time is cheap.
            self._conn.execute("DELETE FROM llm_calls WHERE incident_id = ?", (iid,))
            for c in incident.llm_calls:
                self._conn.execute(
                    """INSERT INTO llm_calls
                       (incident_id, purpose, model, provider, prompt_tokens,
                        completion_tokens, cost_usd, latency_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        iid,
                        c.purpose,
                        c.model,
                        c.provider,
                        c.prompt_tokens,
                        c.completion_tokens,
                        c.cost_usd,
                        c.latency_ms,
                    ),
                )
            # Append-only audit row.
            self._conn.execute(
                "INSERT INTO audit_log (written_at, incident_id, sha256, operation)"
                " VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), iid, sha, "insert"),
            )
            self._conn.commit()
        return iid

    # ---------- reads ----------

    def get_incident(self, incident_id: str | UUID) -> Incident | None:
        iid = str(incident_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT raw_json FROM incidents WHERE id = ?", (iid,)
            ).fetchone()
        if not row:
            return None
        return Incident.model_validate_json(row["raw_json"])

    def list_incidents(
        self,
        *,
        limit: int = 50,
        since: datetime | None = None,
        predicted_class: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, created_at, source, dag_id, task_id, predicted_class,"
            " resolved, resolution_kind, total_cost_usd, total_latency_s, error"
            " FROM incidents WHERE 1=1"
        )
        params: list[Any] = []
        if since:
            sql += " AND created_at >= ?"
            params.append(since.isoformat())
        if predicted_class:
            sql += " AND predicted_class = ?"
            params.append(predicted_class)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def count_file_patches_last_24h(self, file_path: str, since: datetime) -> int:
        """Count the number of times file_path has been proposed to be changed in the last 24h."""
        count = 0
        sql = "SELECT raw_json FROM incidents WHERE created_at >= ?"
        with self._lock:
            rows = self._conn.execute(sql, (since.isoformat(),)).fetchall()
        for r in rows:
            try:
                incident = Incident.model_validate_json(r["raw_json"])
                norm_target = os.path.normpath(file_path)
                for f in incident.proposed_files_changed:
                    if os.path.normpath(f) == norm_target:
                        count += 1
            except Exception:
                pass
        return count

    def aggregate(self, *, since: datetime | None = None) -> dict[str, Any]:
        """One-shot stats useful for dashboards: count, resolution rate,
        total $ spent, mean latency.
        """
        sql_where = ""
        params: list[Any] = []
        if since:
            sql_where = " WHERE created_at >= ?"
            params.append(since.isoformat())
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) as n,"
                f"       SUM(resolved)  as resolved,"
                f"       SUM(total_cost_usd) as total_cost,"
                f"       AVG(total_latency_s) as mean_latency"
                f"  FROM incidents{sql_where}",
                params,
            ).fetchone()
        n = row["n"] or 0
        return {
            "n": n,
            "resolved": row["resolved"] or 0,
            "resolution_rate": (row["resolved"] or 0) / n if n else 0.0,
            "total_cost_usd": row["total_cost"] or 0.0,
            "mean_latency_s": row["mean_latency"] or 0.0,
        }

    def verify_audit(self) -> list[dict[str, Any]]:
        """Re-hash every incident's raw_json and compare to the audit_log.
        Returns a list of `{incident_id, expected_sha, actual_sha}` for
        any row whose hash no longer matches — i.e. the row was tampered.
        """
        bad: list[dict[str, Any]] = []
        with self._lock:
            for r in self._conn.execute(
                "SELECT i.id, i.raw_json,"
                "  (SELECT sha256 FROM audit_log a WHERE a.incident_id = i.id"
                "    ORDER BY a.id DESC LIMIT 1) as expected"
                " FROM incidents i"
            ).fetchall():
                actual = hashlib.sha256(r["raw_json"].encode("utf-8")).hexdigest()
                if actual != r["expected"]:
                    bad.append(
                        {
                            "incident_id": r["id"],
                            "expected_sha": r["expected"],
                            "actual_sha": actual,
                        }
                    )
        return bad


_default_store: SQLiteStore | None = None
_default_store_lock = threading.Lock()


def get_default_store() -> SQLiteStore | None:
    """Return the singleton store if SHDPA_STORAGE_PATH is set.

    Returns None if the env var is unset — callers MUST handle that
    (it means "persistence is off, just run in-memory"). This keeps
    the eval harness fast (no disk I/O per fixture) while letting
    production turn on persistence by setting one env var.
    """
    global _default_store
    path = os.getenv("SHDPA_STORAGE_PATH")
    if not path:
        return None
    with _default_store_lock:
        if _default_store is None or str(_default_store.path) != path:
            _default_store = SQLiteStore(path)
    return _default_store
