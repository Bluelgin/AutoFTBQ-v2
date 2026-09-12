"""Thread-safe bridge state with no UI or transport dependencies."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
import secrets
from threading import RLock
import time

from .protocol import GameContext, Handshake, PROTOCOL_VERSION, ProtocolError
from .request_manager import GameRequestManager
from .shared_state import SharedProjectState
from .book_sync import diff_project_payload, snapshot_to_project_payload
from ..infrastructure.app_logging import LOGGER_NAME
from snbt_parser import to_snbt


LOGGER = logging.getLogger(LOGGER_NAME)

_COMPACT_OBJECT_KEYS = (
    "id", "type", "item", "item_id", "entity", "entity_id", "entity_type",
    "structure", "count", "amount", "dimension", "icon", "title",
)


def _bounded_summary_value(value, *, depth: int = 0):
    if depth > 2:
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value[:500] if isinstance(value, str) else value
    if isinstance(value, list):
        return [_bounded_summary_value(item, depth=depth + 1) for item in value[:16]]
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:24]:
            summarized = _bounded_summary_value(item, depth=depth + 1)
            if summarized is not None:
                result[str(key)[:80]] = summarized
        return result
    return str(value)[:500]


def _compact_quest_object(value: dict) -> dict:
    result = {}
    for key in _COMPACT_OBJECT_KEYS:
        if key in value:
            result[key] = _bounded_summary_value(value[key])
    return result


def _compact_description(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:500] for item in value[:8] if isinstance(item, str)]


class BridgeService:
    MAX_SESSIONS = 64
    REQUIRED_GAME_CAPABILITIES = {
        "agent.transactional_edit", "project.timeline.v1",
        "project.snapshot.v1", "write.auto_apply.v1",
        "game_query.registry_batch", "game_query.registry_validate",
        "context.selected_chapters", "context.agent_selection.v1",
        "scope.enforced.v1",
        "request.preflight_sync.v1",
        "request.generation_recovery.v1",
        "agent.shared_core.v1",
        "data.evidence.v1",
        "transaction.strict_snbt.v1",
        "transaction.batch_index.v1",
        "agent.live_steps.v1",
        "result.server_truth.v1",
        "revision.network_fingerprint.v1",
    }

    def __init__(self, *, shared_state: SharedProjectState | None = None) -> None:
        self._lock = RLock()
        self._sessions: dict[str, dict] = {}
        self._contexts: dict[str, GameContext] = {}
        self._latest_session_id = ""
        self._started_at = time.time()
        self._reconciled_conversations: set[str] = set()
        self.shared_state = shared_state or SharedProjectState()
        self.requests = GameRequestManager(self.shared_state)

    @staticmethod
    def health() -> dict:
        return {
            "service": "AutoFTBQ Studio",
            "status": "ready",
            "protocol_version": PROTOCOL_VERSION,
        }

    def handshake(self, payload: dict) -> dict:
        request = Handshake.parse(payload)
        missing = self.REQUIRED_GAME_CAPABILITIES.difference(request.capabilities)
        if missing:
            raise ProtocolError(
                "AutoFTBQ Agent Mod 版本过旧；请安装 0.1.0-alpha.14 或更新版本"
            )
        session_id = secrets.token_urlsafe(24)
        with self._lock:
            self._sessions[session_id] = {
                "client": request,
                "project_id": "",
                "conversation_id": "",
                "connected_at": datetime.now(timezone.utc).isoformat(),
                "seen_at": time.monotonic(),
            }
            self._latest_session_id = session_id
            while len(self._sessions) > self.MAX_SESSIONS:
                expired = next(iter(self._sessions))
                self._sessions.pop(expired, None)
                self._contexts.pop(expired, None)
        LOGGER.info(
            "Game bridge handshake accepted: mod=%s minecraft=%s loader=%s ftbq=%s project=%s",
            request.mod_version, request.minecraft_version, request.loader.name,
            request.ftb_quests_version, "pending-world-context",
        )
        return {
            "accepted": True,
            "session_id": session_id,
            "project_id": "",
            "conversation_id": "",
            "project_pending": True,
            "protocol_version": PROTOCOL_VERSION,
            "minimum_mod_version": "0.1.0-alpha.14",
            "capabilities": [
                "agent.layout_sketch.v1",
                "context.chapter", "context.selected_chapters", "context.selected_quests",
                "context.agent_selection.v1", "scope.enforced.v1",
                "request.preflight_sync.v1",
                "request.generation_recovery.v1",
                "agent.shared_core.v1",
                "data.evidence.v1",
                "result.server_truth.v1",
                "revision.network_fingerprint.v1",
                "context.registry_summary",
                "agent.transactional_edit", "agent.cancel", "game_query.selected_quest_details",
                "game_query.registry_search", "game_query.registry_batch",
                "game_query.registry_validate", "game_query.recipe_search",
                "proposal.preview", "proposal.decision", "conflict.book_revision",
                "security.server_authoritative", "write.transaction.v1",
                "application.recovery.v1",
                "project.timeline.v1", "project.snapshot.v1", "write.auto_apply.v1",
            ],
        }

    def update_context(self, payload: dict) -> dict:
        context = GameContext.parse(payload)
        with self._lock:
            if context.session_id not in self._sessions:
                raise ProtocolError("unknown session_id")
            session = self._sessions[context.session_id]
            project = self.shared_state.resolve_project(
                session["client"].client_id, context.world_id,
            )
            session["project_id"] = project["project_id"]
            session["conversation_id"] = project["conversation_id"]
            previous = self._contexts.get(context.session_id)
            if previous is not None and context.revision < previous.revision:
                raise ProtocolError("context revision moved backwards")
            self._contexts[context.session_id] = context
            self._sessions[context.session_id]["seen_at"] = time.monotonic()
            self._latest_session_id = context.session_id
        self.requests.restore_studio_transactions(
            context.session_id, project["project_id"], project["conversation_id"],
        )
        conversation_id = project["conversation_id"]
        with self._lock:
            should_reconcile = conversation_id not in self._reconciled_conversations
            if should_reconcile:
                self._reconciled_conversations.add(conversation_id)
        if should_reconcile:
            interrupted = self.shared_state.reconcile_interrupted_work(
                project["project_id"], conversation_id, before=self._started_at,
            )
            if interrupted:
                LOGGER.info("Reconciled %s interrupted Agent request(s)", interrupted)
        if previous is None or previous.world_id != context.world_id:
            LOGGER.info(
                "Game context bound: project=%s world=%s editable=%s revision=%s",
                project["project_id"], context.world_id,
                context.book_summary.get("server_can_edit"), context.book_revision,
            )
        return {
            "accepted": True, "revision": context.revision,
            "project_id": project["project_id"],
            "conversation_id": project["conversation_id"],
        }

    def context(self, session_id: str) -> dict | None:
        with self._lock:
            value = self._contexts.get(str(session_id))
            return asdict(value) if value is not None else None

    def agent_context(self, session_id: str) -> dict | None:
        """Enrich live selection with the shared Studio task-book snapshot."""
        context = self.context(session_id)
        identity = self.session_identity(session_id)
        if context is None or identity is None:
            return context
        envelope = self.shared_state.snapshot(identity["project_id"])
        if envelope is None or envelope.get("format") != "ftbquests-snbt-v1":
            return context
        try:
            project = snapshot_to_project_payload(envelope)
        except ProtocolError:
            LOGGER.exception("Unable to enrich game Agent context from task-book snapshot")
            return context
        selected_ids = {
            str(value.get("id", "")).strip().upper()
            for value in context.get("selected_quests", []) if isinstance(value, dict)
        }
        selected_chapter_ids = {
            str(value.get("id", "")).strip().upper()
            for value in context.get("selected_chapters", []) if isinstance(value, dict)
        }
        details = []
        chapter_details = []
        total_bytes = 0
        truncated = False
        max_context_bytes = 192 * 1024
        for chapter in project.get("chapters", []):
            if not isinstance(chapter, dict):
                continue
            chapter_id = str(chapter.get("id", ""))
            chapter_id_key = chapter_id.strip().upper()
            chapter_quests = []
            chapter_bytes = 0
            chapter_truncated = False
            for quest in chapter.get("quests", []):
                if not isinstance(quest, dict):
                    continue
                quest_id = str(quest.get("id", "")).strip().upper()
                tasks = [
                    _compact_quest_object(item) for item in quest.get("tasks", [])
                    if isinstance(item, dict)
                ][:128]
                rewards = [
                    _compact_quest_object(item) for item in quest.get("rewards", [])
                    if isinstance(item, dict)
                ][:128]
                summary_detail = {
                    "id": quest_id,
                    "chapter_id": chapter_id,
                    "title": quest.get("title", ""),
                    "subtitle": quest.get("subtitle", ""),
                    "icon": quest.get("icon", ""),
                    "description": _compact_description(quest.get("description", [])),
                    "tasks": tasks,
                    "rewards": rewards,
                    "task_ids": [
                        str(item.get("id", "")) for item in quest.get("tasks", [])
                        if isinstance(item, dict) and item.get("id")
                    ][:128],
                    "reward_ids": [
                        str(item.get("id", "")) for item in quest.get("rewards", [])
                        if isinstance(item, dict) and item.get("id")
                    ][:128],
                    "detail_level": "summary",
                }
                if quest_id in selected_ids:
                    detail = dict(summary_detail)
                    raw_snbt = to_snbt(quest)
                    if len(raw_snbt) > 24_000:
                        raw_snbt = raw_snbt[:24_000] + "…"
                        truncated = True
                    detail["raw_snbt"] = raw_snbt
                    detail["detail_level"] = "full"
                    encoded_size = len(json.dumps(
                        detail, ensure_ascii=False, separators=(",", ":"),
                    ).encode("utf-8"))
                    if total_bytes + chapter_bytes + encoded_size > max_context_bytes:
                        truncated = True
                    else:
                        details.append(detail)
                        total_bytes += encoded_size
                if chapter_id_key in selected_chapter_ids:
                    summary_size = len(json.dumps(
                        summary_detail, ensure_ascii=False, separators=(",", ":"),
                    ).encode("utf-8"))
                    if total_bytes + chapter_bytes + summary_size > max_context_bytes:
                        chapter_truncated = True
                        truncated = True
                    else:
                        chapter_quests.append(summary_detail)
                        chapter_bytes += summary_size
            if chapter_id_key in selected_chapter_ids:
                chapter_detail = {
                    "id": chapter_id,
                    "title": chapter.get("title", ""),
                    "quest_count": len(chapter.get("quests", [])),
                    "included_quest_count": len(chapter_quests),
                    "truncated": chapter_truncated,
                    "quests": chapter_quests,
                }
                chapter_details.append(chapter_detail)
                total_bytes += chapter_bytes
            if truncated and total_bytes >= max_context_bytes:
                break
        context["selected_quest_details"] = details
        context["selected_chapter_details"] = chapter_details
        context["selected_quest_details_source"] = "studio_task_book_snapshot"
        context["selected_chapter_details_source"] = "studio_task_book_snapshot"
        context["selected_quest_details_truncated"] = truncated
        context["selected_chapter_details_truncated"] = truncated
        return context

    def submit_request(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ProtocolError("request must be an object")
        session_id = str(payload.get("session_id", ""))
        from .sketch import validate_sketch
        sketch = validate_sketch(payload.get("layout_sketch"))
        revision = payload.get("context_revision")
        with self._lock:
            context = self._contexts.get(session_id)
            if context is None:
                raise ProtocolError("game context must be synchronized before submitting a request")
            if revision != context.revision:
                raise ProtocolError("context_revision does not match the latest game context")
            session = self._sessions[session_id]
        result = self.requests.submit(
            session_id, payload.get("prompt", ""), revision,
            context.book_revision, context.server_book_revision,
            session.get("project_id", ""), session.get("conversation_id", ""),
            layout_sketch=sketch,
        )
        LOGGER.info(
            "Game Agent request queued: request=%s project=%s context_revision=%s",
            result.get("request_id", ""), session.get("project_id", ""), revision,
        )
        return result

    def session_identity(self, session_id: str) -> dict | None:
        with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None:
                return None
            return {
                "project_id": session.get("project_id", ""),
                "conversation_id": session.get("conversation_id", ""),
            }

    def events(self, session_id: str, after: int = 0, limit: int = 200) -> list[dict]:
        identity = self.session_identity(session_id)
        if identity is None:
            raise ProtocolError("unknown session_id")
        return self.shared_state.events(identity["conversation_id"], after, limit)

    def save_book_snapshot(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ProtocolError("request must be an object")
        session_id = str(payload.get("session_id", ""))
        identity = self.session_identity(session_id)
        if identity is None:
            raise ProtocolError("unknown session_id")
        revision = str(payload.get("book_revision", ""))
        snapshot_format = str(payload.get("format", ""))
        snapshot = payload.get("snapshot")
        if not revision or snapshot_format not in {"ftbquests-snbt-v1", "autoftbq-v2"}:
            raise ProtocolError("invalid task-book snapshot metadata")
        if not isinstance(snapshot, dict):
            raise ProtocolError("task-book snapshot must be an object")
        try:
            result = self.shared_state.save_snapshot(
                identity["project_id"], revision, snapshot_format, snapshot,
            )
            LOGGER.info(
                "Task-book snapshot stored: project=%s revision=%s format=%s",
                identity["project_id"], revision, snapshot_format,
            )
            return result
        except ValueError as exc:
            raise ProtocolError(str(exc)) from exc

    def book_snapshot(self, session_id: str) -> dict | None:
        identity = self.session_identity(session_id)
        if identity is None:
            return None
        return self.shared_state.snapshot(identity["project_id"])

    def latest_book_payload(self) -> dict | None:
        with self._lock:
            session_id = self._latest_session_id
        envelope = self.book_snapshot(session_id) if session_id else None
        return snapshot_to_project_payload(envelope) if envelope else None

    def has_latest_book_snapshot(self) -> bool:
        with self._lock:
            session = self._sessions.get(self._latest_session_id)
            project_id = session.get("project_id", "") if session else ""
        return bool(project_id and self.shared_state.has_snapshot(project_id))

    def queue_studio_book(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ProtocolError("Studio task book must be an object")
        with self._lock:
            session_id = self._latest_session_id
            session = self._sessions.get(session_id)
            context = self._contexts.get(session_id)
        if session is None or context is None:
            raise ProtocolError("no synchronized game session is available")
        envelope = self.shared_state.snapshot(session.get("project_id", ""))
        if envelope is None:
            raise ProtocolError("the game has not uploaded a task-book snapshot")
        expected = str(payload.get("base_book_revision", ""))
        if not expected or expected != envelope.get("book_revision"):
            raise ProtocolError("the live task book changed; reload it in Studio before syncing")
        if expected != context.server_book_revision or context.book_revision != expected:
            raise ProtocolError("client, server, and Studio task-book revisions do not match")
        desired = payload.get("project")
        if not isinstance(desired, dict) or desired.get("format") != "autoftbq-v2":
            raise ProtocolError("invalid Studio project payload")
        operations = diff_project_payload(snapshot_to_project_payload(envelope), desired)
        result = self.requests.create_studio_transaction(
            session_id=session_id, project_id=session.get("project_id", ""),
            conversation_id=session.get("conversation_id", ""),
            context_revision=context.revision, book_revision=expected,
            summary=str(payload.get("summary") or "Studio 工作台同步"),
            operations=operations,
        )
        LOGGER.info(
            "Studio task-book transaction queued: proposal=%s project=%s operations=%s",
            result.get("proposal_id", ""), session.get("project_id", ""), len(operations),
        )
        return result

    def decide_proposal(self, proposal_id: str, payload: dict, *, confirm: bool) -> dict | None:
        if not isinstance(payload, dict):
            raise ProtocolError("request must be an object")
        session_id = str(payload.get("session_id", ""))
        revision = payload.get("context_revision")
        with self._lock:
            context = self._contexts.get(session_id)
            if context is None:
                raise ProtocolError("game context must be synchronized before deciding a proposal")
            if revision != context.revision:
                raise ProtocolError("context_revision does not match the latest game context")
            if confirm and context.book_summary.get("server_can_edit") is not True:
                raise ProtocolError("the game server does not grant FTB Quests edit permission")
        return self.requests.decide_proposal(
            proposal_id, session_id, context.book_revision,
            context.server_book_revision, confirm=confirm,
        )

    def record_proposal_application(self, proposal_id: str, payload: dict) -> dict | None:
        if not isinstance(payload, dict):
            raise ProtocolError("request must be an object")
        session_id = str(payload.get("session_id", ""))
        with self._lock:
            if session_id not in self._sessions:
                raise ProtocolError("unknown session_id")
        result = self.requests.record_application(proposal_id, session_id, payload)
        if result is not None:
            LOGGER.info(
                "Game transaction result: proposal=%s status=%s revision=%s",
                proposal_id, result.get("status", ""),
                result.get("applied_book_revision", ""),
            )
        return result

    def snapshot(self) -> dict:
        """Return display-safe connection metadata without exposing the token."""
        with self._lock:
            session = self._sessions.get(self._latest_session_id)
            if session is None:
                return {"available": False}
            client: Handshake = session["client"]
            context = self._contexts.get(self._latest_session_id)
            return {
                "available": True,
                "session_id": self._latest_session_id,
                "minecraft_version": client.minecraft_version,
                "loader": client.loader.name,
                "loader_version": client.loader.version,
                "ftb_quests_version": client.ftb_quests_version,
                "seconds_since_sync": max(0, int(time.monotonic() - session["seen_at"])),
                "chapter_title": context.chapter_title if context else "",
                "selected_chapters": len(context.selected_chapters) if context else 0,
                "selected_quests": len(context.selected_quests) if context else 0,
                "project_id": session.get("project_id", ""),
                "conversation_id": session.get("conversation_id", ""),
                "mod_version": client.mod_version,
                "client_can_edit": context.book_summary.get("can_edit") if context else None,
                "server_can_edit": context.book_summary.get("server_can_edit") if context else None,
            }
