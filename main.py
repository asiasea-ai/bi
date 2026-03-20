#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
@Project : 金灯塔 BI Skill (OpenClaw Universal Agent)
@Company : Asiasea (asiasea-ai)
@License : PROPRIETARY AND CONFIDENTIAL
====================================================================
v1.2.0 - 对齐开发整理汇报文档
  · supported-systems 返回值完整存储（oss_api / oss_static_domain）
  · Token 存储 expires_at，调用前主动检查，<5 分钟提前刷新
  · ECharts 地址改用 oss_static_domain 动态拼接
  · OSS 上传文件名带时间戳，防覆盖
  · oss_api 地址从 session 读取，不硬编码
  · 数据为空时不生成报表，询问用户调整条件
  · HTML 改为白底蓝灰主色，底部增加总结区
  · 发布接口 payload 对齐规范（含 system_name / created_by）
  · 请求参数从 api_registry params[] 按需构建，不再乱枪打鸟
====================================================================
"""
import json
import os
import datetime
import requests

# ==================== 常量 ====================
DEFAULT_OSS_STATIC_DOMAIN = "https://jindengta-archive.oss-cn-beijing.aliyuncs.com/theme/web/bi"
PUBLISH_API = "https://bi-api.jindengta.cn/supply-chain/api/skills/archive/push"

# ==================== 多用户状态隔离 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_session_file(user_id: str) -> str:
    safe = "".join(c for c in str(user_id) if c.isalnum() or c in ("-", "_")) if user_id else "default_user"
    return os.path.join(BASE_DIR, f".session_{safe}.json")

def load_session(user_id: str) -> dict:
    f = get_session_file(user_id)
    if os.path.exists(f):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            pass
    return {
        "auth_password": None,
        "awaiting_password": False,
        "initialized": False,
        "user_phone": None,
        # OSS 配置（从 supported-systems 接口获取）
        "oss_domain": None,
        "oss_api": None,
        "oss_static_domain": None,
        # 系统上下文
        "system_name": None,
        "system_id": None,
        "system_auth_headers": {},
        "token_expires_at": None,
        # api_registry 不缓存，每次查询前实时拉取
        # 报表上下文
        "last_report_url": None,
        "last_report_title": None,
    }

def save_session(user_id: str, data: dict):
    with open(get_session_file(user_id), "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)

# ==================== 数据工具 ====================
def safe_float(val) -> float:
    try:
        if val is None or val == "":
            return 0.0
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

_FIELD_DICT = {
    "budgettotal": "总基数", "usedamount": "消耗额", "totalprice": "累计金额",
    "waithxprice": "待核销额", "budgetno": "业务单号", "applyusername": "申请人",
    "departmentname": "部门", "ewecomfepartmentname": "业务组织",
    "statusname": "当前状态", "createtime": "创建时间",
}

def t_key(k: str) -> str:
    return _FIELD_DICT.get(str(k).lower(), str(k))

def extract_generic_schema(datas: list) -> tuple:
    """多样本投票判断字段类型，避免首条 None 误判"""
    if not datas:
        return [], []
    sample_size = min(10, len(datas))
    samples = datas[:sample_size]
    all_keys = list(samples[0].keys())
    _skip = {"id", "pageno", "pagesize", "tenantid", "method"}

    num_votes: dict = {k: 0 for k in all_keys if str(k).lower() not in _skip}
    txt_votes: dict = {k: 0 for k in all_keys if str(k).lower() not in _skip}

    for row in samples:
        for k in num_votes:
            v = row.get(k)
            if v is None or v == "":
                continue
            try:
                float(v)
                num_votes[k] += 1
            except (ValueError, TypeError):
                txt_votes[k] += 1

    threshold = sample_size * 0.5
    num_k = [k for k in num_votes if num_votes[k] >= threshold]
    txt_k = [k for k in txt_votes if txt_votes.get(k, 0) >= threshold and k not in num_k]
    priority = ["total", "amount", "price", "num"]
    num_k.sort(key=lambda x: sum(1 for p in priority if p in x.lower()), reverse=True)
    return num_k[:2], txt_k[:4]

def infer_chart_type(txt_keys: list, datas: list) -> str:
    """
    时间维度字段 → line；数据条数少且单指标 → pie；其余 → bar
    """
    time_hints = {"time", "date", "month", "year", "day", "week", "period", "日期", "月份", "年份"}
    for k in txt_keys:
        if any(h in str(k).lower() for h in time_hints):
            return "line"
    if len(datas) <= 6:
        return "pie"
    return "bar"

def match_api_by_intent(text: str, api_registry: list):
    """双向中文子串匹配：Pass1 精确 → Pass2 滑窗模糊"""
    def clean(name: str) -> str:
        for kw in ["查询", "列表", "接口文档", "接口"]:
            name = name.replace(kw, "")
        return name.strip()

    candidates = [(api, clean(api.get("name", ""))) for api in api_registry]
    candidates = [(api, name) for api, name in candidates if name]

    for api, name in candidates:
        if name in text:
            return api

    sub_windows: set = set()
    for wlen in range(2, 7):
        for i in range(len(text) - wlen + 1):
            sub_windows.add(text[i:i + wlen])

    for api, name in candidates:
        if any(sw in name for sw in sub_windows):
            return api
    return None

# ==================== Token 主动过期检查 ====================
def is_token_near_expiry(ctx: dict) -> bool:
    """距过期不足 5 分钟则需要提前刷新"""
    expires_at = ctx.get("token_expires_at")
    if not expires_at:
        return False
    try:
        exp = datetime.datetime.fromisoformat(str(expires_at))
        return datetime.datetime.now() >= exp - datetime.timedelta(minutes=5)
    except Exception:
        return False

# ==================== 后端 API 桥接层 ====================
def build_business_headers(ctx_headers: dict) -> dict:
    h = {"Content-Type": "application/json"}
    if isinstance(ctx_headers, dict):
        for k, v in ctx_headers.items():
            h[k] = str(v)
    return h

def api_get_supported_systems(auth_pwd: str) -> tuple:
    """
    返回 (systems_list, oss_config_dict)
    oss_config: { oss_domain, oss_api, oss_static_domain }
    """
    try:
        resp = requests.get(
            "https://bi-api.jindengta.cn/supply-chain/api/auth/supported-systems",
            headers={"auth": auth_pwd}, timeout=5
        ).json()
        if resp.get("code") == 100000:
            result = resp.get("result", {})
            oss_config = {
                "oss_domain": result.get("oss_domain", ""),
                "oss_api": result.get("oss_api", ""),
                "oss_static_domain": result.get("oss_static_domain") or DEFAULT_OSS_STATIC_DOMAIN,
            }
            return result.get("list", []), oss_config
    except Exception:
        pass
    return [], {}

def api_get_registry(system_id: int, auth_pwd: str) -> list:
    try:
        resp = requests.get(
            f"https://bi-api.jindengta.cn/supply-chain/api/system/api-registry?system_id={system_id}",
            headers={"auth": auth_pwd}, timeout=5
        ).json()
        if resp.get("code") == 100000:
            return resp.get("result", {}).get("list", [])
    except Exception:
        pass
    return []

def api_get_system_token(system_id: int, auth_pwd: str) -> tuple:
    """返回 (auth_headers_dict, expires_at_str | None)"""
    try:
        resp = requests.get(
            f"https://bi-api.jindengta.cn/supply-chain/api/auth/system-token?system_id={system_id}",
            headers={"auth": auth_pwd}, timeout=5
        ).json()
        if resp.get("code") == 100000:
            result = resp.get("result", {})
            data = result.get("data", {})
            expires_at = result.get("expires_at") or data.get("expires_at")
            return data, expires_at
    except Exception:
        pass
    return {}, None

def _is_token_expired(resp: dict) -> bool:
    if resp.get("code") in [401, 403, 40001]:
        return True
    msg = str(resp.get("msg", "") or "").lower()
    return any(k in msg for k in ["失效", "过期", "token", "unauthorized", "expire"])

def _refresh_token(ctx: dict, auth_pwd: str, user_id: str):
    """刷新 Token 并更新 session。成功返回 None，失败返回错误描述。"""
    new_auth, new_expires = api_get_system_token(ctx.get("system_id"), auth_pwd)
    if not new_auth:
        return "Token 已过期，且刷新失败（请检查 auth 密码或联系管理员）。"
    ctx["system_auth_headers"] = new_auth
    ctx["token_expires_at"] = new_expires
    save_session(user_id, ctx)
    return None

def fetch_business_data(api_url: str, params: dict, ctx: dict, auth_pwd: str, user_id: str) -> tuple:
    """
    带无感 Token 刷新的业务请求。
    Step 0: 调用前主动检查过期（<5分钟提前刷新）
    Step 1: 发起请求
    Step 2: 响应 401 等 → 刷新 → 重试一次
    返回 (datas: list, error: str | None)
    """
    if is_token_near_expiry(ctx):
        err = _refresh_token(ctx, auth_pwd, user_id)
        if err:
            return [], err

    headers = build_business_headers(ctx.get("system_auth_headers", {}))
    try:
        resp = requests.get(api_url, headers=headers, params=params, timeout=10).json()
    except Exception as e:
        return [], f"网络请求失败：{e}"

    if _is_token_expired(resp):
        err = _refresh_token(ctx, auth_pwd, user_id)
        if err:
            return [], err
        headers = build_business_headers(ctx.get("system_auth_headers", {}))
        try:
            resp = requests.get(api_url, headers=headers, params=params, timeout=10).json()
        except Exception as e:
            return [], f"Token 刷新后重试请求失败：{e}"

    if resp.get("code") != 100000:
        return [], f"网关阻断：{resp.get('msg', '未知业务错')}（code={resp.get('code')}）"

    return resp.get("data", {}).get("datas", []), None

def api_upload_html_to_oss(html_content: str, auth_pwd: str, oss_api: str,
                            system_name: str, report_name: str) -> str:
    """文件名带时间戳防覆盖：{system}_{report}_{YYYYMMDD_HHmmss}.html"""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_sys = "".join(c for c in system_name if c.isalnum() or c in ("-", "_"))
    safe_rpt = "".join(c for c in report_name if c.isalnum() or c in ("-", "_"))
    filename = f"{safe_sys}_{safe_rpt}_{ts}.html"
    upload_url = oss_api if oss_api else "https://bi-api.jindengta.cn/supply-chain/api/skills/archive/upload"
    try:
        resp = requests.post(
            upload_url,
            headers={"auth": auth_pwd},
            files={"file": (filename, html_content.encode("utf-8"), "text/html")},
            timeout=15,
        ).json()
        if resp.get("code") == 100000:
            return resp.get("result", {}).get("preview_url", "")
    except Exception:
        pass
    return ""

def api_publish_report(system_id: int, url: str, user_phone: str, auth_pwd: str) -> tuple:
    """
    发布接口：/push
    payload: { system_id, file_url, user_phone }
    """
    try:
        resp = requests.post(
            PUBLISH_API,
            headers={"auth": auth_pwd},
            json={"system_id": system_id, "file_url": url, "user_phone": user_phone or ""},
            timeout=10,
        ).json()
        if resp.get("code") == 100000:
            return True, resp.get("result", {}).get("published_url", url)
        return False, resp.get("msg", "未知错误")
    except Exception as e:
        return False, str(e)

# ==================== 请求参数构建（基于 api_registry params[]） ====================
_TIME_START_HINTS = {"starttime", "createstime", "start_date", "begintime", "startdate", "stime", "begin"}
_TIME_END_HINTS   = {"endtime",   "createetime", "end_date",   "endtime",   "enddate",   "etime", "end"}

def build_api_params(api_meta: dict, start_date: str, end_date: str) -> dict:
    """
    从 api_registry 的 params[] 按文档按需构建请求参数。
    无文档时回退通用参数集。
    """
    param_defs = api_meta.get("params", [])
    if not param_defs:
        return {
            "method": "ALL", "pageNo": 1, "pageSize": 200,
            "startTime": start_date, "endTime": end_date,
            "createStime": start_date, "createEtime": end_date,
        }

    params: dict = {}
    for p in param_defs:
        field = p.get("field") or p.get("name", "")
        if not field:
            continue
        fl = field.lower()
        if fl in ("pageno", "page_no", "page"):
            params[field] = 1
        elif fl in ("pagesize", "page_size", "limit"):
            params[field] = 200
        elif fl == "method":
            params[field] = "ALL"
        elif any(h in fl for h in _TIME_START_HINTS):
            params[field] = start_date
        elif any(h in fl for h in _TIME_END_HINTS):
            params[field] = end_date
        elif p.get("required") in (True, "true", 1, "1"):
            example = p.get("example") or p.get("default")
            if example is not None:
                params[field] = example
    return params

# ==================== HTML 大屏生成 ====================
# 结构（从上至下）：报表标题区 → 筛选条件区 → BI内容区（图表+表格）→ 底部总结区
#
# 安全机制：
#   - window.UPLOAD_TOKEN = ""  ← OSS 存此空占位，后端代理返回 HTML 时动态 replace 注入真实 Token
#   - doQuery() 用注入后的 Token 发起真实 API 查询，实现时效性动态刷新
#   - OSS 文件本身永远不含凭证，符合 LICENSE 2(b)
def generate_html_report(
    oss_static_domain: str,
    system: str, metric_label: str, time_range: str, start_date: str, end_date: str,
    val1_label: str, val1: float, val2_label: str, val2: float,
    table_rows: list, num_keys: list, txt_keys: list,
    summary_html: str,
    api_url: str,
    param_defs: list,   # 来自 api_registry 的 params[]，驱动筛选区动态渲染
) -> str:
    # ECharts 固定 OSS 地址，禁止外链 CDN
    echarts_url = f"{oss_static_domain.rstrip('/')}/echarts.min.js"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    val_diff = val1 - val2
    used_pct = round(val2 / val1 * 100) if val1 > 0 else 0
    chart_type = infer_chart_type(txt_keys, table_rows)

    # ── 动态筛选区 HTML ──────────────────────────────────────────
    # 根据 param_defs 生成表单控件，隐藏系统级参数，时间参数用 date picker
    _HIDDEN_FIELDS = {"pageno", "page_no", "page", "pagesize", "page_size", "limit", "method"}

    def _is_time_start(f: str) -> bool:
        return any(h in f.lower() for h in {"starttime", "createstime", "start_date", "begintime", "startdate", "stime"})

    def _is_time_end(f: str) -> bool:
        return any(h in f.lower() for h in {"endtime", "createetime", "end_date", "endtime", "enddate", "etime"})

    filter_inputs_html = ""
    # 收集需要展示的参数（去重 start/end，只展示一对日期）
    shown_time_start = False
    shown_time_end   = False

    visible_params = []  # [(field, label, input_type, default_val, placeholder)]
    for p in (param_defs or []):
        field = p.get("field") or p.get("name", "")
        if not field or field.lower() in _HIDDEN_FIELDS:
            continue
        label     = p.get("label") or p.get("desc") or t_key(field)
        example   = p.get("example") or p.get("default") or ""

        if _is_time_start(field):
            if shown_time_start:
                continue
            shown_time_start = True
            visible_params.append((field, "开始日期", "date", start_date, ""))
        elif _is_time_end(field):
            if shown_time_end:
                continue
            shown_time_end = True
            visible_params.append((field, "结束日期", "date", end_date, ""))
        else:
            # 只显示必填的非时间参数
            if p.get("required") in (True, "true", 1, "1"):
                visible_params.append((field, label, "text", str(example), str(example)))

    # 如果 param_defs 里没有时间字段（兜底），强制加一对日期
    if not shown_time_start:
        visible_params.insert(0, ("startTime", "开始日期", "date", start_date, ""))
    if not shown_time_end:
        idx = 1 if shown_time_start or not visible_params else 1
        visible_params.insert(idx, ("endTime", "结束日期", "date", end_date, ""))

    for field, label, itype, default_val, placeholder in visible_params:
        ph = f'placeholder="{placeholder}"' if placeholder else ""
        filter_inputs_html += (
            f'<label class="filter-label">{label}：</label>'
            f'<input type="{itype}" id="fi_{field}" name="{field}" '
            f'value="{default_val}" {ph} class="filter-input">'
        )

    # CFG 里带上 param_defs 供 doQuery 动态构建请求参数
    cfg = json.dumps({
        "url": api_url,
        "num_keys": num_keys,
        "txt_keys": txt_keys,
        "val1_label": val1_label,
        "val2_label": val2_label,
        "chart_type": chart_type,
        "param_defs": [
            {"field": (p.get("field") or p.get("name", "")),
             "is_time_start": _is_time_start(p.get("field") or p.get("name", "")),
             "is_time_end":   _is_time_end(p.get("field") or p.get("name", "")),
             "hidden": (p.get("field") or p.get("name", "")).lower() in _HIDDEN_FIELDS}
            for p in (param_defs or [])
            if (p.get("field") or p.get("name", ""))
        ],
        # 兜底时间字段名（当 param_defs 无时间字段时使用）
        "fallback_time_start": "startTime" if not shown_time_start else "",
        "fallback_time_end":   "endTime"   if not shown_time_end   else "",
    }, ensure_ascii=False)

    # 初始渲染表头 + 表体（最多 200 条）
    thead = (
        "<tr>"
        + "".join(f"<th>{t_key(k)}</th>" for k in txt_keys)
        + "".join(f"<th>{t_key(k)}</th>" for k in num_keys)
        + "</tr>"
    )
    tbody_rows = ""
    for i, r in enumerate(table_rows[:200]):
        row_cls = " class='alt'" if i % 2 == 1 else ""
        tbody_rows += f"<tr{row_cls}>"
        for k in txt_keys:
            tbody_rows += f"<td>{r.get(k) or '—'}</td>"
        for k in num_keys:
            tbody_rows += f"<td class='num'>¥{safe_float(r.get(k)):,.2f}</td>"
        tbody_rows += "</tr>"

    # 初始图表选项（静态数据，doQuery 刷新后会重绘）
    if chart_type == "line" and txt_keys and num_keys:
        x_data = json.dumps([str(r.get(txt_keys[0], "")) for r in table_rows[:200]], ensure_ascii=False)
        y_data = json.dumps([safe_float(r.get(num_keys[0])) for r in table_rows[:200]])
        init_chart_js = f"""
    mainChart.setOption({{
      tooltip: {{ trigger:'axis' }},
      grid: {{ left:'3%', right:'4%', bottom:'8%', top:'8%', containLabel:true }},
      xAxis: {{ type:'category', data:{x_data}, axisLabel:{{ rotate:30, color:'#606266' }} }},
      yAxis: {{ type:'value', axisLabel:{{ color:'#606266', formatter: function(v){{ return '¥'+v.toLocaleString(); }} }} }},
      series: [{{
        name:{json.dumps(t_key(num_keys[0]), ensure_ascii=False)}, type:'line',
        data:{y_data}, smooth:true,
        areaStyle:{{ color:{{ type:'linear',x:0,y:0,x2:0,y2:1,
          colorStops:[{{offset:0,color:'rgba(64,158,255,0.25)'}},{{offset:1,color:'rgba(64,158,255,0)'}}] }} }},
        itemStyle:{{color:'#409EFF'}}, lineStyle:{{color:'#409EFF',width:2}}
      }}]
    }});"""
    elif chart_type == "pie" and txt_keys and num_keys:
        pie_data = json.dumps(
            [{"name": str(r.get(txt_keys[0], "—")), "value": safe_float(r.get(num_keys[0]))}
             for r in table_rows[:200]],
            ensure_ascii=False
        )
        init_chart_js = f"""
    mainChart.setOption({{
      tooltip: {{ trigger:'item', formatter:'{{b}}: ¥{{c}} ({{d}}%)' }},
      legend: {{ orient:'vertical', left:'left', textStyle:{{color:'#606266'}} }},
      series: [{{
        type:'pie', radius:['40%','70%'], data:{pie_data},
        label:{{ formatter:'{{b}}\\n{{d}}%', color:'#303133' }}
      }}]
    }});"""
    else:
        s1_data = json.dumps([safe_float(r.get(num_keys[0])) for r in table_rows[:30]]) if num_keys else "[]"
        s2_data = json.dumps([safe_float(r.get(num_keys[1])) for r in table_rows[:30]]) if len(num_keys) > 1 else "[]"
        x_data = json.dumps([str(r.get(txt_keys[0], "")) if txt_keys else "" for r in table_rows[:30]], ensure_ascii=False)
        series2 = (
            f"{{ name:{json.dumps(val2_label, ensure_ascii=False)}, type:'bar', data:{s2_data}, barWidth:'25%',"
            f" itemStyle:{{color:'#67C23A', borderRadius:[4,4,0,0]}} }},"
        ) if len(num_keys) > 1 else ""
        init_chart_js = f"""
    mainChart.setOption({{
      tooltip: {{ trigger:'axis', axisPointer:{{type:'shadow'}} }},
      legend: {{ top:8, textStyle:{{color:'#606266'}} }},
      grid: {{ left:'3%', right:'4%', bottom:'8%', top:'16%', containLabel:true }},
      xAxis: {{ type:'category', data:{x_data}, axisLabel:{{ rotate:30, color:'#606266' }} }},
      yAxis: {{ type:'value', axisLabel:{{ color:'#606266', formatter: function(v){{ return '¥'+v.toLocaleString(); }} }} }},
      series: [
        {{ name:{json.dumps(val1_label, ensure_ascii=False)}, type:'bar', data:{s1_data}, barWidth:'25%',
          itemStyle:{{color:'#409EFF', borderRadius:[4,4,0,0]}} }},
        {series2}
      ]
    }});"""

    # doQuery 重绘图表选项模板（使用 JS 动态数据，变量名与 doQuery 内一致）
    redraw_chart_line = f"""
    mainChart.setOption({{
      tooltip: {{ trigger:'axis' }},
      grid: {{ left:'3%', right:'4%', bottom:'8%', top:'8%', containLabel:true }},
      xAxis: {{ type:'category', data:xArr, axisLabel:{{ rotate:30, color:'#606266' }} }},
      yAxis: {{ type:'value', axisLabel:{{ color:'#606266', formatter: function(v){{ return '¥'+v.toLocaleString(); }} }} }},
      series: [{{
        name:{json.dumps(t_key(num_keys[0]) if num_keys else val1_label, ensure_ascii=False)},
        type:'line', data:y1Arr, smooth:true,
        areaStyle:{{ color:{{ type:'linear',x:0,y:0,x2:0,y2:1,
          colorStops:[{{offset:0,color:'rgba(64,158,255,0.25)'}},{{offset:1,color:'rgba(64,158,255,0)'}}] }} }},
        itemStyle:{{color:'#409EFF'}}, lineStyle:{{color:'#409EFF',width:2}}
      }}]
    }});"""
    redraw_chart_pie = f"""
    var pieData = datas.slice(0,200).map(function(r){{
      return {{name: String(r[{json.dumps(txt_keys[0]) if txt_keys else '""'}]||'—'),
               value: parseFloat(r[{json.dumps(num_keys[0]) if num_keys else '""'}]||0)}};
    }});
    mainChart.setOption({{
      tooltip: {{ trigger:'item', formatter:'{{b}}: ¥{{c}} ({{d}}%)' }},
      legend: {{ orient:'vertical', left:'left', textStyle:{{color:'#606266'}} }},
      series: [{{ type:'pie', radius:['40%','70%'], data:pieData,
        label:{{ formatter:'{{b}}\\n{{d}}%', color:'#303133' }} }}]
    }});"""
    redraw_chart_bar = f"""
    mainChart.setOption({{
      tooltip: {{ trigger:'axis', axisPointer:{{type:'shadow'}} }},
      legend: {{ top:8, textStyle:{{color:'#606266'}} }},
      grid: {{ left:'3%', right:'4%', bottom:'8%', top:'16%', containLabel:true }},
      xAxis: {{ type:'category', data:xArr, axisLabel:{{ rotate:30, color:'#606266' }} }},
      yAxis: {{ type:'value', axisLabel:{{ color:'#606266', formatter: function(v){{ return '¥'+v.toLocaleString(); }} }} }},
      series: [
        {{ name:{json.dumps(val1_label, ensure_ascii=False)}, type:'bar', data:y1Arr, barWidth:'25%',
          itemStyle:{{color:'#409EFF', borderRadius:[4,4,0,0]}} }},
        {f"{{ name:{json.dumps(val2_label, ensure_ascii=False)}, type:'bar', data:y2Arr, barWidth:'25%', itemStyle:{{color:'#67C23A', borderRadius:[4,4,0,0]}} }}," if len(num_keys) > 1 else ""}
      ]
    }});"""

    # 选择 doQuery 内使用的重绘分支
    if chart_type == "line":
        redraw_chart_js = redraw_chart_line
    elif chart_type == "pie":
        redraw_chart_js = redraw_chart_pie
    else:
        redraw_chart_js = redraw_chart_bar

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{system} · {metric_label} · {time_range}</title>
<script src="{echarts_url}"></script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif;
  background: #f0f2f5; color: #303133; min-height: 100vh; padding: 20px;
}}
.container {{ max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }}
.zone {{
  background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; padding: 24px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.05);
}}

/* ── 1. 报表标题区 ── */
.zone-title {{ background: linear-gradient(to right, #fdfbfb, #ebedee); text-align: center; }}
.zone-title h2 {{ font-size: 24px; font-weight: 700; color: #303133; margin-bottom: 8px; }}
.zone-title .sub {{ font-size: 13px; color: #909399; }}
.zone-title .tag {{
  display: inline-block; margin-top: 10px; padding: 4px 14px;
  background: rgba(64,158,255,0.1); color: #409EFF;
  border-radius: 12px; font-size: 13px;
}}

/* ── 2. 筛选条件区 ── */
.zone-filter {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; border-left: 4px solid #409EFF; }}
.zone-filter label {{ font-size: 13px; font-weight: 600; color: #606266; white-space: nowrap; }}
.zone-filter input[type=date] {{
  padding: 7px 10px; border: 1px solid #dcdfe6; border-radius: 4px;
  font-size: 13px; outline: none; transition: border 0.2s; color: #303133;
}}
.zone-filter input[type=date]:focus {{ border-color: #409EFF; }}
.btn-query {{
  padding: 8px 22px; background: #409EFF; color: #fff;
  border: none; border-radius: 4px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: opacity 0.2s;
}}
.btn-query:hover {{ opacity: 0.85; }}
.btn-query:disabled {{ background: #a0cfff; cursor: not-allowed; }}
.status-tag {{ font-size: 12px; color: #909399; margin-left: 4px; }}

/* ── 3. BI 内容区 ── */
.zone-bi {{ display: flex; flex-direction: column; gap: 20px; }}
.chart-box {{ width: 100%; height: 400px; }}
.section-label {{ font-size: 13px; font-weight: 600; color: #606266; margin-bottom: 12px; }}
.tbl-wrap {{ overflow-x: auto; max-height: 480px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }}
thead th {{
  padding: 11px 14px; background: #f5f7fa; color: #606266; font-weight: 600;
  border-bottom: 1px solid #ebeef5; position: sticky; top: 0; z-index: 2; white-space: nowrap;
}}
tbody td {{ padding: 11px 14px; border-bottom: 1px solid #ebeef5; color: #606266; }}
tbody tr:nth-child(even) td {{ background: #fafafa; }}
tbody tr:hover td {{ background: #f0f7ff; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; color: #409EFF; font-weight: 500; }}

/* ── 4. 底部总结区 ── */
.zone-summary {{ background: #fafafa; }}
.zone-summary h3 {{ font-size: 15px; font-weight: 700; color: #303133; margin-bottom: 14px; }}
.kpi-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 14px; }}
.kpi-item {{ flex: 1; min-width: 160px; padding: 14px 18px; background: #fff; border-radius: 6px; border: 1px solid #ebeef5; }}
.kpi-item.blue {{ border-left: 3px solid #409EFF; }}
.kpi-item.green {{ border-left: 3px solid #67C23A; }}
.kpi-item.amber {{ border-left: 3px solid #E6A23C; }}
.kpi-item.purple {{ border-left: 3px solid #9B59B6; }}
.kpi-label {{ font-size: 12px; color: #909399; margin-bottom: 4px; }}
.kpi-val {{ font-size: 22px; font-weight: 700; color: #303133; font-variant-numeric: tabular-nums; }}
.kpi-val.blue {{ color: #409EFF; }} .kpi-val.green {{ color: #67C23A; }}
.advice-box {{
  padding: 14px 16px; border-radius: 6px; font-size: 14px; line-height: 1.8;
  border-left: 4px solid #E6A23C; background: rgba(230,162,60,0.08); color: #606266;
}}
.advice-box.green {{ border-color: #67C23A; background: rgba(103,194,58,0.08); }}
.advice-box.red {{ border-color: #F56C6C; background: rgba(245,108,108,0.08); }}
.footer-meta {{
  margin-top: 16px; padding-top: 12px; border-top: 1px dashed #e4e7ed;
  font-size: 12px; color: #c0c4cc; text-align: center;
}}

@media (max-width: 768px) {{
  body {{ padding: 12px; }}
  .kpi-row {{ flex-direction: column; }}
  .chart-box {{ height: 280px; }}
  .zone-filter {{ gap: 8px; }}
}}
</style>
</head>
<body>
<script>
  // ⚠️ 安全占位：OSS 存储此空字符串，后端预览代理返回 HTML 时动态 replace 注入真实 Token
  window.UPLOAD_TOKEN = "";
</script>

<div class="container">

  <!-- ① 报表标题区 -->
  <div class="zone zone-title">
    <h2>📊 {system} · {metric_label}</h2>
    <div class="sub">数据时间范围：{start_date} 至 {end_date}</div>
    <span class="tag" id="status_tag">📦 {len(table_rows)} 条 · 快照生成于 {now_str}</span>
  </div>

  <!-- ② 筛选条件区（根据接口 params[] 动态渲染） -->
  <div class="zone zone-filter">
    <label class="filter-label" style="font-weight:600;">筛选条件：</label>
    {filter_inputs_html}
    <button class="btn-query" id="btn_q" onclick="doQuery()">🔍 查询</button>
    <span class="status-tag" id="msg_tag"></span>
  </div>

  <!-- ③ BI 内容区 -->
  <div class="zone zone-bi">
    <!-- 上方：图表 -->
    <div>
      <div class="section-label">📈 数据图表</div>
      <div id="chart_box" class="chart-box"></div>
    </div>
    <!-- 下方：明细表格 -->
    <div>
      <div class="section-label">📋 数据明细（共 <span id="total_count">{len(table_rows)}</span> 条，展示前 200 条）</div>
      <div class="tbl-wrap">
        <table>
          <thead id="tbl_head">{thead}</thead>
          <tbody id="tbl_body">{tbody_rows}</tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ④ 底部总结区 -->
  <div class="zone zone-summary">
    <h3>💡 数据总结与建议</h3>
    <div class="kpi-row">
      <div class="kpi-item blue">
        <div class="kpi-label">{val1_label}</div>
        <div class="kpi-val blue" id="sum_v1">¥{val1:,.2f}</div>
      </div>
      <div class="kpi-item green">
        <div class="kpi-label">{val2_label}</div>
        <div class="kpi-val green" id="sum_v2">¥{val2:,.2f}</div>
      </div>
      <div class="kpi-item amber">
        <div class="kpi-label">差额</div>
        <div class="kpi-val" id="sum_diff">¥{abs(val_diff):,.2f}</div>
      </div>
      <div class="kpi-item purple">
        <div class="kpi-label">度量比率</div>
        <div class="kpi-val" id="sum_pct">{used_pct}%</div>
      </div>
    </div>
    <div class="advice-box" id="advice_box">{summary_html}</div>
    <div class="footer-meta">
      ⏱ 生成时间：{now_str} &nbsp;·&nbsp; 数据来源：{system} · {metric_label} &nbsp;·&nbsp; 金灯塔 BI 数据引擎
    </div>
  </div>

</div>

<script>
var mainChart = echarts.init(document.getElementById('chart_box'));
var CFG = {cfg};

var FIELD_DICT = {{
  "budgettotal":"总基数","usedamount":"消耗额","totalprice":"累计金额","waithxprice":"待核销额",
  "budgetno":"业务单号","applyusername":"申请人","departmentname":"部门",
  "ewecomfepartmentname":"业务组织","statusname":"当前状态","createtime":"创建时间"
}};
function tKey(k) {{ return FIELD_DICT[String(k).toLowerCase()] || k; }}
function fmt(n) {{ return (n||0).toLocaleString('zh-CN', {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}

// 初始渲染（静态数据）
(function initChart() {{
  {init_chart_js}
  window.addEventListener('resize', function() {{ mainChart.resize(); }});
}})();

// 动态查询：使用后端代理注入的 Token
async function doQuery() {{
  var btn = document.getElementById('btn_q');
  var msg = document.getElementById('msg_tag');
  var tag = document.getElementById('status_tag');
  btn.disabled = true; btn.textContent = '查询中...';
  msg.textContent = ''; tag.textContent = '⏳ 正在拉取最新数据...';

  // 组装请求头
  var headers = {{ 'Content-Type': 'application/json' }};
  if (window.UPLOAD_TOKEN) {{
    headers['auth']          = window.UPLOAD_TOKEN;
    headers['Authorization'] = window.UPLOAD_TOKEN;
    headers['token']         = window.UPLOAD_TOKEN;
  }}

  // 动态构建请求参数：从 CFG.param_defs 遍历，读取对应表单控件的值
  var u = new URL(CFG.url);
  var startVal = '', endVal = '';

  // 固定系统参数
  u.searchParams.set('pageNo',   '1');
  u.searchParams.set('pageSize', '200');
  u.searchParams.set('method',   'ALL');

  if (CFG.param_defs && CFG.param_defs.length > 0) {{
    CFG.param_defs.forEach(function(p) {{
      if (p.hidden) return;
      var el = document.getElementById('fi_' + p.field);
      if (!el) return;
      var val = el.value;
      if (!val) return;
      u.searchParams.set(p.field, val);
      if (p.is_time_start) startVal = val;
      if (p.is_time_end)   endVal   = val;
    }});
  }}

  // 兜底：param_defs 无时间字段时读取兜底控件
  if (CFG.fallback_time_start) {{
    var el = document.getElementById('fi_' + CFG.fallback_time_start);
    if (el && el.value) {{ u.searchParams.set(CFG.fallback_time_start, el.value); startVal = el.value; }}
  }}
  if (CFG.fallback_time_end) {{
    var el = document.getElementById('fi_' + CFG.fallback_time_end);
    if (el && el.value) {{ u.searchParams.set(CFG.fallback_time_end, el.value); endVal = el.value; }}
  }}

  if (!startVal || !endVal) {{ alert('请填写完整时间范围'); btn.disabled=false; btn.textContent='🔍 查询'; return; }}

  try {{
    var res = await fetch(u.toString(), {{ method: 'GET', headers: headers }});
    var d   = await res.json();
    if (d.code !== 100000) throw new Error(d.msg || '接口拒绝响应');

    var datas = (d.data && d.data.datas) || [];
    var nv1 = 0, nv2 = 0;

    // 重建表头
    var thHtml = '<tr>';
    CFG.txt_keys.forEach(function(k) {{ thHtml += '<th>' + tKey(k) + '</th>'; }});
    CFG.num_keys.forEach(function(k) {{ thHtml += '<th>' + tKey(k) + '</th>'; }});
    thHtml += '</tr>';
    document.getElementById('tbl_head').innerHTML = thHtml;

    // 重建表体
    var tbHtml = '';
    datas.slice(0, 200).forEach(function(r, idx) {{
      var v1 = CFG.num_keys.length > 0 ? parseFloat(r[CFG.num_keys[0]] || 0) : 0;
      var v2 = CFG.num_keys.length > 1 ? parseFloat(r[CFG.num_keys[1]] || 0) : 0;
      nv1 += v1; nv2 += v2;
      var cls = idx % 2 === 1 ? ' class="alt"' : '';
      tbHtml += '<tr' + cls + '>';
      CFG.txt_keys.forEach(function(k) {{ tbHtml += '<td>' + (r[k] || '—') + '</td>'; }});
      CFG.num_keys.forEach(function(k) {{
        tbHtml += '<td class="num">¥' + parseFloat(r[k] || 0).toLocaleString('zh-CN', {{minimumFractionDigits:2}}) + '</td>';
      }});
      tbHtml += '</tr>';
    }});
    document.getElementById('tbl_body').innerHTML = tbHtml;
    document.getElementById('total_count').textContent = datas.length;

    // 重绘 KPI
    var diff = Math.abs(nv1 - nv2);
    var pct  = nv1 > 0 ? Math.round(nv2 / nv1 * 100) : 0;
    document.getElementById('sum_v1').textContent   = '¥' + fmt(nv1);
    document.getElementById('sum_v2').textContent   = '¥' + fmt(nv2);
    document.getElementById('sum_diff').textContent = '¥' + fmt(diff);
    document.getElementById('sum_pct').textContent  = pct + '%';

    // 重绘建议
    var adv = document.getElementById('advice_box');
    adv.className = 'advice-box';
    if (nv1 === 0 && nv2 === 0) {{
      adv.innerHTML = '⚪ 该时段未捕获到有效业务数据，建议扩大时间范围或核查上游流水。';
    }} else if (pct >= 90) {{
      adv.classList.add('red');
      adv.innerHTML = '🔴 <strong>风险预警</strong>：【' + CFG.val2_label + '】占【' + CFG.val1_label + '】比重已达 <strong>' + pct + '%</strong>，触及高位警戒线，建议立刻启动熔断或人工复核机制。';
    }} else if (pct >= 70) {{
      adv.innerHTML = '🟡 <strong>管控提示</strong>：结构化比率已达 <strong>' + pct + '%</strong>，处于偏高水位，请密切跟踪后续资源流转动向。';
    }} else {{
      adv.classList.add('green');
      adv.innerHTML = '🟢 <strong>执行建议</strong>：数据基盘稳定，核心转化率在合理区间（<strong>' + pct + '%</strong>），可保持现有资源释放节奏。';
    }}

    // 重绘图表
    var xArr  = datas.slice(0,200).map(function(r){{ return String(r[CFG.txt_keys[0]] || ''); }});
    var y1Arr = datas.slice(0,200).map(function(r){{ return parseFloat(r[CFG.num_keys[0]] || 0); }});
    var y2Arr = CFG.num_keys.length > 1
      ? datas.slice(0,200).map(function(r){{ return parseFloat(r[CFG.num_keys[1]] || 0); }})
      : [];
    {redraw_chart_js}

    tag.textContent = '✅ 数据已更新（' + datas.length + ' 条）';
  }} catch(err) {{
    tag.textContent = '❌ 查询失败：' + err.message;
    msg.textContent = '（Token 可能已过期，请刷新预览链接重试）';
  }} finally {{
    btn.disabled = false; btn.textContent = '🔍 查询';
  }}
}}
</script>
</body>
</html>"""

