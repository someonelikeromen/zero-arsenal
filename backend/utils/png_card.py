"""
用途: PNG 角色卡（SillyTavern / Chub.ai 格式）编解码 —— 在 PNG tEXt chunk 中嵌入角色 JSON。
用法（import 调用）:
    from backend.utils.png_card import encode_card, decode_card
    png_bytes = encode_card(base_png_or_none, payload_dict)
    payload   = decode_card(png_bytes)   # -> dict（已自动解 V2 data 包裹）
环境变量: 无
MCP集成: 可直接包装；核心函数 encode_card / decode_card 均为纯函数。
Skill集成: 由 characters 路由的 import-png / export-png 端点调用。

兼容性：
- 解码识别 tEXt 关键字 "chara"（SillyTavern/Chub 通用），值为 base64(JSON)
- V2 格式 {"spec":"chara_card_v2","data":{...}} 会自动提取 data
- 编码生成一张占位 PNG（纯色方块），并写入 "chara" tEXt chunk
"""
from __future__ import annotations
import base64
import json
import struct
import zlib
from typing import Optional


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    """构造一个 PNG chunk：长度(4) + 类型(4) + 数据 + CRC(4)。"""
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _make_placeholder_png(size: int = 64, rgb: tuple[int, int, int] = (63, 63, 70)) -> bytes:
    """生成一张纯色 PNG（默认 zinc-700 灰），作为无头像角色卡的载体。"""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8bit, color type 2 (RGB)
    # 原始扫描行：每行前缀 filter byte 0
    row = b"\x00" + bytes(rgb) * size
    raw = row * size
    idat = zlib.compress(raw, 9)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _iter_chunks(png: bytes):
    """迭代 PNG chunks，yield (type_bytes, data_bytes, full_chunk_bytes)。"""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是有效的 PNG 文件")
    pos = 8
    while pos < len(png):
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        ctype = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        full = png[pos:pos + 12 + length]
        yield ctype, data, full
        pos += 12 + length
        if ctype == b"IEND":
            break


def encode_card(base_png: Optional[bytes], payload: dict) -> bytes:
    """
    将 payload（角色 JSON）写入 PNG 的 "chara" tEXt chunk。
    base_png 为 None 时生成占位 PNG。已有的 chara chunk 会被替换。
    """
    png = base_png or _make_placeholder_png()
    b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    text_data = b"chara\x00" + b64
    new_chunk = _chunk(b"tEXt", text_data)

    out = bytearray(png[:8])
    inserted = False
    for ctype, data, full in _iter_chunks(png):
        # 跳过已有的 chara tEXt（避免重复）
        if ctype == b"tEXt" and data.startswith(b"chara\x00"):
            continue
        if ctype == b"IEND" and not inserted:
            out += new_chunk
            inserted = True
        out += full
    if not inserted:
        # 没有 IEND（异常），直接追加
        out += new_chunk
    return bytes(out)


def decode_card(png: bytes) -> dict:
    """
    从 PNG 中提取 "chara" tEXt chunk 并解析为角色 JSON dict。
    自动剥离 V2 包裹（spec/data）。失败抛 ValueError。
    """
    for ctype, data, _full in _iter_chunks(png):
        if ctype == b"tEXt" and data.startswith(b"chara\x00"):
            b64 = data[len(b"chara\x00"):]
            try:
                raw = base64.b64decode(b64).decode("utf-8")
                obj = json.loads(raw)
            except Exception as e:
                raise ValueError(f"chara chunk 解析失败: {e}")
            # V2: {"spec":"chara_card_v2","data":{...}}
            if isinstance(obj, dict) and "data" in obj and isinstance(obj["data"], dict):
                return obj["data"]
            return obj
    raise ValueError("PNG 中未找到角色卡数据（缺少 chara tEXt chunk）")
