"""
全局资产库路由：NPC 模板 + 物品模板 CRUD，以及导入到会话的操作。
"""
from __future__ import annotations
import json
import time
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class CreateNpcTemplateRequest(BaseModel):
    name: str
    key: str = ""
    plugin_key: str = "crossover"
    profile_json: dict = {}


class UpdateNpcTemplateRequest(BaseModel):
    name: Optional[str] = None
    plugin_key: Optional[str] = None
    profile_json: Optional[dict] = None


class ImportNpcRequest(BaseModel):
    session_id: str


class CreateItemTemplateRequest(BaseModel):
    name: str
    item_type: str = "equipment"
    plugin_key: str = "crossover"
    data_json: dict = {}


class UpdateItemTemplateRequest(BaseModel):
    name: Optional[str] = None
    item_type: Optional[str] = None
    plugin_key: Optional[str] = None
    data_json: Optional[dict] = None


class GrantItemRequest(BaseModel):
    session_id: str
    quantity: int = 1


# ── NPC 模板路由 ──────────────────────────────────────────────────────────────

@router.get("/assets/npcs")
async def list_npc_templates(plugin_key: Optional[str] = None):
    async with get_db() as db:
        if plugin_key:
            rows = await (await db.execute(
                "SELECT * FROM npc_templates WHERE plugin_key=? ORDER BY name ASC",
                (plugin_key,)
            )).fetchall()
        else:
            rows = await (await db.execute(
                "SELECT * FROM npc_templates ORDER BY name ASC"
            )).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["profile_json"] = json.loads(d.get("profile_json") or "{}")
        except Exception:
            d["profile_json"] = {}
        result.append(d)
    return {"npcs": result}


@router.post("/assets/npcs")
async def create_npc_template(req: CreateNpcTemplateRequest):
    nid = str(uuid.uuid4())
    now = time.time()
    key = req.key or req.name.lower().replace(" ", "_").replace("-", "_")
    # Ensure key uniqueness
    async with get_db() as db:
        existing = await (await db.execute(
            "SELECT id FROM npc_templates WHERE key=?", (key,)
        )).fetchone()
        if existing:
            key = f"{key}_{nid[:8]}"
        await db.execute(
            "INSERT INTO npc_templates (id, name, key, plugin_key, profile_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (nid, req.name, key, req.plugin_key, json.dumps(req.profile_json, ensure_ascii=False), now, now)
        )
        await db.commit()
    return {"npc_id": nid, "key": key, "name": req.name}


@router.patch("/assets/npcs/{nid}")
async def update_npc_template(nid: str, req: UpdateNpcTemplateRequest):
    async with get_db() as db:
        row = await (await db.execute("SELECT id FROM npc_templates WHERE id=?", (nid,))).fetchone()
        if not row:
            raise HTTPException(404, "NPC template not found")
        updates, vals = [], []
        if req.name is not None: updates.append("name=?"); vals.append(req.name)
        if req.plugin_key is not None: updates.append("plugin_key=?"); vals.append(req.plugin_key)
        if req.profile_json is not None:
            updates.append("profile_json=?")
            vals.append(json.dumps(req.profile_json, ensure_ascii=False))
        if updates:
            vals += [time.time(), nid]
            await db.execute(f"UPDATE npc_templates SET {','.join(updates)},updated_at=? WHERE id=?", vals)
            await db.commit()
    return {"ok": True}


@router.delete("/assets/npcs/{nid}")
async def delete_npc_template(nid: str):
    async with get_db() as db:
        await db.execute("DELETE FROM npc_templates WHERE id=?", (nid,))
        await db.commit()
    return {"ok": True}


@router.post("/assets/npcs/{nid}/import")
async def import_npc_to_session(nid: str, req: ImportNpcRequest):
    """将全局 NPC 模板导入到指定会话的 npc_profiles 中。"""
    async with get_db() as db:
        tmpl = await (await db.execute("SELECT * FROM npc_templates WHERE id=?", (nid,))).fetchone()
        if not tmpl:
            raise HTTPException(404, "NPC template not found")
        # Check session exists
        sess = await (await db.execute("SELECT id FROM sessions WHERE id=?", (req.session_id,))).fetchone()
        if not sess:
            raise HTTPException(404, "Session not found")

        now = time.time()
        new_id = str(uuid.uuid4())
        key = dict(tmpl)["key"]

        # Check for key conflict in session
        existing = await (await db.execute(
            "SELECT id FROM npc_profiles WHERE session_id=? AND key=?", (req.session_id, key)
        )).fetchone()
        if existing:
            return {"ok": True, "message": "NPC already exists in session", "npc_id": dict(existing)["id"]}

        await db.execute(
            "INSERT INTO npc_profiles (id, session_id, key, name, profile_json, world_key, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (new_id, req.session_id, key, dict(tmpl)["name"],
             dict(tmpl)["profile_json"], "", now, now)
        )
        await db.commit()
    return {"ok": True, "npc_id": new_id, "key": key}