# ==================== 建议文本（对话 + HTML 两套） ====================
def build_advice(val1: float, val2: float, val1_label: str, val2_label: str) -> tuple:
    """返回 (plain_text, html_text)"""
    used_pct = round(val2 / val1 * 100) if val1 > 0 else 0
    if used_pct >= 90:
        plain = f"风险预警：{val2_label} 占 {val1_label} 比重达 {used_pct}%，触及高位警戒线，建议立刻启动熔断或复核机制。"
        html  = (f"🔴 <strong>风险预警</strong>：当前【{val2_label}】占【{val1_label}】比重已达 <strong>{used_pct}%</strong>，"
                 f"触及高位警戒线，建议立刻启动熔断或复核机制。")
    elif used_pct >= 70:
        plain = f"管控提示：{val2_label} 占 {val1_label} 比重达 {used_pct}%，处于偏高水位，请密切跟踪后续流转。"
        html  = (f"🟡 <strong>管控提示</strong>：结构化比率已达 <strong>{used_pct}%</strong>，"
                 f"处于偏高水位，请密切跟踪后续流转动向。")
    else:
        plain = f"数据稳定：{val2_label} 占 {val1_label} 比重为 {used_pct}%，在合理区间内，可保持现有节奏。"
        html  = (f"🟢 <strong>执行建议</strong>：数据基盘稳定，核心转化率在合理区间（<strong>{used_pct}%</strong>），"
                 f"可保持现有资源释放节奏。")
    return plain, html

