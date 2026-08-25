"""Loss-minimizing editor store for real FTB Quests SNBT directories."""

from __future__ import annotations

from copy import deepcopy
import json
import os
import uuid

from .ftb.validation import validate_ftb_store
from .ftb.persistence import FTBCompoundSynchronizer, FTBStorePersistence, write_json_atomic
from .ftb.source import FTBBookSourceReader, locate_quest_root
from .ftb.documents import FTBDocumentEditor
from .ftb.canvas_objects import FTBCanvasObjectEditor
from .ftb.chapters import FTBChapterEditor
from .ftb.quests import FTBQuestEditor
from .ftb.quest_objects import (
    FTBQuestObjectEditor, refresh_quest_sections, sync_task, task_count, task_target,
)
from .ftb.translations import FTBTranslationEditor
from .ftb.schema import CURRENT_FILE_VERSION
from .project import Chapter, ProjectStore, Quest, QuestBookProject, Task


def new_ftb_id() -> str:
    return f"{uuid.uuid4().int & 0x7FFFFFFFFFFFFFFF:016X}"


def _document_key(relative_path: str) -> str:
    key = os.path.normpath(str(relative_path or ""))
    if not key or os.path.isabs(key) or key == ".." or key.startswith(".." + os.sep):
        raise ValueError("文档路径必须位于任务书目录中")
    return key


def _icon_id(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("id") or value.get("item") or "")
    return ""


