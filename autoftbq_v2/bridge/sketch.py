"""Bounded, image-only layout input. Never translate strokes into inferred nodes."""
import base64
import struct
from .protocol import ProtocolError


def validate_sketch(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"image_data_url", "mode"}:
        raise ProtocolError("画板附件格式错误")
    mode = value["mode"]
    url = value["image_data_url"]
    prefix = "data:image/png;base64,"
    if mode not in {"shape", "nodes"} or not isinstance(url, str) or not url.startswith(prefix):
        raise ProtocolError("画板仅支持 PNG 图片及外形/节点优先模式")
    if len(url) > 3_000_000:
        raise ProtocolError("画板图片过大，请简化草图")
    try:
        raw = base64.b64decode(url[len(prefix):], validate=True)
        if raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
            raise ValueError()
        w, h = struct.unpack('>II', raw[16:24])
        if not (64 <= w <= 2048 and 64 <= h <= 2048 and w * h <= 2_097_152):
            raise ValueError()
        from PySide6.QtGui import QImage
        image = QImage.fromData(raw, "PNG")
        if image.isNull() or image.width() != w or image.height() != h:
            raise ValueError()
    except Exception as exc:
        raise ProtocolError("画板 PNG 无效或尺寸超限（最长边 2048）") from exc
    return {"image_data_url": url, "mode": mode}


def enforce_new_chapter_only(base, operations, owned_chapters):
    """Only new objects in a single request-owned chapter may be modified."""
    existing = {str(c['id']).upper() for c in base.get('chapters', [])}
    existing.update(str(q['id']).upper() for c in base.get('chapters', []) for q in c.get('quests', []))
    parents = {str(q['id']).upper(): str(c['id']).upper()
               for c in base.get('chapters', []) for q in c.get('quests', [])}
    objects = {str(o['id']).upper(): str(c['id']).upper()
               for c in base.get('chapters', []) for q in c.get('quests', [])
               for o in q.get('tasks', []) + q.get('rewards', []) if 'id' in o}
    allowed = set(owned_chapters)
    for op in operations:
        kind = op.get('kind')
        if kind == 'upsert_chapter_raw':
            cid = op['chapter_id'].upper()
            if cid in existing and cid not in allowed:
                raise ProtocolError("草图生成第一版仅允许新建章节，不能修改已有章节")
            allowed.add(cid)
            if len(allowed) != 1:
                raise ProtocolError("每张草图只能生成一个新章节")
        elif kind == 'upsert_quest_raw':
            cid, qid = op['chapter_id'].upper(), op['quest_id'].upper()
            if cid not in allowed or (qid in existing and parents.get(qid) not in allowed):
                raise ProtocolError("草图任务必须属于本次新建章节")
            parents[qid] = cid
        elif kind == 'upsert_quest_object_raw':
            oid = op['object_id'].upper()
            if parents.get(op['quest_id'].upper()) not in allowed or (oid in objects and objects[oid] not in allowed):
                raise ProtocolError("草图条件只能写入本次新建任务")
        elif kind == 'delete_quest' and parents.get(op['quest_id'].upper()) in allowed:
            pass
        elif kind == 'remove_quest_object' and objects.get(op['object_id'].upper()) in allowed:
            pass
        else:
            raise ProtocolError("草图生成不能删除对象或修改全局配置")
    return allowed
