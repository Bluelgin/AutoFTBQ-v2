"""Normalized application state stored alongside recoverable workspace drafts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WorkspaceState:
    project_path: str = ""
    last_modpack_folder: str = ""
    current_chapter_id: str = ""
    current_quest_id: str = ""
    chat: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    agent_history: list[dict] = field(default_factory=list)
    agent_run_state: dict = field(default_factory=dict)
    agent_request_context: dict = field(default_factory=dict)
    agent_queue: list[str] = field(default_factory=list)
    agent_chapter_ids: set[str] = field(default_factory=set)
    agent_quest_ids: set[str] = field(default_factory=set)
    prompt: str = ""
    view: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, session: dict, store) -> "WorkspaceState":
        session = session if isinstance(session, dict) else {}
        context = session.get("agent_context", {})
        context = context if isinstance(context, dict) else {}
        return cls(
            project_path=str(session.get("project_path") or ""),
            last_modpack_folder=str(
                session.get("last_modpack_folder") or store.project.mod_folder or "",
            ),
            current_chapter_id=str(session.get("current_chapter_id") or ""),
            current_quest_id=str(session.get("current_quest_id") or ""),
            chat=[
                {"role": str(value.get("role", "agent")), "text": str(value.get("text", ""))}
                for value in session.get("chat", [])
                if isinstance(value, dict)
            ][-300:],
            actions=[
                {"name": str(value.get("name", "")), "detail": str(value.get("detail", ""))}
                for value in session.get("actions", [])
                if isinstance(value, dict)
            ][-500:],
            agent_history=[
                {"role": str(value.get("role", "")), "content": str(value.get("content", ""))}
                for value in session.get("agent_history", [])
                if isinstance(value, dict) and value.get("role") in {"user", "assistant"}
            ][-20:],
            agent_run_state=(
                dict(session.get("agent_run_state", {}))
                if isinstance(session.get("agent_run_state"), dict) else {}
            ),
            agent_request_context=(
                dict(session.get("agent_request_context", {}))
                if isinstance(session.get("agent_request_context"), dict) else {}
            ),
            agent_queue=[
                str(value).strip()
                for value in session.get("agent_queue", [])
                if str(value).strip()
            ][-20:],
            agent_chapter_ids={str(value) for value in context.get("chapter_ids", [])},
            agent_quest_ids={str(value) for value in context.get("quest_ids", [])},
            prompt=str(session.get("prompt") or ""),
            view=dict(session.get("view", {})) if isinstance(session.get("view"), dict) else {},
        )

    def to_dict(self) -> dict:
        return {
            "format": "autoftbq-v2-session",
            "format_version": 1,
            "project_path": self.project_path,
            "last_modpack_folder": self.last_modpack_folder,
            "current_chapter_id": self.current_chapter_id,
            "current_quest_id": self.current_quest_id,
            "chat": self.chat[-300:],
            "actions": self.actions[-500:],
            "agent_history": self.agent_history[-20:],
            "agent_run_state": self.agent_run_state,
            "agent_request_context": self.agent_request_context,
            "agent_queue": self.agent_queue[-20:],
            "agent_context": {
                "chapter_ids": sorted(self.agent_chapter_ids),
                "quest_ids": sorted(self.agent_quest_ids),
            },
            "prompt": self.prompt,
            "view": dict(self.view),
        }
