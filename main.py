#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
@Project : 金灯塔 BI Skill (OpenClaw Agent)
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
        "auth_password": None,       # 新增：全局访问密码
        "awaiting_password": False,  # 新增：密码等待状态锁
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

# ==================== 工具函数 ====================
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

# ==================== 后端 API (全链路注入 auth 密码) ====================
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
            headers={"auth": auth_pwd},
            files={"file": ("bi_report.html", html_content.encode("utf-8"), "text/html")},
            timeout=15,
        ).json()
        if resp.get("code") == 100000: return resp.get("result", {}).get("preview_url", "")
    except Exception: pass
    return ""

def api_publish_report(url: str, title: str, auth_pwd: str) -> tuple:
    try:
        resp = requests.post(
            "https://o.yayuit.cn/dw/api/skills/archive/publish",
            headers={"auth": auth_pwd},
            json={"url": url, "title": title},
            timeout=10,
        ).json()
        if resp.get("code") == 100000: return True, resp.get("result", {}).get("published_url", url)
        return False, resp.get("msg", "未知错误")
    except Exception as e:
        return False, str(e)

# ==================== 指标元数据 ====================
_METRIC_MAP = [
    {"key": "报销单", "keywords": ["bx", "报销"], "label": "费用报销度量"},
    {"key": "部门周期预算", "keywords": ["yearBudget", "预算"], "label": "部门预算矩阵"},
]

def resolve_metric(full_text: str) -> dict | None:
    if any(kw in full_text for kw in ["预算"]): return next(m for m in _METRIC_MAP if m["key"] == "部门周期预算")
    if any(kw in full_text for kw in ["报销", "费用", "报销单"]): return next(m for m in _METRIC_MAP if m["key"] == "报销单")
    return None

# ==================== HTML 高端大屏生成器 ====================
def generate_html_report(
    system: str, metric_label: str, metric_key: str, time_range: str,
    start_date: str, end_date: str, val1_label: str, val1: float,
    val2_label: str, val2: float, table_rows: list, 
    api_url: str, headers_dict: dict
) -> str:
    echarts_url = "https://jindengta-archive.oss-cn-beijing.aliyuncs.com/theme/web/bi/echarts.min.js"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    val_diff = val1 - val2
    used_pct = round(val2 / val1 * 100) if val1 > 0 else 0
    
    # 将包含全局 auth 密码的 headers 字典混淆注入，确保前端能发起真实跨域请求
    config_payload = json.dumps({"url": api_url, "headers": headers_dict, "metric": metric_key})
    config_b64 = base64.b64encode(config_payload.encode('utf-8')).decode('utf-8')

    if metric_key == "报销单":
        thead = "<tr><th>报销单号</th><th>申请人</th><th>核算部门</th><th>报销总额</th><th>待核销金额</th><th>审核状态</th></tr>"
        tbody_rows = ""
        for row in table_rows[:50]:
            tp, wh = safe_float(row.get("totalprice")), safe_float(row.get("waitHxPrice"))
            tbody_rows += f"""<tr>
              <td class="mono">{row.get('budgetNo') or '—'}</td>
              <td>{row.get('applyUserName') or '—'}</td>
              <td>{row.get('departmentName') or '—'}</td>
              <td class="num">¥{tp:,.2f}</td><td class="num">¥{wh:,.2f}</td>
              <td><span class="badge">{row.get('statusName') or '—'}</span></td>
            </tr>"""
    else:
        thead = "<tr><th>部门名称</th><th>预算总基数</th><th>已使用金额</th><th>可用结余</th><th>消耗进度</th></tr>"
        tbody_rows = ""
        for row in table_rows[:50]:
            bt, ua = safe_float(row.get("budgetTotal")), safe_float(row.get("usedAmount"))
            rem = bt - ua
            pct_row = round(ua / bt * 100) if bt > 0 else 0
            tbody_rows += f"""<tr>
              <td>{row.get('ewecomFepartmentName') or '—'}</td>
              <td class="num">¥{bt:,.2f}</td><td class="num">¥{ua:,.2f}</td>
              <td class="num {"danger" if rem < 0 else ""} t-bold">¥{rem:,.2f}</td>
              <td><div class="pg-bar"><div class="pg-fill {"pg-err" if pct_row>80 else ""}" style="width:{min(pct_row,100)}%"></div></div><span class="pg-txt">{pct_row}%</span></td>
            </tr>"""

    # 动态流式布局 + 毛玻璃视觉 (Modern UI)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>智能可视化空间</title>
