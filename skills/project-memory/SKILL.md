---
name: project-memory
description: 项目记忆 skill，用于在同一项目的不同对话之间持久化和共享知识。应在每个新会话开始时加载相关上下文，在会话过程中发现重要信息时（代码架构洞察、问题解决方案、设计决策、关键文件位置）自动保存。消除重复的代码探索，节省时间和 token。触发短语包括：'记住这个'、'保存到记忆'、'之前关于XX的结论'、'加载上下文'，或者当检测到正在重复探索已经发现过的代码时自动触发。
---

# 项目记忆 — 项目级知识持久化

## 概述

项目记忆提供项目级别的持久化、结构化知识存储。无需在每次新对话中重新发现相同的代码结构、重复阅读相同的文件、重新分析相同的架构，本 skill 维护一个活跃的知识库，任何会话都可以读取和写入。

## 与内置 `update_memory` 的边界（重要）

两者职责互补，不要混淆：

| 维度 | 内置 `update_memory` | 本 skill `project-memory` |
|------|----------------------|---------------------------|
| 存储对象 | 用户偏好、Agent 角色设定、长期否定指令 | 项目级技术知识（代码地图、架构、解决方案、决策） |
| 生效范围 | 跨任务、跨项目持续生效 | 优先项目级，必要时升级到全局 |
| 触发场景 | "以后都用 X"、"记住我习惯…" | "这个模块的入口在…"、"Bug X 是因为…" |

**判断口诀**：是"用户怎么希望我做事"→ `update_memory`；是"项目长什么样" → `project-memory`。

## 核心概念

知识库以结构化 Markdown 文件的形式存储在 **记忆存储** 目录下：

- **项目级存储**: `{workspace}/.project-memory/` — 当前项目特有的知识
- **全局存储**: `~/.project-memory/` — 跨项目通用的知识

### 记忆分类

| 分类 | 文件 | 用途 |
|------|------|------|
| 代码地图 | `code-map.md` | 关键文件、模块、它们的用途和相互关系 |
| 架构理解 | `architecture.md` | 系统设计、模式、数据流、依赖关系 |
| 问题解决 | `solutions.md` | 问题-解决方案对、调试经验 |
| 设计决策 | `decisions.md` | 设计决策及其理由 |
| 工作日志 | `work-log.md` | 按时间顺序记录的重要变更和上下文 |
| 术语表 | `glossary.md` | 项目特有的术语、缩写、约定 |

## 工作流程

### 阶段一：会话开始 — 加载相关记忆

每次新会话开始时，或用户开始处理某个主题时：

1. 检查 `{workspace}/.project-memory/` 是否存在
2. 如果索引文件存在 (`{workspace}/.project-memory/index.json`)，**先读取索引获取概览**，仅当索引中存在与当前任务标签/标题相关的条目时再发起 `search`
3. 运行: `python3 {skill_dir}/scripts/memory_manager.py search "{workspace}" "{主题关键词}" --json` 以 JSON 形式取回结构化结果，便于程序化筛选
4. **加载体积硬约束**：单次最多采用前 5 条命中、单条内容截取至 80 行；条目过多时优先依赖 index.json 的标题清单，再按需逐条 `search`

### 阶段二：会话进行中 — 捕获知识

会话过程中每当有重要发现时，立即持久化保存。重要发现包括：

- **代码结构洞察**: "这个模块做了X，关键文件是Y和Z"
- **架构理解**: "服务A通过gRPC调用服务B，数据流经过..."
- **问题解决方案**: "错误X的原因是Y，通过Z修复了"
- **设计决策**: "我们选择了方案A而不是B，因为..."
- **关键文件位置**: "主入口在...，配置在..."

保存记忆的命令：

```bash
python3 {skill_dir}/scripts/memory_manager.py add "{workspace}" "{category}" "{title}" "{content}"
```

其中 `{category}` 是以下之一: `code-map`, `architecture`, `solutions`, `decisions`, `work-log`, `glossary`。

### 阶段三：会话结束 — 总结并保存

当会话结束前（或用户表示完成时），如果完成了重要工作：

1. 总结本次会话中的关键发现和决策
2. 保存到相应的记忆分类中
3. 更新工作日志，记录会话摘要

运行：

