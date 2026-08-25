"""Project file loading, saving, and export infrastructure."""

from __future__ import annotations

import json

from ai_module import import_json_to_snbt

from ..ftb_store import FTBQuestStore


class ProjectFileService:
    """Hide project format and filesystem details from the Qt window."""

    def load(self, path: str):
        return FTBQuestStore.load_project(path)

    def save(self, store, path: str = "") -> dict:
        if getattr(store, "is_real", False):
            result = dict(store.save_all())
            result["kind"] = "real"
            return result
        if not path:
            raise ValueError("保存草稿项目时必须提供文件路径")
        store.save(path)
        return {"kind": "draft", "path": path}

    def export(self, store, output_folder: str) -> dict:
        if hasattr(store, "export_directory"):
            result = dict(store.export_directory(output_folder))
            result["kind"] = "directory"
            return result
        output = import_json_to_snbt(
            json.dumps(store.project.to_ai_data(), ensure_ascii=False),
            mod_folder=store.project.mod_folder or None,
            output_dir=output_folder,
        )
        return {"kind": "legacy", "output": output}
