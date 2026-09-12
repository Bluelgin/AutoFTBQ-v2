"""Atomic filesystem persistence used by the FTB Quests store."""

from __future__ import annotations

from datetime import datetime
from copy import deepcopy
import json
import os
import shutil
import tempfile

from snbt_parser import to_snbt

from .quest_objects import sync_task


def write_json_atomic(path: str, payload: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


class AtomicBookWriter:
    """Install a set of SNBT payloads with backup and rollback protection."""

    def write(
        self,
        root: str,
        payloads: dict[str, str],
        *,
        deletions=(),
        stage_prefix: str = ".autoftbq-stage-",
    ) -> dict:
        root = os.path.abspath(root)
        os.makedirs(root, exist_ok=True)
        deletion_targets = {os.path.abspath(path) for path in deletions}
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_root = os.path.join(root, ".autoftbq-backups", stamp)
        stage_root = tempfile.mkdtemp(prefix=stage_prefix, dir=root)
        staged: dict[str, str] = {}
        installed: list[str] = []
        existed: set[str] = set()
        try:
            for index, (target, content) in enumerate(payloads.items()):
                temporary = os.path.join(stage_root, f"{index}.snbt")
                with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
                staged[os.path.abspath(target)] = temporary

            for target in set(staged) | deletion_targets:
                if os.path.isfile(target):
                    existed.add(target)
                    backup = os.path.join(backup_root, os.path.relpath(target, root))
                    os.makedirs(os.path.dirname(backup), exist_ok=True)
                    shutil.copy2(target, backup)

            for target, temporary in staged.items():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(temporary, target)
                installed.append(target)
            for target in deletion_targets:
                if os.path.isfile(target):
                    os.remove(target)
                installed.append(target)
        except Exception:
            for target in reversed(installed):
                backup = os.path.join(backup_root, os.path.relpath(target, root))
                if os.path.isfile(backup):
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copy2(backup, target)
                elif target not in existed and os.path.isfile(target):
                    os.remove(target)
            raise
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)
        return {
            "saved": len(installed),
            "backup": backup_root if os.path.isdir(backup_root) else "",
        }


class FTBCompoundSynchronizer:
    """Merge editable chapter/quest models back into untouched raw compounds."""

    def __init__(self, store, new_id) -> None:
        self.store = store
        self.new_id = new_id

    def quest(self, quest) -> dict:
        raw = deepcopy(self.store.raw_quests.get(quest.id, {}))
        raw["id"] = quest.id
        raw["title"] = quest.title
        if quest.subtitle or "subtitle" in raw:
            raw["subtitle"] = quest.subtitle
        if quest.icon or "icon" in raw:
            if isinstance(raw.get("icon"), dict):
                raw["icon"]["id"] = quest.icon
            else:
                raw["icon"] = quest.icon
        raw["x"] = float(quest.x)
        raw["y"] = float(quest.y)
        if quest.shape:
            raw["shape"] = quest.shape
        else:
            raw.pop("shape", None)
        if quest.dependencies or "dependencies" in raw:
            raw["dependencies"] = list(quest.dependencies)
        old_tasks = raw.get("tasks", []) if isinstance(raw.get("tasks"), list) else []
        raw["tasks"] = [
            sync_task(
                task,
                old_tasks[index] if index < len(old_tasks) else {},
                self.new_id,
            )
            for index, task in enumerate(quest.tasks)
        ]
        raw["rewards"] = deepcopy(quest.rewards)
        if quest.description or "description" in raw:
            raw["description"] = list(quest.description)
        self.store.raw_quests[quest.id] = raw
        return raw

    def chapter(self, chapter) -> dict:
        raw = deepcopy(self.store.raw_chapters.get(chapter.id, {}))
        raw["id"] = chapter.id
        raw.setdefault("filename", chapter.id)
        raw["title"] = chapter.title
        if isinstance(raw.get("icon"), dict):
            raw["icon"]["id"] = chapter.icon
        else:
            raw["icon"] = chapter.icon
        raw["quests"] = [self.quest(quest) for quest in chapter.quests]
        self.store.raw_chapters[chapter.id] = raw
        return raw


class FTBStorePersistence:
    """Build and atomically install real-book and workspace payloads."""

    def __init__(self, store, synchronizer: FTBCompoundSynchronizer) -> None:
        self.store = store
        self.synchronizer = synchronizer
        self.writer = AtomicBookWriter()

    def save_all(self) -> dict:
        store = self.store
        if not store.dirty_chapters and not store.dirty_documents and not store.deleted_documents:
            return {"saved": 0, "backup": ""}
        payloads: dict[str, str] = {}
        os.makedirs(os.path.join(store.quest_root, "chapters"), exist_ok=True)
        for chapter_id in list(store.dirty_chapters):
            chapter = store.chapter(chapter_id)
            if chapter is not None:
                payloads[store.chapter_files[chapter_id]] = (
                    to_snbt(self.synchronizer.chapter(chapter)) + "\n"
                )
        for relative in store.dirty_documents:
            payloads[os.path.join(store.quest_root, relative)] = (
                to_snbt(store.raw_documents[relative]) + "\n"
            )
        deletions = {
            os.path.join(store.quest_root, relative)
            for relative in store.deleted_documents
        }
        result = self.writer.write(store.quest_root, payloads, deletions=deletions)
        store.dirty_chapters.clear()
        store.dirty_documents.clear()
        store.deleted_documents.clear()
        return result

    def export_directory(self, output_root: str) -> dict:
        store = self.store
        root = os.path.abspath(output_root)
        os.makedirs(root, exist_ok=True)
        payloads: dict[str, str] = {}
        for chapter in store.project.chapters:
            raw = self.synchronizer.chapter(chapter)
            filename = str(raw.get("filename") or chapter.id)
            payloads[os.path.join(root, "chapters", f"{filename}.snbt")] = to_snbt(raw) + "\n"
        for relative, raw in store.raw_documents.items():
            if relative not in store.deleted_documents:
                payloads[os.path.join(root, relative)] = to_snbt(raw) + "\n"
        result = self.writer.write(root, payloads, stage_prefix=".autoftbq-export-")
        return {**result, "root": root}

    def project_payload(self) -> dict:
        store = self.store
        chapters = [
            deepcopy(self.synchronizer.chapter(chapter))
            for chapter in store.project.chapters
        ]
        return {
            "format": "autoftbq-v2",
            "format_version": 2,
            "project": {
                "title": store.project.title,
                "mod_folder": store.project.mod_folder,
            },
            "documents": deepcopy(store.raw_documents),
            "chapters": chapters,
        }

    def save_workspace(self, path: str) -> None:
        store = self.store
        payload = self.project_payload()
        payload["workspace_source"] = {
            "is_real": bool(store.is_real),
            "quest_root": store.quest_root,
            "chapter_files": dict(store.chapter_files),
            "dirty_chapters": sorted(store.dirty_chapters),
            "dirty_documents": sorted(store.dirty_documents),
            "deleted_documents": sorted(store.deleted_documents),
        }
        write_json_atomic(path, payload)

    def save(self, path: str = "") -> None:
        if self.store.is_real:
            self.save_all()
            return
        if not path:
            raise ValueError("请指定 v2 项目文件")
        write_json_atomic(path, self.project_payload())