<script src="{echarts_url}"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
:root {{
    --bg: #0f172a; --panel: rgba(30, 41, 59, 0.7); --border: rgba(255,255,255,0.1);
    --text: #f8fafc; --text-m: #94a3b8; --p1: #3b82f6; --p2: #10b981; --err: #ef4444;
}}
body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }}
.dashboard {{ max-width: 1400px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
.glass-box {{ background: var(--panel); backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: 16px; padding: 24px; box-shadow: 0 8px 32px rgba(0,0,0,0.3); transition: transform 0.3s; }}
.glass-box:hover {{ transform: translateY(-2px); }}

/* 头部与检索台 */
.header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; }}
.h-title {{ font-size: 24px; font-weight: 800; background: linear-gradient(90deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
.ctrl-bar {{ display: flex; gap: 12px; align-items: center; background: rgba(0,0,0,0.2); padding: 8px 16px; border-radius: 12px; border: 1px solid var(--border); }}
.ctrl-bar input {{ background: transparent; border: 1px solid var(--border); color: #fff; padding: 8px 12px; border-radius: 8px; color-scheme: dark; outline: none; }}
.btn {{ background: var(--p1); color: #fff; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: all 0.2s; }}
.btn:hover {{ background: #2563eb; box-shadow: 0 0 15px rgba(59,130,246,0.5); }}
.btn:disabled {{ background: #475569; color: #94a3b8; cursor: not-allowed; box-shadow: none; }}

/* 核心 KPI 组 */
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; }}
.kpi {{ display: flex; flex-direction: column; gap: 8px; }}
.kpi-lb {{ font-size: 13px; color: var(--text-m); text-transform: uppercase; letter-spacing: 1px; }}
.kpi-v {{ font-size: 32px; font-weight: 800; font-family: monospace; text-shadow: 0 2px 10px rgba(0,0,0,0.5); }}
.v-blue {{ color: #60a5fa; }} .v-green {{ color: #34d399; }} .v-warn {{ color: #facc15; }}

/* 图表自适应网格 */
.chart-grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 24px; }}
@media(max-width: 1024px) {{ .chart-grid {{ grid-template-columns: 1fr; }} }}
.chart {{ width: 100%; height: 350px; }}
.chart-sm {{ width: 100%; height: 300px; }}

/* 极简表格 */
.tbl-box {{ overflow-x: auto; max-height: 400px; }}
table {{ width: 100%; border-collapse: collapse; text-align: left; }}
th {{ padding: 16px; font-size: 12px; color: var(--text-m); border-bottom: 1px solid var(--border); position: sticky; top: 0; background: #1e293b; z-index: 10; }}
td {{ padding: 16px; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 14px; }}
.num {{ text-align: right; font-family: monospace; font-size: 15px; }}
.danger {{ color: var(--err); }} .t-bold {{ font-weight: 600; }}
.badge {{ background: rgba(59,130,246,0.2); color: #93c5fd; padding: 4px 10px; border-radius: 6px; font-size: 12px; }}
.pg-bar {{ display: inline-block; width: 100px; height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; }}
.pg-fill {{ height: 100%; background: var(--p2); border-radius: 3px; box-shadow: 0 0 10px var(--p2); }}
.pg-err {{ background: var(--err); box-shadow: 0 0 10px var(--err); }}
.pg-txt {{ margin-left: 10px; font-size: 12px; color: var(--text-m); }}
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
        <div class="kpi"><span class="kpi-lb">流转率</span><span class="kpi-v" id="kv_pct" style="color:#fff;">{used_pct}%</span></div>
    </div>

    <div class="chart-grid">
        <div class="glass-box"><div id="chart_bar" class="chart"></div></div>
        <div class="glass-box"><div id="chart_gauge" class="chart"></div></div>
    </div>

    <div class="glass-box">
        <div style="margin-bottom: 16px; font-weight: 600; color: var(--text-m);">底层基础业务数据 (Top 50)</div>
        <div class="tbl-box"><table><thead>{thead}</thead><tbody id="tbl_body">{tbody_rows}</tbody></table></div>
    </div>
</div>

<script>
// 图表暗色系渲染引擎
var barC = echarts.init(document.getElementById('chart_bar'));
var gaugeC = echarts.init(document.getElementById('chart_gauge'));
const CFG = JSON.parse(atob('{config_b64}'));

function draw(v1, v2) {{
  var pct = v1 > 0 ? Math.round(v2 / v1 * 100) : 0;
  barC.setOption({{
    tooltip: {{ trigger: 'axis', backgroundColor: 'rgba(15,23,42,0.9)', textStyle: {{color: '#fff'}}, borderColor: '#334155' }},
    grid: {{ left: '3%', right: '3%', bottom: '5%', top: '15%', containLabel: true }},
    xAxis: {{ type: 'category', data: ['度量规模'], axisLine: {{lineStyle: {{color: '#475569'}}}} }},
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
      data: [{{ value: pct, name: '当前水位' }}], title: {{ color: '#94a3b8', fontSize: 14, offsetCenter: [0, '-20%'] }}
    }}]
  }});
}}
draw({val1}, {val2});
window.addEventListener('resize', () => {{ barC.resize(); gaugeC.resize(); }});

// 核心查询逻辑 (真实接口路由联调)
async function doQuery() {{
  var s = document.getElementById('i_start').value, e = document.getElementById('i_end').value;
  if(!s || !e) return alert('请输入完整时间探针');
  
  var btn = document.getElementById('btn_q'), msg = document.getElementById('sys_msg');
  btn.disabled = true; btn.textContent = '数据提取中...'; msg.textContent = '正在穿透业务网关...';

  var h = CFG.headers; h['Content-Type'] = 'application/json';
  var u = new URL(CFG.url);
  u.searchParams.append('method', 'ALL'); u.searchParams.append('pageNo', '1'); u.searchParams.append('pageSize', '50');
  
  if (CFG.metric === '部门周期预算') {{ u.searchParams.append('startTime', s); u.searchParams.append('endTime', e); }}
  else {{ u.searchParams.append('createStime', s); u.searchParams.append('createEtime', e); }}

  try {{
    var res = await fetch(u, {{ method: 'GET', headers: h }});
    var d = await res.json();
    if (d.code !== 100000) throw new Error(d.msg || '节点拒绝');
    
    var datas = (d.data && d.data.datas) || [], nv1 = 0, nv2 = 0;
    var tb = document.getElementById('tbl_body'); tb.innerHTML = '';
    
    datas.slice(0, 50).forEach(r => {{
      if (CFG.metric === '报销单') {{
        var tp = parseFloat(r.totalprice||0), wh = parseFloat(r.waitHxPrice||0); nv1+=tp; nv2+=wh;
        tb.innerHTML += `<tr><td class="mono">${{r.budgetNo||'—'}}</td><td>${{r.applyUserName||'—'}}</td><td>${{r.departmentName||'—'}}</td><td class="num">¥${{tp.toLocaleString()}}</td><td class="num">¥${{wh.toLocaleString()}}</td><td><span class="badge">${{r.statusName||'—'}}</span></td></tr>`;
      }} else {{
        var bt = parseFloat(r.budgetTotal||0), ua = parseFloat(r.usedAmount||0), rem = bt-ua, p = bt>0 ? Math.min(100, Math.round(ua/bt*100)) : 0; nv1+=bt; nv2+=ua;
        tb.innerHTML += `<tr><td>${{r.ewecomFepartmentName||'—'}}</td><td class="num">¥${{bt.toLocaleString()}}</td><td class="num">¥${{ua.toLocaleString()}}</td><td class="num ${{rem<0?'danger':''}} t-bold">¥${{rem.toLocaleString()}}</td><td><div class="pg-bar"><div class="pg-fill ${{p>80?'pg-err':''}}" style="width:${{p}}%"></div></div><span class="pg-txt">${{p}}%</span></td></tr>`;
      }}
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

    # 🔴 [强制安全拦截] 所有操作前提：必须有 Auth 密码
    if not ctx.get("auth_password"):
        if ctx.get("awaiting_password"):
            # 捕获用户输入的密码
            pwd = full_text.strip()
            ctx["auth_password"] = pwd
            ctx["awaiting_password"] = False
            ctx["initialized"] = True
            save_session(user_id, ctx)
            
            # 密码存入后，自动触发环境初始化
            systems = api_get_supported_systems(pwd)
            if not systems: 
                return "❌ 通信加密失败或网络异常，未获取到系统节点。请检查 auth 密码是否正确，发送「初始化」重试。"
            
            lines = ["🔐 **安全网关鉴权通过，环境已就绪。**\n\n💡 **请选择您要进入的物理板块：**"]
            for sys in systems: lines.append(f"- **{sys.get('system_name')}**")
            lines.append("\n*(示例指令：切换系统 供应链系统)*")
            return "\n".join(lines)
        else:
            # 开启等待密码锁
            ctx["awaiting_password"] = True
            save_session(user_id, ctx)
            return "🛡️ **系统安全握手**\n\n在执行初始化及后续数据提取前，**请先输入您的安全访问密码**（该值将作为全链路接口请求的 auth 凭证）："

    # 特殊指令：安全重置
    if cmd in ["初始化", "重置密码"]:
        ctx["auth_password"] = None
        ctx["awaiting_password"] = True
        ctx["initialized"] = False
        save_session(user_id, ctx)
        return "🛡️ **环境锁已重置**\n\n**请重新输入您的安全访问密码**，以建立新的加密会话："

    pwd = ctx.get("auth_password")

    # 路由 1：系统列表
    if cmd == "系统列表":
        systems = api_get_supported_systems(pwd)
        if not systems: return "❌ 获取业务域失败，请确认网关状态。"
        curr = ctx.get("system_name")
        lines = ["📋 **当前挂载的业务板块：**\n"]
        for s in systems:
            mark = " ✅（当前活跃）" if curr == s.get("system_name") else ""
            lines.append(f"- **{s.get('system_name')}**{mark}")
        return "\n".join(lines)

    # 路由 2：系统切换与上下文感知
    if cmd.startswith("切换系统"):
        if not args: return "❌ 请指定业务域，例如：`切换系统 E网`"
        target = args[0]
        systems = api_get_supported_systems(pwd)
        target_sys = next((s for s in systems if s.get("system_name") == target), None)
        if not target_sys: return f"❌ 未找到标识为「{target}」的节点。"
        
        sys_id = target_sys.get("id")
        auth_data = api_get_system_token(sys_id, pwd)
        if not auth_data: return f"❌ 进入「{target}」被拒：未能下发系统 Token 凭证。"
        
        # 实时拉取真实支持的接口名单
        api_list = api_get_registry(sys_id, pwd)
        ctx.update({"system_name": target, "system_id": sys_id, "system_auth_headers": auth_data, "api_registry": api_list})
        save_session(user_id, ctx)
        
        # 🟢 [解决幻觉问题]：从真实接口列表中提取出明确的业务名词给用户作为提示
        clean_names = []
        for api in api_list:
            name = api.get("name", "").replace("查询", "").replace("列表", "").replace("接口文档", "").strip()
            if name: clean_names.append(name)
        
        sample_word = clean_names[0] if clean_names else "相关报表"
        
        return f"✅ 已为您切入 **{target}** 业务域。\n\n> 💡 您现在可以通过自然语言探查数据了。无需死板指令，您可以直接对我说：\n> **「帮我分析一下本月的{sample_word}数据」**"

    # 路由 3：核心语义数据查询
    QUERY_KEYWORDS = ["报表", "数据看板", "BI", "统计", "分析", "查询", "报销", "预算", "费用", "明细", "趋势", "度量"]
    if any(kw in full_text for kw in QUERY_KEYWORDS):
        system = ctx.get("system_name")
        if not system: return "⚠️ 未检测到活跃的业务板块，请先发送「系统列表」并切入相关域。"

        start_date, end_date, time_range = parse_time_keywords(full_text)
        if not start_date: return "⚠️ 意图参数缺失：请补充明确的时间边界（如：**本月**、**上月**、**今天**）。"

        metric_info = resolve_metric(full_text)
        if not metric_info: return f"⚠️ 在【{system}】中未能语义对齐具体的业务指标，请说明具体意图（如：预算、报销）。"

        metric_key, metric_label = metric_info["key"], metric_info["label"]
        
        # 🟢 构建包含所有必要权限的请求头
        headers = {"Content-Type": "application/json", "auth": pwd}
        headers.update(ctx.get("system_auth_headers", {}))

        val1 = val2 = 0.0
        val1_label = val2_label = api_url = ""
        table_rows = []

        # 🟢 [解决 HTML 接口域名不对的问题] 动态从真实 API Registry 提取完整的 Path 和域名
        for api in ctx.get("api_registry", []):
            path = api.get("path", "")
            if metric_key == "部门周期预算" and "yearBudget" in path:
                api_url = path
                break
            elif metric_key == "报销单" and "bx" in path:
                api_url = path
                break
        
        # 如果 Registry 中未返回，则给予智能降级拼接
        if not api_url:
            api_url = "https://e.asagroup.cn/asae-e/yearBudget/query" if metric_key == "部门周期预算" else "https://e.asagroup.cn/asae-e/bx"
        elif not api_url.startswith("http"):
            api_url = "https://e.asagroup.cn" + (api_url if api_url.startswith("/") else "/" + api_url)

        try:
            params = {"method": "ALL", "pageNo": 1, "pageSize": 50}
            if metric_key == "部门周期预算":
                params.update({"startTime": start_date, "endTime": end_date})
                resp = requests.get(api_url, headers=headers, params=params, timeout=10).json()
                if resp.get("code") != 100000: return f"❌ 查询异常：{resp.get('msg', '未知业务错')}"
                datas = resp.get("data", {}).get("datas", [])
                val1 = sum(safe_float(r.get("budgetTotal")) for r in datas)
                val2 = sum(safe_float(r.get("usedAmount")) for r in datas)
                val1_label, val2_label = "预算总基数", "已消耗金额"
                table_rows = datas

            elif metric_key == "报销单":
                params.update({"createStime": start_date, "createEtime": end_date})
                resp = requests.get(api_url, headers=headers, params=params, timeout=10).json()
                if resp.get("code") != 100000: return f"❌ 查询异常：{resp.get('msg', '未知业务错')}"
                datas = resp.get("data", {}).get("datas", [])
                val1 = sum(safe_float(r.get("totalprice")) for r in datas)
                val2 = sum(safe_float(r.get("waitHxPrice")) for r in datas)
                val1_label, val2_label = "累积报销总额", "待核销余量"
                table_rows = datas

        except Exception as e:
            return f"❌ 物理链路穿透失败，请检查网络或确认网关连通性。（{e}）"

        # 渲染静态快照
        html = generate_html_report(
            system, metric_label, metric_key, time_range, start_date, end_date,
            val1_label, val1, val2_label, val2, table_rows, api_url, headers
        )
        
        preview_url = api_upload_html_to_oss(html, pwd)
        if not preview_url: return "❌ 云端计算层已响应，但未能将拓扑结构生成公网可视化快照，操作挂起。"

        ctx["last_report_url"] = preview_url
        ctx["last_report_title"] = f"{system} · {metric_label}"
        save_session(user_id, ctx)

        # 🟢 [增加底层数据支持的执行建议与总结]
        used_pct = round(val2 / val1 * 100) if val1 > 0 else 0
        advice = ""
        if used_pct >= 90:
            advice = "🔴 **风险预警**：当前指标额度/预算已趋于枯竭（>90%）。建议立刻启动红线管控机制，并审查近期大额流转业务。"
        elif used_pct >= 70:
            advice = "🟡 **执行建议**：当前额度水位偏高（>70%）。建议加强各部门核销进度跟进，防范月末超支风险。"
        elif val1 > 0:
            advice = "🟢 **执行建议**：目前整体业务运行平稳，资源余量充足，建议保持当前节奏稳健推进。"
        else:
            advice = "⚪ **执行建议**：当前筛选周期内未产生有效的基础核算数据，请检查业务流是否正常推进或调整时间探针跨度。"

        return (
            f"📊 **{ctx['last_report_title']} 空间计算完毕**\n"
            f"⏱️ 探针跨度：{time_range} ({start_date} ~ {end_date})\n\n"
            f"🔗 [🌐 点击进入深度数据空间（支持前端二次渲染与实时交叉过滤）]({preview_url})\n\n"
            f"💡 **AI 智能研报摘要**：\n"
            f"- **趋势总结**：在选定的 {time_range} 内，该业务线核心标的 **{val1_label}** 为 ¥{val1:,.2f}，实际发生 **{val2_label}** ¥{val2:,.2f}，综合占比折合 **{used_pct}%**。\n"
            f"- {advice}\n\n"
            f"> 📌 数据流已封装，您可随时对我发送「发布」将此空间沉淀至知识库。"
        )

    # 路由 4：快照固化发布
    if any(kw in full_text for kw in ["发布", "保存", "固化"]):
        if not ctx.get("last_report_url"): return "⚠️ 内存栈中暂无活跃的数据空间，请先发起查询意图。"
        ok, result = api_publish_report(ctx["last_report_url"], ctx.get("last_report_title", ""), pwd)
        if ok: return f"✅ **知识库矩阵固化成功**\n\n空间《{ctx.get('last_report_title')}》已被永久锚定。\n🔗 外部访问链接：{result}"
        return f"❌ 固化发布发生网络级异常：{result}"

    return "未能从您的表述中解析出有效意图。如需重新开始，请发送「初始化」或「重置密码」。"