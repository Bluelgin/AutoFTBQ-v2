"""Offline item model and icon index for modpack projects."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import shutil
import threading
import time
import zipfile
from typing import Callable

from PySide6.QtGui import QImage

from ..editor.model_renderer import (
    classify_static_model, render_spawn_egg_placeholder, render_static_model,
)


BUILTIN_REGISTRIES = {
    "dimension": {
        "minecraft:overworld": "主世界",
        "minecraft:the_nether": "下界",
        "minecraft:the_end": "末地",
    },
    "fluid": {
        "minecraft:water": "水",
        "minecraft:lava": "岩浆",
    },
    "entity": {
        f"minecraft:{value}": label for value, label in (
            ("allay", "悦灵"), ("armadillo", "犰狳"), ("axolotl", "美西螈"),
            ("bat", "蝙蝠"), ("bee", "蜜蜂"), ("blaze", "烈焰人"),
            ("bogged", "沼骸"), ("breeze", "旋风人"), ("camel", "骆驼"),
            ("cat", "猫"), ("cave_spider", "洞穴蜘蛛"), ("chicken", "鸡"),
            ("cod", "鳕鱼"), ("cow", "牛"), ("creeper", "苦力怕"),
            ("dolphin", "海豚"), ("donkey", "驴"), ("drowned", "溺尸"),
            ("elder_guardian", "远古守卫者"), ("ender_dragon", "末影龙"),
            ("enderman", "末影人"), ("endermite", "末影螨"), ("evoker", "唤魔者"),
            ("fox", "狐狸"), ("frog", "青蛙"), ("ghast", "恶魂"),
            ("goat", "山羊"), ("guardian", "守卫者"), ("hoglin", "疣猪兽"),
            ("horse", "马"), ("husk", "尸壳"), ("iron_golem", "铁傀儡"),
            ("llama", "羊驼"), ("magma_cube", "岩浆怪"), ("mooshroom", "哞菇"),
            ("mule", "骡"), ("ocelot", "豹猫"), ("panda", "熊猫"),
            ("parrot", "鹦鹉"), ("phantom", "幻翼"), ("pig", "猪"),
            ("piglin", "猪灵"), ("piglin_brute", "猪灵蛮兵"), ("pillager", "掠夺者"),
            ("polar_bear", "北极熊"), ("rabbit", "兔子"), ("ravager", "劫掠兽"),
            ("salmon", "鲑鱼"), ("sheep", "绵羊"), ("shulker", "潜影贝"),
            ("silverfish", "蠹虫"), ("skeleton", "骷髅"), ("slime", "史莱姆"),
            ("sniffer", "嗅探兽"), ("snow_golem", "雪傀儡"), ("spider", "蜘蛛"),
            ("squid", "鱿鱼"), ("stray", "流浪者"), ("strider", "炽足兽"),
            ("tadpole", "蝌蚪"), ("trader_llama", "行商羊驼"), ("turtle", "海龟"),
            ("vex", "恼鬼"), ("villager", "村民"), ("vindicator", "卫道士"),
            ("wandering_trader", "流浪商人"), ("warden", "监守者"),
            ("witch", "女巫"), ("wither", "凋灵"), ("wither_skeleton", "凋灵骷髅"),
            ("wolf", "狼"), ("zoglin", "僵尸疣猪兽"), ("zombie", "僵尸"),
            ("zombie_villager", "僵尸村民"), ("zombified_piglin", "僵尸猪灵"),
        )
    },
    "stat": {
        f"minecraft:{value}": label for value, label in (
            ("mob_kills", "击杀生物"), ("player_kills", "击杀玩家"),
            ("deaths", "死亡次数"), ("jump", "跳跃次数"), ("walk_one_cm", "步行距离"),
            ("sprint_one_cm", "疾跑距离"), ("swim_one_cm", "游泳距离"),
            ("fly_one_cm", "飞行距离"), ("play_time", "游玩时间"),
            ("damage_dealt", "造成伤害"), ("damage_taken", "承受伤害"),
            ("animals_bred", "繁殖动物"), ("fish_caught", "钓到鱼"),
            ("traded_with_villager", "与村民交易"), ("raid_win", "赢得袭击"),
        )
    },
}

SUSPICIOUS_ITEM_TOKENS = frozenset({
    "debug", "test", "testing", "dev", "developer", "wip", "unfinished",
    "internal", "placeholder", "dummy", "deprecated", "unused", "missingno",
})
UNSAFE_VANILLA_ITEMS = frozenset({
    "minecraft:air", "minecraft:barrier", "minecraft:debug_stick",
    "minecraft:structure_void", "minecraft:structure_block", "minecraft:jigsaw",
    "minecraft:command_block", "minecraft:chain_command_block",
    "minecraft:repeating_command_block", "minecraft:light",
})


@dataclass(frozen=True)
class ResourceRef:
    source: str
    entry: str = ""

    @property
    def modified(self) -> int:
        try:
            return int(os.path.getmtime(self.source))
        except OSError:
            return 0

    def read(self, max_bytes: int = 8 * 1024 * 1024) -> bytes:
        if self.entry:
            with zipfile.ZipFile(self.source, "r") as archive:
                info = archive.getinfo(self.entry)
                if info.file_size > max_bytes:
                    raise ValueError(f"资源过大：{self.entry}")
                return archive.read(info)
        if os.path.getsize(self.source) > max_bytes:
            raise ValueError(f"资源过大：{self.source}")
        with open(self.source, "rb") as handle:
            return handle.read()


@dataclass
class ItemAsset:
    item_id: str
    name: str
    model_path: str = ""
    texture_path: str = ""
    icon_path: str = ""
    render_status: str = "missing"
    model_kind: str = ""


@dataclass(frozen=True)
class AgentItemAvailability:
    item_id: str
    status: str
    allowed: bool
    reasons: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


class AssetIndex:
    """Layer Minecraft resources and lazily cache recognizable item icons."""

    def __init__(self, pack_root: str, cache_root: str):
        self.pack_root = os.path.abspath(pack_root)
        self.cache_root = os.path.abspath(cache_root)
        pack_key = hashlib.sha1(os.path.normcase(self.pack_root).encode("utf-8")).hexdigest()[:12]
        self.cache_dir = os.path.join(self.cache_root, pack_key)
        self.resources: dict[str, ResourceRef] = {}
        self._json_cache: dict[str, dict] = {}
        self.items: dict[str, ItemAsset] = {}
        self.registries: dict[str, dict[str, str]] = {}
        self.recipe_outputs: set[str] = set()
        self.recipe_inputs: set[str] = set()
        self.loot_outputs: set[str] = set()
        self.item_availability: dict[str, AgentItemAvailability] = {}
        self._icon_locks_guard = threading.Lock()
        self._icon_locks: dict[str, threading.Lock] = {}
        self._build_archives: dict[str, zipfile.ZipFile] = {}

    @classmethod
    def build(
        cls, pack_root: str, all_items: dict, cache_root: str,
        recipe_inputs: dict | None = None,
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> "AssetIndex":
        index = cls(pack_root, cache_root)
        os.makedirs(index.cache_dir, exist_ok=True)
        report = progress or (lambda _message: None)
        stopped = cancelled or (lambda: False)
        started_at = time.monotonic()
        try:
            report("正在收集 Mod 与资源包目录…")
            index._collect_resources(stopped)
            index._check_cancelled(stopped)
            report("正在整理物品模型索引…")
            for namespace_index, (_namespace, values) in enumerate(all_items.items()):
                if not isinstance(values, dict):
                    continue
                for item_id, name in values.items():
                    index.items[item_id] = ItemAsset(item_id=item_id, name=str(name))
                index._cooperate(stopped, namespace_index)
            index._augment_items_from_resources(stopped)
            report("正在整理实体、结构与战利品目录…")
            index._build_registries(stopped)
            recipes = recipe_inputs if isinstance(recipe_inputs, dict) else {}
            index.recipe_outputs = {str(value) for value in recipes if ":" in str(value)}
            index.recipe_inputs = {
                str(item_id)
                for values in recipes.values() if isinstance(values, list)
                for item_id in values if ":" in str(item_id)
            }
            index.loot_outputs = index._collect_loot_outputs(stopped)
            report(f"正在校验 {len(index.items)} 个 Agent 可用物品…")
            index._build_agent_availability(stopped)
        finally:
            index._close_build_archives()
        report(f"资源索引完成（{time.monotonic() - started_at:.1f} 秒）")
        return index

    def cache_payload(self) -> dict:
        """Return JSON-safe immutable scan metadata; rendered pixmaps remain lazy."""
        return {
            "resources": {
                key: [value.source, value.entry] for key, value in self.resources.items()
            },
            "items": {
                key: {
                    "name": value.name,
                    "model_path": value.model_path,
                    "texture_path": value.texture_path,
                    "icon_path": value.icon_path,
                    "render_status": value.render_status,
                    "model_kind": value.model_kind,
                }
                for key, value in self.items.items()
            },
            "registries": self.registries,
            "recipe_outputs": sorted(self.recipe_outputs),
            "recipe_inputs": sorted(self.recipe_inputs),
            "loot_outputs": sorted(self.loot_outputs),
            "item_availability": {
                key: {
                    "status": value.status, "allowed": value.allowed,
                    "reasons": list(value.reasons), "evidence": list(value.evidence),
                }
                for key, value in self.item_availability.items()
            },
        }

    @classmethod
    def from_cache_payload(cls, pack_root: str, cache_root: str, payload: dict) -> "AssetIndex":
        if not isinstance(payload, dict):
            raise ValueError("invalid asset cache")
        resources = payload.get("resources", {})
        items = payload.get("items", {})
        availability = payload.get("item_availability", {})
        if (not isinstance(resources, dict) or len(resources) > 500_000
                or not isinstance(items, dict) or len(items) > 250_000
                or not isinstance(availability, dict) or len(availability) > 250_000):
            raise ValueError("asset cache exceeds bounds")
        index = cls(pack_root, cache_root)
        os.makedirs(index.cache_dir, exist_ok=True)
        for key, value in resources.items():
            if (not isinstance(value, list) or len(value) != 2
                    or not isinstance(value[0], str) or not isinstance(value[1], str)):
                raise ValueError("invalid resource cache entry")
            index.resources[str(key)] = ResourceRef(value[0], value[1])
        item_fields = {
            "model_path", "texture_path", "icon_path", "render_status", "model_kind",
        }
        for item_id, value in items.items():
            if not isinstance(value, dict):
                raise ValueError("invalid item cache entry")
            details = {key: str(value.get(key, "")) for key in item_fields}
            index.items[str(item_id)] = ItemAsset(
                item_id=str(item_id), name=str(value.get("name", item_id)), **details,
            )
        registries = payload.get("registries", {})
        if not isinstance(registries, dict) or len(registries) > 100:
            raise ValueError("invalid registry cache")
        index.registries = {
            str(kind): {str(key): str(value) for key, value in values.items()}
            for kind, values in registries.items() if isinstance(values, dict)
        }
        index.recipe_outputs = {str(value) for value in payload.get("recipe_outputs", [])}
        index.recipe_inputs = {str(value) for value in payload.get("recipe_inputs", [])}
        index.loot_outputs = {str(value) for value in payload.get("loot_outputs", [])}
        for item_id, value in availability.items():
            if not isinstance(value, dict):
                raise ValueError("invalid availability cache entry")
            index.item_availability[str(item_id)] = AgentItemAvailability(
                str(item_id), str(value.get("status", "blocked")),
                bool(value.get("allowed")),
                tuple(str(item) for item in value.get("reasons", [])[:16]),
                tuple(str(item) for item in value.get("evidence", [])[:16]),
            )
        return index

    @staticmethod
    def _check_cancelled(cancelled: Callable[[], bool]) -> None:
        if cancelled():
            raise InterruptedError("资源恢复已取消")

    @classmethod
    def _cooperate(cls, cancelled: Callable[[], bool], index: int) -> None:
        if index % 16:
            return
        cls._check_cancelled(cancelled)
        # QThread does not bypass Python's GIL. Yield regularly so the Qt event
        # loop can paint and receive input during large pure-Python indexes.
        time.sleep(0.001)

    def _augment_items_from_resources(self, cancelled=lambda: False) -> None:
        """Include resource-defined items even when registry scanning missed them."""
        candidates = []
        for index, key in enumerate(self.resources):
            self._cooperate(cancelled, index)
            parts = key.split("/")
            if len(parts) < 4 or parts[0] != "assets":
                continue
            namespace = parts[1]
            item_path = ""
            if parts[2] == "items" and key.endswith(".json"):
                item_path = "/".join(parts[3:])[:-5]
            elif len(parts) >= 5 and parts[2:4] == ["models", "item"] and key.endswith(".json"):
                item_path = "/".join(parts[4:])[:-5]
            elif len(parts) >= 5 and parts[2:4] == ["textures", "item"] and key.endswith(".png"):
                item_path = "/".join(parts[4:])[:-4]
            if item_path:
                candidates.append(f"{namespace}:{item_path}")
        for item_id in candidates:
            self.items.setdefault(item_id, ItemAsset(item_id=item_id, name=item_id))

    def _collect_loot_outputs(self, cancelled=lambda: False) -> set[str]:
        outputs: set[str] = set()

        def visit(value) -> None:
            if isinstance(value, dict):
                entry_type = str(value.get("type", ""))
                name = value.get("name", "")
                if entry_type.endswith(":item") and isinstance(name, str) and ":" in name:
                    outputs.add(name)
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        for index, key in enumerate(self.resources):
            self._cooperate(cancelled, index)
            if key.startswith("data/") and (
                "/loot_table/" in key or "/loot_tables/" in key
            ) and key.endswith(".json"):
                visit(self._json(key))
        return outputs

    @staticmethod
    def _suspicious_tokens(item_id: str) -> set[str]:
        path = str(item_id).split(":", 1)[-1]
        normalized = path.replace("-", "_").replace(".", "_").replace("/", "_")
        return {value for value in normalized.split("_") if value in SUSPICIOUS_ITEM_TOKENS}

    def _model_evidence(self, item_id: str) -> tuple[bool, list[str], list[str]]:
        namespace, _path = item_id.split(":", 1)
        model_path, model, resolved = self._resolve_model(item_id)
        reasons: list[str] = []
        evidence: list[str] = []
        if self._resource_key(model_path) not in self.resources:
            reasons.append("缺少物品模型")
            return False, reasons, evidence
        evidence.append("物品模型存在")
        textures = model.get("textures", {}) if isinstance(model, dict) else {}
        textures = textures if isinstance(textures, dict) else {}
        concrete = []
        for raw in textures.values():
            value = str(raw or "")
            for _depth in range(12):
                if not value.startswith("#"):
                    break
                value = str(textures.get(value[1:], "") or "")
            if value:
                concrete.append(value)
        missing = []
        for value in concrete:
            texture_namespace = value.split(":", 1)[0] if ":" in value else namespace
            if texture_namespace == "minecraft":
                continue
            path = self._location(value, namespace, "textures", ".png")
            if self._resource_key(path) not in self.resources:
                missing.append(value)
        if missing:
            reasons.append(f"模型引用的贴图不存在：{missing[0]}")
            return False, reasons, evidence
        if not concrete and not resolved:
            reasons.append("模型没有可验证的物品贴图")
            return False, reasons, evidence
        evidence.append("模型贴图完整")
        return True, reasons, evidence

    def _build_agent_availability(self, cancelled=lambda: False) -> None:
        values: dict[str, AgentItemAvailability] = {}
        for index, item_id in enumerate(self.items):
            self._cooperate(cancelled, index)
            reasons: list[str] = []
            evidence: list[str] = []
            suspicious = self._suspicious_tokens(item_id)
            if item_id in UNSAFE_VANILLA_ITEMS:
                reasons.append("属于命令、调试或技术用途物品")
            elif suspicious:
                reasons.append(f"ID 包含可疑开发标记：{sorted(suspicious)[0]}")

            namespace = item_id.split(":", 1)[0] if ":" in item_id else ""
            if namespace == "minecraft" and not reasons:
                evidence.append("原版稳定物品")
                render_safe = True
            elif item_id.endswith("_spawn_egg"):
                render_safe = True
                evidence.append("标准刷怪蛋运行时模型")
            else:
                render_safe, model_reasons, model_evidence = self._model_evidence(item_id)
                reasons.extend(model_reasons)
                evidence.extend(model_evidence)

            gameplay_sources = []
            if item_id in self.recipe_outputs:
                gameplay_sources.append("有效配方产物")
            if item_id in self.recipe_inputs:
                gameplay_sources.append("有效配方原料")
            if item_id in self.loot_outputs:
                gameplay_sources.append("战利品产物")
            evidence.extend(gameplay_sources)

            if reasons or not render_safe:
                status, allowed = "blocked", False
            elif namespace == "minecraft" or gameplay_sources:
                status, allowed = "allowed", True
            else:
                status, allowed = "uncertain", False
                reasons.append("未发现配方或战利品等游戏内使用证据")
            values[item_id] = AgentItemAvailability(
                item_id, status, allowed, tuple(dict.fromkeys(reasons)),
                tuple(dict.fromkeys(evidence)),
            )
        self.item_availability = values

    def agent_item_status(self, item_id: str) -> AgentItemAvailability:
        item_id = str(item_id or "").strip()
        known = self.item_availability.get(item_id)
        if known is not None:
            return known
        return AgentItemAvailability(
            item_id, "blocked", False, ("ID 不在已扫描的整合包物品索引中",), (),
        )

    def agent_availability_map(self) -> dict[str, dict]:
        return {
            item_id: {
                "status": value.status,
                "allowed": value.allowed,
                "reasons": list(value.reasons),
                "evidence": list(value.evidence),
            }
            for item_id, value in self.item_availability.items()
        }

    @staticmethod
    def _keep_resource(key: str) -> bool:
        if key.startswith("assets/"):
            return key.endswith((".json", ".png", "/ftb_quests_theme.txt"))
        if not key.startswith("data/") or not key.endswith(".json"):
            return False
        return any(marker in key for marker in (
            "/advancement/", "/advancements/", "/dimension/", "/worldgen/biome/",
            "/worldgen/structure/", "/loot_table/", "/loot_tables/",
            "/tags/entity_type/", "/tags/fluid/",
        ))

    @staticmethod
    def _resource_key(value: str) -> str:
        return str(value).replace("\\", "/").lstrip("/").lower()

    def _add_archive(self, path: str) -> None:
        try:
            archive = zipfile.ZipFile(path, "r")
            if len(archive.infolist()) > 250_000:
                archive.close()
                return
            self._build_archives[path] = archive
            for info in archive.infolist():
                key = self._resource_key(info.filename)
                if info.is_dir():
                    continue
                if not self._keep_resource(key):
                    continue
                self.resources[key] = ResourceRef(path, info.filename)
        except (OSError, zipfile.BadZipFile):
            return

    def _add_directory(self, root: str) -> None:
        if not os.path.isdir(root):
            return
        for current, _dirs, files in os.walk(root):
            for filename in files:
                path = os.path.join(current, filename)
                relative = self._resource_key(os.path.relpath(path, root))
                if self._keep_resource(relative):
                    self.resources[relative] = ResourceRef(path)

    def _collect_resources(self, cancelled=lambda: False) -> None:
        root = self.pack_root
        mods_dir = os.path.join(root, "mods") if os.path.isdir(os.path.join(root, "mods")) else root
        # Later layers override earlier ones, matching the useful subset of resource-pack behavior.
        if os.path.isdir(root):
            for index, filename in enumerate(sorted(os.listdir(root))):
                self._cooperate(cancelled, index)
                if filename.lower().endswith(".jar"):
                    self._add_archive(os.path.join(root, filename))
        if os.path.isdir(mods_dir):
            for index, filename in enumerate(sorted(os.listdir(mods_dir))):
                self._cooperate(cancelled, index)
                if filename.lower().endswith((".jar", ".zip")):
                    self._add_archive(os.path.join(mods_dir, filename))
        self._add_directory(os.path.join(root, "kubejs"))
        resourcepacks = os.path.join(root, "resourcepacks")
        if os.path.isdir(resourcepacks):
            for filename in sorted(os.listdir(resourcepacks)):
                path = os.path.join(resourcepacks, filename)
                if os.path.isdir(path):
                    self._add_directory(path)
                elif filename.lower().endswith(".zip"):
                    self._add_archive(path)

    def _close_build_archives(self) -> None:
        for archive in self._build_archives.values():
            try:
                archive.close()
            except OSError:
                pass
        self._build_archives.clear()

    def _read_ref(self, ref: ResourceRef, max_bytes: int = 8 * 1024 * 1024) -> bytes:
        if ref.entry:
            archive = self._build_archives.get(ref.source)
            if archive is not None:
                info = archive.getinfo(ref.entry)
                if info.file_size > max_bytes:
                    raise ValueError(f"资源过大：{ref.entry}")
                return archive.read(info)
        return ref.read(max_bytes=max_bytes)

    def _json(self, path: str) -> dict:
        key = self._resource_key(path)
        if key in self._json_cache:
            return self._json_cache[key]
        ref = self.resources.get(key)
        if ref is None:
            return {}
        try:
            value = json.loads(self._read_ref(ref).decode("utf-8-sig"))
            result = value if isinstance(value, dict) else {}
        except (OSError, UnicodeError, ValueError, KeyError, zipfile.BadZipFile):
            result = {}
        self._json_cache[key] = result
        return result

    @staticmethod
    def _location(value: str, default_namespace: str, category: str, extension: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        namespace, path = raw.split(":", 1) if ":" in raw else (default_namespace, raw)
        path = path.removeprefix(f"{category}/")
        return f"assets/{namespace}/{category}/{path}{extension}"

    @staticmethod
    def _first_model(value) -> str:
        if isinstance(value, dict):
            model_type = str(value.get("type", ""))
            model = value.get("model")
            if isinstance(model, str) and (model_type.endswith(":model") or not model_type):
                return model
            for key in ("model", "fallback", "on_true", "on_false", "cases", "entries", "models"):
                found = AssetIndex._first_model(value.get(key))
                if found:
                    return found
            for nested in value.values():
                found = AssetIndex._first_model(nested)
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = AssetIndex._first_model(nested)
                if found:
                    return found
        return ""

    def _resolve_texture(self, item_id: str) -> tuple[str, str]:
        model_path, _model, texture_paths = self._resolve_model(item_id)
        texture_path = next(iter(texture_paths.values()), "")
        return model_path, texture_path

    def _resolve_model(self, item_id: str) -> tuple[str, dict, dict[str, str]]:
        namespace, item_path = item_id.split(":", 1)
        direct = self._location(f"{namespace}:{item_path}", namespace, "textures/item", ".png")

        definition_path = f"assets/{namespace}/items/{item_path}.json"
        definition = self._json(definition_path)
        model_location = self._first_model(definition.get("model", definition))
        model_path = self._location(
            model_location or f"{namespace}:item/{item_path}", namespace, "models", ".json"
        )
        textures: dict[str, str] = {}
        combined: dict = {}
        visited = set()
        current = model_path
        for _depth in range(20):
            key = self._resource_key(current)
            if not current or key in visited:
                break
            visited.add(key)
            model = self._json(current)
            if not model:
                break
            for name, value in model.items():
                if name != "textures":
                    combined.setdefault(str(name), value)
            for name, value in model.get("textures", {}).items() if isinstance(model.get("textures"), dict) else []:
                textures.setdefault(str(name), str(value))
            parent = model.get("parent", "")
            if not isinstance(parent, str) or not parent or parent.startswith("builtin/"):
                break
            current = self._location(parent, namespace, "models", ".json")

        if not textures and self._resource_key(direct) in self.resources:
            textures["layer0"] = f"{namespace}:item/{item_path}"
            combined.setdefault("parent", "minecraft:item/generated")

        resolved: dict[str, str] = {}
        for name, raw_texture in textures.items():
            texture = raw_texture
            for _depth in range(12):
                if not isinstance(texture, str) or not texture.startswith("#"):
                    break
                texture = textures.get(texture[1:], "")
            texture_path = self._location(texture, namespace, "textures", ".png") if texture else ""
            if self._resource_key(texture_path) in self.resources:
                resolved[name] = texture_path
        if self._resource_key(direct) in self.resources:
            resolved.setdefault("direct", direct)
        combined["textures"] = textures
        return model_path, combined, resolved

    def _resolve_assets(self) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        for item in self.items.values():
            if ":" not in item.item_id:
                continue
            item.model_path, item.texture_path = self._resolve_texture(item.item_id)
            if item.texture_path:
                item.render_status = "texture"
            elif self._resource_key(item.model_path) in self.resources:
                item.render_status = "model_fallback"

    def icon_for(self, item_id: str) -> str:
        with self._icon_lock(str(item_id)):
            return self._render_icon(str(item_id))

    def _icon_lock(self, item_id: str) -> threading.Lock:
        with self._icon_locks_guard:
            return self._icon_locks.setdefault(item_id, threading.Lock())

    def cached_icon_for(self, item_id: str) -> str:
        """Return only an already rendered icon; never decode or render on the UI thread."""
        item = self.items.get(str(item_id))
        path = item.icon_path if item is not None else ""
        return path if path and os.path.isfile(path) else ""

    def _render_icon(self, item_id: str) -> str:
        item = self.items.get(item_id)
        if item is None:
            return ""
        if item.render_status == "missing" and not item.model_path:
            item.model_path, item.texture_path = self._resolve_texture(item.item_id)
            if item.texture_path:
                item.render_status = "texture"
            elif self._resource_key(item.model_path) in self.resources:
                item.render_status = "model_fallback"
            else:
                item.render_status = "unavailable"
        model_path, model, texture_paths = self._resolve_model(item.item_id)
        item.model_path = model_path
        item.texture_path = next(iter(texture_paths.values()), "")
        if not item.texture_path:
            if item.item_id.endswith("_spawn_egg"):
                return self._generated_spawn_egg(item)
            item.render_status = "unavailable"
            return ""
        if item.icon_path and os.path.isfile(item.icon_path):
            return item.icon_path
        refs = {
            name: self.resources.get(self._resource_key(path))
            for name, path in texture_paths.items()
        }
        refs = {name: ref for name, ref in refs.items() if ref is not None}
        if not refs:
            return ""
        digest = hashlib.sha1(
            ("static-model-v1|" + item_id + "|" + json.dumps(model, sort_keys=True) + "|" + "|".join(
                f"{name}:{ref.source}:{ref.entry}:{ref.modified}" for name, ref in sorted(refs.items())
            )).encode("utf-8")
        ).hexdigest()[:16]
        target = os.path.join(self.cache_dir, f"{digest}.png")
        classified_kind = classify_static_model(model, refs)
        item.model_kind = "dynamic_fallback" if classified_kind == "dynamic" else classified_kind
        if not os.path.isfile(target):
            try:
                images = {name: QImage.fromData(ref.read()) for name, ref in refs.items()}
                rendered, kind = render_static_model(model, images)
                item.model_kind = kind
                if not rendered.isNull() and kind in {"layered", "block"}:
                    if not rendered.save(target, "PNG"):
                        return ""
                else:
                    # Dynamic/builtin models often ship a representative direct item texture.
                    ref = refs.get("direct") or next(iter(refs.values()))
                    if ref.entry:
                        with open(target, "wb") as handle:
                            handle.write(ref.read())
                    else:
                        shutil.copyfile(ref.source, target)
                    item.model_kind = kind if kind != "dynamic" else "dynamic_fallback"
            except OSError:
                return ""
        else:
            try:
                os.utime(target, None)
            except OSError:
                pass
        item.icon_path = target
        item.render_status = "rendered_model" if item.model_kind in {"layered", "block"} else "texture"
        return target

    def _generated_spawn_egg(self, item: ItemAsset) -> str:
        digest = hashlib.sha1(f"spawn-egg-v1|{item.item_id}".encode("utf-8")).hexdigest()[:16]
        target = os.path.join(self.cache_dir, f"{digest}.png")
        if not os.path.isfile(target):
            os.makedirs(self.cache_dir, exist_ok=True)
            image = render_spawn_egg_placeholder(item.item_id)
            if image.isNull() or not image.save(target, "PNG"):
                return ""
        item.icon_path = target
        item.model_kind = "spawn_egg_fallback"
        item.render_status = "generated_fallback"
        return target

    def cached_image_for(self, resource_id: str) -> str:
        raw = str(resource_id or "").strip()
        if not raw:
            return ""
        namespace, path = raw.split(":", 1) if ":" in raw else ("minecraft", raw)
        path = path.lstrip("/")
        if path.startswith("assets/"):
            resource_path = path
        else:
            path = path.removeprefix("textures/")
            if not path.lower().endswith(".png"):
                path += ".png"
            resource_path = f"assets/{namespace}/textures/{path}"
        ref = self.resources.get(self._resource_key(resource_path))
        if ref is None:
            return ""
        digest = hashlib.sha1(
            f"image|{resource_path}|{ref.source}|{ref.entry}|{ref.modified}".encode("utf-8")
        ).hexdigest()[:16]
        target = os.path.join(self.cache_dir, f"{digest}.png")
        return target if os.path.isfile(target) else ""

    def cleanup_cache(
        self, max_age_seconds: int = 14 * 24 * 60 * 60, max_bytes: int = 256 * 1024 * 1024,
    ) -> dict:
        """Remove stale disk icons and bound the shared cache by least-recent use."""
        root = os.path.abspath(self.cache_root)
        if not os.path.isdir(root):
            return {"removed": 0, "bytes_removed": 0, "remaining_bytes": 0}
        cutoff = time.time() - max(60, int(max_age_seconds))
        files = []
        for current, _dirs, names in os.walk(root):
            for name in names:
                if not name.lower().endswith(".png"):
                    continue
                path = os.path.abspath(os.path.join(current, name))
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                files.append([path, stat.st_mtime, stat.st_size])
        removed = 0
        bytes_removed = 0
        remaining = sum(value[2] for value in files)
        for path, modified, size in sorted(files, key=lambda value: value[1]):
            if modified >= cutoff and remaining <= int(max_bytes):
                continue
            try:
                os.remove(path)
            except OSError:
                continue
            removed += 1
            bytes_removed += size
            remaining -= size
        return {"removed": removed, "bytes_removed": bytes_removed, "remaining_bytes": remaining}

    def icon_status_text(self, item_id: str) -> str:
        item = self.items.get(str(item_id))
        if item is None:
            return ""
        return {
            "block": "静态立体模型预览",
            "layered": "多层物品贴图预览",
            "dynamic_fallback": "动态游戏模型 · 当前显示代表贴图",
            "texture": "原始物品贴图",
            "spawn_egg_fallback": "刷怪蛋代表图标 · 游戏内颜色可能不同",
        }.get(item.model_kind, "暂无可用图标" if item.render_status == "unavailable" else "")

    def image_for(self, resource_id: str) -> str:
        """Resolve an arbitrary namespaced PNG resource to the local icon cache."""
        raw = str(resource_id or "").strip()
        if not raw:
            return ""
        namespace, path = raw.split(":", 1) if ":" in raw else ("minecraft", raw)
        path = path.lstrip("/")
        if path.startswith("assets/"):
            resource_path = path
        else:
            path = path.removeprefix("textures/")
            if not path.lower().endswith(".png"):
                path += ".png"
            resource_path = f"assets/{namespace}/textures/{path}"
        ref = self.resources.get(self._resource_key(resource_path))
        if ref is None:
            return ""
        digest = hashlib.sha1(
            f"image|{resource_path}|{ref.source}|{ref.entry}|{ref.modified}".encode("utf-8")
        ).hexdigest()[:16]
        target = os.path.join(self.cache_dir, f"{digest}.png")
        if not os.path.isfile(target):
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                if ref.entry:
                    with open(target, "wb") as handle:
                        handle.write(ref.read())
                else:
                    shutil.copyfile(ref.source, target)
            except OSError:
                return ""
        return target

    def quest_shapes(self) -> list[str]:
        """Read the active FTB Quests theme's declared extension shapes."""
        ref = next(
            (value for key, value in self.resources.items() if key.endswith("/ftb_quests_theme.txt")),
            None,
        )
        if ref is None:
            return []
        try:
            text = ref.read(max_bytes=512 * 1024).decode("utf-8-sig")
        except (OSError, UnicodeError, ValueError, KeyError, zipfile.BadZipFile):
            return []
        result = []
        for line in text.splitlines():
            content = line.split("#", 1)[0].strip()
            if not content.startswith("extra_quest_shapes:"):
                continue
            for value in content.split(":", 1)[1].split(","):
                shape = value.strip()
                if shape and shape not in result:
                    result.append(shape)
        return result

    def _build_registries(self, cancelled=lambda: False) -> None:
        self.registries = {
            registry: dict(values) for registry, values in BUILTIN_REGISTRIES.items()
        }
        translations = {}
        for locale in ("en_us", "zh_cn"):
            for index, key in enumerate(sorted(self.resources)):
                self._cooperate(cancelled, index)
                if not key.startswith("assets/") or not key.endswith(f"/lang/{locale}.json"):
                    continue
                translations.update(self._json(key))
        for translation_key, name in translations.items():
            parts = str(translation_key).split(".")
            registry = {"entity": "entity", "fluid": "fluid", "biome": "biome"}.get(parts[0])
            if registry and len(parts) >= 3:
                identifier = f"{parts[1]}:{'.'.join(parts[2:])}"
                self.registries.setdefault(registry, {})[identifier] = str(name)
        patterns = (
            ("advancement", ("advancement", "advancements")),
            ("dimension", ("dimension",)),
            ("biome", ("worldgen/biome",)),
            ("structure", ("worldgen/structure",)),
            ("loot_table", ("loot_table", "loot_tables")),
            ("entity_tag", ("tags/entity_type",)),
            ("fluid_tag", ("tags/fluid",)),
        )
        for index, key in enumerate(self.resources):
            self._cooperate(cancelled, index)
            if not key.startswith("data/") or not key.endswith(".json"):
                continue
            parts = key.split("/", 2)
            if len(parts) != 3:
                continue
            namespace, remainder = parts[1], parts[2]
            for registry, roots in patterns:
                root = next((value for value in roots if remainder.startswith(value + "/")), "")
                if not root:
                    continue
                value = remainder[len(root) + 1:-5]
                identifier = f"{namespace}:{value}"
                if registry.endswith("_tag"):
                    identifier = f"#{identifier}"
                self.registries.setdefault(registry, {}).setdefault(identifier, identifier)
                break

    @staticmethod
    def builtin_registry_values(registry: str) -> dict[str, str]:
        return dict(BUILTIN_REGISTRIES.get(str(registry), {}))

    def registry_values(self, registry: str) -> dict[str, str]:
        if registry == "item":
            return {item_id: asset.name for item_id, asset in self.items.items()}
        return dict(self.registries.get(str(registry), {}))

    def search_registry(self, registry: str, query: str = "", limit: int = 100) -> list[tuple[str, str]]:
        needle = str(query or "").casefold().strip()
        values = self.registry_values(registry)
        matches = [
            (identifier, name) for identifier, name in values.items()
            if not needle or needle in identifier.casefold() or needle in str(name).casefold()
        ]
        return sorted(matches, key=lambda value: (value[1].casefold(), value[0]))[:max(1, int(limit))]

    def summary(self) -> dict:
        resolved = sum(1 for item in self.items.values() if item.texture_path)
        model_only = sum(1 for item in self.items.values() if item.render_status == "model_fallback")
        return {
            "items": len(self.items),
            "agent_allowed": sum(1 for value in self.item_availability.values() if value.allowed),
            "agent_blocked": sum(1 for value in self.item_availability.values() if value.status == "blocked"),
            "agent_uncertain": sum(1 for value in self.item_availability.values() if value.status == "uncertain"),
            "icons": resolved,
            "model_fallbacks": model_only,
            "rendered_models": sum(
                1 for item in self.items.values() if item.render_status == "rendered_model"
            ),
            "pending": sum(1 for item in self.items.values() if item.render_status == "missing"),
            "resources": len(self.resources),
            "registries": sum(len(values) for values in self.registries.values()),
        }
