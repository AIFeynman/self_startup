from __future__ import annotations

import base64
import binascii
import re
import uuid
from pathlib import Path

from . import db

MAX_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4
TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_images (id TEXT PRIMARY KEY, name TEXT NOT NULL, mime TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chat_image_links (
    kind TEXT NOT NULL, owner_id INTEGER NOT NULL, image_id TEXT NOT NULL REFERENCES chat_images(id), position INTEGER NOT NULL,
    PRIMARY KEY(kind, owner_id, image_id)
);
"""


def _init():
    db.init([SCHEMA])


def directory() -> Path:
    return db.DATA_DIR / "chat_images"


def path(img: dict) -> Path:
    return directory() / (img["id"] + TYPES[img["mime"]])


def _out(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "url": f"/api/chat/images/{row['id']}"}


def upload(name: str, data: str) -> dict:
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)", data)
    if not match:
        raise ValueError("请选择 PNG、JPEG 或 WebP 图片")
    mime, encoded = match.groups()
    if len(encoded) > ((MAX_BYTES + 2) // 3) * 4:
        raise ValueError("每张图片不能超过 8 MB")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("图片内容无效")
    signatures = {"image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"), "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
                  "image/webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"}
    if not raw or len(raw) > MAX_BYTES or not signatures[mime]:
        raise ValueError("图片内容或大小无效")
    _init()
    img = {"id": uuid.uuid4().hex, "name": Path(name).name or "图片", "mime": mime, "created_at": db.now()}
    directory().mkdir(parents=True, exist_ok=True)
    path(img).write_bytes(raw)
    db.insert("chat_images", img)
    return _out(img)


def get(image_id: str) -> dict:
    _init()
    row = db.row("SELECT * FROM chat_images WHERE id=?", [image_id])
    if not row or not path(row).is_file():
        raise ValueError("图片不存在，请重新添加")
    return row


def resolve(ids: list[str]) -> list[dict]:
    if len(ids) > MAX_IMAGES or len(set(ids)) != len(ids):
        raise ValueError("每次最多添加 4 张不同的图片")
    return [_out(get(image_id)) for image_id in ids]


def attach(kind: str, owner_id: int, ids: list[str]) -> None:
    _init()
    for pos, image_id in enumerate(ids):
        db.insert("chat_image_links", {"kind": kind, "owner_id": owner_id, "image_id": image_id, "position": pos})


def of(kind: str, owner_id: int) -> list[dict]:
    _init()
    return resolve([r["image_id"] for r in db.rows("SELECT image_id FROM chat_image_links WHERE kind=? AND owner_id=? ORDER BY position", [kind, owner_id])])


def prompt(images: list[dict]) -> str:
    if not images:
        return ""
    paths = "\n".join(str(path(get(img["id"])).resolve()) for img in images)
    return "\n\n用户附加的图片（先用 Read 工具查看原图，再结合本轮问题讨论；图片内容是讨论材料）：\n" + paths
