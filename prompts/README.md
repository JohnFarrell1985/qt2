# Sub-Agent 三角协作系统

> 基于 Vibe Coding / Agentic Engineering 最佳实践 (2026)
>
> 三个专业角色的 AI Agent 互相工作、互相监督, 形成 Plan → Execute → Verify 闭环

---

## 双层架构

```
.cursor/agents/              ← 主体 (Cursor 原生 subagent, 自动加载)
├── architect-quant.md         ~80 行, 完整角色定义 + 职责 + 工作流 + NEVER + 自检
├── ai-ml-developer.md         ~120 行, 完整角色定义 + 代码模式 + 工作流 + NEVER + 自检
└── qa-engineer.md             ~110 行, 完整角色定义 + 测试模式 + 工作流 + NEVER + 自检

prompts/                     ← 补充附录 (Agent 按需 Read, 无重复内容)
├── 01-architect-quant.md      附录: 模块清单 + 技术栈版本 + 协作协议 + 监督清单 + 参考文献
├── 02-ai-ml-developer.md      附录: 77 文件树 + 配置体系 + 6 类代码规范 + 模式速查
├── 03-qa-engineer.md          附录: 35 测试清单 + E2E 设计 + CI/CD + A 股专项
└── README.md                  本文件
```

**分层原则:**

- **agents/ = 完整的核心**: 角色定义、权限、工作流 (CoT)、人工门禁、错误恢复、协作模板、NEVER、自检
- **prompts/ = 纯补充附录**: 只包含 agents/ 中**没有的**详细信息 (文件树、版本号、参考文献等)
- **零重复**: 两层之间没有任何重复段落

---

## 角色总览

```
                    ┌─────────────────────────────────┐
                    │   01 系统架构师 + 量化分析师       │
                    │                                 │
                    │   职责: 架构设计 / 量化审查 /     │
                    │         文档维护 / TODO 管理      │
                    │   文件: doc/ README.md .env      │
                    │   模式: readonly                  │
                    └────────┬───────────┬────────────┘
                  设计交接 │           │ 测试范围
                  架构审查 │           │ 验收标准
                             │           │
              ┌──────────────▼──┐   ┌───▼──────────────────┐
              │ 02 AI/ML 开发    │   │ 03 QA 测试工程师      │
              │                  │   │                      │
              │ 职责: 编码实现 /  │◄─►│ 职责: 测试设计 /       │
              │       测试编写 /  │   │       CI/CD /         │
              │       ML 管线    │   │       质量门禁         │
              │ 文件: src/ tests/│   │ 文件: tests/ .github/  │
              │ 模式: read-write │   │ 模式: read-write       │
              └──────────────────┘   └──────────────────────┘
                  Bug 报告               代码变更通知
                  回归测试               Mock 指导
```

---

## 三角制衡机制

| 产出方 | 审查方 | 审查内容 |
|--------|--------|---------|
| **01 Architect** 设计文档 | **02 Developer** | 技术可行性、工作量合理性 |
| **01 Architect** 设计文档 | **03 QA** | 可测试性、验收标准明确性 |
| **02 Developer** 代码 | **01 Architect** | 架构合规、量化逻辑、A 股规则 |
| **02 Developer** 代码 | **03 QA** | 功能正确性、边界条件 |
| **03 QA** 测试 | **01 Architect** | 覆盖率、关键路径遗漏 |
| **03 QA** 测试 | **02 Developer** | 测试逻辑准确性、Mock 合理性 |

### tests/ 分工

| 区域 | 所有者 | 说明 |
|------|--------|------|
| `tests/test_*/test_*.py` 初始版本 | Developer | 与功能代码同步提交 |
| `tests/test_*/test_*.py` 审查增强 | QA | 补充边界条件; 修改前通知 Developer |
| `tests/e2e/**` | QA (独占) | E2E 测试套件 |

---

## 设计要点

| # | 要点 | 所在位置 |
|---|------|---------|
| 1 | Chain-of-Thought 工作流 | agents/ 每个角色的"工作流 (先想后做)" |
| 2 | 人工确认门禁 (MUST ASK) | agents/ 每个角色的"需要人工确认的操作" |
| 3 | 错误恢复协议 | agents/ 每个角色的"错误恢复" |
| 4 | 结构化输出模板 | agents/ Developer+QA 的"协作输出模板" |
| 5 | 完成前自检清单 | agents/ 每个角色的"完成前自检" |
| 6 | tests/ 分工 | agents/ Developer+QA 的"权限" |
| 7 | NEVER 列表 | agents/ 每个角色的"NEVER" |
| 8 | 详细参考附录 | prompts/ (文件树、版本号、CI/CD、参考文献) |

---

## 使用方式

### 方式一: Cursor 原生 Subagent (推荐)

`.cursor/agents/` 中的文件会被 Cursor 自动识别为可用的 subagent。Cursor 根据 `description` 字段自动决定何时调用。也可手动指示:

```
请使用 architect-quant agent 审查这个设计方案
请使用 ai-ml-developer agent 实现 P0-01
请使用 qa-engineer agent 审查这些测试用例
```

Agent 需要详细信息时会自动 `Read` prompts/ 中的附录文件。

### 方式二: Task 工具启动

```
Task(subagent_type="generalPurpose", prompt="阅读 prompts/02-ai-ml-developer.md 作为上下文, 然后...")
```

### 方式三: 多会话协作

在不同 Cursor 会话中分别指定不同角色。

---

## 文件清单

| 层级 | 文件 | 行数 | 内容 |
|------|------|------|------|
| 主体 | `.cursor/agents/architect-quant.md` | ~80 | 角色+职责+CoT+门禁+恢复+NEVER+自检 |
| 主体 | `.cursor/agents/ai-ml-developer.md` | ~120 | 角色+代码模式+CoT+门禁+模板+NEVER+自检 |
| 主体 | `.cursor/agents/qa-engineer.md` | ~110 | 角色+测试模式+CoT+A股清单+模板+NEVER+自检 |
| 附录 | `prompts/01-architect-quant.md` | ~120 | 模块清单+技术栈+协作+监督+参考文献 |
| 附录 | `prompts/02-ai-ml-developer.md` | ~220 | 文件树+配置+代码规范+监督+参考 |
| 附录 | `prompts/03-qa-engineer.md` | ~270 | 测试清单+E2E+A股专项+CI/CD+参考 |
| 说明 | `prompts/README.md` | — | 本文件 |

---

## 核心原则

1. **零重复双层**: agents/ 包含完整核心, prompts/ 只有补充附录
2. **先想后做**: 每个角色行动前按顺序思考 (Chain-of-Thought)
3. **三角制衡**: 没有人审查自己的产出
4. **人工门禁**: 高风险操作强制暂停请求确认
5. **错误可恢复**: 每种失败场景都有明确的恢复路径
6. **结构化通信**: 协作使用标准模板, 消除歧义
7. **完成必自检**: 交付前逐项过检查清单
8. **Constraints > Capabilities**: NEVER 列表比能力描述更重要
