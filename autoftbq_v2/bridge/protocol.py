"""Versioned, loader-neutral messages exchanged with the game mod."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PROTOCOL_VERSION = 1
MAX_SELECTED_QUESTS = 256
MAX_SELECTED_CHAPTERS = 64
MAX_QUESTS_PER_SELECTED_CHAPTER = 4096
MAX_CAPABILITIES = 128


class ProtocolError(ValueError):
    """A bridge message is malformed or incompatible."""


def _text(value: Any, field: str, *, limit: int = 256, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{field} must be a string")
    result = value.strip()
    if required and not result:
        raise ProtocolError(f"{field} is required")
    if len(result) > limit:
        raise ProtocolError(f"{field} is too long")
    return result


def _mapping(value: Any, field: str) -> dict:
    if not isinstance(value, dict):
        raise ProtocolError(f"{field} must be an object")
    return value


@dataclass(frozen=True)
class LoaderInfo:
    name: str
    version: str

    @classmethod
    def parse(cls, value: Any) -> "LoaderInfo":
        raw = _mapping(value, "loader")
        return cls(_text(raw.get("name"), "loader.name", limit=40),
                   _text(raw.get("version"), "loader.version", limit=80))


@dataclass(frozen=True)
class Handshake:
    client_id: str
    minecraft_version: str
    loader: LoaderInfo
    ftb_quests_version: str
    mod_version: str
    capabilities: tuple[str, ...]

    @classmethod
    def parse(cls, value: Any) -> "Handshake":
        raw = _mapping(value, "handshake")
        version = raw.get("protocol_version")
        if version != PROTOCOL_VERSION:
            raise ProtocolError(
                f"unsupported protocol_version {version!r}; expected {PROTOCOL_VERSION}"
            )
        capabilities = raw.get("capabilities", [])
        if not isinstance(capabilities, list) or len(capabilities) > MAX_CAPABILITIES:
            raise ProtocolError("capabilities must be a bounded array")
        parsed_capabilities = tuple(
            dict.fromkeys(_text(item, "capability", limit=100) for item in capabilities)
        )
        return cls(
            client_id=_text(raw.get("client_id"), "client_id", limit=100),
            minecraft_version=_text(raw.get("minecraft_version"), "minecraft_version", limit=40),
            loader=LoaderInfo.parse(raw.get("loader")),
            ftb_quests_version=_text(raw.get("ftb_quests_version"), "ftb_quests_version", limit=80),
            mod_version=_text(raw.get("mod_version"), "mod_version", limit=80),
            capabilities=parsed_capabilities,
        )


@dataclass(frozen=True)
class QuestSelection:
    id: str
    title: str
    chapter_id: str
    x: float
    y: float

    @classmethod
    def parse(cls, value: Any) -> "QuestSelection":
        raw = _mapping(value, "selected_quest")
        try:
            x, y = float(raw.get("x", 0.0)), float(raw.get("y", 0.0))
        except (TypeError, ValueError) as exc:
            raise ProtocolError("quest coordinates must be numeric") from exc
        return cls(
            id=_text(raw.get("id"), "selected_quest.id", limit=32),
            title=_text(raw.get("title", ""), "selected_quest.title", limit=500, required=False),
            chapter_id=_text(
                raw.get("chapter_id", ""), "selected_quest.chapter_id",
                limit=32, required=False,
            ),
            x=x,
            y=y,
        )


@dataclass(frozen=True)
class ChapterSelection:
    id: str
    title: str
    quest_ids: tuple[str, ...]

    @classmethod
    def parse(cls, value: Any) -> "ChapterSelection":
        raw = _mapping(value, "selected_chapter")
        quest_ids = raw.get("quest_ids", [])
        if (not isinstance(quest_ids, list)
                or len(quest_ids) > MAX_QUESTS_PER_SELECTED_CHAPTER):
            raise ProtocolError("selected_chapter.quest_ids must be a bounded array")
        return cls(
            id=_text(raw.get("id"), "selected_chapter.id", limit=32),
            title=_text(
                raw.get("title", ""), "selected_chapter.title",
                limit=500, required=False,
            ),
            quest_ids=tuple(dict.fromkeys(
                _text(item, "selected_chapter.quest_id", limit=32)
                for item in quest_ids
            )),
        )


@dataclass(frozen=True)
class GameContext:
    session_id: str
    revision: int
    world_id: str
    chapter_id: str
    chapter_title: str
    selected_chapters: tuple[ChapterSelection, ...]
    selected_quests: tuple[QuestSelection, ...]
    book_summary: dict
    registry_summary: dict
    book_revision: str
    server_book_revision: str

    @classmethod
    def parse(cls, value: Any) -> "GameContext":
        raw = _mapping(value, "context")
        revision = raw.get("revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise ProtocolError("revision must be a non-negative integer")
        chapter = _mapping(raw.get("chapter", {}), "chapter")
        selected = raw.get("selected_quests", [])
        if not isinstance(selected, list) or len(selected) > MAX_SELECTED_QUESTS:
            raise ProtocolError("selected_quests must be a bounded array")
        selected_chapters = raw.get("selected_chapters", [])
        if (not isinstance(selected_chapters, list)
                or len(selected_chapters) > MAX_SELECTED_CHAPTERS):
            raise ProtocolError("selected_chapters must be a bounded array")
        return cls(
            session_id=_text(raw.get("session_id"), "session_id", limit=100),
            revision=revision,
            world_id=_text(raw.get("world_id", ""), "world_id", limit=200, required=False),
            chapter_id=_text(chapter.get("id", ""), "chapter.id", limit=32, required=False),
            chapter_title=_text(chapter.get("title", ""), "chapter.title", limit=500, required=False),
            selected_chapters=tuple(
                ChapterSelection.parse(item) for item in selected_chapters
            ),
            selected_quests=tuple(QuestSelection.parse(item) for item in selected),
            book_summary=_mapping(raw.get("book_summary", {}), "book_summary"),
            registry_summary=_mapping(raw.get("registry_summary", {}), "registry_summary"),
            book_revision=_text(
                raw.get("book_revision", ""), "book_revision", limit=128, required=False,
            ),
            server_book_revision=_text(
                raw.get("server_book_revision", ""), "server_book_revision",
                limit=128, required=False,
            ),
        )
