# OpenClaw 与 qt 投研技能包

本目录按 [OpenClaw / AgentSkills](https://docs.openclaw.ai/skills) 与 **workspace** 习惯整理：技能位于 **`workspace/skills/<技能名>/SKILL.md`**（可含 `references/` 等），与官方「工作区根下的 `/skills`」一致。

内容来自 [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) 的 `agent/src/skills/`，经 `scripts/sync_vibe_skills.py` 同步到本仓库。

**重要**：文内会提及 Vibe 专用工具名（如 `factor_analysis`）。在 qt 侧应以 **本仓库 `src/` 回测与因子管线、QMT、FastAPI** 为准；工具映射见 **`workspace/AGENTS.md`**。

---

## 1. 前置条件

| 项目 | 说明 |
|------|------|
| OpenClaw | 已安装 Gateway / Desktop，且版本支持 [AgentSkills](https://agentskills.io/) 与 `skills.load` 配置（参见 [Skills 文档](https://docs.openclaw.ai/skills)）。 |
| Python | 3.10+，用于运行 `scripts/sync_vibe_skills.py`（仅同步技能时用到，与 qt 主项目可共用 venv）。 |
| 可选：Vibe-Trading 源码 | 克隆到本机任意路径，供同步脚本读取 `agent/src/skills/`。不克隆也可仅在首次用 `git submodule` 或发行包提供源目录。 |
| 路径 | OpenClaw 在 Windows 下对 `extraDirs` / workspace 一般使用 **正斜杠** 或转义后的绝对路径，避免混用未转义反斜杠导致 JSON 解析失败。 |

---

## 2. 目录结构（与 OpenClaw workspace 对齐）

```
openclaw/
  README.md                          # 本说明（配置与部署）
  AGENTS.md                          # 指向 workspace/AGENTS.md
  config.openclaw.snippet.json5      # 可复制到 openclaw.json5 的片段模板
  workspace/                         # 建议作为 Gateway 的 workspace 根（本仓库内镜像）
    README.md                        # 工作区子说明
    AGENTS.md                        # Agent 行为与 qt 工具映射
    skills/                          # 主技能包：skills/<name>/SKILL.md
    .agents/skills/                  # 项目级覆盖技能，默认可空
    logs/                            # 可选：本地日志占位
  scripts/
    sync_vibe_skills.py              # 从 Vibe-Trading 同步到 workspace/skills
    sync_vibe_skills.ps1
```

OpenClaw 技能 **precedence**（简记）：工作区 **`skills/`** 优先级高；**`.agents/skills/`** 用于项目级补丁。细节以你安装的 OpenClaw 版本文档为准。

---

## 3. 首次部署：生成 `workspace/skills`

1. 克隆 [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) 到本机，记下根目录路径，下文记为 `VIBE_ROOT`。
2. 在 **qt 仓库根目录** 执行同步（输出目录固定为 **`openclaw/workspace/skills/`**）。

**完整同步**（含各技能下大目录，例如 `tushare/references`，体积大、首次耗时长）：

```bash
# Linux / macOS
python openclaw/scripts/sync_vibe_skills.py --source /path/to/Vibe-Trading

# Windows（cmd）
python openclaw\scripts\sync_vibe_skills.py --source C:\Users\you\git\Vibe-Trading
```

**轻量同步**（仅 `SKILL.md` 及常见 `examples*`，适合提交到 git、CI 快）：

```bash
python openclaw/scripts/sync_vibe_skills.py --source C:\Users\you\git\Vibe-Trading --shallow
```

**扩展同步**（Vibe 侧几乎全部技能，仍排除脚本内 `QT_EXCLUDE_FROM_ALL` 中的弱相关项）：

```bash
python openclaw/scripts/sync_vibe_skills.py --source C:\Users\you\git\Vibe-Trading --all-vibe
```

**仅预览**不写盘：

```bash
python openclaw/scripts/sync_vibe_skills.py --source C:\Users\you\git\Vibe-Trading --dry-run
```

也可用环境变量省略 `--source`：

```text
Windows cmd:  set VIBE_TRADING_ROOT=C:\Users\you\git\Vibe-Trading
PowerShell:   $env:VIBE_TRADING_ROOT = "C:\Users\you\git\Vibe-Trading"
```

然后执行：

```bash
python openclaw\scripts\sync_vibe_skills.py
```

### 3.1 PowerShell 一键（可选）

```powershell
cd C:\Users\you\git\qt
$env:VIBE_TRADING_ROOT = "C:\Users\you\git\Vibe-Trading"
.\openclaw\scripts\sync_vibe_skills.ps1 -Shallow
```

---

## 4. 配置 OpenClaw（两种部署方式）

OpenClaw 主配置一般为 **`~/.openclaw/openclaw.json5`**（Windows：`%USERPROFILE%\.openclaw\openclaw.json5`）。以下路径请把 **`you`** 换成你的 Windows 用户名，或按实际盘符修改。

### 方式 A：将 workspace 根指向本仓库（推荐）

把 Gateway / 本机 Agent 使用的 **workspace 根目录** 设为 **qt 仓库内的**：

```text
C:/Users/you/git/qt/openclaw/workspace
```

这样与官方约定一致：工作区根下直接有 **`skills/`**、**`.agents/skills/`**、**`AGENTS.md`**。

**操作要点**（名称因 OpenClaw 版本 UI 略有差异，请在「Workspace / 工作区 / Gateway 设置」中查找）：

1. 打开 OpenClaw 设置或 `openclaw.json5`。
2. 将 **workspace path** / **project root**（或等价项）设为上述绝对路径。
3. 保存后 **重启 Gateway** 或 **新建会话**，使技能列表重新加载。
4. 若文档中要求 **JSON5**，请使用 `config.openclaw.snippet.json5` 中与 `extraDirs` **互斥**理解：已用方式 A 时，通常 **不必** 再重复配置指向同一 `skills` 的 `extraDirs`（除非官方说明可叠加；避免重复加载同名技能）。

### 方式 B：不修改全局 workspace，仅追加技能目录

保持你原有 workspace 不变，在 **`openclaw.json5`** 的 **`skills.load.extraDirs`** 中增加一项，指向 **仅技能根目录**：

```text
C:/Users/you/git/qt/openclaw/workspace/skills
```

注意：`extraDirs` 在官方说明中 **precedence 较低**；若与 workspace 内同名技能冲突，以 [官方文档](https://docs.openclaw.ai/skills) 的优先级表为准。

**合并步骤**：

1. 用文本编辑器打开 `%USERPROFILE%\.openclaw\openclaw.json5`（若不存在，可从 OpenClaw 文档生成最小配置或经应用首次启动创建）。
2. 将本仓库 **`config.openclaw.snippet.json5`** 中的 `skills.load` 片段合并进去。
3. 把片段里 **`C:/Users/YOU/git/...`** 替换为你本机 **qt 仓库** 的真实绝对路径；**全程使用正斜杠** 最省心。
4. 可开启 `watch: true`，保存后技能目录变更会自动刷新（见 [Skills config](https://docs.openclaw.ai/tools/skills-config)）。
5. 保存并重启 Gateway / 新开会话。

### 4.1 片段模板位置

仓库内模板文件：**`openclaw/config.openclaw.snippet.json5`**（含注释，复制时勿把 `//` 注释粘进 **严格 JSON** 解析器；JSON5 一般允许注释）。

---

## 5. 部署后验证

1. **文件存在**：确认 `openclaw/workspace/skills/<某技能名>/SKILL.md` 存在（例如 `factor-research`）。
2. **OpenClaw UI / 日志**：在技能列表或调试日志中能看到已加载 skill 名称（与 `SKILL.md` frontmatter 中 `name` 一致）。
3. **对话内**：向 Agent 提问「列出当前可用技能中与 factor 相关的」或触发与 `AGENTS.md` 一致的 qt 工作流，观察是否引用 `workspace/AGENTS.md` 中的约束。

若技能未出现：检查路径是否拼写错误、Gateway 是否重启、当前 Agent 是否被 **allowlist** 限制了 `skills`（参见 OpenClaw 中 `agents.defaults.skills`）。

---

## 6. 更新与日常维护

| 场景 | 操作 |
|------|------|
| 上游 Vibe-Trading 更新 | 在 `VIBE_ROOT` 下 `git pull`，再运行 `sync_vibe_skills.py`（需要时加 `--shallow` 或全量）。 |
| 团队内统一版本 | 将 `openclaw/workspace/skills` **提交到 git**（大目录建议 `.gitattributes` + LFS 或仅提交 `--shallow` 结果）。 |
| 私有覆盖技能 | 在 **`openclaw/workspace/.agents/skills/<name>/`** 放置同名或新名 `SKILL.md`，勿改公共 `skills/` 目录下的上游同步内容，便于下次同步冲掉。 |

---

## 7. 团队协作建议

- 在 **README 或内部 wiki** 固定：`VIBE_TRADING_ROOT`、是否使用 `--shallow`、是否提交 `skills` 到仓库。
- **CI**：可对 `sync_vibe_skills.py --dry-run` 做检查，或与 Vibe 某 **commit SHA** 对齐后跑同步并 `git diff --exit-code`（按你们规范定制）。
- **不要**在仓库中提交 **OpenClaw 全局配置里** 的个人 Token；使用各开发者本机 `openclaw.json5` 或密钥管理。

---

## 8. 故障排除

| 现象 | 可能原因与处理 |
|------|----------------|
| 同步报「未找到 agent/src/skills」 | `--source` 须指向 **Vibe-Trading 仓库根**，不是 `agent` 子目录。 |
| OpenClaw 读不到技能 | 路径错误、未重启 Gateway、JSON5 语法错误（缺逗号、错误引号）、`extraDirs` 指到了 `skills` 的上级或下级多一层。 |
| Windows 下编码/超时 | `mcp-server-fetch` 等与 Python 相关的工具可设 `PYTHONIOENCODING=utf-8`（见各 MCP 文档）；与 **本 README 技能同步** 无强依赖。 |
| 技能与 qt 行为不一致 | 以 **`workspace/AGENTS.md`** 中的工具映射为准，必要时在 skills 旁加团队 **patch** 于 `.agents/skills/`。 |

---

## 9. 安全与合规

- 第三方技能视为 **不可信文档**，生产环境启用前请人工抽查（[OpenClaw Security](https://docs.openclaw.ai/skills)）。
- 技能内容 **不构成投资建议**；交易与合规以 qt 系统与监管要求为准。

---

## 10. 协议与链接

- 上游 Vibe-Trading：**MIT**（以 [其仓库](https://github.com/HKUDS/Vibe-Trading) 为准）。
- OpenClaw：[Skills](https://docs.openclaw.ai/skills) · [Skills 配置](https://docs.openclaw.ai/tools/skills-config) · [ClawHub](https://clawhub.ai/)
- AgentSkills 规范：<https://agentskills.io/>