# ==================== OpenClaw 主入口 ====================
def handle(command: str, args: list, **kwargs) -> str:
    user_id = kwargs.get("user_id", kwargs.get("sender_id", "default_user"))
    ctx = load_session(user_id)
    cmd = command.strip().lstrip("/")
    full_text = (cmd + " " + " ".join(args)).strip()

    # ── 全局密码拦截 ──────────────────────────────────────────
    if not ctx.get("auth_password"):
        if ctx.get("awaiting_password"):
            pwd = full_text.strip()
            ctx["auth_password"] = pwd
            ctx["awaiting_password"] = False
            ctx["initialized"] = True

            systems, oss_config = api_get_supported_systems(pwd)
            if not systems:
                ctx["auth_password"] = None
                ctx["awaiting_password"] = False
                save_session(user_id, ctx)
                return "❌ 通信加密失败或网络异常，未获取到业务域。请检查密码是否正确，发送「初始化」重试。"

            ctx.update(oss_config)
            save_session(user_id, ctx)

            lines = ["🔐 **安全握手成功，大模型链路已就绪。**\n", "💡 **请指定要挂载的物理板块：**"]
            for s in systems:
                lines.append(f"- **{s.get('system_name')}**")
            lines.append("\n*(提示：回复 切换系统 <板块名>)*")
            lines.append("\n> 🛡️ *为了您的账号安全，建议长按撤回刚才输入的密码消息。*")
            return "\n".join(lines)
        else:
            ctx["awaiting_password"] = True
            save_session(user_id, ctx)
            return "🛡️ **网关安全锁验证**\n\n请输入您的访问授权密码："

    pwd = ctx.get("auth_password")

    # ── 固定指令路由 ──────────────────────────────────────────
    if cmd in ["初始化", "重置", "重置密码"]:
        ctx.update({"auth_password": None, "awaiting_password": True, "initialized": False})
        save_session(user_id, ctx)
        return "🛡️ **环境锁已阻断**\n\n**请重新输入新会话的访问密码**："

    if cmd == "系统列表":
        systems, _ = api_get_supported_systems(pwd)
        if not systems:
            return "❌ 获取业务域失败，请确认底层网关状态。"
        curr = ctx.get("system_name")
        lines = ["📋 **当前网络内的业务域：**\n"]
        for s in systems:
            lines.append(f"- **{s.get('system_name')}**" + (" ✅" if curr == s.get("system_name") else ""))
        return "\n".join(lines)

    if cmd.startswith("切换系统"):
        if not args:
            return "❌ 缺失目标参数，例如：`切换系统 E网`"
        target = args[0]
        systems, oss_config = api_get_supported_systems(pwd)
        if oss_config:
            ctx.update(oss_config)
        target_sys = next((s for s in systems if s.get("system_name") == target), None)
        if not target_sys:
            return f"❌ 未能锚定「{target}」节点。发送「系统列表」查看可用板块。"
        sys_id = target_sys.get("id")
        auth_data, expires_at = api_get_system_token(sys_id, pwd)
        if not auth_data:
            return f"❌ 越权阻断：「{target}」未能下发访问凭证。"
        ctx.update({
            "system_name": target, "system_id": sys_id,
            "system_auth_headers": auth_data,
            "token_expires_at": expires_at,
        })
        save_session(user_id, ctx)

        # 实时拉一次注册表，仅用于展示可用维度，不存 session
        api_list = api_get_registry(sys_id, pwd)

        clean_names = [
            api.get("name", "").replace("查询", "").replace("列表", "").replace("接口文档", "").strip()
            for api in api_list
        ]
        clean_names = [n for n in clean_names if n]
        avail_str = "、".join(clean_names)
        sample = clean_names[0] if clean_names else "业务快照"
        return (
            f"✅ 已为您切入 **{target}** 数据池。\n\n"
            f"📌 **当前可分析的维度：** {avail_str}\n\n"
            f"> 💡 直接对我说：**「帮我分析本月的{sample}」**"
        )

    if any(kw in full_text for kw in ["发布", "保存", "固化"]):
        if not ctx.get("last_report_url"):
            return "⚠️ 内存无活跃对象，请先发起数据查询。"
        ok, result = api_publish_report(
            ctx.get("system_id"),
            ctx["last_report_url"],
            ctx.get("user_phone", ""),
            pwd,
        )
        if ok:
            return (f"✅ **报表已发布至胜算平台**\n\n"
                    f"《{ctx.get('last_report_title')}》已永久锚定。\n"
                    f"🔗 平台链接：{result}")
        return f"❌ 发布失败：{result}"

    # ── BI 意图解析：优先匹配 api_registry（每次实时拉取，不用 session 缓存） ──
    system = ctx.get("system_name")
    sys_id = ctx.get("system_id")

    if system and sys_id:
        # 实时拉取最新注册表，确保路由元数据不过期
        api_registry = api_get_registry(sys_id, pwd)
        if not api_registry:
            return (
                f"⚠️ 实时获取【{system}】接口注册表失败。\n\n"
                f"可能原因：网关暂时不可用，或该系统无已注册接口。\n"
                f"请稍后重试，或联系管理员确认注册表配置。"
            )
        target_api = match_api_by_intent(full_text, api_registry)

        if not target_api:
            avail = [
                a.get("name", "").replace("查询", "").replace("接口文档", "").strip()
                for a in api_registry
            ]
            avail_str = "、".join(filter(None, avail))
            return (
                f"⚠️ 在【{system}】中未能匹配到您说的业务维度。\n\n"
                f"📌 **当前支持分析的维度有：** {avail_str}\n\n"
                f"请描述您想分析哪个维度，例如：「帮我分析本月的{avail[0] if avail else '报销单'}」"
            )

        start_date, end_date, time_range = parse_time_keywords(full_text)
        if not start_date:
            metric_hint = target_api.get("name", "").replace("接口文档", "")
            return f"⚠️ 已锁定【{metric_hint}】，请补充**时间范围**（如：本月、上月、昨日、今年）。"

        metric_label = target_api.get("name", "业务洞察").replace("接口文档", "")
        raw_path = target_api.get("path", "")
        req_url = target_api.get("request_url", "")

        if raw_path.startswith("http"):
            api_url = raw_path
        else:
            if not req_url:
                return (f"❌ 接口路由配置异常：网关未下发【{metric_label}】的 request_url，请联系管理员修复。")
            api_url = req_url.rstrip("/") + "/" + raw_path.lstrip("/")

        params = build_api_params(target_api, start_date, end_date)
        datas, err = fetch_business_data(api_url, params, ctx, pwd, user_id)
        if err:
            return f"❌ {err}"

        # 数据为空：不生成报表，询问用户
        if not datas:
            return (
                f"⚠️ **【{metric_label}】在 {time_range}（{start_date} ～ {end_date}）内未查询到数据。**\n\n"
                f"可能原因：该时段无业务记录，或筛选条件过严。\n"
                f"是否调整时间范围重新查询？（如：上月、今年）"
            )

        num_keys, txt_keys = extract_generic_schema(datas)
        val1_key = num_keys[0] if len(num_keys) > 0 else ""
        val2_key = num_keys[1] if len(num_keys) > 1 else ""
        val1 = sum(safe_float(r.get(val1_key)) for r in datas) if val1_key else 0.0
        val2 = sum(safe_float(r.get(val2_key)) for r in datas) if val2_key else 0.0
        val1_label = t_key(val1_key) if val1_key else "主度量值"
        val2_label = t_key(val2_key) if val2_key else "副度量值"

        advice_plain, advice_html = build_advice(val1, val2, val1_label, val2_label)

        oss_static = ctx.get("oss_static_domain") or DEFAULT_OSS_STATIC_DOMAIN
        html = generate_html_report(
            oss_static, system, metric_label, time_range, start_date, end_date,
            val1_label, val1, val2_label, val2,
            datas, num_keys, txt_keys,
            summary_html=advice_html,
            api_url=api_url,
            param_defs=target_api.get("params", []),
        )

        oss_api = ctx.get("oss_api") or ""
        preview_url = api_upload_html_to_oss(html, pwd, oss_api, system, metric_label)
        if not preview_url:
            return (
                "❌ 数据已获取，但 OSS 上传失败。\n\n"
                "请稍后重新发送相同指令重试，或联系管理员检查 OSS 服务状态。"
            )

        ctx["last_report_url"] = preview_url
        ctx["last_report_title"] = f"{system} · {metric_label} · {time_range}"
        save_session(user_id, ctx)

        gen_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"📊 **{metric_label}**\n\n"
            f"🔗 预览地址：{preview_url}\n\n"
            f"📝 总结与建议：\n{advice_plain}\n\n"
            f"⏱ 生成时间：{gen_time}\n\n"
            f"---\n"
            f"需要将该报表**发布到胜算平台**，还是设置**定时推送**？"
        )

    # ── 兜底 ──
    if not ctx.get("system_name"):
        return (
            "⚠️ 未检测到挂载域。\n\n"
            "请先发送「系统列表」查看可用板块，再通过「切换系统 <板块名>」进入对应数据域。"
        )
    return "未能解析此意图。如需新指令请直接对话，或回复「重置密码」清空鉴权。"