#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
@Project : 金灯塔 BI Skill (OpenClaw Universal Agent)
@Company : Asiasea (asiasea-ai)
@License : PROPRIETARY AND CONFIDENTIAL
====================================================================
"""
import json
import os
import datetime
import requests
import base64

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
        "auth_password": None,       
        "awaiting_password": False,  
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

# ==================== 泛型数据处理引擎 ====================
def safe_float(val) -> float:
    try:
        if val is None or val == "": return 0.0
        return float(val)
    except (ValueError, TypeError):
        return 0.0

def parse_time_keywords(text: str):
    now = datetime.datetime.now()
    if "本月" in text:
        return now.replace(day=1).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), "本月"
    if "上个月" in text or "上月" in text:
        last = now.replace(day=1) - datetime.timedelta(days=1)
        return last.replace(day=1).strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d"), "上个月"
    if "昨天" in text or "昨日" in text:
        y = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        return y, y, "昨天"
    if "今天" in text or "今日" in text:
        t = now.strftime("%Y-%m-%d")
        return t, t, "今天"
    if "本周" in text:
        return (now - datetime.timedelta(days=now.weekday())).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), "本周"
    if "上周" in text:
        sun = now - datetime.timedelta(days=now.weekday() + 1)
        mon = sun - datetime.timedelta(days=6)
        return mon.strftime("%Y-%m-%d"), sun.strftime("%Y-%m-%d"), "上周"
    if "今年" in text or "本年" in text:
        return now.replace(month=1, day=1).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), "今年"
    return None, None, ""

# 全局字段语义翻译字典（让英文字段名在图表中显示为人话，未知字段保持原样）
_FIELD_DICT = {
    "budgettotal": "总基数", "usedamount": "消耗额", "totalprice": "累计金额", "waithxprice": "待核销额",
    "budgetno": "业务单号", "applyusername": "申请人", "departmentname": "部门", 
    "ewecomfepartmentname": "业务组织", "statusname": "当前状态", "createtime": "创建时间"
}
def t_key(k: str) -> str:
    return _FIELD_DICT.get(str(k).lower(), str(k))

def extract_generic_schema(datas: list) -> tuple:
    """动态扫描 API JSON，自动提取最适合作为 KPI 的数字列和文本列"""
    if not datas: return [], []
    sample = datas[0]
    num_k, txt_k = [], []
    for k, v in sample.items():
        if str(k).lower() in ['id', 'pageno', 'pagesize', 'tenantid', 'method']: continue
        try:
            float(v)
            num_k.append(k)
        except (ValueError, TypeError):
            txt_k.append(k)
    # 按常见度量关键词优先级排序数字列
    priority = ['total', 'amount', 'price', 'num']
    num_k.sort(key=lambda x: sum(1 for p in priority if p in x.lower()), reverse=True)
    return num_k[:2], txt_k[:4]

# ==================== 后端 API (全链路严格注入 Auth) ====================
def build_safe_headers(auth_pwd: str, ctx_headers: dict) -> dict:
    """安全展开系统凭证，避免字典嵌套作为请求头"""
    h = {"Content-Type": "application/json", "auth": auth_pwd}
    if isinstance(ctx_headers, dict):
        for k, v in ctx_headers.items():
            h[k] = str(v)
    return h

def api_get_supported_systems(auth_pwd: str) -> list:
    try:
        resp = requests.get("https://o.yayuit.cn/dw/api/auth/supported-systems", headers={"auth": auth_pwd}, timeout=5).json()
        if resp.get("code") == 100000: return resp.get("result", {}).get("list", [])
    except Exception: pass
    return []

def api_get_registry(system_id: int, auth_pwd: str) -> list:
    try:
        resp = requests.get(f"https://o.yayuit.cn/dw/api/system/api-registry?system_id={system_id}", headers={"auth": auth_pwd}, timeout=5).json()
        if resp.get("code") == 100000: return resp.get("result", {}).get("list", [])
    except Exception: pass
    return []

def api_get_system_token(system_id: int, auth_pwd: str) -> dict:
    try:
        resp = requests.get(f"https://o.yayuit.cn/dw/api/auth/system-token?system_id={system_id}", headers={"auth": auth_pwd}, timeout=5).json()
        if resp.get("code") == 100000: return resp.get("result", {}).get("data", {})
    except Exception: pass
    return {}

def api_upload_html_to_oss(html_content: str, auth_pwd: str) -> str:
    try:
        resp = requests.post(
            "https://o.yayuit.cn/dw/api/skills/archive/upload",
            headers={"auth": auth_pwd}, files={"file": ("bi_report.html", html_content.encode("utf-8"), "text/html")},
            timeout=15,
        ).json()
        if resp.get("code") == 100000: return resp.get("result", {}).get("preview_url", "")
    except Exception: pass
    return ""

def api_publish_report(url: str, title: str, auth_pwd: str) -> tuple:
    try:
        resp = requests.post(
            "https://o.yayuit.cn/dw/api/skills/archive/publish",
            headers={"auth": auth_pwd}, json={"url": url, "title": title}, timeout=10
        ).json()
        if resp.get("code") == 100000: return True, resp.get("result", {}).get("published_url", url)
        return False, resp.get("msg", "未知错误")
    except Exception as e: return False, str(e)

# ==================== 泛型 HTML 动态大屏生成器 ====================
def generate_html_report(
    system: str, metric_label: str, time_range: str, start_date: str, end_date: str, 
    val1_label: str, val1: float, val2_label: str, val2: float, 
    table_rows: list, num_keys: list, txt_keys: list, api_url: str, headers_dict: dict
) -> str:
    echarts_url = "https://jindengta-archive.oss-cn-beijing.aliyuncs.com/theme/web/bi/echarts.min.js"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    val_diff = val1 - val2
    used_pct = round(val2 / val1 * 100) if val1 > 0 else 0
    
    # 将动态提取的键名也发给前端，让前端知道怎么画图
    config_payload = json.dumps({"url": api_url, "headers": headers_dict, "num_keys": num_keys, "txt_keys": txt_keys})
    config_b64 = base64.b64encode(config_payload.encode('utf-8')).decode('utf-8')

    # 动态组装表格
    thead = "<tr>" + "".join([f"<th>{t_key(k)}</th>" for k in txt_keys]) + "".join([f"<th>{t_key(k)}</th>" for k in num_keys]) + "</tr>"
    tbody_rows = ""
    for r in table_rows[:50]:
        tbody_rows += "<tr>"
        for k in txt_keys: tbody_rows += f"<td>{r.get(k) or '—'}</td>"
        for k in num_keys: tbody_rows += f"<td class='num'>¥{safe_float(r.get(k)):,.2f}</td>"
        tbody_rows += "</tr>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>智能可视化空间</title><script src="{echarts_url}"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
:root {{ --bg: #0f172a; --panel: rgba(30,41,59,0.7); --border: rgba(255,255,255,0.1); --text: #f8fafc; --text-m: #94a3b8; --p1: #3b82f6; --p2: #10b981; --err: #ef4444; }}
body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }}
.dashboard {{ max-width: 1400px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
.glass-box {{ background: var(--panel); backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: 16px; padding: 24px; box-shadow: 0 8px 32px rgba(0,0,0,0.3); transition: transform 0.3s; }}
.glass-box:hover {{ transform: translateY(-2px); }}
.header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; }}
.h-title {{ font-size: 24px; font-weight: 800; background: linear-gradient(90deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
.ctrl-bar {{ display: flex; gap: 12px; align-items: center; background: rgba(0,0,0,0.2); padding: 8px 16px; border-radius: 12px; border: 1px solid var(--border); }}
.ctrl-bar input {{ background: transparent; border: 1px solid var(--border); color: #fff; padding: 8px 12px; border-radius: 8px; color-scheme: dark; outline: none; }}
.btn {{ background: var(--p1); color: #fff; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: all 0.2s; }}
.btn:hover {{ background: #2563eb; box-shadow: 0 0 15px rgba(59,130,246,0.5); }}
.btn:disabled {{ background: #475569; color: #94a3b8; cursor: not-allowed; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; }}
.kpi {{ display: flex; flex-direction: column; gap: 8px; }}
.kpi-lb {{ font-size: 13px; color: var(--text-m); letter-spacing: 1px; }}
.kpi-v {{ font-size: 32px; font-weight: 800; font-family: monospace; text-shadow: 0 2px 10px rgba(0,0,0,0.5); }}
.v-blue {{ color: #60a5fa; }} .v-green {{ color: #34d399; }} .v-warn {{ color: #facc15; }}
.chart-grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 24px; }}
@media(max-width: 1024px) {{ .chart-grid {{ grid-template-columns: 1fr; }} }}
.chart {{ width: 100%; height: 350px; }}
.tbl-box {{ overflow-x: auto; max-height: 400px; }}
table {{ width: 100%; border-collapse: collapse; text-align: left; }}
th {{ padding: 16px; font-size: 12px; color: var(--text-m); border-bottom: 1px solid var(--border); position: sticky; top: 0; background: #1e293b; z-index: 10; }}
td {{ padding: 16px; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 14px; }}
.num {{ text-align: right; font-family: monospace; font-size: 15px; color: #cbd5e1; }}
</style>
</head>
<body>
<div class="dashboard">
    <div class="glass-box header">
        <div class="h-title">⚗️ {metric_label} · 智能矩阵</div>
        <div class="ctrl-bar">
            <span style="color:var(--text-m);font-size:14px;">时间探针：</span>
            <input type="date" id="i_start" value="{start_date}"> - <input type="date" id="i_end" value="{end_date}">
            <button class="btn" id="btn_q" onclick="doQuery()">渲染重载</button>
            <span id="sys_msg" style="font-size:12px;color:var(--text-m);margin-left:10px;">{now_str}</span>
        </div>
    </div>
    <div class="glass-box kpi-grid">
        <div class="kpi"><span class="kpi-lb">{val1_label}</span><span class="kpi-v v-blue" id="kv1">¥{val1:,.0f}</span></div>
        <div class="kpi"><span class="kpi-lb">{val2_label}</span><span class="kpi-v v-green" id="kv2">¥{val2:,.0f}</span></div>
        <div class="kpi"><span class="kpi-lb">绝对差额</span><span class="kpi-v v-warn" id="kv_diff">¥{abs(val_diff):,.0f}</span></div>
        <div class="kpi"><span class="kpi-lb">度量比率</span><span class="kpi-v" id="kv_pct" style="color:#fff;">{used_pct}%</span></div>
    </div>
    <div class="chart-grid">
        <div class="glass-box"><div id="chart_bar" class="chart"></div></div>
        <div class="glass-box"><div id="chart_gauge" class="chart"></div></div>
    </div>
    <div class="glass-box">
        <div style="margin-bottom: 16px; font-weight: 600; color: var(--text-m);">底层网关数据流 (Top 50)</div>
        <div class="tbl-box"><table><thead>{thead}</thead><tbody id="tbl_body">{tbody_rows}</tbody></table></div>
    </div>
</div>

<script>
var barC = echarts.init(document.getElementById('chart_bar'));
var gaugeC = echarts.init(document.getElementById('chart_gauge'));
const CFG = JSON.parse(atob('{config_b64}'));

function draw(v1, v2) {{
  var pct = v1 > 0 ? Math.round(v2 / v1 * 100) : 0;
  barC.setOption({{
    tooltip: {{ trigger: 'axis', backgroundColor: 'rgba(15,23,42,0.9)', textStyle: {{color: '#fff'}}, borderColor: '#334155' }},
    grid: {{ left: '3%', right: '3%', bottom: '5%', top: '15%', containLabel: true }},
    xAxis: {{ type: 'category', data: ['多维度量对比'], axisLine: {{lineStyle: {{color: '#475569'}}}} }},
    yAxis: {{ type: 'value', splitLine: {{lineStyle: {{color: '#1e293b', type: 'dashed'}}}}, axisLabel: {{color: '#94a3b8'}} }},
    series: [
      {{ name: '{val1_label}', type: 'bar', data: [v1], barWidth: '20%', itemStyle: {{ color: new echarts.graphic.LinearGradient(0,0,0,1, [{{offset:0,color:'#60a5fa'}},{{offset:1,color:'#2563eb'}}]), borderRadius: [8,8,0,0] }} }},
      {{ name: '{val2_label}', type: 'bar', data: [v2], barWidth: '20%', itemStyle: {{ color: new echarts.graphic.LinearGradient(0,0,0,1, [{{offset:0,color:'#34d399'}},{{offset:1,color:'#059669'}}]), borderRadius: [8,8,0,0] }} }}
    ]
  }});

  var gColor = pct >= 90 ? '#ef4444' : pct >= 70 ? '#facc15' : '#34d399';
  gaugeC.setOption({{
    series: [{{
      type: 'gauge', progress: {{ show: true, width: 18, itemStyle: {{color: gColor}} }},
      axisLine: {{ lineStyle: {{ width: 18, color: [[1, '#1e293b']] }} }},
      axisTick: {{show: false}}, splitLine: {{show: false}}, axisLabel: {{show: false}},
      detail: {{ valueAnimation: true, formatter: '{{value}}%', color: '#fff', fontSize: 32, fontWeight: 800, offsetCenter: [0, '20%'] }},
      data: [{{ value: pct, name: '当前比率水位' }}], title: {{ color: '#94a3b8', fontSize: 14, offsetCenter: [0, '-20%'] }}
    }}]
  }});
}}
draw({val1}, {val2});
window.addEventListener('resize', () => {{ barC.resize(); gaugeC.resize(); }});

async function doQuery() {{
  var s = document.getElementById('i_start').value, e = document.getElementById('i_end').value;
  if(!s || !e) return alert('请输入完整时间探针');
  var btn = document.getElementById('btn_q'), msg = document.getElementById('sys_msg');
  btn.disabled = true; btn.textContent = '提取中...'; msg.textContent = '正在穿透网关...';

  var h = CFG.headers; h['Content-Type'] = 'application/json';
  var u = new URL(CFG.url);
  // 采用泛型 Payload：直接双管齐下传递不同格式的时间字段，由后端自行按需解析
  u.searchParams.append('method', 'ALL'); u.searchParams.append('pageNo', '1'); u.searchParams.append('pageSize', '50');
  u.searchParams.append('startTime', s); u.searchParams.append('endTime', e);
  u.searchParams.append('createStime', s); u.searchParams.append('createEtime', e);

  try {{
    var res = await fetch(u, {{ method: 'GET', headers: h }});
    var d = await res.json();
    if (d.code !== 100000) throw new Error(d.msg || '节点拒绝');
    
    var datas = (d.data && d.data.datas) || [], nv1 = 0, nv2 = 0;
    var tb = document.getElementById('tbl_body'); tb.innerHTML = '';
    
    // 完全动态的 JS 表格与数值装载
    datas.slice(0, 50).forEach(r => {{
      var v1 = CFG.num_keys.length > 0 ? parseFloat(r[CFG.num_keys[0]]||0) : 0;
      var v2 = CFG.num_keys.length > 1 ? parseFloat(r[CFG.num_keys[1]]||0) : 0;
      nv1 += v1; nv2 += v2;
      
      var row_html = "<tr>";
      CFG.txt_keys.forEach(k => {{ row_html += `<td>${{r[k]||'—'}}</td>`; }});
      CFG.num_keys.forEach(k => {{ row_html += `<td class="num">¥${{parseFloat(r[k]||0).toLocaleString()}}</td>`; }});
      row_html += "</tr>";
      tb.innerHTML += row_html;
    }});

    document.getElementById('kv1').textContent = '¥' + Math.round(nv1).toLocaleString();
    document.getElementById('kv2').textContent = '¥' + Math.round(nv2).toLocaleString();
    document.getElementById('kv_diff').textContent = '¥' + Math.round(Math.abs(nv1-nv2)).toLocaleString();
    document.getElementById('kv_pct').textContent = (nv1>0 ? Math.round(nv2/nv1*100) : 0) + '%';
    
    draw(nv1, nv2);
    msg.textContent = '✅ 链路同步完成';
  }} catch(err) {{ msg.textContent = '❌ 路由异常: ' + err.message; }} 
  finally {{ btn.disabled = false; btn.textContent = '渲染重载'; }}
}}
</script>
</body>
</html>"""