class FTBQuestStore(ProjectStore):
    """ProjectStore facade backed by untouched real chapter compounds."""

    is_real = True

    def __init__(self, quest_root: str, project: QuestBookProject, source_backed: bool = True):
        super().__init__(project)
        self.is_real = bool(source_backed)
        self.quest_root = os.path.abspath(quest_root) if quest_root else ""
        self.raw_chapters: dict[str, dict] = {}
        self.raw_quests: dict[str, dict] = {}
        self.raw_documents: dict[str, dict] = {}
        self.chapter_files: dict[str, str] = {}
        self.dirty_chapters: set[str] = set()
        self.dirty_documents: set[str] = set()
        self.deleted_documents: set[str] = set()
        self.documents = FTBDocumentEditor(self, _document_key, new_ftb_id)
        self.canvas_objects = FTBCanvasObjectEditor(self, new_ftb_id)
        self.chapters = FTBChapterEditor(self, new_ftb_id, _document_key)
        self.quest_editor = FTBQuestEditor(self, new_ftb_id)
        self.compound_sync = FTBCompoundSynchronizer(self, new_ftb_id)
        self.persistence = FTBStorePersistence(self, self.compound_sync)
        self.quest_objects = FTBQuestObjectEditor(self, new_ftb_id)
        self.translations = FTBTranslationEditor(self, self._translation_path)
        self._undo = []
        self._redo = []

    @classmethod
    def create_new(cls, title: str = "新的整合包任务书", with_starter: bool = True) -> "FTBQuestStore":
        store = cls("", QuestBookProject(title=title), source_backed=False)
        store.raw_documents[os.path.normpath("data.snbt")] = {"version": CURRENT_FILE_VERSION}
        store.raw_documents[os.path.normpath("chapter_groups.snbt")] = {"chapter_groups": []}
        if with_starter:
            chapter = store.create_chapter("开始规划", "minecraft:writable_book")
            store.add_quest(
                chapter.id,
                "告诉 Agent 你的目标",
                "在右侧描述整合包玩法，Agent 会通过工具逐步编辑这里。",
                "checkmark",
            )
        store._undo.clear()
        store._redo.clear()
        store.dirty_chapters.clear()
        store.dirty_documents.clear()
        return store

    @classmethod
    def from_project(cls, project: QuestBookProject) -> "FTBQuestStore":
        """Upgrade the old lightweight v2 project without retaining invalid legacy IDs."""
        store = cls.create_new(project.title, with_starter=False)
        store.project.mod_folder = project.mod_folder
        chapter_ids: dict[str, str] = {}
        quest_ids: dict[str, str] = {}
        pending_dependencies: list[tuple[str, list[str]]] = []
        for old_chapter in project.chapters:
            chapter = store.create_chapter(old_chapter.title, old_chapter.icon)
            chapter_ids[old_chapter.id] = chapter.id
            for old_quest in old_chapter.quests:
                first = old_quest.tasks[0] if old_quest.tasks else Task()
                quest = store.add_quest(
                    chapter.id, old_quest.title, "\n".join(old_quest.description),
                    first.type, first.target, first.count,
                )
                quest.subtitle = old_quest.subtitle
                quest.icon = old_quest.icon
                quest.shape = old_quest.shape
                quest.x = old_quest.x
                quest.y = old_quest.y
                quest.tasks = deepcopy(old_quest.tasks) or [Task()]
                quest.rewards = []
                for reward in old_quest.rewards:
                    value = deepcopy(reward) if isinstance(reward, dict) else {"type": "item", "item": reward}
                    value.setdefault("id", new_ftb_id())
                    value.setdefault("type", "item")
                    quest.rewards.append(value)
                quest_ids[old_quest.id] = quest.id
                pending_dependencies.append((quest.id, list(old_quest.dependencies)))
                store._sync_quest(quest)
        for quest_id, dependencies in pending_dependencies:
            found = store.quest(quest_id)
            if found:
                found[1].dependencies = [quest_ids[value] for value in dependencies if value in quest_ids]
        for chapter in store.project.chapters:
            store._sync_chapter(chapter)
        store._undo.clear()
        store._redo.clear()
        store.dirty_chapters.clear()
        store.dirty_documents.clear()
        return store

    @classmethod
    def load_project(cls, path: str) -> "FTBQuestStore":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls._from_project_payload(payload)

    @classmethod
    def _from_project_payload(cls, payload: dict) -> "FTBQuestStore":
        if not isinstance(payload, dict) or payload.get("format") != "autoftbq-v2":
            return cls.from_project(QuestBookProject.from_dict(payload))
        metadata = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
        project = QuestBookProject(
            title=str(metadata.get("title") or "未命名任务书"),
            mod_folder=str(metadata.get("mod_folder") or ""),
            format_version=2,
        )
        store = cls("", project, source_backed=False)
        documents = payload.get("documents", {})
        if isinstance(documents, dict):
            store.raw_documents = {
                os.path.normpath(str(key)): deepcopy(value)
                for key, value in documents.items() if isinstance(value, dict)
            }
        chapters = payload.get("chapters", [])
        for index, raw in enumerate(chapters if isinstance(chapters, list) else []):
            if not isinstance(raw, dict):
                continue
            chapter = store._chapter_from_raw(raw, f"chapter_{index}.snbt")
            project.chapters.append(chapter)
            store.raw_chapters[chapter.id] = deepcopy(raw)
            for raw_quest in raw.get("quests", []) if isinstance(raw.get("quests"), list) else []:
                if isinstance(raw_quest, dict) and raw_quest.get("id"):
                    store.raw_quests[str(raw_quest["id"])] = raw_quest
        store.load_errors = []
        return store

    @classmethod
    def load_workspace(cls, path: str) -> "FTBQuestStore":
        """Restore an editor snapshot without writing anything to its source pack."""
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        store = cls._from_project_payload(payload)
        source = payload.get("workspace_source", {}) if isinstance(payload, dict) else {}
        if isinstance(source, dict) and source.get("is_real") and source.get("quest_root"):
            store.is_real = True
            store.quest_root = os.path.abspath(str(source["quest_root"]))
            store.chapter_files = {
                str(key): os.path.abspath(str(value))
                for key, value in source.get("chapter_files", {}).items()
                if value
            }
            store.dirty_chapters = set(source.get("dirty_chapters", []))
            store.dirty_documents = {os.path.normpath(str(value)) for value in source.get("dirty_documents", [])}
            store.deleted_documents = {os.path.normpath(str(value)) for value in source.get("deleted_documents", [])}
        store._undo.clear()
        store._redo.clear()
        return store

    @classmethod
    def load_directory(cls, quest_root: str, mod_folder: str = "") -> "FTBQuestStore":
        source = FTBBookSourceReader().read(quest_root)
        project = QuestBookProject(
            title=os.path.basename(os.path.abspath(mod_folder or quest_root)) or "FTB Quests",
            mod_folder=os.path.abspath(mod_folder or quest_root),
        )
        store = cls(quest_root, project)
        store.raw_documents = source.documents
        for filename, path, raw in source.chapters:
            chapter = store._chapter_from_raw(raw, filename)
            project.chapters.append(chapter)
            store.raw_chapters[chapter.id] = raw
            store.chapter_files[chapter.id] = path
            for raw_quest in raw.get("quests", []):
                if isinstance(raw_quest, dict) and raw_quest.get("id"):
                    store.raw_quests[str(raw_quest["id"])] = raw_quest
        store.load_errors = source.errors
        return store

    @staticmethod
    def _chapter_from_raw(raw: dict, filename: str) -> Chapter:
        chapter_id = str(raw.get("id") or raw.get("filename") or os.path.splitext(filename)[0])
        quests = []
        for raw_quest in raw.get("quests", []) if isinstance(raw.get("quests"), list) else []:
            if not isinstance(raw_quest, dict):
                continue
            tasks = []
            for raw_task in raw_quest.get("tasks", []) if isinstance(raw_quest.get("tasks"), list) else []:
                if isinstance(raw_task, dict):
                    tasks.append(Task(
                        type=str(raw_task.get("type") or "checkmark"),
                        target=task_target(raw_task),
                        count=task_count(raw_task),
                    ))
            quests.append(Quest(
                id=str(raw_quest.get("id") or new_ftb_id()),
                title=str(raw_quest.get("title") or "未命名任务"),
                subtitle=str(raw_quest.get("subtitle") or ""),
                icon=_icon_id(raw_quest.get("icon")),
                description=[str(line) for line in raw_quest.get("description", [])]
                if isinstance(raw_quest.get("description"), list) else [],
                tasks=tasks or [Task()],
                rewards=deepcopy(raw_quest.get("rewards", []))
                if isinstance(raw_quest.get("rewards"), list) else [],
                dependencies=[str(value) for value in raw_quest.get("dependencies", [])],
                x=float(raw_quest.get("x", 0) or 0),
                y=float(raw_quest.get("y", 0) or 0),
                shape=str(raw_quest.get("shape", "")),
            ))
        return Chapter(
            id=chapter_id,
            title=str(raw.get("title") or raw.get("filename") or os.path.splitext(filename)[0]),
            icon=_icon_id(raw.get("icon")) or "minecraft:book",
            quests=quests,
        )

    def _snapshot(self):
        return (
            deepcopy(self.project),
            deepcopy(self.raw_chapters),
            deepcopy(self.raw_quests),
            deepcopy(self.raw_documents),
            dict(self.chapter_files),
            set(self.dirty_chapters),
            set(self.dirty_documents),
            set(self.deleted_documents),
        )

    def _restore(self, snapshot) -> None:
        (
            self.project,
            self.raw_chapters,
            self.raw_quests,
            self.raw_documents,
            self.chapter_files,
            self.dirty_chapters,
            self.dirty_documents,
            self.deleted_documents,
        ) = deepcopy(snapshot)

    def capture_state(self):
        """Include raw SNBT state and command history in Agent transactions."""
        return self._snapshot(), deepcopy(self._undo), deepcopy(self._redo)

    def capture_checkpoint_state(self):
        """Capture content plus history positions for bounded Agent checkpoints."""
        return self._snapshot(), len(self._undo), deepcopy(self._redo)

    def restore_checkpoint_state(self, snapshot) -> None:
        raw_state, undo_length, redo = snapshot
        self._restore(raw_state)
        self._undo = self._undo[: int(undo_length)]
        self._redo = deepcopy(redo)

    def restore_state(self, snapshot) -> None:
        raw_state, undo, redo = snapshot
        self._restore(raw_state)
        self._undo = deepcopy(undo)
        self._redo = deepcopy(redo)

    def _checkpoint(self) -> None:
        self._undo.append(self._snapshot())
        self._undo = self._undo[-100:]
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        return True

    def _mark_quest(self, quest_id: str) -> None:
        found = self.quest(quest_id)
        if found:
            self.dirty_chapters.add(found[0].id)

    def create_chapter(self, title: str, icon: str = "minecraft:book") -> Chapter:
        return self.chapters.create(title, icon)

    def remove_chapter(self, chapter_id: str) -> bool:
        return self.chapters.remove(chapter_id)

    def move_chapter(self, chapter_id: str, new_index: int) -> list[Chapter]:
        return self.chapters.move(chapter_id, new_index)

    def add_quest(self, chapter_id: str, title: str, description: str = "", task_type: str = "checkmark", target: str = "", count: int = 1) -> Quest:
        return self.quest_editor.add(
            chapter_id, title, description, task_type, target, count,
        )

    def update_quest(self, quest_id: str, **changes) -> Quest:
        return self.quest_editor.update(quest_id, **changes)

    def move_quest(self, quest_id: str, x: float, y: float) -> Quest:
        return self.quest_editor.move(quest_id, x, y)

    def move_quest_to_chapter(self, quest_id: str, chapter_id: str, x: float | None = None, y: float | None = None) -> Quest:
        return self.quest_editor.move_to_chapter(quest_id, chapter_id, x, y)

    def copy_quest(
        self, quest_id: str, chapter_id: str, x: float, y: float, with_dependencies: bool = True,
    ) -> Quest:
        return self.quest_editor.copy(
            quest_id, chapter_id, x, y, with_dependencies,
        )

    def copy_chapter_object(self, source_chapter_id: str, kind: str, object_id: str, target_chapter_id: str, x: float, y: float) -> dict:
        return self.canvas_objects.copy(
            source_chapter_id, kind, object_id, target_chapter_id, x, y,
        )

    def _copy_translation_ids(self, id_map: dict[str, str]) -> None:
        additions = []
        prefix = os.path.normpath("lang") + os.sep
        for path, raw in self.raw_documents.items():
            if not path.startswith(prefix):
                continue
            locale = path[len(prefix):].split(os.sep, 1)[0]
            for key, value in raw.items():
                parts = str(key).split(".", 2)
                if len(parts) == 3 and parts[1] in id_map:
                    target_path = self._translation_path(locale, parts[0], id_map[parts[1]])
                    additions.append((target_path, f"{parts[0]}.{id_map[parts[1]]}.{parts[2]}", deepcopy(value)))
        for path, key, value in additions:
            self.raw_documents.setdefault(path, {})[key] = value
            self.dirty_documents.add(path)

    def connect(self, quest_id: str, dependency_id: str) -> Quest:
        return self.quest_editor.connect(quest_id, dependency_id)

    def disconnect(self, quest_id: str, dependency_id: str) -> Quest:
        return self.quest_editor.disconnect(quest_id, dependency_id)

    def remove_quest(self, quest_id: str) -> bool:
        return self.quest_editor.remove(quest_id)

    def remove_canvas_objects(self, chapter_id: str, references: list[tuple[str, str]]) -> int:
        return self.canvas_objects.remove_many(chapter_id, references)

    def replace_quest_sections(self, quest_id: str, tasks, rewards) -> Quest:
        return self.quest_editor.replace_sections(quest_id, tasks, rewards)

    def raw_sections(self, quest_id: str) -> tuple[list, list]:
        raw = self.raw_quests.get(quest_id, {})
        return deepcopy(raw.get("tasks", [])), deepcopy(raw.get("rewards", []))

    def quest_data(self, quest_id: str) -> dict:
        if quest_id not in self.raw_quests:
            raise ValueError(f"找不到任务：{quest_id}")
        return deepcopy(self.raw_quests[quest_id])

    def chapter_data(self, chapter_id: str) -> dict:
        if chapter_id not in self.raw_chapters:
            raise ValueError(f"找不到章节：{chapter_id}")
        return deepcopy(self.raw_chapters[chapter_id])

    def update_quest_fields(self, quest_id: str, changes: dict) -> dict:
        """Patch official quest properties without replacing child collections."""
        if not isinstance(changes, dict):
            raise ValueError("任务修改必须是 compound")
        forbidden = {"id", "tasks", "rewards"}
        if forbidden.intersection(changes):
            raise ValueError("任务 ID、条件和奖励必须使用对应的专用命令修改")
        found = self.quest(quest_id)
        if found is None:
            raise ValueError(f"找不到任务：{quest_id}")
        self._checkpoint()
        raw = self.raw_quests.setdefault(quest_id, {})
        for field, value in changes.items():
            if value is None:
                raw.pop(str(field), None)
            else:
                raw[str(field)] = deepcopy(value)
        quest = found[1]
        quest.title = str(raw.get("title") or quest.title)
        quest.subtitle = str(raw.get("subtitle") or "")
        quest.icon = _icon_id(raw.get("icon"))
        description = raw.get("description", [])
        quest.description = [str(line) for line in description] if isinstance(description, list) else [str(description)]
        quest.x = float(raw.get("x", quest.x) or 0)
        quest.y = float(raw.get("y", quest.y) or 0)
        quest.shape = str(raw.get("shape", ""))
        dependencies = raw.get("dependencies", [])
        quest.dependencies = [str(value) for value in dependencies] if isinstance(dependencies, list) else []
        self.dirty_chapters.add(found[0].id)
        return deepcopy(raw)

    def update_chapter_fields(self, chapter_id: str, changes: dict) -> dict:
        """Patch official chapter properties without replacing quests or canvas objects."""
        if not isinstance(changes, dict):
            raise ValueError("章节修改必须是 compound")
        forbidden = {"id", "quests", "quest_links", "images"}
        if forbidden.intersection(changes):
            raise ValueError("章节 ID、任务、链接和图片必须使用对应的专用命令修改")
        chapter = self.chapter(chapter_id)
        if chapter is None:
            raise ValueError(f"找不到章节：{chapter_id}")
        self._checkpoint()
        raw = self.raw_chapters.setdefault(chapter_id, {})
        for field, value in changes.items():
            if value is None:
                raw.pop(str(field), None)
            else:
                raw[str(field)] = deepcopy(value)
        chapter.title = str(raw.get("title") or chapter.title)
        chapter.icon = _icon_id(raw.get("icon")) or chapter.icon
        self.dirty_chapters.add(chapter_id)
        return deepcopy(raw)

    def add_chapter_object(self, chapter_id: str, kind: str, values: dict) -> dict:
        return self.canvas_objects.add(chapter_id, kind, values)

    def update_chapter_object(self, chapter_id: str, kind: str, object_id: str, changes: dict) -> dict:
        return self.canvas_objects.update(chapter_id, kind, object_id, changes)

    def remove_chapter_object(self, chapter_id: str, kind: str, object_id: str) -> bool:
        return self.canvas_objects.remove(chapter_id, kind, object_id)

    def document(self, relative_path: str) -> dict:
        """Return an editable supporting document without exposing store state."""
        return self.documents.document(relative_path)

    def list_locales(self) -> list[str]:
        return self.translations.locales()

    def translation_entries(self, locale: str) -> dict:
        return self.translations.entries(locale)

    def _translation_path(self, locale: str, object_type: str, object_id: str) -> str:
        chapter = None
        if object_type == "quest":
            found = self.quest(object_id)
            chapter = found[0] if found else None
        elif object_type in {"task", "quest_link"}:
            for candidate in self.project.chapters:
                raw = self.raw_chapters.get(candidate.id, {})
                if object_type == "quest_link":
                    values = raw.get("quest_links", [])
                else:
                    values = [
                        child
                        for quest in raw.get("quests", []) if isinstance(quest, dict)
                        for child in quest.get("tasks", []) if isinstance(child, dict)
                    ]
                if any(str(value.get("id") or "") == object_id for value in values if isinstance(value, dict)):
                    chapter = candidate
                    break
        if chapter is not None:
            filename = os.path.basename(self.chapter_files.get(chapter.id, f"{chapter.id}.snbt"))
            return _document_key(os.path.join("lang", locale, "chapters", filename))
        split_name = {
            "chapter": "chapter", "reward": "reward", "reward_table": "reward_table",
            "chapter_group": "chapter_group", "image": "image",
        }.get(object_type, object_type)
        return _document_key(os.path.join("lang", locale, f"{split_name}.snbt"))

    def update_translation(self, locale: str, object_type: str, object_id: str, field: str, value) -> dict:
        return self.translations.update(locale, object_type, object_id, field, value)

    def _remove_translation_ids(self, object_ids: set[str]) -> None:
        self.translations.remove_object_ids(object_ids)

    def update_document(self, relative_path: str, changes: dict) -> dict:
        """Patch a book/group/reward-table compound while preserving unknown keys."""
        return self.documents.update(relative_path, changes)

    def replace_document(self, relative_path: str, value: dict) -> dict:
        return self.documents.replace(relative_path, value)

    def remove_document(self, relative_path: str) -> bool:
        return self.documents.remove(relative_path)

    def document_objects(self, relative_path: str, section: str) -> list[dict]:
        return self.documents.objects(relative_path, section)

    def add_document_object(self, relative_path: str, section: str, values: dict) -> dict:
        return self.documents.add_object(relative_path, section, values)

    def update_document_object(self, relative_path: str, section: str, object_id: str, changes: dict) -> dict:
        return self.documents.update_object(relative_path, section, object_id, changes)

    def remove_document_object(self, relative_path: str, section: str, object_id: str) -> bool:
        return self.documents.remove_object(relative_path, section, object_id)

    def move_document_object(self, relative_path: str, section: str, object_id: str, new_index: int) -> list[dict]:
        return self.documents.move_object(relative_path, section, object_id, new_index)

    def create_reward_table(self, title: str = "新奖励表") -> dict:
        table_id = new_ftb_id()
        relative = os.path.join("reward_tables", f"{table_id}.snbt")
        value = {"id": table_id, "title": str(title or "新奖励表"), "rewards": []}
        self.replace_document(relative, value)
        return {"path": relative, "data": deepcopy(value)}

    def create_chapter_group(self, title: str = "新章节分组") -> dict:
        return self.add_document_object(
            "chapter_groups.snbt", "chapter_groups", {"title": str(title or "新章节分组")},
        )

    def remove_chapter_group(self, group_id: str) -> bool:
        key = _document_key("chapter_groups.snbt")
        groups = self.raw_documents.get(key, {}).get("chapter_groups", [])
        index = next((i for i, group in enumerate(groups) if isinstance(group, dict) and str(group.get("id")) == str(group_id)), -1)
        if index < 0:
            return False
        self._checkpoint()
        groups.pop(index)
        self.dirty_documents.add(key)
        for chapter_id, raw in self.raw_chapters.items():
            if str(raw.get("group") or "") == str(group_id):
                raw["group"] = ""
                self.dirty_chapters.add(chapter_id)
        return True

    def list_reward_tables(self) -> list[dict]:
        tables = []
        prefix = "reward_tables" + os.sep
        for relative, raw in sorted(self.raw_documents.items()):
            if relative.startswith(prefix):
                tables.append({"path": relative, "data": deepcopy(raw)})
        return tables

    def add_quest_object(self, quest_id: str, kind: str, type_id: str, values: dict | None = None) -> dict:
        return self.quest_objects.add(quest_id, kind, type_id, values)

    def update_quest_object(self, quest_id: str, kind: str, object_id: str, changes: dict) -> dict:
        return self.quest_objects.update(quest_id, kind, object_id, changes)

    def remove_quest_object(self, quest_id: str, kind: str, object_id: str) -> bool:
        return self.quest_objects.remove(quest_id, kind, object_id)

    def move_quest_object(self, quest_id: str, kind: str, object_id: str, new_index: int) -> list[dict]:
        return self.quest_objects.move(quest_id, kind, object_id, new_index)

    @staticmethod
    def _refresh_quest_sections(quest: Quest, raw: dict) -> None:
        refresh_quest_sections(quest, raw)

    def _sync_task(self, task: Task, raw: dict) -> dict:
        return sync_task(task, raw, new_ftb_id)

    def _sync_quest(self, quest: Quest) -> dict:
        return self.compound_sync.quest(quest)

    def _sync_chapter(self, chapter: Chapter) -> dict:
        return self.compound_sync.chapter(chapter)

    def save_all(self) -> dict:
        return self.persistence.save_all()

    def export_directory(self, output_root: str) -> dict:
        """Write a complete standalone FTB Quests book without rebinding this project."""
        return self.persistence.export_directory(output_root)

    def _project_payload(self) -> dict:
        return self.persistence.project_payload()

    @staticmethod
    def _write_json_atomic(path: str, payload: dict) -> None:
        write_json_atomic(path, payload)

    def save_workspace(self, path: str) -> None:
        self.persistence.save_workspace(path)

    def save(self, path: str = "") -> None:
        self.persistence.save(path)

    def summary(self) -> dict:
        result = super().summary()
        data = self.raw_documents.get(os.path.normpath("data.snbt"), {})
        result.update({
            "source": "ftbquests_snbt" if self.is_real else "autoftbq_v2_project",
            "file_version": data.get("version"),
            "supporting_documents": sorted(self.raw_documents),
            "reward_tables": len(self.list_reward_tables()),
            "load_errors": list(getattr(self, "load_errors", [])),
        })
        return result

    def validate(self, known_items: dict | None = None) -> list[dict]:
        # The base project model only knows same-chapter dependencies, while FTB
        # Quests permits references to objects in other chapters.
        basic = [
            issue for issue in super().validate(known_items)
            if not str(issue.get("message", "")).startswith("依赖不存在：")
        ]
        detailed = validate_ftb_store(self, known_items)
        seen = set()
        result = []
        for issue in basic + detailed:
            key = (issue.get("severity"), issue.get("location"), issue.get("message"))
            if key not in seen:
                seen.add(key)
                result.append(issue)
        return result
