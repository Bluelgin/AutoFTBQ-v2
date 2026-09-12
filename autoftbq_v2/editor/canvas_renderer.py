"""Quest scene composition separated from the main editor window."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QGraphicsRectItem


@dataclass(frozen=True)
class CanvasRenderResult:
    chapter_title: str = ""
    quest_nodes: dict | None = None


class QuestCanvasRenderer:
    """Build graphics items from Store data without owning editor state."""

    def __init__(
        self,
        quest_node_factory,
        image_node_factory,
        link_node_factory,
        dependency_factory,
        curved_dependency_factory,
    ):
        self.quest_node_factory = quest_node_factory
        self.image_node_factory = image_node_factory
        self.link_node_factory = link_node_factory
        self.dependency_factory = dependency_factory
        self.curved_dependency_factory = curved_dependency_factory

    def render(
        self,
        scene,
        store,
        chapter_id: str,
        *,
        selected_quest_id: str = "",
        agent_quest_ids=(),
        asset_index=None,
        icon_loader=None,
        agent_busy: bool = False,
        on_quest_move=None,
        on_image_move=None,
        on_link_move=None,
        on_link_open=None,
    ) -> CanvasRenderResult:
        scene.clear()
        chapter = store.chapter(chapter_id)
        if chapter is None:
            return CanvasRenderResult()

        nodes = {}
        raw_chapter = store.chapter_data(chapter.id) if hasattr(store, "chapter_data") else {}
        images = raw_chapter.get("images", [])
        for raw in images if isinstance(images, list) else []:
            if not isinstance(raw, dict):
                continue
            image_path = (
                asset_index.cached_image_for(str(raw.get("image") or ""))
                if asset_index and hasattr(asset_index, "cached_image_for") else ""
            )
            scene.addItem(self.image_node_factory(raw, image_path, on_image_move))

        scoped_quests = set(agent_quest_ids)
        for quest in chapter.quests:
            task = quest.tasks[0] if quest.tasks else None
            icon_id = quest.icon or (task.target if task else "")
            icon_path = (
                asset_index.cached_icon_for(icon_id)
                if asset_index and hasattr(asset_index, "cached_icon_for") else ""
            )
            asset = getattr(asset_index, "items", {}).get(icon_id) if asset_index else None
            pending = bool(asset and getattr(asset, "render_status", "missing") != "unavailable")
            status_reader = getattr(asset_index, "icon_status_text", None) if asset_index else None
            icon_status = str(status_reader(icon_id) or "") if callable(status_reader) else ""
            if icon_id and not icon_path and not icon_status:
                icon_status = "后台准备中" if pending else "没有找到可用模型或代表贴图"
            node = self.quest_node_factory(
                quest, quest.x * 72, quest.y * 72, icon_path, on_quest_move,
                agent_context=quest.id in scoped_quests,
                icon_id=icon_id, icon_loader=icon_loader,
                icon_placeholder="…" if pending and not icon_path else ("?" if icon_id and not icon_path else ""),
                icon_status=icon_status,
            )
            node.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, not agent_busy)
            scene.addItem(node)
            nodes[quest.id] = node

        chapter_hides = bool(raw_chapter.get("default_hide_dependency_lines", False))
        for quest in chapter.quests:
            target = nodes.get(quest.id)
            target_raw = store.quest_data(quest.id) if hasattr(store, "quest_data") else {}
            if bool(target_raw.get("hide_dependency_lines", chapter_hides)):
                continue
            control_map = target_raw.get("dep_control_pts", {})
            control_map = control_map if isinstance(control_map, dict) else {}
            for dependency_id in quest.dependencies:
                source = nodes.get(dependency_id)
                if source is None or target is None:
                    continue
                source_raw = store.quest_data(dependency_id) if hasattr(store, "quest_data") else {}
                if bool(source_raw.get("hide_dependent_lines", False)):
                    continue
                controls = control_map.get(str(dependency_id))
                line = self._dependency_line(source, target, controls)
                scene.addItem(line)

        titles = {
            quest.id: quest.title
            for source_chapter in store.project.chapters
            for quest in source_chapter.quests
        }
        links = raw_chapter.get("quest_links", [])
        for raw in links if isinstance(links, list) else []:
            if not isinstance(raw, dict):
                continue
            linked_id = str(raw.get("linked_quest") or "")
            scene.addItem(self.link_node_factory(
                raw, titles.get(linked_id, ""), on_link_move, on_link_open,
            ))

        selected_node = nodes.get(selected_quest_id)
        if selected_node is not None:
            scene.blockSignals(True)
            selected_node.setSelected(True)
            scene.blockSignals(False)
        return CanvasRenderResult(chapter.title, nodes)

    def _dependency_line(self, source, target, controls):
        if isinstance(controls, list) and len(controls) == 4:
            try:
                return self.curved_dependency_factory(
                    source, target, [float(value) for value in controls],
                )
            except (TypeError, ValueError):
                pass
        return self.dependency_factory(source, target)
