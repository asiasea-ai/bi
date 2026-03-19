#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os

# ==================== 多用户状态隔离 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_session_file(user_id: str) -> str:
    # 防注入处理，如果没有传入 user_id 则使用默认沙箱
    safe_user_id = "".join(c for c in str(user_id) if c.isalnum() or c in ('-', '_')) if user_id else "default_user"
    return os.path.join(BASE_DIR, f".session_{safe_user_id}.json")

def load_session(user_id: str) -> dict:
    session_file = get_session_file(user_id)
    if os.path.exists(session_file):
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"initialized": False, "system_name": None}

def save_session(user_id: str, data: dict):
    with open(get_session_file(user_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==================== OpenClaw 唯一指定入口 ====================

def handle(command: str, args: list, **kwargs) -> str:
    """
    OpenClaw 引擎要求的主入口函数。
    返回的字符串将直接作为机器人的回复输出。
    """
    # OpenClaw 通常会将上下文参数放在 kwargs 中，尝试提取 user_id
    user_id = kwargs.get("user_id", kwargs.get("sender_id", "default_user"))
    ctx = load_session(user_id)
    
    # 指令标准化处理
    cmd = command.strip().lstrip('/')
    full_text = cmd + " " + " ".join(args)

    # 1. 路由：初始化
    if cmd in ["金灯塔BI 初始化", "初始化"]:
        ctx["initialized"] = True
        ctx["system_name"] = "销售系统"
        save_session(user_id, ctx)
        return "✅ **金灯塔BI系统初始化完成**\n\n权限已加载。默认进入【销售系统】。\n💡 提示：您可以输入「系统列表」查看所有系统，或输入「切换系统 财务系统」进行切换。"

    # 2. 路由：系统列表
    elif cmd == "系统列表":
        if not ctx.get("initialized"):
            return "⚠️ 权限未就绪，请先发送「初始化」。"
        
        curr = ctx.get("system_name")
        return f"📋 **支持的业务系统：**\n1. 销售系统 {'✅' if curr == '销售系统' else ''}\n2. 库存系统 {'✅' if curr == '库存系统' else ''}\n3. 财务系统 {'✅' if curr == '财务系统' else ''}"

    # 3. 路由：切换系统
    elif cmd.startswith("切换系统"):
        if not ctx.get("initialized"):
            return "⚠️ 权限未就绪，请先发送「初始化」。"
        
        if not args:
            return "❌ 请指定要切换的系统，例如：`切换系统 财务系统`"
            
        target_system = args[0]
        valid_systems = ["销售系统", "库存系统", "财务系统"]
        
        if target_system not in valid_systems:
            return f"❌ 系统 '{target_system}' 不存在，可用系统: {', '.join(valid_systems)}"
        
        ctx["system_name"] = target_system
        save_session(user_id, ctx)
        return f"✅ 成功切换至 **{target_system}** 环境。"

    # 4. 路由：BI 数据查询（保留了强制要求时间和指标的防呆设计）
    elif any(kw in cmd for kw in ["报表", "数据看板", "BI", "统计", "分析", "查询"]):
        if not ctx.get("initialized"):
            return "⚠️ 权限未就绪，请先发送「初始化」后再查询数据。"
        
        system = ctx.get("system_name")
        
        # 强制参数提取：如果用户没带时间词汇，强制追问，不给默认值
        time_range = ""
        if any(t in full_text for t in ["月", "周", "天", "日", "昨", "年"]):
            time_range = "指定时间段"
        else:
            return "⚠️ 请补充**时间范围**（如：上个月、昨天、最近7天）。\n例如：`查询上个月的销售额`。"
            
        # 强制参数提取：识别指标
        metric = ""
        if "销售" in full_text: metric = "销售额"
        elif "订单" in full_text: metric = "订单量"
        elif "库存" in full_text: metric = "库存"
        else:
            return "⚠️ 请补充**查询指标**（如：销售额、订单量）。\n例如：`查询昨天的订单量`。"

        # 返回格式化好的最终文案
        return f"""📊 **{system} - {metric} 报表**

⏱ 查询范围：{time_range}
- 期初数据：15,000
- 期末数据：32,500
- 环比增长：116.6%

*(以上为模拟演示数据)*"""

    else:
        return f"收到未识别的指令：{command}。您可以尝试发送「初始化」或「系统列表」。"