"""Offline item model and icon index for modpack projects."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import shutil
import zipfile

from PySide6.QtGui import QImage

from ..editor.model_renderer import classify_static_model, render_static_model


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


class AssetIndex:
    """Layer Minecraft resources and lazily cache recognizable item icons."""

    def __init__(self, pack_root: str, cache_root: str):
        self.pack_root = os.path.abspath(pack_root)
        pack_key = hashlib.sha1(os.path.normcase(self.pack_root).encode("utf-8")).hexdigest()[:12]
        self.cache_dir = os.path.join(os.path.abspath(cache_root), pack_key)
        self.resources: dict[str, ResourceRef] = {}
        self.items: dict[str, ItemAsset] = {}
        self.registries: dict[str, dict[str, str]] = {}

    @classmethod
    def build(cls, pack_root: str, all_items: dict, cache_root: str) -> "AssetIndex":
        index = cls(pack_root, cache_root)
        os.makedirs(index.cache_dir, exist_ok=True)
        index._collect_resources()
        for namespace, values in all_items.items():
            if not isinstance(values, dict):
                continue
            for item_id, name in values.items():
                index.items[item_id] = ItemAsset(item_id=item_id, name=str(name))
        index._build_registries()
        return index

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
            with zipfile.ZipFile(path, "r") as archive:
                if len(archive.infolist()) > 250_000:
                    return
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

    def _collect_resources(self) -> None:
        root = self.pack_root
        mods_dir = os.path.join(root, "mods") if os.path.isdir(os.path.join(root, "mods")) else root
        # Later layers override earlier ones, matching the useful subset of resource-pack behavior.
        if os.path.isdir(root):
            for filename in sorted(os.listdir(root)):
                if filename.lower().endswith(".jar"):
                    self._add_archive(os.path.join(root, filename))
        if os.path.isdir(mods_dir):
            for filename in sorted(os.listdir(mods_dir)):
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

    def _json(self, path: str) -> dict:
        ref = self.resources.get(self._resource_key(path))
        if ref is None:
            return {}
        try:
            value = json.loads(ref.read().decode("utf-8-sig"))
            return value if isinstance(value, dict) else {}
        except (OSError, UnicodeError, ValueError, KeyError, zipfile.BadZipFile):
            return {}

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
                    # Keep the exact original for the common single-layer path.
                    ref = next(iter(refs.values()))
                    if ref.entry:
                        with open(target, "wb") as handle:
                            handle.write(ref.read())
                    else:
                        shutil.copyfile(ref.source, target)
                    item.model_kind = kind if kind != "dynamic" else "dynamic_fallback"
            except OSError:
                return ""
        item.icon_path = target
        item.render_status = "rendered_model" if item.model_kind in {"layered", "block"} else "texture"
        return target

    def icon_status_text(self, item_id: str) -> str:
        item = self.items.get(str(item_id))
        if item is None:
            return ""
        return {
            "block": "静态立体模型预览",
            "layered": "多层物品贴图预览",
            "dynamic_fallback": "动态游戏模型 · 当前显示代表贴图",
            "texture": "原始物品贴图",
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

    def _build_registries(self) -> None:
        self.registries = {
            registry: dict(values) for registry, values in BUILTIN_REGISTRIES.items()
        }
        translations = {}
        for locale in ("en_us", "zh_cn"):
            for key in sorted(self.resources):
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
        for key in self.resources:
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
            "icons": resolved,
            "model_fallbacks": model_only,
            "rendered_models": sum(
                1 for item in self.items.values() if item.render_status == "rendered_model"
            ),
            "pending": sum(1 for item in self.items.values() if item.render_status == "missing"),
            "resources": len(self.resources),
            "registries": sum(len(values) for values in self.registries.values()),
        }
