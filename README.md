# 🌌 金灯塔 BI Skill

> 基于 OpenClaw 构建的企业级智能 BI 数据代理。通过自然语言驱动实时 API 穿透，端到端生成可交互可视化报表。

**Repository**：`asiasea-ai/bi`  
**Version**：1.3.0  
**License**：PROPRIETARY AND CONFIDENTIAL

---

## 核心能力

- **自然语言 → 实时数据**：识别用户意图，匹配业务 API，每次查询实时穿透，不复用缓存
- **多系统动态切换**：通过元数据注册表支持任意数量的异构业务系统，无需改代码
- **Token 全生命周期管理**：调用前主动检查过期（<5 分钟），401 后无感刷新重试
- **安全 HTML 快照**：OSS 文件无凭证，Token 由后端代理在返回时动态注入
- **可交互报表**：筛选区支持重新选择日期触发真实 API 查询，图表/表格/KPI/建议全部刷新

---

## 架构

```
用户自然语言
      │
      ▼
  handle()  ← OpenClaw 入口
      │
      ├── 鉴权层（session 持久化密码，Token 主动刷新）
      │
      ├── 意图路由
      │     ├── 固定指令：初始化 / 系统列表 / 切换系统 / 发布
      │     └── BI 查询：
      │           ├── 实时拉取 api_registry（不缓存）
      │           ├── 双向滑窗匹配目标 API
      │           ├── 时间关键词解析
      │           ├── fetch_business_data()  ← 带无感 Token 刷新
      │           ├── extract_generic_schema()  ← 多样本投票
      │           ├── generate_html_report()  ← 四区结构
      │           └── api_upload_html_to_oss()  ← 带时间戳文件名
      │
      └── 返回：预览链接 + 数据总结 + 建议
```

---

## 模块说明

### Session 管理

| 函数 | 说明 |
|------|------|
| `load_session(user_id)` | 读取用户会话文件，不存在则返回默认结构 |
| `save_session(user_id, data)` | 持久化会话到本地 JSON 文件 |

**Session 字段设计原则**：只存凭证和系统上下文，不存业务数据。

| 存入 session | 不存 session |
|-------------|-------------|
| auth_password、system_auth_headers、token_expires_at | api_registry（每次实时拉） |
| oss_domain、oss_api、oss_static_domain | 业务查询结果 datas |
| system_name、system_id | 任何接口返回的列表数据 |
| last_report_url、last_report_title | |

---

### Token 管理

| 函数 | 说明 |
|------|------|
| `is_token_near_expiry(ctx)` | 距过期不足 5 分钟返回 True |
| `_refresh_token(ctx, pwd, user_id)` | 刷新 Token 并写回 session，失败返回错误描述 |
| `fetch_business_data(...)` | 封装完整请求链路：主动检查过期 → 请求 → 401 被动刷新 → 重试 |

---

### 意图识别

| 函数 | 说明 |
|------|------|
| `match_api_by_intent(text, api_registry)` | 双向中文子串滑窗匹配（Pass1 精确，Pass2 模糊） |
| `parse_time_keywords(text)` | 解析本月/上月/昨日/今天/本周/上周/今年，返回 (start, end, label) |
| `build_api_params(api_meta, start, end)` | 从 api_registry 的 params[] 文档按需构建请求参数，无文档时兜底通用参数集 |

---

### 数据处理

| 函数 | 说明 |
|------|------|
| `extract_generic_schema(datas)` | 取前 10 条多数投票判断字段类型（数值/文本），避免首条 None 误判 |
| `infer_chart_type(txt_keys, datas)` | 时间维度 → line，条数 ≤ 6 → pie，其余 → bar |
| `safe_float(val)` | 容错浮点转换，None/空字符串返回 0.0 |
| `t_key(k)` | 字段名语义翻译（英文 key → 中文展示名） |

---

### HTML 报表生成

`generate_html_report()` 输出完整独立 HTML，四区结构：

```
① 报表标题区  →  {系统} · {报表名} · {时间范围}
② 筛选条件区  →  日期 picker + [查询] 按钮（doQuery 触发真实 API）
③ BI 内容区   →  ECharts 图表（上）+ 数据明细表格（下，最多 200 条）
④ 底部总结区  →  KPI 汇总卡片 + 智能建议 + 生成时间/数据来源
```

**安全设计**：
```js
// OSS 存储此空占位，后端代理返回 HTML 时 replace 注入真实 Token
window.UPLOAD_TOKEN = "";
```

`doQuery()` 读取注入后的 Token 发起真实查询，刷新图表、表格、KPI、建议全部同步更新。

ECharts 使用固定 OSS 托管地址，**禁止外链任何 CDN（jsdelivr/unpkg/cdnjs）**。

---

### API 依赖

| 方法 | 接口 | 用途 |
|------|------|------|
| GET | `/dw/api/auth/supported-systems` | 获取系统列表 + OSS 配置（oss_api / oss_static_domain） |
| GET | `/dw/api/auth/system-token?system_id=` | 获取/刷新业务系统 Token |
| GET | `/dw/api/system/api-registry?system_id=` | 实时拉取接口注册表（每次查询都拉，不缓存） |
| POST | `/dw/api/skills/archive/upload` | 上传 HTML 到 OSS，返回 preview_url |
| POST | `/dw/api/skills/archive/push` | 发布报表至胜算平台（payload: system_id + file_url + user_phone） |

---

## 安全合规

本 Skill 严格遵守 LICENSE 约束：

| 条款 | 实现方式 |
|------|---------|
| 2(b) 禁止 Token 写入前端 | OSS HTML 中 `window.UPLOAD_TOKEN = ""`，后端代理动态注入 |
| 2(b) 禁止凭证上传公共 OSS | 上传前验证 HTML 不含任何 auth 头，auth 密码仅用于网关鉴权层 |
| 2(c) 禁止暴露后端架构 | api_registry 路由信息不透传给终端用户；接口 URL 仅存于 CFG 配置，无 Token |
| 3(a) 数据链路加密 | 所有请求强制 HTTPS |
| 3(b) 最小权限 | 业务 Token 仅携带当前用户权限，auth 密码不注入业务请求 |

---

## 接入方式

```bash
cd /path/to/openclaw/skills/
git clone git@github.com:asiasea-ai/bi.git asiasea-bi
```

重载 Gateway 守护进程完成路由注入。

---

## 使用示例

```
用户：初始化
Skill：请输入访问密码

用户：••••••••
Skill：安全握手成功，可用系统：E网、胜算...

用户：切换系统 E网
Skill：已切入 E网，可分析维度：报销单、年度预算...

用户：帮我分析本月的报销单
Skill：📊 报销单
       🔗 预览地址：https://...（时效链接）
       📝 总结：消耗额占总基数 73%，处于偏高水位...

用户：发布
Skill：✅ 已发布至胜算平台，链接：https://...
```