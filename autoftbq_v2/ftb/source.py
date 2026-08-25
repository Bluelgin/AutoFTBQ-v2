"""Filesystem reader for real FTB Quests SNBT books."""

from __future__ import annotations

from dataclasses import dataclass, field
import os

from snbt_parser import parse_snbt


def locate_quest_root(pack_root: str) -> str:
    root = os.path.abspath(pack_root)
    candidates = [
        os.path.join(root, "config", "ftbquests", "quests"),
        os.path.join(root, "ftbquests", "quests"),
        root,
    ]
    for candidate in candidates:
        if os.path.isdir(os.path.join(candidate, "chapters")):
            return candidate
    return ""


@dataclass
class LoadedFTBSource:
    chapters: list[tuple[str, str, dict]] = field(default_factory=list)
    documents: dict[str, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class FTBBookSourceReader:
    def read(self, quest_root: str) -> LoadedFTBSource:
        root = os.path.abspath(quest_root)
        chapters_dir = os.path.join(root, "chapters")
        if not os.path.isdir(chapters_dir):
            raise ValueError("所选位置没有 config/ftbquests/quests/chapters")
        result = LoadedFTBSource()
        result.documents = self._read_documents(root, result.errors)
        for filename in sorted(os.listdir(chapters_dir)):
            if not filename.lower().endswith(".snbt"):
                continue
            path = os.path.join(chapters_dir, filename)
            raw = self._read_compound(path, filename, "章节根节点不是 compound", result.errors)
            if raw is not None:
                result.chapters.append((filename, path, raw))
        if not result.chapters and result.errors:
            raise ValueError("无法读取章节：" + "; ".join(result.errors[:3]))
        return result

    def _read_documents(self, root: str, errors: list[str]) -> dict[str, dict]:
        candidates = ["data.snbt", "chapter_groups.snbt"]
        reward_dir = os.path.join(root, "reward_tables")
        if os.path.isdir(reward_dir):
            candidates.extend(
                os.path.join("reward_tables", filename)
                for filename in sorted(os.listdir(reward_dir))
                if filename.lower().endswith(".snbt")
            )
        lang_dir = os.path.join(root, "lang")
        if os.path.isdir(lang_dir):
            for current, _dirs, files in os.walk(lang_dir):
                candidates.extend(
                    os.path.relpath(os.path.join(current, filename), root)
                    for filename in sorted(files)
                    if filename.lower().endswith(".snbt")
                )
        documents = {}
        for relative in candidates:
            path = os.path.join(root, relative)
            if not os.path.isfile(path):
                continue
            raw = self._read_compound(path, relative, "根节点不是 compound", errors)
            if raw is not None:
                documents[os.path.normpath(relative)] = raw
        return documents

    @staticmethod
    def _read_compound(path: str, label: str, type_error: str, errors: list[str]):
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                raw = parse_snbt(handle.read())
            if not isinstance(raw, dict):
                raise ValueError(type_error)
            return raw
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            return None
