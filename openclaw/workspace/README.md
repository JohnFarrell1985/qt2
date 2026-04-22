# OpenClaw 工作区（仓库内镜像）

本目录对齐 [OpenClaw 文档](https://docs.openclaw.ai/skills) 中 **Gateway workspace** 习惯用法：

| 路径 | 含义 |
|------|------|
| `skills/` | 工作区技能包（**AgentSkills**），`skills/<name>/SKILL.md`；本仓库由 `../scripts/sync_vibe_skills.py` 从 Vibe-Trading 同步。 |
| `.agents/skills/` | 项目/代理级技能覆盖，可为空；用于同名技能补丁或私有技能。 |
| `logs/` | 可选；本地运行/日志可放此处，默认仅占位，不提交敏感内容。 |
| `AGENTS.md` | 本工作区 Agent 使用说明与 qt 工具映射。 |

在 **本机 OpenClaw** 中，可将 **Gateway 的 workspace 根目录** 设为本目录的**绝对路径**（例如 `C:/Users/you/git/qt/openclaw/workspace`），或使用 `skills.load.extraDirs` 仅指向本目录下的 **`skills`**，见 `../config.openclaw.snippet.json5`。

> 若你使用用户主目录下 `~/.openclaw/workspace/`，结构相同，可将本目录内容复制或软链过去。