# ==================== OpenClaw 主入口 ====================
def handle(command: str, args: list, **kwargs) -> str:
    user_id = kwargs.get("user_id", kwargs.get("sender_id", "default_user"))
    ctx = load_session(user_id)
    cmd = command.strip().lstrip("/")
    full_text = (cmd + " " + " ".join(args)).strip()

    # 🔴 全局密码拦截体系
    if not ctx.get("auth_password"):
        if ctx.get("awaiting_password"):
            pwd = full_text.strip()
            ctx.update({"auth_password": pwd, "awaiting_password": False, "initialized": True})
            save_session(user_id, ctx)
            
            systems = api_get_supported_systems(pwd)
            if not systems: 
                return "❌ 通信加密失败或网络异常，未获取到业务域。请检查密码是否正确，发送「初始化」重试。"
            
            lines = ["🔐 **安全握手成功，大模型链路已就绪。**\n\n💡 **请指定要挂载的物理板块：**"]
            for sys in systems: lines.append(f"- **{sys.get('system_name')}**")
            lines.append("\n*(提示：回复 切换系统 <板块名>)*")
            return "\n".join(lines)
        else:
            ctx["awaiting_password"] = True
            save_session(user_id, ctx)
            return "🛡️ **网关安全锁验证**\n\n在执行语义数据探索前，**请在此输入您的访问授权密码**（该密码将静默保护您的所有查询）："

    if cmd in ["初始化", "重置", "重置密码"]:
        ctx.update({"auth_password": None, "awaiting_password": True, "initialized": False})
        save_session(user_id, ctx)
        return "🛡️ **环境锁已阻断**\n\n**请重新输入新会话的访问密码**："

    pwd = ctx.get("auth_password")

    if cmd == "系统列表":
        systems = api_get_supported_systems(pwd)
        if not systems: return "❌ 获取业务域失败，请确认底层网关状态。"
        curr = ctx.get("system_name")
        lines = ["📋 **当前网络内的业务域：**\n"]
        for s in systems:
            lines.append(f"- **{s.get('system_name')}**" + (" ✅" if curr == s.get("system_name") else ""))
        return "\n".join(lines)

    if cmd.startswith("切换系统"):
        if not args: return "❌ 缺失目标参数，例如：`切换系统 E网`"
        target = args[0]
        systems = api_get_supported_systems(pwd)
        target_sys = next((s for s in systems if s.get("system_name") == target), None)
        if not target_sys: return f"❌ 未能锚定「{target}」节点。"
        
        sys_id = target_sys.get("id")
        auth_data = api_get_system_token(sys_id, pwd)
        if not auth_data: return f"❌ 越权阻断：「{target}」未能下发访问凭证。"
        
        # 实时拉取并缓存系统的 API 路由表
        api_list = api_get_registry(sys_id, pwd)
        ctx.update({"system_name": target, "system_id": sys_id, "system_auth_headers": auth_data, "api_registry": api_list})
        save_session(user_id, ctx)
        
        # 动态提取真实可用的指标用于提示，杜绝大模型猜词幻觉
        clean_names = [api.get("name", "").replace("查询", "").replace("列表", "").replace("接口文档", "").strip() for api in api_list]
        clean_names = [n for n in clean_names if n]
        sample = clean_names[0] if clean_names else "业务快照"
        
        return f"✅ 已为您切入 **{target}** 数据池。\n\n> 💡 您现在可以直接对我说：\n> **「帮我分析本月的{sample}」**"

    # ==================== 泛型 BI 意图解析 ====================
    if any(kw in full_text for kw in ["报表", "数据看板", "BI", "统计", "分析", "查询", "趋势", "度量", "提取"]):
        system = ctx.get("system_name")
        if not system: return "⚠️ 未检测到挂载域，请先发送「系统列表」并切入相关板块。"

        start_date, end_date, time_range = parse_time_keywords(full_text)
        if not start_date: return "⚠️ 请补充分析探针的**时间范围**（如：本月、上月、昨日）。"

        # 动态遍历注册表，寻找匹配用户意图的 API
        target_api = None
        for api in ctx.get("api_registry", []):
            name_clean = api.get("name", "").replace("查询", "").replace("列表", "").replace("接口文档", "").strip()
            if name_clean and name_clean in full_text:
                target_api = api
                break
                
        # 兼容处理：如果没有精确命中，但包含核心关键词则智能降级匹配
        if not target_api:
            for api in ctx.get("api_registry", []):
                path = api.get("path", "")
                if "预算" in full_text and "yearBudget" in path: target_api = api; break
                if "报销" in full_text and "bx" in path: target_api = api; break
                
        if not target_api: 
            return f"⚠️ 在【{system}】中未能语义对齐具体的业务指标，请使用更准确的业务词汇。"

        metric_label = target_api.get("name", "业务洞察").replace("接口文档", "")
        raw_path = target_api.get("path", "")
        
        # 动态处理接口域名
        if raw_path.startswith("http"): api_url = raw_path
        else: api_url = "https://e.asagroup.cn" + (raw_path if raw_path.startswith("/") else "/" + raw_path)

        # 严格组装安全 Headers
        headers = build_safe_headers(pwd, ctx.get("system_auth_headers", {}))
        
        # 使用“全覆盖”传参，应对后端可能存在的各种日期字段命名
        params = {
            "method": "ALL", "pageNo": 1, "pageSize": 50,
            "startTime": start_date, "endTime": end_date,
            "createStime": start_date, "createEtime": end_date
        }

        try:
            resp = requests.get(api_url, headers=headers, params=params, timeout=10).json()
            if resp.get("code") != 100000: return f"❌ 网关阻断：{resp.get('msg', '未知业务错')}"
            datas = resp.get("data", {}).get("datas", [])
        except Exception as e:
            return f"❌ 物理链路穿透失败，网关未响应。（{e}）"

        # 核心泛化逻辑：根据返回的 JSON 自动推导结构
        num_keys, txt_keys = extract_generic_schema(datas)
        
        val1_key = num_keys[0] if len(num_keys) > 0 else ""
        val2_key = num_keys[1] if len(num_keys) > 1 else ""
        
        val1 = sum(safe_float(r.get(val1_key)) for r in datas) if val1_key else 0.0
        val2 = sum(safe_float(r.get(val2_key)) for r in datas) if val2_key else 0.0
        
        val1_label = t_key(val1_key) if val1_key else "度量A"
        val2_label = t_key(val2_key) if val2_key else "度量B"

        html = generate_html_report(
            system, metric_label, time_range, start_date, end_date,
            val1_label, val1, val2_label, val2, datas, num_keys, txt_keys, api_url, headers
        )
        
        preview_url = api_upload_html_to_oss(html, pwd)
        if not preview_url: return "❌ 云计算已响应，但在执行大屏流固化时失败，操作挂起。"

        ctx["last_report_url"] = preview_url
        ctx["last_report_title"] = f"{system} · {metric_label}"
        save_session(user_id, ctx)

        # 严格根据实际数据产生执行建议
        used_pct = round(val2 / val1 * 100) if val1 > 0 else 0
        if not datas:
            advice = "⚪ **执行建议**：探针未能捕获到该周期的有效数据，建议扩大时间范围或核查上游流水。"
        elif used_pct >= 90:
            advice = f"🔴 **风险预警**：当前【{val2_label}】占【{val1_label}】比重已达 {used_pct}%，触及高位警戒线，建议立刻启动熔断或复核机制。"
        elif used_pct >= 70:
            advice = f"🟡 **管控提示**：结构化比率已达 {used_pct}%，处于偏高水位，请密切跟踪后续流转动向。"
        else:
            advice = f"🟢 **执行建议**：数据基盘稳定，核心转化率在合理区间（{used_pct}%），可保持现有资源释放节奏。"

        # 严格控制输出排版，包含四大版块
        return (
            f"📊 **{ctx['last_report_title']} 空间计算完毕**\n\n"
            f"📋 **基础信息**\n"
            f"- 分析对象：{metric_label}\n"
            f"- 探针跨度：{time_range} ({start_date} ~ {end_date})\n"
            f"- 穿透记录：{len(datas)} 条\n\n"
            f"🔗 [🌐 点击进入动态可视化数据大屏]({preview_url})\n\n"
            f"📈 **数据总计**\n"
            f"- **{val1_label}**：¥{val1:,.2f}\n"
            f"- **{val2_label}**：¥{val2:,.2f}\n\n"
            f"💡 **智能分析与执行建议**\n"
            f"- {advice}\n\n"
            f"> 📌 数据流已封装，若需将该大屏挂载至公区，请发送「发布」。"
        )

    if any(kw in full_text for kw in ["发布", "保存", "固化"]):
        if not ctx.get("last_report_url"): return "⚠️ 内存无活跃对象，请先发起数据查询。"
        ok, result = api_publish_report(ctx["last_report_url"], ctx.get("last_report_title", ""), pwd)
        if ok: return f"✅ **知识库矩阵固化成功**\n\n《{ctx.get('last_report_title')}》已被永久锚定。\n🔗 外部访问链接：{result}"
        return f"❌ 发布层抛出异常：{result}"

    return "未能解析此意图。如需新指令请直接对话，或回复「重置密码」清空鉴权。"