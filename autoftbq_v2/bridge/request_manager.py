"""Bounded asynchronous Agent requests and game-side read-only query broker."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import math
import secrets
from threading import Event, RLock
import time

from .protocol import ProtocolError


TERMINAL_STATES = {"completed", "failed", "cancelled"}
ALLOWED_GAME_QUERIES = {
    "get_selected_quest_details", "search_registry", "search_registry_batch",
    "validate_registry_ids", "search_recipes",
    "inspect_game_data",
}


@dataclass
class RequestRecord:
    id: str
    session_id: str
    prompt: str
    context_revision: int
    project_id: str = ""
    conversation_id: str = ""
    book_revision: str = ""
    server_book_revision: str = ""
    status: str = "queued"
    stage: str = "queued"
    message: str = "等待 Studio Agent"
    result: str = ""
    error: str = ""
    cancel_requested: bool = False
    pause_requested: bool = False
    layout_sketch: dict | None = None
    proposal_id: str = ""
    outcome: str = "pending"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "request_id": self.id,
            "status": self.status,
            "progress": {"stage": self.stage, "message": self.message},
            "result": self.result,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "pause_requested": self.pause_requested,
            "has_layout_sketch": self.layout_sketch is not None,
            "proposal_id": self.proposal_id,
            "outcome": self.outcome,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class QueryTicket:
    id: str
    request_id: str
    session_id: str
    name: str
    arguments: dict
    event: Event = field(default_factory=Event)
    result: dict | None = None
    delivered: bool = False


@dataclass
class ProposalRecord:
    id: str
    request_id: str
    session_id: str
    base_context_revision: int
    base_book_revision: str
    base_server_book_revision: str
    summary: str
    operations: list[dict]
    status: str = "proposed"
    application_message: str = ""
    applied_book_revision: str = ""
    id_map: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "proposal_id": self.id,
            "request_id": self.request_id,
            "status": self.status,
            "base_context_revision": self.base_context_revision,
            "base_book_revision": self.base_book_revision,
            "base_server_book_revision": self.base_server_book_revision,
            "summary": self.summary,
            "operations": [dict(value) for value in self.operations],
            "application_message": self.application_message,
            "applied_book_revision": self.applied_book_revision,
            "id_map": dict(self.id_map),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class GameRequestManager:
    MAX_REQUESTS = 100
    MAX_PROMPT_CHARS = 8000
    MAX_QUERY_ARGUMENT_BYTES = 64 * 1024
    # Forge's packet codec accepts at most 262,144 Java characters / 786,432 UTF-8 bytes.
    # Keep headroom so a proposal accepted by Studio can always reach the game server.
    MAX_PROPOSAL_CHARS = 250_000
    MAX_PROPOSAL_BYTES = 750_000
    MAX_PROPOSAL_OPERATIONS = 1000
    MAX_GAME_QUERIES_PER_REQUEST = 12

    def __init__(self, shared_state=None) -> None:
        self._lock = RLock()
        self._records: dict[str, RequestRecord] = {}
        self._queue: deque[str] = deque()
        self._queries: dict[str, QueryTicket] = {}
        self._query_queues: dict[str, deque[str]] = {}
        self._query_counts: dict[str, int] = {}
        self._query_cache: dict[tuple[str, str, str], dict] = {}
        self._proposals: dict[str, ProposalRecord] = {}
        self._studio_transaction_queues: dict[str, deque[str]] = {}
        self.shared_state = shared_state

    def submit(self, session_id: str, prompt: str, context_revision: int,
               book_revision: str = "", server_book_revision: str = "",
               project_id: str = "", conversation_id: str = "", layout_sketch=None) -> dict:
        text = str(prompt or "").strip()
        if not text:
            raise ProtocolError("prompt is required")
        if len(text) > self.MAX_PROMPT_CHARS:
            raise ProtocolError("prompt is too long")
        if not isinstance(context_revision, int) or context_revision < 0:
            raise ProtocolError("context_revision must be a non-negative integer")
        record = RequestRecord(
            id=secrets.token_urlsafe(18),
            session_id=str(session_id),
            prompt=text,
            context_revision=context_revision,
            project_id=str(project_id),
            conversation_id=str(conversation_id),
            book_revision=str(book_revision or ""),
            server_book_revision=str(server_book_revision or ""),
            layout_sketch=layout_sketch,
        )
        with self._lock:
            active = next((value for value in self._records.values()
                           if value.session_id == str(session_id)
                           and value.status not in TERMINAL_STATES), None)
            if active is not None:
                raise ProtocolError(
                    "已有 Agent 请求正在处理；请等待完成或先点击取消后再发送"
                )
            self._trim()
            if len(self._records) >= self.MAX_REQUESTS:
                raise ProtocolError("too many active Agent requests")
            self._records[record.id] = record
            self._queue.append(record.id)
        self._event(record, "chat.user", "game", {
            "request_id": record.id, "text": record.prompt,
            "context_revision": record.context_revision,
            **({"layout_sketch": record.layout_sketch} if record.layout_sketch else {}),
        })
        return record.public()

    def _event(self, record: RequestRecord, kind: str, origin: str,
               payload: dict) -> None:
        if self.shared_state is None or not record.project_id or not record.conversation_id:
            return
        self.shared_state.append_event(
            record.project_id, record.conversation_id, kind, origin, payload,
        )

    def _trim(self) -> None:
        # Make room for one incoming record while preferentially retaining
        # every non-terminal request.
        while len(self._records) >= self.MAX_REQUESTS:
            removable = next(
                (key for key, value in self._records.items() if value.status in TERMINAL_STATES),
                None,
            )
            if removable is None:
                break
            self._records.pop(removable, None)
            stale = [key for key, value in self._proposals.items()
                     if value.request_id == removable]
            for key in stale:
                self._proposals.pop(key, None)

    def take_next(self) -> RequestRecord | None:
        with self._lock:
            while self._queue:
                record = self._records.get(self._queue.popleft())
                if record is not None and record.status == "queued":
                    record.status = "running"
                    record.stage = "preparing"
                    record.message = "Studio 正在准备任务书 Agent"
                    record.updated_at = time.time()
                    return record
        return None

    def get(self, request_id: str) -> RequestRecord | None:
        with self._lock:
            return self._records.get(str(request_id))

    def public(self, request_id: str) -> dict | None:
        with self._lock:
            record = self._records.get(str(request_id))
            return record.public() if record else None

    def list_public(self, session_id: str, limit: int = 20) -> list[dict]:
        result_limit = max(1, min(int(limit), 50))
        with self._lock:
            values = [value.public() for value in self._records.values()
                      if value.session_id == str(session_id)]
        return list(reversed(values[-result_limit:]))

    def conversation_messages(self, session_id: str, before_request_id: str,
                              limit: int = 6) -> list[dict]:
        with self._lock:
            history = []
            for value in self._records.values():
                if value.id == str(before_request_id):
                    break
                if (value.session_id == str(session_id)
                        and value.status == "completed" and value.result):
                    history.append((value.prompt, value.result))
            history = history[-max(0, min(int(limit), 12)):]
        messages = []
        for prompt, result in history:
            messages.append({"role": "user", "content": prompt})
            messages.append({"role": "assistant", "content": result})
        return messages

    def progress(self, request_id: str, stage: str, message: str) -> None:
        event = None
        with self._lock:
            record = self._records.get(str(request_id))
            if record and record.status == "running":
                record.stage = str(stage)[:80]
                record.message = str(message)[:500]
                record.updated_at = time.time()
                event = (record, record.stage, record.message)
        if event:
            self._event(event[0], "work.progress", "studio", {
                "request_id": event[0].id, "stage": event[1], "message": event[2],
            })

    def complete(self, request_id: str, result: str, *, outcome: str | None = None) -> None:
        completed = None
        with self._lock:
            record = self._records.get(str(request_id))
            if record and record.status == "running":
                record.status = "completed"
                record.stage = "completed"
                record.message = "Agent 请求完成"
                record.result = str(result)[:100_000]
                record.outcome = str(outcome or (
                    "proposal_prepared" if record.proposal_id else "analysis_only"
                ))[:80]
                record.updated_at = time.time()
                completed = record
        if completed:
            self._event(completed, "chat.assistant", "studio", {
                "request_id": completed.id, "text": completed.result,
                "proposal_id": completed.proposal_id, "outcome": completed.outcome,
            })

    def fail(self, request_id: str, error: str) -> None:
        failed = None
        with self._lock:
            record = self._records.get(str(request_id))
            if record and record.status not in TERMINAL_STATES:
                record.status = "failed"
                record.stage = "failed"
                record.message = "Agent 请求失败"
                record.error = str(error)[:2000]
                record.outcome = "failed"
                record.updated_at = time.time()
                failed = record
            self._invalidate_proposals_locked(request_id, "invalidated")
        self._release_queries(request_id, {"error": "request_failed"})
        if failed:
            self._event(failed, "work.failed", "studio", {
                "request_id": failed.id, "error": failed.error,
            })

    def set_paused(self, request_id: str, paused: bool) -> dict | None:
        with self._lock:
            record = self._records.get(str(request_id))
            if record is None:
                return None
            if record.status not in TERMINAL_STATES:
                record.pause_requested = bool(paused)
                record.message = "正在暂停，等待当前安全步骤结束" if paused else "正在继续"
                record.updated_at = time.time()
            return record.public()

    def is_paused(self, request_id: str) -> bool:
        with self._lock:
            record = self._records.get(str(request_id))
            return bool(record and record.pause_requested and record.status not in TERMINAL_STATES)

    def cancel(self, request_id: str) -> dict | None:
        with self._lock:
            record = self._records.get(str(request_id))
            if record is None:
                return None
            record.cancel_requested = True
            if record.status not in TERMINAL_STATES:
                record.status = "cancelled"
                record.stage = "cancelled"
                record.message = "已取消；进行中的模型连接可能稍后结束"
                record.updated_at = time.time()
            self._invalidate_proposals_locked(request_id, "cancelled")
            result = record.public()
        self._release_queries(request_id, {"error": "request_cancelled"})
        self._event(record, "work.cancelled", "game", {"request_id": record.id})
        return result

    def is_cancelled(self, request_id: str) -> bool:
        with self._lock:
            record = self._records.get(str(request_id))
            return record is None or record.cancel_requested or record.status == "cancelled"

    def request_game_query(
        self, request_id: str, session_id: str, name: str, arguments: dict,
        *, timeout: float = 20.0,
    ) -> dict:
        if name not in ALLOWED_GAME_QUERIES:
            return {"error": f"unsupported read-only game query: {name}"}
        if not isinstance(arguments, dict):
            return {"error": "query arguments must be an object"}
        encoded = json.dumps(arguments, ensure_ascii=False).encode("utf-8")
        if len(encoded) > self.MAX_QUERY_ARGUMENT_BYTES:
            return {"error": "query arguments are too large"}
        if self.is_cancelled(request_id):
            return {"error": "request_cancelled"}
        cache_key = (
            str(request_id), str(name),
            json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        with self._lock:
            cached = self._query_cache.get(cache_key)
            if cached is not None and name != "inspect_game_data":
                return dict(cached)
            used = self._query_counts.get(str(request_id), 0)
            if used >= self.MAX_GAME_QUERIES_PER_REQUEST:
                return {
                    "error": "game_query_budget_exhausted",
                    "message": (
                        "本次请求的游戏查询预算已用完；请使用批量查询结果完成回答，"
                        "不要继续逐项查询或猜测 ID"
                    ),
                    "used": used,
                    "limit": self.MAX_GAME_QUERIES_PER_REQUEST,
                }
            self._query_counts[str(request_id)] = used + 1
        ticket = QueryTicket(
            id=secrets.token_urlsafe(16), request_id=request_id,
            session_id=session_id, name=name, arguments=dict(arguments),
        )
        with self._lock:
            self._queries[ticket.id] = ticket
            self._query_queues.setdefault(session_id, deque()).append(ticket.id)
        deadline = time.monotonic() + max(1.0, min(float(timeout), 30.0))
        while not ticket.event.wait(0.25):
            if self.is_cancelled(request_id):
                return {"error": "request_cancelled"}
            if time.monotonic() >= deadline:
                with self._lock:
                    self._queries.pop(ticket.id, None)
                return {"error": "game_query_timeout", "message": "游戏端未及时返回查询结果"}
        result = ticket.result or {"error": "empty_game_query_result"}
        if "error" not in result and name != "inspect_game_data":
            with self._lock:
                self._query_cache[cache_key] = dict(result)
        return result

    def query_usage(self, request_id: str) -> tuple[int, int]:
        with self._lock:
            return (self._query_counts.get(str(request_id), 0),
                    self.MAX_GAME_QUERIES_PER_REQUEST)

    def begin_query_batch(self, request_id: str) -> None:
        """Renew a bounded batch while retaining verified query results."""
        with self._lock:
            self._query_counts[str(request_id)] = 0

    def take_game_query(self, session_id: str) -> dict | None:
        with self._lock:
            queue = self._query_queues.setdefault(str(session_id), deque())
            while queue:
                ticket = self._queries.get(queue.popleft())
                if ticket is not None and not ticket.delivered:
                    ticket.delivered = True
                    return {
                        "query_id": ticket.id,
                        "request_id": ticket.request_id,
                        "name": ticket.name,
                        "arguments": dict(ticket.arguments),
                    }
        return None

    def resolve_game_query(self, session_id: str, query_id: str, result: dict) -> bool:
        if not isinstance(result, dict):
            raise ProtocolError("query result must be an object")
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
            raise ProtocolError("query result is too large")
        with self._lock:
            ticket = self._queries.get(str(query_id))
            if ticket is None or ticket.session_id != str(session_id):
                return False
            ticket.result = dict(result)
            self._queries.pop(ticket.id, None)
            ticket.event.set()
            return True

    def _release_queries(self, request_id: str, result: dict) -> None:
        with self._lock:
            tickets = [value for value in self._queries.values() if value.request_id == request_id]
            for ticket in tickets:
                ticket.result = dict(result)
                self._queries.pop(ticket.id, None)
                ticket.event.set()

    def interrupt_all(self, message: str = "Studio 已关闭，请重新连接后重试") -> int:
        """Finish every volatile Agent request before the bridge disappears."""
        with self._lock:
            request_ids = [value.id for value in self._records.values()
                           if value.status not in TERMINAL_STATES]
        for request_id in request_ids:
            self.fail(request_id, message)
        return len(request_ids)

    def _invalidate_proposals_locked(self, request_id: str, status: str) -> None:
        for value in self._proposals.values():
            if value.request_id == str(request_id) and value.status == "proposed":
                value.status = status
                value.updated_at = time.time()

    def create_proposal(self, request_id: str, summary: str, operations: list) -> dict:
        clean_summary = str(summary or "").strip()
        if not clean_summary or len(clean_summary) > 4000:
            raise ProtocolError("proposal summary is required and must not exceed 4000 characters")
        if not isinstance(operations, list) or not operations:
            raise ProtocolError("proposal operations must be a non-empty array")
        if len(operations) > self.MAX_PROPOSAL_OPERATIONS:
            raise ProtocolError("proposal contains too many operations")
        clean_operations = []
        for index, value in enumerate(operations):
            try:
                clean_operations.append(self._validate_operation(value))
            except ProtocolError as exc:
                raise ProtocolError(f"operations[{index}]: {exc}") from exc
        if not self._proposal_fits_transport(clean_operations):
            raise ProtocolError("proposal is too large")
        with self._lock:
            request = self._records.get(str(request_id))
            if request is None or request.status != "running":
                raise ProtocolError("request is not running")
            if request.proposal_id:
                raise ProtocolError("request already has a proposal")
            if not request.book_revision:
                raise ProtocolError("game client did not provide a task-book revision")
            if not request.server_book_revision or request.server_book_revision == "unavailable":
                raise ProtocolError("game server did not provide an authoritative task-book revision")
            if request.book_revision != request.server_book_revision:
                raise ProtocolError("client and server task-book definitions are not synchronized")
            proposal = ProposalRecord(
                id=secrets.token_urlsafe(18), request_id=request.id,
                session_id=request.session_id,
                base_context_revision=request.context_revision,
                base_book_revision=request.book_revision,
                base_server_book_revision=request.server_book_revision,
                summary=clean_summary, operations=clean_operations,
            )
            self._proposals[proposal.id] = proposal
            request.proposal_id = proposal.id
            request.outcome = "proposal_prepared"
            request.updated_at = time.time()
            public = proposal.public()
        self._event(request, "change.prepared", "studio", {
            "request_id": request.id, "proposal": public,
        })
        return public

    def public_proposal(self, proposal_id: str) -> dict | None:
        with self._lock:
            value = self._proposals.get(str(proposal_id))
            return value.public() if value else None

    def create_studio_transaction(
        self, *, session_id: str, project_id: str, conversation_id: str,
        context_revision: int, book_revision: str, summary: str,
        operations: list[dict],
    ) -> dict:
        clean_summary = str(summary or "Studio 工作台同步").strip()[:4000]
        clean_operations = [self._validate_operation(value) for value in operations]
        if not clean_operations:
            return {"accepted": True, "status": "unchanged", "operation_count": 0}
        if len(clean_operations) > self.MAX_PROPOSAL_OPERATIONS:
            raise ProtocolError("Studio transaction contains too many operations")
        if not self._proposal_fits_transport(clean_operations):
            raise ProtocolError("Studio transaction is too large")
        request = RequestRecord(
            id=secrets.token_urlsafe(18), session_id=str(session_id), prompt=clean_summary,
            context_revision=int(context_revision), project_id=str(project_id),
            conversation_id=str(conversation_id), book_revision=str(book_revision),
            server_book_revision=str(book_revision), status="completed", stage="completed",
            message="等待游戏端应用 Studio 工作台修改", result="Studio 工作台修改已进入同步队列",
            outcome="proposal_prepared",
        )
        proposal = ProposalRecord(
            id=secrets.token_urlsafe(18), request_id=request.id,
            session_id=request.session_id, base_context_revision=request.context_revision,
            base_book_revision=request.book_revision,
            base_server_book_revision=request.server_book_revision,
            summary=clean_summary, operations=clean_operations, status="confirmed",
        )
        request.proposal_id = proposal.id
        with self._lock:
            self._trim()
            if len(self._records) >= self.MAX_REQUESTS:
                raise ProtocolError("too many active Agent requests")
            self._records[request.id] = request
            self._proposals[proposal.id] = proposal
            self._studio_transaction_queues.setdefault(request.session_id, deque()).append(
                proposal.id
            )
        if self.shared_state is not None:
            self.shared_state.save_transaction(project_id, conversation_id, {
                **proposal.public(), "session_id": request.session_id,
                "project_id": request.project_id,
                "conversation_id": request.conversation_id,
            })
        self._event(request, "change.queued", "studio", {
            "request_id": request.id, "proposal_id": proposal.id,
            "summary": clean_summary, "operation_count": len(clean_operations),
        })
        return {"accepted": True, "status": "queued", "request_id": request.id,
                "proposal_id": proposal.id, "operation_count": len(clean_operations)}

    def take_studio_transaction(self, session_id: str) -> dict | None:
        with self._lock:
            queue = self._studio_transaction_queues.setdefault(str(session_id), deque())
            while queue:
                proposal = self._proposals.get(queue[0])
                if proposal is not None and proposal.status == "confirmed":
                    return proposal.public()
                queue.popleft()
        return None

    def restore_studio_transactions(self, session_id: str, project_id: str,
                                    conversation_id: str) -> None:
        if self.shared_state is None:
            return
        for value in self.shared_state.pending_transactions(project_id):
            proposal_id = str(value.get("proposal_id", ""))
            request_id = str(value.get("request_id", ""))
            if not proposal_id or not request_id:
                continue
            with self._lock:
                proposal = self._proposals.get(proposal_id)
                if proposal is not None:
                    proposal.session_id = str(session_id)
                else:
                    request = RequestRecord(
                        id=request_id, session_id=str(session_id),
                        prompt=str(value.get("summary", "Studio 工作台同步")),
                        context_revision=int(value.get("base_context_revision", 0)),
                        project_id=str(project_id), conversation_id=str(conversation_id),
                        book_revision=str(value.get("base_book_revision", "")),
                        server_book_revision=str(value.get("base_server_book_revision", "")),
                        status="completed", stage="completed",
                        message="等待游戏端恢复未完成的 Studio 同步",
                        result="Studio 工作台修改已恢复到同步队列",
                        proposal_id=proposal_id,
                        outcome="proposal_prepared",
                    )
                    proposal = ProposalRecord(
                        id=proposal_id, request_id=request_id, session_id=str(session_id),
                        base_context_revision=request.context_revision,
                        base_book_revision=request.book_revision,
                        base_server_book_revision=request.server_book_revision,
                        summary=str(value.get("summary", "Studio 工作台同步")),
                        operations=[dict(item) for item in value.get("operations", [])],
                        status="confirmed",
                    )
                    self._records[request_id] = request
                    self._proposals[proposal_id] = proposal
                queue = self._studio_transaction_queues.setdefault(str(session_id), deque())
                if proposal_id not in queue:
                    queue.append(proposal_id)

    def decide_proposal(self, proposal_id: str, session_id: str,
                        book_revision: str, server_book_revision: str,
                        *, confirm: bool) -> dict | None:
        with self._lock:
            value = self._proposals.get(str(proposal_id))
            if value is None or value.session_id != str(session_id):
                return None
            if value.status != "proposed":
                raise ProtocolError("proposal has already been decided")
            if not book_revision or book_revision != value.base_book_revision:
                raise ProtocolError("task book changed after the proposal was created")
            if (not server_book_revision
                    or server_book_revision != value.base_server_book_revision
                    or server_book_revision != book_revision):
                raise ProtocolError("server task book changed after the proposal was created")
            value.status = "confirmed" if confirm else "rejected"
            value.updated_at = time.time()
            return value.public()

    def record_application(self, proposal_id: str, session_id: str, payload: dict) -> dict | None:
        status = str(payload.get("status", ""))
        if status not in {"applied", "failed", "conflict", "undone"}:
            raise ProtocolError("invalid proposal application status")
        message = str(payload.get("message", ""))[:2000]
        revision = str(payload.get("server_book_revision", ""))[:128]
        id_map = payload.get("id_map", {})
        if not isinstance(id_map, dict) or len(id_map) > self.MAX_PROPOSAL_OPERATIONS:
            raise ProtocolError("proposal id_map must be a bounded object")
        clean_map = {}
        for key, value in id_map.items():
            name = str(key)[:256]
            object_id = str(value)[:64]
            if not name or not object_id:
                raise ProtocolError("proposal id_map contains an invalid entry")
            clean_map[name] = object_id
        if status in {"applied", "undone"} and not revision:
            raise ProtocolError("successful proposal transition requires server_book_revision")
        with self._lock:
            proposal = self._proposals.get(str(proposal_id))
            if proposal is None or proposal.session_id != str(session_id):
                return None
            if proposal.status == status:
                if (proposal.application_message == message
                        and proposal.applied_book_revision == revision
                        and proposal.id_map == clean_map):
                    return proposal.public()
                raise ProtocolError("proposal application replay does not match stored result")
            expected = "applied" if status == "undone" else "confirmed"
            if proposal.status != expected:
                raise ProtocolError("proposal is not in the required application state")
            proposal.status = status
            proposal.application_message = message
            proposal.applied_book_revision = revision
            proposal.id_map = clean_map
            proposal.updated_at = time.time()
            public = proposal.public()
            request = self._records.get(proposal.request_id)
            if request is not None:
                request.outcome = status
                request.updated_at = time.time()
        if request is not None:
            self._event(request, "change." + status, "game", {
                "request_id": request.id, "proposal_id": proposal.id,
                "status": status, "message": message,
                "server_book_revision": revision, "id_map": clean_map,
            })
        if self.shared_state is not None:
            self.shared_state.update_transaction(public)
        return public

    @staticmethod
    def _proposal_fits_transport(operations: list[dict]) -> bool:
        encoded = json.dumps(
            operations, ensure_ascii=False, separators=(",", ":"),
        )
        return (len(encoded) <= GameRequestManager.MAX_PROPOSAL_CHARS
                and len(encoded.encode("utf-8")) <= GameRequestManager.MAX_PROPOSAL_BYTES)

    @staticmethod
    def operation_fields() -> dict:
        return {
            "update_book_raw": ({"data_snbt"}, {"data_snbt"}),
            "upsert_chapter_group_raw": (
                {"group_id", "data_snbt"}, {"group_id", "data_snbt"},
            ),
            "delete_chapter_group": ({"group_id"}, {"group_id"}),
            "upsert_reward_table_raw": (
                {"reward_table_id", "data_snbt"}, {"reward_table_id", "data_snbt"},
            ),
            "delete_reward_table": ({"reward_table_id"}, {"reward_table_id"}),
            "upsert_chapter_raw": (
                {"chapter_id", "data_snbt"}, {"chapter_id", "data_snbt"},
            ),
            "upsert_quest_raw": (
                {"quest_id", "chapter_id", "data_snbt"},
                {"quest_id", "chapter_id", "data_snbt"},
            ),
            "upsert_quest_object_raw": (
                {"quest_id", "object_kind", "object_id", "type_id", "data_snbt"},
                {"quest_id", "object_kind", "object_id", "type_id", "data_snbt"},
            ),
            "remove_quest_object": ({"object_id"}, {"object_id"}),
            "delete_quest": ({"quest_id"}, {"quest_id"}),
            "delete_chapter": ({"chapter_id"}, {"chapter_id"}),
            "create_chapter": ({"temp_id", "title"}, {"temp_id", "title", "subtitle", "icon"}),
            "create_quest": (
                {"temp_id", "chapter_id", "title", "x", "y"},
                {"temp_id", "chapter_id", "title", "subtitle", "description", "icon", "x", "y"},
            ),
            "update_quest": ({"quest_id", "changes"}, {"quest_id", "changes"}),
            "add_dependency": (
                {"quest_id", "dependency_id"}, {"quest_id", "dependency_id"},
            ),
            "add_item_task": (
                {"quest_id", "item_id", "count"}, {"quest_id", "item_id", "count"},
            ),
            "add_item_reward": (
                {"quest_id", "item_id", "count"}, {"quest_id", "item_id", "count"},
            ),
            "add_checkmark_task": ({"quest_id"}, {"quest_id"}),
            "add_xp_task": ({"quest_id", "amount"}, {"quest_id", "amount"}),
            "add_xp_reward": ({"quest_id", "amount"}, {"quest_id", "amount"}),
            "add_xp_levels_reward": ({"quest_id", "amount"}, {"quest_id", "amount"}),
        }
    @staticmethod
    def _validate_operation(value) -> dict:
        if not isinstance(value, dict):
            raise ProtocolError("proposal operation must be an object")
        kind = str(value.get("kind", ""))
        schemas = GameRequestManager.operation_fields()
        if kind not in schemas:
            raise ProtocolError(f"unsupported proposal operation: {kind}")
        required, allowed = schemas[kind]
        keys = set(value) - {"kind"}
        if not required.issubset(keys) or not keys.issubset(allowed):
            raise ProtocolError(
                f"invalid fields for proposal operation: {kind}; "
                f"missing={sorted(required - keys)}; unexpected={sorted(keys - allowed)}; "
                f"required={sorted(required)}; allowed={sorted(allowed)}. "
                "Create conditions and rewards with separate add_* operations; "
                "create dependencies with add_dependency."
            )
        result = {"kind": kind}
        for key in keys:
            item = value[key]
            if key in {"x", "y"}:
                if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item):
                    raise ProtocolError(f"{key} must be a finite number")
                result[key] = max(-1_000_000.0, min(float(item), 1_000_000.0))
            elif key in {"count", "amount"}:
                if not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 2_147_483_647:
                    raise ProtocolError(f"{key} must be a positive integer")
                result[key] = item
            elif key == "description":
                result[key] = GameRequestManager._validate_description(item)
            elif key == "changes":
                result[key] = GameRequestManager._validate_quest_changes(item)
            else:
                text = str(item or "").strip()
                limit = 1024 * 1024 if key == "data_snbt" else (
                    4000 if key in {"title", "subtitle"} else 256
                )
                if not text or len(text) > limit:
                    raise ProtocolError(f"{key} is required and too long")
                if key == "object_kind" and text not in {"task", "reward"}:
                    raise ProtocolError("object_kind must be task or reward")
                result[key] = text
        return result

    @staticmethod
    def _validate_quest_changes(value) -> dict:
        if not isinstance(value, dict) or not value:
            raise ProtocolError("quest changes must be a non-empty object")
        allowed = {"title", "subtitle", "description", "icon", "x", "y"}
        if not set(value).issubset(allowed):
            raise ProtocolError("quest changes contain unsupported fields")
        result = {}
        for key, item in value.items():
            if key in {"x", "y"}:
                if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item):
                    raise ProtocolError(f"{key} must be a finite number")
                result[key] = max(-1_000_000.0, min(float(item), 1_000_000.0))
            elif key == "description":
                result[key] = GameRequestManager._validate_description(item)
            else:
                text = str(item or "").strip()
                if key != "icon" and not text:
                    raise ProtocolError(f"{key} must not be empty")
                if len(text) > 4000:
                    raise ProtocolError(f"{key} is too long")
                result[key] = text
        return result

    @staticmethod
    def _validate_description(value) -> list[str]:
        if not isinstance(value, list) or len(value) > 256:
            raise ProtocolError("description must be an array with at most 256 strings")
        result = []
        for item in value:
            if not isinstance(item, str) or len(item) > 4000:
                raise ProtocolError("description entries must be strings up to 4000 characters")
            result.append(item)
        return result
