"""Application service for loading modpack resources and an optional quest book."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import tempfile
import time
from typing import Callable

import mod_scanner

from .asset_index import AssetIndex
from .app_logging import LOGGER_NAME
from ..ftb_store import FTBQuestStore, locate_quest_root


LOGGER = logging.getLogger(LOGGER_NAME)


class ModpackScanService:
    def __init__(self, cache_root: str):
        self.cache_root = cache_root

    def scan(
        self,
        folder: str,
        *,
        load_quest_book: bool = True,
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        started_at = time.monotonic()
        report_status = progress or (lambda _message: None)
        stopped = cancelled or (lambda: False)
        mods_folder = os.path.join(folder, "mods")
        mods_dir = mods_folder if os.path.isdir(mods_folder) else folder

        def report_items(current, total, filename):
            if stopped():
                raise InterruptedError("资源恢复已取消")
            report_status(f"扫描模组 {current}/{total}\n{filename}")

        fingerprint = self._pack_fingerprint(folder, stopped)
        cached = self._load_scan_cache(fingerprint)
        item_cache_hit = cached is not None
        if cached is None:
            report_status("首次读取模组物品与配方…")
            items = mod_scanner.scan_folder_items(mods_dir, progress_cb=report_items)
            recipes = dict(getattr(mod_scanner, "_recipe_inputs_cache", {}))
            self._save_scan_cache(fingerprint, items, recipes)
        else:
            items, recipes = cached
            report_status("已载入整合包扫描缓存，正在恢复资源索引…")
        if stopped():
            raise InterruptedError("资源恢复已取消")
        asset_index = self._load_asset_cache(folder, fingerprint)
        asset_cache_hit = asset_index is not None
        if asset_index is None:
            report_status("正在建立图标资源目录…\n图标将在需要时按需解析")
            asset_index = AssetIndex.build(
                folder, items, self.cache_root, recipes,
                progress=report_status, cancelled=stopped,
            )
            self._save_asset_cache(fingerprint, asset_index)
        else:
            report_status("已恢复完整资源索引，无需重新解析 Mod JAR")
        if stopped():
            raise InterruptedError("资源恢复已取消")
        report_status("正在读取 FTB Quests 任务书…")
        quest_root = locate_quest_root(folder)
        store = FTBQuestStore.load_directory(quest_root, folder) if quest_root and load_quest_book else None
        LOGGER.info(
            "Modpack resources ready: folder=%s seconds=%.2f item_cache=%s "
            "asset_cache=%s items=%s resources=%s",
            folder, time.monotonic() - started_at, item_cache_hit, asset_cache_hit,
            sum(len(value) for value in items.values() if isinstance(value, dict)),
            len(getattr(asset_index, "resources", {})),
        )
        return {
            "folder": folder,
            "items": items,
            "recipes": recipes,
            "asset_index": asset_index,
            "quest_root": quest_root,
            "store": store,
        }

    def _pack_fingerprint(self, folder: str, cancelled: Callable[[], bool]) -> str:
        digest = hashlib.sha256(b"autoftbq-resource-scan-v2\0")
        digest.update(os.path.normcase(os.path.abspath(folder)).encode("utf-8", "surrogatepass"))
        digest.update(b"\0")
        roots = [os.path.join(folder, "mods"), os.path.join(folder, "resourcepacks"),
                 os.path.join(folder, "kubejs")]
        seen = 0
        for root in roots:
            if not os.path.isdir(root):
                continue
            for current, _dirs, names in os.walk(root):
                for name in sorted(names):
                    path = os.path.join(current, name)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    relative = os.path.relpath(path, folder).replace("\\", "/")
                    digest.update(relative.encode("utf-8", "surrogatepass"))
                    digest.update(f"\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode("ascii"))
                    seen += 1
                    if seen % 128 == 0:
                        if cancelled():
                            raise InterruptedError("资源恢复已取消")
                        time.sleep(0.001)
        return digest.hexdigest()[:24]

    def _cache_path(self, fingerprint: str) -> str:
        root = os.path.join(os.path.dirname(self.cache_root), "scan")
        return os.path.join(root, f"{fingerprint}.json.gz")

    def _asset_cache_path(self, fingerprint: str) -> str:
        root = os.path.join(os.path.dirname(self.cache_root), "scan")
        return os.path.join(root, f"asset-{fingerprint}.json.gz")

    def _load_scan_cache(self, fingerprint: str) -> tuple[dict, dict] | None:
        path = self._cache_path(fingerprint)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                value = json.load(handle)
            items, recipes = value.get("items"), value.get("recipes")
            if isinstance(items, dict) and isinstance(recipes, dict):
                return items, recipes
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        return None

    def _save_scan_cache(self, fingerprint: str, items: dict, recipes: dict) -> None:
        path = self._cache_path(fingerprint)
        root = os.path.dirname(path)
        os.makedirs(root, exist_ok=True)
        temporary = ""
        try:
            descriptor, temporary = tempfile.mkstemp(prefix="scan-", suffix=".tmp", dir=root)
            os.close(descriptor)
            with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=3) as handle:
                json.dump({"items": items, "recipes": recipes}, handle,
                          ensure_ascii=False, separators=(",", ":"))
            os.replace(temporary, path)
        except (OSError, TypeError, ValueError):
            if temporary:
                try:
                    os.remove(temporary)
                except OSError:
                    pass

    def _load_asset_cache(self, folder: str, fingerprint: str) -> AssetIndex | None:
        path = self._asset_cache_path(fingerprint)
        try:
            if os.path.getsize(path) > 64 * 1024 * 1024:
                return None
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            return AssetIndex.from_cache_payload(folder, self.cache_root, payload)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def _save_asset_cache(self, fingerprint: str, asset_index: AssetIndex) -> None:
        payload_reader = getattr(asset_index, "cache_payload", None)
        if not callable(payload_reader):
            return
        path = self._asset_cache_path(fingerprint)
        root = os.path.dirname(path)
        os.makedirs(root, exist_ok=True)
        temporary = ""
        try:
            descriptor, temporary = tempfile.mkstemp(prefix="asset-", suffix=".tmp", dir=root)
            os.close(descriptor)
            with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=3) as handle:
                json.dump(payload_reader(), handle, ensure_ascii=False,
                          separators=(",", ":"))
            os.replace(temporary, path)
        except (OSError, TypeError, ValueError):
            if temporary:
                try:
                    os.remove(temporary)
                except OSError:
                    pass
