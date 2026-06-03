"""
骰子引擎 — 基于 noveldemo/tools/roller.py 迁移，提供 HTTP API 封装。
确定性计算，结果不可被 LLM 更改。
"""
import random
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

# ── 常量 ────────────────────────────────────────────────────────────────────

ATTRIBUTES = ["strength", "dexterity", "stamina", "intelligence", "spirit", "charisma", "composure"]
ATTR_SHORT = {
    "strength": "STR", "dexterity": "DEX", "stamina": "STA",
    "intelligence": "INT", "spirit": "SPI", "charisma": "CHA", "composure": "COM"
}

BODY_PARTS = ["head", "torso", "left_arm", "right_arm", "left_leg", "right_leg"]
PART_BASE_HP_MULT = {"head": 2, "torso": 3, "left_arm": 1.5, "right_arm": 1.5, "left_leg": 1.5, "right_leg": 1.5}
HIT_TABLE = [(1, 2, "head"), (3, 5, "torso"), (6, 7, "left_arm"), (8, 8, "right_arm"),
             (9, 9, "left_leg"), (10, 10, "right_leg")]

# ── Pydantic 请求/响应模型 ────────────────────────────────────────────────────

class RollRequest(BaseModel):
    pool: Optional[int] = Field(None, ge=0, description="直接指定骰池大小（与 attribute 二选一）")
    attribute: Optional[str] = Field(None, description="属性名（需配合 character_data）")
    skill: Optional[str] = Field(None, description="技能名")
    modifier: int = Field(0, description="骰池修正值")
    threshold: int = Field(8, ge=1, le=10, description="成功阈值")
    character_data: Optional[dict] = Field(None, description="角色数据 JSON（可选，用于属性计算）")
    reason: str = Field("", description="判定原因（用于归档和叙事）")
    session_id: Optional[str] = Field(None)
    message_id: Optional[str] = Field(None)
    seed: Optional[int] = Field(None, description="随机种子（指定后结果可复现，用于回放/审计）")

class DiceRollResult(BaseModel):
    pool: int
    threshold: int
    rolls: list[int]
    successes: int
    ones: int
    net: int
    result: str
    botch: bool
    verdict: str          # success / failure / botch / critical
    narrative_hint: str   # 叙事建议
    attribute: str = ""
    skill: str = ""
    reason: str = ""
    pool_formula: str = ""
    timestamp: str = ""
    seed: Optional[int] = None

# ── 核心骰子函数 ──────────────────────────────────────────────────────────────