# ── 物品模板路由 ──────────────────────────────────────────────────────────────

@router.get("/assets/items")
async def list_item_templates(item_type: Optional[str] = None, plugin_key: Optional[str] = None):
    async with get_db() as db:
        conditions, vals = [], []
        if item_type: conditions.append("item_type=?"); vals.append(item_type)
        if plugin_key: conditions.append("plugin_key=?"); vals.append(plugin_key)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await (await db.execute(
            f"SELECT * FROM item_templates {where} ORDER BY name ASC", vals
        )).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["data_json"] = json.loads(d.get("data_json") or "{}")
        except Exception:
            d["data_json"] = {}
        result.append(d)
    return {"items": result}


@router.post("/assets/items")
async def create_item_template(req: CreateItemTemplateRequest):
    iid = str(uuid.uuid4())
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO item_templates (id, name, item_type, plugin_key, data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (iid, req.name, req.item_type, req.plugin_key,
             json.dumps(req.data_json, ensure_ascii=False), now, now)
        )
        await db.commit()
    return {"item_id": iid, "name": req.name}


@router.patch("/assets/items/{iid}")
async def update_item_template(iid: str, req: UpdateItemTemplateRequest):
    async with get_db() as db:
        row = await (await db.execute("SELECT id FROM item_templates WHERE id=?", (iid,))).fetchone()
        if not row:
            raise HTTPException(404, "Item template not found")
        updates, vals = [], []
        if req.name is not None: updates.append("name=?"); vals.append(req.name)
        if req.item_type is not None: updates.append("item_type=?"); vals.append(req.item_type)
        if req.plugin_key is not None: updates.append("plugin_key=?"); vals.append(req.plugin_key)
        if req.data_json is not None:
            updates.append("data_json=?")
            vals.append(json.dumps(req.data_json, ensure_ascii=False))
        if updates:
            vals += [time.time(), iid]
            await db.execute(f"UPDATE item_templates SET {','.join(updates)},updated_at=? WHERE id=?", vals)
            await db.commit()
    return {"ok": True}


@router.delete("/assets/items/{iid}")
async def delete_item_template(iid: str):
    async with get_db() as db:
        await db.execute("DELETE FROM item_templates WHERE id=?", (iid,))
        await db.commit()
    return {"ok": True}


@router.post("/assets/items/{iid}/grant")
async def grant_item_to_session(iid: str, req: GrantItemRequest):
    """将物品模板添加到指定会话角色卡的 inventory 中。"""
    async with get_db() as db:
        item = await (await db.execute("SELECT * FROM item_templates WHERE id=?", (iid,))).fetchone()
        if not item:
            raise HTTPException(404, "Item template not found")
        char_row = await (await db.execute(
            "SELECT id, data_json FROM character_cards WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
            (req.session_id,)
        )).fetchone()
        if not char_row:
            raise HTTPException(404, "Character card not found for session")

        char_data = json.loads(dict(char_row)["data_json"] or "{}")
        item_data = dict(item)
        try:
            item_props = json.loads(item_data.get("data_json") or "{}")
        except Exception:
            item_props = {}

        inventory: list = char_data.get("inventory", [])
        inventory.append({
            "id": str(uuid.uuid4()),
            "name": item_data["name"],
            "type": item_data["item_type"],
            "quantity": req.quantity,
            "description": item_props.get("description", ""),
            **{k: v for k, v in item_props.items() if k != "description"},
        })
        char_data["inventory"] = inventory

        await db.execute(
            "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
            (json.dumps(char_data, ensure_ascii=False), time.time(), dict(char_row)["id"])
        )
        await db.commit()
    return {"ok": True, "item_name": item_data["name"], "quantity": req.quantity}
