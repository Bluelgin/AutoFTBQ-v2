"""Persistent project timeline shared by Studio and the in-game editor."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
import time
import uuid


def default_state_path() -> Path:
    override = os.environ.get("AUTOFTBQ_STATE_PATH", "").strip()
    return Path(override) if override else Path.home() / ".autoftbq" / "studio-bridge.sqlite3"


class SharedProjectState:
    """Small SQLite event store; payloads remain JSON and forward compatible."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_state_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    stable_key TEXT NOT NULL UNIQUE,
                    client_id TEXT NOT NULL,
                    world_id TEXT NOT NULL DEFAULT '',
                    conversation_id TEXT NOT NULL,
                    book_revision TEXT NOT NULL DEFAULT '',
                    snapshot_json TEXT NOT NULL DEFAULT '',
                    snapshot_format TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_conversation_cursor
                    ON events(conversation_id, event_id);
                CREATE TABLE IF NOT EXISTS transactions (
                    proposal_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS transactions_project_status
                    ON transactions(project_id, status, updated_at);
                """
            )

    @staticmethod
    def _stable_key(client_id: str, world_id: str = "") -> str:
        return f"{str(client_id).strip()}::{str(world_id).strip()}"

    def resolve_project(self, client_id: str, world_id: str = "") -> dict:
        client = str(client_id).strip()
        world = str(world_id).strip()
        key = self._stable_key(client, world)
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT * FROM projects WHERE stable_key = ?", (key,),
            ).fetchone()
            if row is None and ":" in world:
                legacy_world = world.split(":", 1)[0]
                legacy = db.execute(
                    "SELECT * FROM projects WHERE stable_key = ?",
                    (self._stable_key(client, legacy_world),),
                ).fetchone()
                if legacy is not None:
                    db.execute(
                        "UPDATE projects SET stable_key=?, world_id=?, updated_at=? "
                        "WHERE project_id=?",
                        (key, world, time.time(), legacy["project_id"]),
                    )
                    row = db.execute(
                        "SELECT * FROM projects WHERE project_id=?",
                        (legacy["project_id"],),
                    ).fetchone()
            if row is None and world:
                provisional = db.execute(
                    "SELECT * FROM projects WHERE stable_key = ?",
                    (self._stable_key(client),),
                ).fetchone()
                if provisional is not None:
                    conflict = db.execute(
                        "SELECT 1 FROM projects WHERE stable_key = ?", (key,),
                    ).fetchone()
                    if conflict is None:
                        db.execute(
                            "UPDATE projects SET stable_key=?, world_id=?, updated_at=? "
                            "WHERE project_id=?",
                            (key, world, time.time(), provisional["project_id"]),
                        )
                        row = db.execute(
                            "SELECT * FROM projects WHERE project_id=?",
                            (provisional["project_id"],),
                        ).fetchone()
            if row is None:
                project_id = uuid.uuid4().hex
                conversation_id = uuid.uuid4().hex
                now = time.time()
                db.execute(
                    "INSERT INTO projects(project_id, stable_key, client_id, world_id, "
                    "conversation_id, updated_at) VALUES(?,?,?,?,?,?)",
                    (project_id, key, client, world, conversation_id, now),
                )
                row = db.execute(
                    "SELECT * FROM projects WHERE project_id=?", (project_id,),
                ).fetchone()
            return dict(row)

    def append_event(self, project_id: str, conversation_id: str, kind: str,
                     origin: str, payload: dict) -> dict:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("shared event payload is too large")
        now = time.time()
        with self._lock, self._connection() as db:
            cursor = db.execute(
                "INSERT INTO events(project_id, conversation_id, kind, origin, "
                "payload_json, created_at) VALUES(?,?,?,?,?,?)",
                (str(project_id), str(conversation_id), str(kind)[:80],
                 str(origin)[:40], encoded, now),
            )
            event_id = int(cursor.lastrowid)
        return {
            "event_id": event_id, "project_id": str(project_id),
            "conversation_id": str(conversation_id), "kind": str(kind),
            "origin": str(origin), "payload": dict(payload), "created_at": now,
        }

    def latest_agent_checkpoint(self, conversation_id: str) -> dict | None:
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT payload_json FROM events WHERE conversation_id=? AND kind='work.checkpoint' "
                "ORDER BY event_id DESC LIMIT 1", (conversation_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def events(self, conversation_id: str, after: int = 0,
               limit: int = 200) -> list[dict]:
        bounded = max(1, min(int(limit), 500))
        with self._lock, self._connection() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE conversation_id=? AND event_id>? "
                "ORDER BY event_id ASC LIMIT ?",
                (str(conversation_id), max(0, int(after)), bounded),
            ).fetchall()
        return [{
            "event_id": int(row["event_id"]),
            "project_id": row["project_id"],
            "conversation_id": row["conversation_id"],
            "kind": row["kind"], "origin": row["origin"],
            "payload": json.loads(row["payload_json"]),
            "created_at": float(row["created_at"]),
        } for row in rows]

    def reconcile_interrupted_work(self, project_id: str, conversation_id: str,
                                   *, before: float) -> int:
        """Close timeline work left non-terminal by a previous Studio process."""
        with self._lock, self._connection() as db:
            rows = db.execute(
                "SELECT kind, payload_json FROM events WHERE conversation_id=? "
                "AND created_at<? ORDER BY event_id ASC",
                (str(conversation_id), float(before)),
            ).fetchall()
        open_requests: dict[str, dict] = {}
        terminal = {"chat.assistant", "work.failed", "work.cancelled", "work.interrupted"}
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            request_id = str(payload.get("request_id", ""))
            if not request_id:
                continue
            if row["kind"] in {"chat.user", "work.progress"}:
                open_requests[request_id] = payload
            if row["kind"] in terminal:
                open_requests.pop(request_id, None)
        for request_id in open_requests:
            self.append_event(project_id, conversation_id, "work.interrupted", "studio", {
                "request_id": request_id,
                "error": "Studio 上次退出时请求仍在执行；已标记为中断，可重新发送",
            })
        return len(open_requests)

    def save_snapshot(self, project_id: str, revision: str, snapshot_format: str,
                      snapshot: dict) -> dict:
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 16 * 1024 * 1024:
            raise ValueError("task-book snapshot is too large")
        now = time.time()
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT conversation_id FROM projects WHERE project_id=?",
                (str(project_id),),
            ).fetchone()
            if row is None:
                raise ValueError("unknown shared project")
            db.execute(
                "UPDATE projects SET book_revision=?, snapshot_json=?, "
                "snapshot_format=?, updated_at=? WHERE project_id=?",
                (str(revision), encoded, str(snapshot_format), now, str(project_id)),
            )
            conversation_id = row["conversation_id"]
        self.append_event(project_id, conversation_id, "book.snapshot", "game", {
            "revision": str(revision), "format": str(snapshot_format),
        })
        return {"accepted": True, "project_id": str(project_id),
                "book_revision": str(revision), "updated_at": now}

    def snapshot(self, project_id: str) -> dict | None:
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT project_id, conversation_id, book_revision, snapshot_format, "
                "snapshot_json, updated_at FROM projects WHERE project_id=?",
                (str(project_id),),
            ).fetchone()
        if row is None or not row["snapshot_json"]:
            return None
        return {
            "project_id": row["project_id"],
            "conversation_id": row["conversation_id"],
            "book_revision": row["book_revision"],
            "format": row["snapshot_format"],
            "snapshot": json.loads(row["snapshot_json"]),
            "updated_at": float(row["updated_at"]),
        }

    def has_snapshot(self, project_id: str) -> bool:
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT length(snapshot_json) AS size FROM projects WHERE project_id=?",
                (str(project_id),),
            ).fetchone()
        return row is not None and int(row["size"] or 0) > 0

    def save_transaction(self, project_id: str, conversation_id: str,
                         proposal: dict) -> None:
        encoded = json.dumps(proposal, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 10 * 1024 * 1024:
            raise ValueError("transaction is too large")
        with self._lock, self._connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO transactions(proposal_id, project_id, "
                "conversation_id, payload_json, status, updated_at) VALUES(?,?,?,?,?,?)",
                (str(proposal.get("proposal_id", "")), str(project_id),
                 str(conversation_id), encoded, str(proposal.get("status", "")), time.time()),
            )

    def update_transaction(self, proposal: dict) -> None:
        encoded = json.dumps(proposal, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connection() as db:
            db.execute(
                "UPDATE transactions SET payload_json=?, status=?, updated_at=? "
                "WHERE proposal_id=?",
                (encoded, str(proposal.get("status", "")), time.time(),
                 str(proposal.get("proposal_id", ""))),
            )

    def pending_transactions(self, project_id: str) -> list[dict]:
        with self._lock, self._connection() as db:
            rows = db.execute(
                "SELECT payload_json FROM transactions WHERE project_id=? AND status='confirmed' "
                "ORDER BY updated_at ASC", (str(project_id),),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def close(self) -> None:
        return