def roll_dice_pool(pool: int, threshold: int = 8, seed: Optional[int] = None) -> dict:
    """
    d10 骰池判定，10 重骰（额外成功），1 抵消成功。
    seed 参数可指定随机种子，使结果可复现（用于回放和审计）。
    """
    if pool <= 0:
        return {
            "pool": 0, "threshold": threshold, "rolls": [], "successes": 0,
            "ones": 0, "net": 0, "result": "失败", "botch": False,
            "verdict": "failure", "narrative_hint": "没有成功，且无严重后果。",
            "timestamp": datetime.now().isoformat(),
            "seed": seed,
        }
    rng = random.Random(seed) if seed is not None else random
    rolls = [rng.randint(1, 10) for _ in range(pool)]
    successes = sum(1 + (r == 10) for r in rolls if r >= threshold)
    ones = sum(1 for r in rolls if r == 1)
    net = max(0, successes - ones)
    botch = net <= 0 and ones >= max(1, pool // 2)

    if botch:
        result, verdict = "大失败 (Botch!)", "botch"
        narrative_hint = "最糟的情形。描写完全失控与意外后果，可能伤及自身或盟友。"
    elif net == 0:
        result, verdict = "失败", "failure"
        narrative_hint = "没有成功，但无严重后果。描写行动受阻或被迫放弃。"
    elif net == 1:
        result, verdict = "勉强成功", "success"
        narrative_hint = "险之又险的成功，有明显代价或副作用。"
    elif net <= 3:
        result, verdict = "成功", "success"
        narrative_hint = "稳健成功。描写动作的流畅和掌控感。"
    elif net <= 5:
        result, verdict = "大成功!", "critical"
        narrative_hint = "大成功！可附加额外好处，描写惊艳时刻。"
    else:
        result, verdict = "传奇成功!!", "critical"
        narrative_hint = "传说级成功。描写近乎神迹的表现，留下深刻印象。"

    return {
        "pool": pool, "threshold": threshold, "rolls": rolls,
        "successes": successes, "ones": ones, "net": net,
        "result": result, "botch": botch,
        "verdict": verdict, "narrative_hint": narrative_hint,
        "timestamp": datetime.now().isoformat(),
        "seed": seed,
    }


def random_hit_location() -> str:
    r = random.randint(1, 10)
    for lo, hi, part in HIT_TABLE:
        if lo <= r <= hi:
            return part
    return "torso"


def part_status(hp: int, max_hp: int) -> str:
    if hp <= 0:
        return "lost"
    pct = hp / max_hp
    if pct > 0.75:
        return "intact"
    if pct > 0.50:
        return "light"
    if pct > 0.25:
        return "heavy"
    return "crippled"


# ── 角色属性计算（简化版，从 character_data 读取）────────────────────────────

def _effective_attr(char_data: dict, attr: str) -> int:
    attrs = char_data.get("attributes", {})
    a = attrs.get(attr, {"base": 1, "equip": 0, "status": 0, "temp": 0})
    total = a.get("base", 1) + a.get("equip", 0) + a.get("status", 0) + a.get("temp", 0)
    # 部位减值
    body_parts = char_data.get("body_parts", {})
    penalty = 0
    for part, bp in body_parts.items():
        s = part_status(bp.get("hp", bp.get("max_hp", 1)), bp.get("max_hp", 1))
        if s == "heavy":
            if part == "head":
                penalty -= 1
            elif part == "torso":
                penalty -= 1
        elif s in ("crippled", "lost"):
            if part in ("head", "torso"):
                penalty -= 3
    # 心理减值
    psych = char_data.get("psychology", {}).get("state", {})
    stress = psych.get("stress", 0)
    if stress >= 75:
        penalty -= 2
    elif stress >= 50:
        penalty -= 1
    if psych.get("morale", 100) <= 25:
        penalty -= 1
    return max(0, total + penalty)


def compute_roll_request(req: RollRequest) -> DiceRollResult:
    """计算骰池并返回结果。"""
    pool = req.pool
    attr_short = ""
    skill_str = ""

    if pool is None and req.attribute and req.character_data:
        base_pool = _effective_attr(req.character_data, req.attribute)
        # 加技能等级
        skill_bonus = 0
        if req.skill:
            skills = req.character_data.get("skills", [])
            sk = next((s for s in skills if s.get("name") == req.skill), None)
            if sk:
                skill_bonus = sk.get("level", 0)
        pool = max(0, base_pool + skill_bonus + req.modifier)
        attr_short = ATTR_SHORT.get(req.attribute, req.attribute)
        skill_str = req.skill or ""
    elif pool is not None:
        pool = max(0, pool + req.modifier)

    if pool is None:
        pool = max(0, req.modifier)

    # 若未指定 seed，从 session_id + message_id 派生稳定种子（支持回放复现）
    seed = req.seed
    if seed is None and req.session_id and req.message_id:
        # 混合哈希：session 前8字节 + message 前8字节 → 确定性种子
        seed_str = (req.session_id[:8] + req.message_id[:8]).encode("utf-8")
        seed = int.from_bytes(seed_str, "big") & 0x7FFFFFFF
    raw = roll_dice_pool(pool, req.threshold, seed=seed)

    formula_parts = []
    if attr_short:
        formula_parts.append(attr_short)
    if skill_str:
        formula_parts.append(f"+{skill_str}")
    if req.modifier != 0:
        formula_parts.append(f"{'+'if req.modifier>0 else ''}{req.modifier}")
    pool_formula = "".join(formula_parts) if formula_parts else f"{pool}d"

    return DiceRollResult(
        **raw,
        attribute=attr_short,
        skill=skill_str,
        reason=req.reason,
        pool_formula=pool_formula,
    )


# ── JSONL 归档 ───────────────────────────────────────────────────────────────

_ARCHIVE_DIR: Optional[Path] = None


def set_archive_dir(path: Path) -> None:
    global _ARCHIVE_DIR
    _ARCHIVE_DIR = path
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def log_roll(result: DiceRollResult, session_id: str = "", message_id: str = "") -> None:
    if _ARCHIVE_DIR is None:
        return
    log_file = _ARCHIVE_DIR / f"rolls_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    entry = result.model_dump()
    entry["session_id"] = session_id
    entry["message_id"] = message_id
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
