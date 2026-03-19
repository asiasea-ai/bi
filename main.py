#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import datetime
import requests

# ==================== 多用户状态隔离 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_session_file(user_id: str) -> str:
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
    return {
        "initialized": False, 
        "user_phone": None,
        "system_name": None,
        "system_id": None,
        "system_auth_headers": {},  
        "api_registry": [],
        "last_report_url": None,
        "last_report_title": None
    }

def save_session(user_id: str, data: dict):
    with open(get_session_file(user_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==================== 时间解析引擎 ====================
def parse_time_keywords(full_text: str):
    now = datetime.datetime.now()
    start_date, end_date = None, None
    time_desc = ""

    if "本月" in full_text:
        start_date = now.replace(day=1).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")
        time_desc = "本月"
    elif "上个月" in full_text or "上月" in full_text:
        first_day_this_month = now.replace(day=1)
        last_day_last_month = first_day_this_month - datetime.timedelta(days=1)
        start_date = last_day_last_month.replace(day=1).strftime("%Y-%m-%d")
        end_date = last_day_last_month.strftime("%Y-%m-%d")
        time_desc = "上个月"
    elif "昨天" in full_text or "昨日" in full_text:
        yesterday = now - datetime.timedelta(days=1)
        start_date = yesterday.strftime("%Y-%m-%d")
        end_date = start_date
        time_desc = "昨天"
    elif "今天" in full_text or "今日" in full_text:
        start_date = now.strftime("%Y-%m-%d")
        end_date = start_date
        time_desc = "今天"
    elif "本周" in full_text:
        start_date = (now - datetime.timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")
        time_desc = "本周"
    elif "上周" in full_text:
        last_sunday = now - datetime.timedelta(days=now.weekday() + 1)
        last_monday = last_sunday - datetime.timedelta(days=6)
        start_date = last_monday.strftime("%Y-%m-%d")
        end_date = last_sunday.strftime("%Y-%m-%d")
        time_desc = "上周"
    elif "今年" in full_text or "本年" in full_text:
        start_date = now.replace(month=1, day=1).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")
        time_desc = "今年"

    return start_date, end_date, time_desc

# ==================== 真实 API 交互工具箱 ====================
def api_get_supported_systems() -> list:
    url = "https://o.yayuit.cn/dw/api/auth/supported-systems"
    try:
        resp = requests.get(url, timeout=5).json()
        if resp.get("code") == 100000:
            return resp.get("result", {}).get("list", [])
    except Exception as e:
        print(f"获取系统列表失败: {e}")
    return []

def api_get_registry(system_id: int) -> list:
    url = f"https://o.yayuit.cn/dw/api/system/api-registry?system_id={system_id}"
    try:
        resp = requests.get(url, timeout=5).json()
        if resp.get("code") == 100000:
            return resp.get("result", {}).get("list", [])
    except Exception as e:
        print(f"获取 API 注册表失败: {e}")
    return []

def api_get_system_token(system_id: int) -> dict:
    url = f"https://o.yayuit.cn/dw/api/auth/system-token?system_id={system_id}"
    try:
        resp = requests.get(url, timeout=5).json()
        if resp.get("code") == 100000:
            return resp.get("result", {}).get("data", {})
    except Exception as e:
        print(f"获取系统鉴权凭证失败: {e}")
    return {}

def api_upload_html_to_oss(html_content: str) -> str:
    url = "https://o.yayuit.cn/dw/api/skills/archive/upload"
    files = {'file': ('bi_report.html', html_content.encode('utf-8'), 'text/html')}
    try:
        resp = requests.post(url, files=files, timeout=10).json()
        if resp.get("code") == 100000:
            return resp.get("result", {}).get("preview_url")
    except Exception:
        pass 
    return ""

# ==================== HTML 报表生成器 (包含前端真实查询交互) ====================
def generate_html_report(system: str, metric: str, time_range: str, start_date: str, end_date: str, 
                         val1_label: str, val1: float, val2_label: str, val2: float,
                         api_url: str, headers_dict: dict) -> str:
    echarts_script_url = "https://jindengta-archive.oss-cn-beijing.aliyuncs.com/theme/web/bi/echarts.min.js"
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 将字典转为 JS 可以直接读取的格式
    headers_json_str = json.dumps(headers_dict, ensure_ascii=False)
    
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{metric} 报表 - {system}</title>
    <script src="{echarts_script_url}"></script>
    <style>
        :root {{ --primary: #5470c6; --bg: #f5f7fa; --card-bg: #ffffff; --text: #333333; --border: #ebeef5; }}
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: var(--bg); color: var(--text); line-height: 1.6; margin: 0; }}
        .container {{ max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }}
        .card {{ background: var(--card-bg); padding: 24px; border-radius: 8px; box-shadow: 0 2px 12px 0 rgba(0,0,0,0.05); }}
        .header-area {{ text-align: center; padding: 30px 20px; background: linear-gradient(135deg, #fff 0%, #f0f2f5 100%); }}
        .header-area h1 {{ margin: 0 0 10px 0; font-size: 28px; color: #2c3e50; }}
        .header-area .meta-info {{ color: #606266; font-size: 14px; display: inline-flex; gap: 10px; align-items: center; }}
        .header-area .meta-info span {{ background: #e4e7ed; padding: 4px 12px; border-radius: 12px; font-weight: 500; }}
        .filter-area {{ display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }}
        .filter-item {{ display: flex; align-items: center; gap: 8px; font-size: 14px; }}
        .filter-item input {{ padding: 6px 12px; border: 1px solid var(--border); border-radius: 4px; outline: none; }}
        .btn-query {{ background: var(--primary); color: white; border: none; padding: 8px 24px; border-radius: 4px; cursor: pointer; font-weight: bold; transition: opacity 0.2s; }}
        .btn-query:hover {{ opacity: 0.8; }}
        .btn-query:disabled {{ background: #a0cfff; cursor: not-allowed; }}
        .bi-area {{ display: flex; flex-direction: column; gap: 20px; }}
        #chart {{ width: 100%; height: 400px; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
        th, td {{ padding: 12px 15px; border-bottom: 1px solid var(--border); }}
        th {{ background-color: #f8f9fa; font-weight: 600; color: #909399; }}
        .summary-area h3 {{ color: var(--primary); margin-top: 0; display: flex; align-items: center; gap: 8px; font-size: 18px; }}
        .summary-content {{ background: #fdfdfd; border-left: 4px solid var(--primary); padding: 15px 20px; margin-bottom: 20px; }}
        .footer-meta {{ margin-top: 20px; padding-top: 15px; border-top: 1px dashed var(--border); font-size: 12px; color: #909399; display: flex; justify-content: space-between; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card header-area">
            <h1>{metric} 报表</h1>
            <div class="meta-info">
                <span>💻 {system}</span>
                <span id="header_time">📅 {time_range}</span>
            </div>
        </div>
        
        <div class="card filter-area">
            <div class="filter-item">
                <label>开始时间:</label>
                <input type="date" id="startDate" value="{start_date}" />
            </div>
            <div class="filter-item">
                <label>结束时间:</label>
                <input type="date" id="endDate" value="{end_date}" />
            </div>
            <button id="queryBtn" class="btn-query" onclick="refreshData()">重新查询</button>
        </div>
        
        <div class="bi-area">
            <div class="card"><div id="chart"></div></div>
            <div class="card">
                <table>
                    <thead><tr><th>数据维度</th><th>数值 (元)</th></tr></thead>
                    <tbody>
                        <tr><td>{val1_label}</td><td id="val1_td">{val1:,.2f}</td></tr>
                        <tr><td>{val2_label}</td><td id="val2_td">{val2:,.2f}</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="card summary-area">
            <h3>📝 智能数据总结</h3>
            <div class="summary-content">
                在【<span id="summary_time">{start_date} 到 {end_date}</span>】内，{system}的{metric}核心指标显示：{val1_label} 为 <strong id="summary_v1">{val1:,.2f}</strong>，{val2_label} 为 <strong id="summary_v2">{val2:,.2f}</strong>。
            </div>
            <div class="footer-meta">
                <span>导出时间：{current_time}</span>
                <span>数据来源：金灯塔 BI 核心引擎 (真实 API 快照)</span>
            </div>
        </div>
    </div>
    
    <script>
        // ECharts 初始化
        var myChart = echarts.init(document.getElementById('chart'));
        
        function updateChart(v1, v2) {{
            myChart.setOption({{
                tooltip: {{ trigger: 'axis' }},
                xAxis: {{ type: 'category', data: ['{val1_label}', '{val2_label}'] }},
                yAxis: {{ type: 'value' }},
                series: [{{ data: [v1, v2], type: 'bar', barWidth: '40%', itemStyle: {{ color: '#5470c6', borderRadius: [4, 4, 0, 0] }}, label: {{ show: true, position: 'top' }} }}]
            }});
        }}
        
        // 初始渲染
        updateChart({val1}, {val2});
        window.addEventListener('resize', function() {{ myChart.resize(); }});

        // 真实业务 API 调用逻辑
        async function refreshData() {{
            const start = document.getElementById('startDate').value;
            const end = document.getElementById('endDate').value;
            if(!start || !end) {{ alert('请选择完整的起止时间'); return; }}

            const btn = document.getElementById('queryBtn');
            btn.innerText = '查询中...';
            btn.disabled = true;

            const metricType = '{metric}';
            const apiUrl = '{api_url}';
            
            // 注入后端的真实鉴权 Header
            const headers = {headers_json_str};
            headers['Content-Type'] = 'application/json';

            // 构造请求参数
            let url = new URL(apiUrl);
            url.searchParams.append('method', 'ALL');
            url.searchParams.append('pageNo', '1');
            url.searchParams.append('pageSize', '25');

            if (metricType === '部门周期预算') {{
                url.searchParams.append('startTime', start);
                url.searchParams.append('endTime', end);
            }} else {{
                url.searchParams.append('createStime', start);
                url.searchParams.append('createEtime', end);
            }}

            try {{
                const response = await fetch(url, {{ method: 'GET', headers: headers }});
                const res = await response.json();
                
                if (res.code === 100000) {{
                    const datas = (res.data && res.data.datas) ? res.data.datas : [];
                    let v1 = 0, v2 = 0;
                    
                    // 根据不同的业务指标提取数据
                    if (metricType === '部门周期预算') {{
                        datas.forEach(item => {{
                            v1 += parseFloat(item.budgetTotal || 0);
                            v2 += parseFloat(item.usedAmount || 0);
                        }});
                    }} else {{
                        datas.forEach(item => {{
                            v1 += parseFloat(item.totalprice || 0);
                            v2 += parseFloat(item.waitHxPrice || 0);
                        }});
                    }}

                    // 更新 UI 数值
                    const formatNum = (num) => num.toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
                    
                    document.getElementById('val1_td').innerText = formatNum(v1);
                    document.getElementById('val2_td').innerText = formatNum(v2);
                    document.getElementById('summary_v1').innerText = formatNum(v1);
                    document.getElementById('summary_v2').innerText = formatNum(v2);
                    document.getElementById('header_time').innerText = `📅 ${{start}} 至 ${{end}}`;
                    document.getElementById('summary_time').innerText = `${{start}} 到 ${{end}}`;
                    
                    // 更新图表
                    updateChart(v1, v2);

                }} else {{
                    alert('查询失败: ' + (res.msg || '未知错误'));
                }}
            }} catch(e) {{
                alert('接口请求异常: ' + e.message);
            }} finally {{
                btn.innerText = '重新查询';
                btn.disabled = false;
            }}
        }}
    </script>
</body>
</html>"""
    return html_content

# ==================== OpenClaw 唯一指定入口 ====================
def handle(command: str, args: list, **kwargs) -> str:
    user_id = kwargs.get("user_id", kwargs.get("sender_id", "default_user"))
    ctx = load_session(user_id)
    
    cmd = command.strip().lstrip('/')
    full_text = cmd + " " + " ".join(args)

    if cmd in ["金灯塔BI 初始化", "初始化"]:
        ctx["initialized"] = True
        ctx["system_name"] = None
        ctx["system_id"] = None
        ctx["system_auth_headers"] = {}  
        ctx["api_registry"] = []
        ctx["user_phone"] = "13800000000" 
        save_session(user_id, ctx)
        return "✅ **金灯塔BI系统初始化完成**\n\n🔒 飞书授权成功，已绑定身份。\n\n💡 **请先选择您要进入的业务系统。**\n您可以输入「系统列表」查看支持的系统，然后回复「切换系统 E网」或「切换系统 供应链系统」进入对应环境。"

    elif cmd == "系统列表":
        if not ctx.get("initialized"): return "⚠️ 权限未就绪，请先发送「初始化」。"
        systems = api_get_supported_systems()
        if not systems: return "❌ 系统列表获取失败，请检查网络或联系管理员。"
        curr = ctx.get("system_name")
        lines = ["📋 **支持的业务系统：**"]
        for sys in systems:
            mark = "✅" if curr == sys.get("system_name") else ""
            lines.append(f"- {sys.get('system_name')} (ID:{sys.get('id')}) {mark}")
        return "\n".join(lines)

    elif cmd.startswith("切换系统"):
        if not ctx.get("initialized"): return "⚠️ 权限未就绪，请先发送「初始化」。"
        if not args: return "❌ 请指定要切换的系统，例如：`切换系统 E网`"
        target_system_name = args[0]
        systems = api_get_supported_systems()
        target_sys = next((s for s in systems if s.get("system_name") == target_system_name), None)
        if not target_sys: return f"❌ 系统 '{target_system_name}' 不存在，请通过「系统列表」确认支持的系统名称。"
        
        sys_id = target_sys.get("id")
        auth_data = api_get_system_token(sys_id)
        if not auth_data: return f"❌ 系统 '{target_system_name}' 切换失败：无法获取系统的访问凭证，请联系管理员。"
            
        api_list = api_get_registry(sys_id)
        ctx["system_name"] = target_system_name
        ctx["system_id"] = sys_id
        ctx["system_auth_headers"] = auth_data  
        ctx["api_registry"] = api_list 
        save_session(user_id, ctx)
        return f"✅ 成功切换至 **{target_system_name}** 环境，系统鉴权已通过。\n📚 动态加载了 {len(api_list)} 个可用数据接口。\n\n您现在可以开始查询了，例如：「查询本月的报销单」。"

    elif any(kw in cmd for kw in ["报表", "数据看板", "BI", "统计", "分析", "查询"]):
        if not ctx.get("initialized"): return "⚠️ 权限未就绪，请先发送「初始化」。"
        
        system = ctx.get("system_name")
        if not system: return "⚠️ 请先选择要查询的业务系统。您可以输入「系统列表」查看支持的系统，并通过「切换系统 <系统名>」进入。"

        start_date, end_date, time_range = parse_time_keywords(full_text)
        if not start_date: return "⚠️ 请补充明确的**时间范围**（如：本月、上个月、昨天）。"

        headers = {"Content-Type": "application/json"}
        headers.update(ctx.get("system_auth_headers", {}))
        
        metric = ""
        val1, val2 = 0.0, 0.0
        val1_label, val2_label = "", ""
        api_url = ""
        
        try:
            if "预算" in full_text: 
                metric = "部门周期预算"
                api_url = "https://e.asagroup.cn/asae-e/yearBudget/query"
                api_params = {"method": "ALL", "pageNo": 1, "pageSize": 25, "startTime": start_date, "endTime": end_date}
                resp = requests.get(api_url, headers=headers, params=api_params, timeout=10).json()
                
                if resp.get("code") == 100000:
                    datas = resp.get("data", {}).get("datas", [])
                    val1 = sum(float(item.get("budgetTotal", 0)) for item in datas)
                    val2 = sum(float(item.get("usedAmount", 0)) for item in datas)
                    val1_label, val2_label = "预算总额 (budgetTotal)", "已用金额 (usedAmount)"
                else:
                    return f"❌ 预算接口业务失败：{resp.get('msg')}"

            elif any(kw in full_text for kw in ["报销", "报销单", "费用"]): 
                metric = "报销单"
                api_url = "https://e.asagroup.cn/asae-e/bx"
                api_params = {"method": "ALL", "pageNo": 1, "pageSize": 25, "createStime": start_date, "createEtime": end_date}
                resp = requests.get(api_url, headers=headers, params=api_params, timeout=10).json()
                
                if resp.get("code") == 100000:
                    datas = resp.get("data", {}).get("datas", [])
                    val1 = sum(float(item.get("totalprice", 0)) for item in datas)
                    val2 = sum(float(item.get("waitHxPrice", 0)) for item in datas)
                    val1_label, val2_label = "报销总额 (totalprice)", "未核销金额 (waitHxPrice)"
                else:
                    return f"❌ 报销单接口业务失败：{resp.get('msg')}"
            else: 
                return "⚠️ 请补充**查询指标**（如：部门周期预算、报销单）。"
                
        except Exception as e:
            return f"❌ 业务接口请求发生严重异常，请检查网络或联系管理员排查。详细错误信息：{str(e)}"

        # 生成带有真实 JS Fetch 交互的 HTML
        html_content = generate_html_report(system, metric, time_range, start_date, end_date, 
                                            val1_label, val1, val2_label, val2, 
                                            api_url, ctx.get("system_auth_headers", {}))
        
        real_preview_url = api_upload_html_to_oss(html_content)
        
        if not real_preview_url:
             return "❌ 业务数据抓取成功，但渲染报表并上传至 OSS 存储库失败，操作已中止。"
        
        ctx["last_report_url"] = real_preview_url
        ctx["last_report_title"] = f"{system} - {metric} 报表"
        save_session(user_id, ctx)

        return f"""📊 **{ctx["last_report_title"]}**

⏱ 查询范围：{time_range} ({start_date} ~ {end_date})
- {val1_label}：{val1:,.2f}
- {val2_label}：{val2:,.2f}

🔗 **完整可视化报表**：[点击查看并自主筛选]({real_preview_url})

💡 *您可以回复「发布」将此快照固化至系统。*"""

    elif any(kw in cmd for kw in ["发布", "保存"]):
        if not ctx.get("initialized"): return "⚠️ 请先发送「初始化」。"
        if not ctx.get("last_report_url"): return "⚠️ 当前没有可发布的报表，请先查询生成一份报表。"
        
        publish_url = ctx.get("last_report_url").replace(".html", "_published.html")
        return f"✅ **发布成功**\n\n报表快照《{ctx.get('last_report_title')}》已持久化保存至胜算平台。\n🔗 正式访问链接：{publish_url}"

    else:
        return f"收到未识别的指令。您可以尝试发送「初始化」、「查询本月报销单」或「系统列表」。"