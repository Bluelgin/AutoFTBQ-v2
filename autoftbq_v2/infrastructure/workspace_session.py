"""Persistence boundary for recoverable v2 workspace drafts."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os

from ..ftb_store import FTBQuestStore


@dataclass(frozen=True)
class LoadedWorkspace:
    store: FTBQuestStore
    session: dict


class WorkspaceSessionRepository:
    """Atomically read and write workspace state without knowing about widgets."""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.project_path = os.path.join(self.workspace_dir, "draft.autoftbq.json")
        self.session_path = os.path.join(self.workspace_dir, "session.json")

    def exists(self) -> bool:
        return os.path.isfile(self.project_path) and os.path.isfile(self.session_path)

    def load(self) -> LoadedWorkspace | None:
        if not self.exists():
            return None
        with open(self.session_path, "r", encoding="utf-8") as handle:
            session = json.load(handle)
        if not isinstance(session, dict) or session.get("format") != "autoftbq-v2-session":
            raise ValueError("工作区会话格式无效")
        return LoadedWorkspace(
            store=FTBQuestStore.load_workspace(self.project_path),
            session=session,
        )

    def save(self, store: FTBQuestStore, session: dict) -> None:
        if not isinstance(session, dict) or session.get("format") != "autoftbq-v2-session":
            raise ValueError("工作区会话格式无效")
        os.makedirs(self.workspace_dir, exist_ok=True)
        store.save_workspace(self.project_path)
        temporary = self.session_path + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(session, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, self.session_path)
        finally:
            if os.path.isfile(temporary):
                try:
                    os.remove(temporary)
                except OSError:
                    pass
