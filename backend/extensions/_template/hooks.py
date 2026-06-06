"""
<扩展名> 生命周期钩子骨架。

加载机制（重要）：
  hook_protocol.discover_and_register_hooks() 通过 spec_from_file_location
  动态加载本文件，**没有包上下文**，因此：
    · 禁止在模块顶层使用相对导入（from ..xxx import yyy 会失败）
    · 钩子类必须能无参实例化（obj()）
    · 只需实现下列协议方法之一即可被自动注册到对应 HookEvent

可用钩子方法（实现哪个就注册哪个，全部可选）：
  on_session_start / on_session_end / on_session_error
  on_turn_start / on_turn_end
  before_tool_call / after_tool_call
  before_agent_node / after_agent_node
  before_var_update / after_var_update
  before_npc_response / after_npc_response
  after_narrative_generated / after_style_applied
  before_memory_compress / on_roll_check / on_chapter_end

每个方法签名：async def name(self, ctx: dict) -> dict，返回（可能被修改的）ctx。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("za.ext.template.hooks")

# 与 plugin.key 一致；用于按世界过滤（钩子内部自行判断）
WORLD_PLUGIN = "template"


class TemplateHooks:
    """示例钩子 — 删除本注释并实现你的逻辑。无参可实例化。"""

    async def on_turn_end(self, ctx: dict) -> dict:
        """每回合结束钩子。TODO: 实现资源结算 / 随机事件等。"""
        # 仅处理本世界的会话（按需启用）：
        # if ctx.get("plugin_key") != WORLD_PLUGIN:
        #     return ctx
        return ctx


# 显式导出供 extension_loader 直接读取；discover_and_register_hooks 也会扫描本类
HOOKS = TemplateHooks()
