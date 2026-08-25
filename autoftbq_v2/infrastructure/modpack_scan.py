"""Application service for loading modpack resources and an optional quest book."""

from __future__ import annotations

import os
from typing import Callable

import mod_scanner

from .asset_index import AssetIndex
from ..ftb_store import FTBQuestStore, locate_quest_root


class ModpackScanService:
    def __init__(self, cache_root: str):
        self.cache_root = cache_root

    def scan(
        self,
        folder: str,
        *,
        load_quest_book: bool = True,
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        report_status = progress or (lambda _message: None)
        mods_folder = os.path.join(folder, "mods")
        mods_dir = mods_folder if os.path.isdir(mods_folder) else folder

        def report_items(current, total, filename):
            report_status(f"扫描模组 {current}/{total}\n{filename}")

        report_status("正在读取模组物品与配方…")
        items = mod_scanner.scan_folder_items(mods_dir, progress_cb=report_items)
        recipes = dict(getattr(mod_scanner, "_recipe_inputs_cache", {}))
        report_status("正在建立图标资源目录…\n图标将在需要时按需解析")
        asset_index = AssetIndex.build(folder, items, self.cache_root)
        report_status("正在读取 FTB Quests 任务书…")
        quest_root = locate_quest_root(folder)
        store = FTBQuestStore.load_directory(quest_root, folder) if quest_root and load_quest_book else None
        return {
            "folder": folder,
            "items": items,
            "recipes": recipes,
            "asset_index": asset_index,
            "quest_root": quest_root,
            "store": store,
        }
