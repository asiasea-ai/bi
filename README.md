# 金灯塔胜算 Skill - OpenClaw

集成飞书与业务数据的 BI 报表插件。采用符合现代 Agent 框架标准的 Headless Tool 设计，依托 LLM 的自然语言解析能力提供数据支撑。

## 安装部署

将项目文件夹直接放置到 OpenClaw 技能目录，保持清单文件位于根路径：

```bash
cp -r skills-simple /path/to/openclaw/skills/jindengta-shengsuan
```
然后重启 Gateway 即可生效。

## 交互范式
告别传统的 /命令 交互模式。用户直接输入自然语言，OpenClaw 引擎会自动解析意图并调度以下内置 Tools：

initialize: 初始化环境

list_systems: 罗列可用系统

switch_system: 切换业务环境

query_bi_data: 拉取业务数据报表

## 对话示例：

“初始化胜算系统”

“切到库存系统”

“查一下昨天的新增用户数”

## 架构说明
本插件为纯数据提供者，仅接收并返回标准 JSON。文本话术的组织交由大模型处理。

具备多用户隔离机制，运行时会在同级目录自动生成 .session_{user_id}.json 状态沙箱。

## Author
小灯胜算团队

## Version
1.0.0 (OpenClaw)