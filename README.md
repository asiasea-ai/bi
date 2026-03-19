# 金灯塔BI Skill - OpenClaw 适配版

完全适配 OpenClaw 引擎 `handle(command, args)` 规范的 BI 报表插件。

**代码仓库**: `asiasea-ai/bi`

## 核心特性
1. **原生兼容**：抛弃了 Subprocess 命令行模式，改用同步函数直接渲染输出。
2. **状态隔离**：通过 `kwargs.get('user_id')` 识别用户，动态生成 `.session_{user_id}.json` 隔离配置。
3. **强参数追问**：在查询指令中，若未识别到时间（如“上个月”）或指标（如“销售额”），脚本会直接打回并提示用户补充，不会胡乱生成假数据。

## 安装部署
从 GitHub 代码仓库直接拉取到 OpenClaw 的 skills 目录下：

```bash
cd /path/to/openclaw/skills/
git clone git@github.com:asiasea-ai/bi.git jindengta-bi
```
部署完成后，重启 Gateway。然后在聊天框发送 初始化 即可体验。