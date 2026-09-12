"""Loopback-only HTTP transport for the AutoFTBQ game bridge."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlparse

from .protocol import ProtocolError
from .service import BridgeService
from ..infrastructure.app_logging import LOGGER_NAME


MAX_BODY_BYTES = 18 * 1024 * 1024
LOGGER = logging.getLogger(LOGGER_NAME)


def default_discovery_path() -> Path:
    return Path.home() / ".autoftbq" / "bridge.json"


class _BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, service: BridgeService, token: str):
        super().__init__(address, handler)
        self.service = service
        self.token = token


class _Handler(BaseHTTPRequestHandler):
    server: _BridgeHTTPServer

    def log_message(self, _format, *_args) -> None:
        return

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.token}"
        return secrets.compare_digest(supplied, expected)

    def _payload(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ProtocolError("invalid Content-Length") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ProtocolError("request body size is invalid")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("request body must be UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ProtocolError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path)
        if path.path == "/v1/health":
            self._reply(200, self.server.service.health())
            return
        if not self._authorized():
            self._reply(401, {"error": "unauthorized"})
            return
        if path.path == "/v1/context":
            session_id = parse_qs(path.query).get("session_id", [""])[0]
            context = self.server.service.context(session_id)
            self._reply(200 if context is not None else 404, context or {"error": "context_not_found"})
            return
        if path.path == "/v1/requests":
            query = parse_qs(path.query)
            session_id = query.get("session_id", [""])[0]
            try:
                limit = int(query.get("limit", ["20"])[0])
            except ValueError:
                limit = 20
            self._reply(200, {"requests": self.server.service.requests.list_public(
                session_id, limit,
            )})
            return
        if path.path == "/v1/events":
            query = parse_qs(path.query)
            session_id = query.get("session_id", [""])[0]
            try:
                after = int(query.get("after", ["0"])[0])
                limit = int(query.get("limit", ["200"])[0])
                events = self.server.service.events(session_id, after, limit)
            except (ValueError, ProtocolError) as exc:
                self._reply(400, {"error": "invalid_request", "message": str(exc)})
                return
            self._reply(200, {"events": events})
            return
        if path.path == "/v1/project/snapshot":
            session_id = parse_qs(path.query).get("session_id", [""])[0]
            snapshot = self.server.service.book_snapshot(session_id)
            self._reply(200 if snapshot else 404,
                        snapshot or {"error": "snapshot_not_found"})
            return
        if path.path.startswith("/v1/requests/"):
            request_id = path.path.removeprefix("/v1/requests/").strip("/")
            result = self.server.service.requests.public(request_id)
            self._reply(200 if result else 404, result or {"error": "request_not_found"})
            return
        if path.path.startswith("/v1/proposals/"):
            proposal_id = path.path.removeprefix("/v1/proposals/").strip("/")
            result = self.server.service.requests.public_proposal(proposal_id)
            self._reply(200 if result else 404, result or {"error": "proposal_not_found"})
            return
        if path.path == "/v1/game-queries/next":
            session_id = parse_qs(path.query).get("session_id", [""])[0]
            result = self.server.service.requests.take_game_query(session_id)
            self._reply(200, {"query": result})
            return
        if path.path == "/v1/studio-transactions/next":
            session_id = parse_qs(path.query).get("session_id", [""])[0]
            result = self.server.service.requests.take_studio_transaction(session_id)
            self._reply(200, {"transaction": result})
            return
        self._reply(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._reply(401, {"error": "unauthorized"})
            return
        try:
            payload = self._payload()
            path = urlparse(self.path).path
            if path == "/v1/handshake":
                result = self.server.service.handshake(payload)
            elif path == "/v1/context":
                result = self.server.service.update_context(payload)
            elif path == "/v1/requests":
                result = self.server.service.submit_request(payload)
            elif path == "/v1/project/snapshot":
                result = self.server.service.save_book_snapshot(payload)
            elif path == "/v1/studio-book/sync":
                result = self.server.service.queue_studio_book(payload)
            elif path.startswith("/v1/requests/") and path.rsplit("/", 1)[-1] in {"pause", "resume"}:
                request_id = path.removeprefix("/v1/requests/").rsplit("/", 1)[0]
                result = self.server.service.requests.set_paused(request_id, path.endswith("/pause"))
                if result is None:
                    self._reply(404, {"error": "request_not_found"})
                    return
            elif path.startswith("/v1/requests/") and path.endswith("/cancel"):
                request_id = path.removeprefix("/v1/requests/").removesuffix("/cancel").strip("/")
                result = self.server.service.requests.cancel(request_id)
                if result is None:
                    self._reply(404, {"error": "request_not_found"})
                    return
            elif path.startswith("/v1/proposals/") and (
                    path.endswith("/confirm") or path.endswith("/reject")):
                confirm = path.endswith("/confirm")
                suffix = "/confirm" if confirm else "/reject"
                proposal_id = path.removeprefix("/v1/proposals/").removesuffix(suffix).strip("/")
                result = self.server.service.decide_proposal(
                    proposal_id, payload, confirm=confirm,
                )
                if result is None:
                    self._reply(404, {"error": "proposal_not_found"})
                    return
            elif path.startswith("/v1/proposals/") and path.endswith("/application"):
                proposal_id = path.removeprefix("/v1/proposals/").removesuffix(
                    "/application").strip("/")
                result = self.server.service.record_proposal_application(
                    proposal_id, payload,
                )
                if result is None:
                    self._reply(404, {"error": "proposal_not_found"})
                    return
            elif path.startswith("/v1/game-queries/") and path.endswith("/result"):
                query_id = path.removeprefix("/v1/game-queries/").removesuffix("/result").strip("/")
                accepted = self.server.service.requests.resolve_game_query(
                    str(payload.get("session_id", "")), query_id,
                    payload.get("result", {}),
                )
                if not accepted:
                    self._reply(404, {"error": "query_not_found"})
                    return
                result = {"accepted": True}
            else:
                self._reply(404, {"error": "not_found"})
                return
            self._reply(200, result)
        except ProtocolError as exc:
            LOGGER.warning("Bridge request rejected: path=%s reason=%s", self.path, exc)
            self._reply(400, {"error": "invalid_request", "message": str(exc)})
        except Exception:
            LOGGER.exception("Unhandled bridge request failure: path=%s", self.path)
            self._reply(500, {
                "error": "internal_error",
                "message": "Studio bridge internal error; see logs/autoftbq_v2.log",
            })


class StudioBridgeServer:
    def __init__(self, *, discovery_path: str | os.PathLike | None = None,
                 service: BridgeService | None = None) -> None:
        self.discovery_path = Path(discovery_path) if discovery_path else default_discovery_path()
        self.service = service or BridgeService()
        self.token = secrets.token_urlsafe(32)
        self._server: _BridgeHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_port) if self._server else 0

    def start(self) -> "StudioBridgeServer":
        if self._server is not None:
            return self
        server = _BridgeHTTPServer(("127.0.0.1", 0), _Handler, self.service, self.token)
        self._server = server
        self._write_discovery()
        self._thread = threading.Thread(
            target=server.serve_forever, name="AutoFTBQ-Bridge", daemon=True,
        )
        self._thread.start()
        LOGGER.info("Game bridge started on 127.0.0.1:%s", self.port)
        return self

    def _write_discovery(self) -> None:
        self.discovery_path.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "protocol_version": 1,
            "host": "127.0.0.1",
            "port": self.port,
            "token": self.token,
            "pid": os.getpid(),
        }
        temporary = self.discovery_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.discovery_path)
        try:
            os.chmod(self.discovery_path, 0o600)
        except OSError:
            pass

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        interrupted = self.service.requests.interrupt_all()
        if interrupted:
            LOGGER.info("Interrupted %s active game Agent request(s) during shutdown", interrupted)
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        try:
            current = json.loads(self.discovery_path.read_text(encoding="utf-8"))
            if secrets.compare_digest(str(current.get("token", "")), self.token):
                self.discovery_path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass
        LOGGER.info("Game bridge stopped")

    def __enter__(self) -> "StudioBridgeServer":
        return self.start()

    def __exit__(self, *_args) -> None:
        self.stop()