```bash
python3 {skill_dir}/scripts/memory_manager.py summarize "{workspace}" "{会话摘要}"
```

## 命令列表

记忆管理脚本 (`scripts/memory_manager.py`) 支持以下命令：

| 命令 | 用法 | 说明 |
|------|------|------|
| `init` | `memory_manager.py init "{workspace}"` | 为项目初始化记忆存储 |
| `add` | `memory_manager.py add "{workspace}" "{category}" "{title}" "{content}" [--tags ...] [--force]` | 添加/更新记忆条目；同分类同标题视为更新；命中敏感信息默认拒绝写入 |
| `search` | `memory_manager.py search "{workspace}" "{keywords}" [--json]` | 按关键词搜索；`--json` 输出结构化结果 |
| `list` | `memory_manager.py list "{workspace}" ["{category}"] [--json]` | 列出全部或指定分类的条目 |
| `remove` | `memory_manager.py remove "{workspace}" "{category}" "{title}"` | 删除指定条目 |
| `pin` | `memory_manager.py pin "{workspace}" "{category}" "{title}" [--unpin]` | 钉住条目（cleanup 永不清理）/ 取消钉住 |
| `summarize` | `memory_manager.py summarize "{workspace}" "{summary}"` | 将会话摘要追加到工作日志 |
| `export` | `memory_manager.py export "{workspace}"` | 导出所有记忆为完整摘要 |
| `cleanup` | `memory_manager.py cleanup "{workspace}" "{days}"` | 清理超过 N 天的旧条目（`decisions`/`glossary` 整体豁免；任何带 `pinned` 标签的条目豁免） |

> 全局存储用法：将 `{workspace}` 替换为 `--global`（或 `~`），脚本会自动写入到 `~/.project-memory/`。
>
> 将 `{skill_dir}` 替换为本 skill 加载时的目录路径，例如 `/root/PythonCodeHub/skills/project-memory`。

## 自动记忆触发

当本 skill 处于激活状态时，在以下情况自动捕获记忆：

1. **代码探索后**: 阅读多个文件以理解某个模块后，将关键发现保存到 `code-map`
2. **调试后**: 发现并修复了 Bug 后，将问题-方案对保存到 `solutions`
3. **架构讨论后**: 讨论了系统设计后，保存到 `architecture`
4. **设计决策后**: 在多个方案中做出选择后，保存到 `decisions`
5. **用户明确要求时**: "记住这个"、"保存一下"、"记录下来..."

## 记忆格式

每条记忆条目在 Markdown 文件中遵循以下结构：

```markdown
### {标题}
- **Date**: {YYYY-MM-DD HH:MM}
- **Tags**: {逗号分隔的关键词}

{内容}

---
```

此格式兼顾人类可读性和程序化检索。

## 索引文件格式

`index.json` 用于快速概览，结构如下（由脚本自动维护，无需手工编辑）：

```json
{
  "updated_at": "2026-05-19 15:00",
  "entries": [
    {
      "category": "code-map",
      "title": "ab_celery 模块入口",
      "tags": ["celery", "orchestration"],
      "date": "2026-05-19 14:00"
    }
  ]
}
```

## 最佳实践

- 保持条目简洁 — 聚焦于洞察而非原始数据
- 使用描述性标题，便于搜索；**同分类同标题会触发更新而非新增**
- 用相关关键词标记条目，便于交叉引用
- 长期有效的设计决策、术语写入 `decisions` / `glossary`，它们默认豁免 cleanup
- 对于必须长期保留的关键经验，可使用 `pin` 钉住
- 定期使用 `cleanup` 审查和清理过期条目（`decisions`/`glossary` 与 `pinned` 不会被删除）
- 项目特有知识优先使用项目级存储
- 会话开始加载记忆时，**先读 index.json**，再按需 `search`，避免一次性灌入全部内容
- 不要在记忆文件中存储敏感信息（密码、密钥、令牌）；脚本会自动检测并拒绝写入，必要时确认后加 `--force`

## 与其他 skill 的协作

- 与 `code-review`：审查中发现的 Bug 模式可写入 `solutions`，便于下次复用
- 与 `design-doc-generator`：生成设计文档时可读取 `architecture` 和 `decisions` 作为输入
- 与 `migrate-to-codehub`：迁移过程中发现的优秀架构可写入 `architecture` 与 `code-map`
