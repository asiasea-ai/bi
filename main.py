#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import argparse

# ==================== 多用户状态隔离 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_session_file(user_id: str) -> str:
    # 防止路径注入攻击，清理 user_id 中的非法字符
    safe_user_id = "".join(c for c in user_id if c.isalnum() or c in ('-', '_'))
    if not safe_user_id:
        safe_user_id = "anonymous"
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
    session_file = get_session_file(user_id)
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==================== 纯粹的数据提供者 ====================

def initialize(user_id: str, ctx: dict) -> dict:
    ctx["initialized"] = True
    ctx["system_name"] = "销售系统" # 默认系统
    save_session(user_id, ctx)
    return {
        "status": "success",
        "message": "系统初始化完成，权限已加载。默认进入【销售系统】。"
    }

def list_systems(user_id: str, ctx: dict) -> dict:
    if not ctx.get("initialized"):
        return {"error": "权限未就绪，请先执行初始化。"}
    
    return {
        "status": "success",
        "systems": ["销售系统", "库存系统", "财务系统"],
        "current_system": ctx.get("system_name")
    }

def switch_system(user_id: str, ctx: dict, args: dict) -> dict:
    if not ctx.get("initialized"):
        return {"error": "权限未就绪，请先执行初始化。"}
    
    target_system = args.get("system_name")
    valid_systems = ["销售系统", "库存系统", "财务系统"]
    
    if target_system not in valid_systems:
        return {"error": f"系统 {target_system} 不存在，可用系统: {', '.join(valid_systems)}"}
    
    ctx["system_name"] = target_system
    save_session(user_id, ctx)
    return {"status": "success", "message": f"成功切换至 {target_system}"}

def query_bi_data(user_id: str, ctx: dict, args: dict) -> dict:
    if not ctx.get("initialized"):
        return {"error": "权限未就绪，请先要求进行系统初始化。"}
    
    system = ctx.get("system_name")
    metric = args.get("metric")
    time_range = args.get("time_range")
    
    if not metric or not time_range:
        return {"error": "缺少必填参数: metric 或 time_range，请向用户询问具体指标和时间范围。"}
    
    # 模拟从后端数据库拉取真实数据
    mock_data = {
        "system_source": system,
        "query_metric": metric,
        "query_time": time_range,
        "data_points": [
            {"label": f"{time_range}期初", "value": 15000},
            {"label": f"{time_range}期末", "value": 32500}
        ],
        "growth_rate": "116.6%"
    }
    return {"status": "success", "data": mock_data}

# ==================== 健壮的执行入口 ====================

def main():
    parser = argparse.ArgumentParser(description="金灯塔胜算 Skill 执行器")
    # 移除 required=True，避免 argparse 触发内部 sys.exit() 导致引擎拿不到 JSON
    parser.add_argument("--action", help="要执行的工具名称")
    parser.add_argument("--args-json", default="{}", help="参数 JSON")
    
    opts, _ = parser.parse_known_args()

    if not opts.action:
        print(json.dumps({"error": "缺少核心参数 --action，无法路由具体工具。"}, ensure_ascii=False))
        return

    # 防崩溃 JSON 解析
    try:
        args = json.loads(opts.args_json) if opts.args_json else {}
    except Exception as e:
        print(json.dumps({"error": f"JSON 参数解析失败: {str(e)}"}, ensure_ascii=False))
        return

    # 强制校验 user_id
    user_id = args.get("user_id")
    if not user_id:
        print(json.dumps({"error": "缺少核心鉴权参数 user_id，无法执行。"}, ensure_ascii=False))
        return

    ctx = load_session(user_id)
    result = {}

    # 路由分配
    if opts.action == "initialize":
        result = initialize(user_id, ctx)
    elif opts.action == "list_systems":
        result = list_systems(user_id, ctx)
    elif opts.action == "switch_system":
        result = switch_system(user_id, ctx, args)
    elif opts.action == "query_bi_data":
        result = query_bi_data(user_id, ctx, args)
    else:
        result = {"error": f"不支持的操作 (action): {opts.action}"}

    # 永远以标准 JSON 格式向框架侧输出
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()