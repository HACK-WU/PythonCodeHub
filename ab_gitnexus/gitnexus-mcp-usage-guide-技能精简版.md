---
name: gitnexus-mcp-quick-reference
purpose: 面向 AI 的 GitNexus MCP 精简说明，后续可继续改造成 Skill
source: gitnexus-mcp-usage-guide.md
---

## GitNexus MCP 使用指导（技能精简版）

### 核心结论

**GitNexus 适合结构化理解和改动评估，grep 适合精确定位和实现确认。最佳实践不是二选一，而是混合使用。**

### 一句话定位

GitNexus 是代码知识图谱工具，擅长回答：

- 谁依赖了它
- 它依赖了谁
- 它有哪些方法
- 改了它会影响什么
- 某个方法的调用链是什么

grep / 文本搜索更擅长回答：

- 这个字符串出现在哪
- 这个字段/枚举/常量被哪里引用
- 某段实现代码写在哪

### 使用前提

先保证仓库已建立索引，否则 GitNexus 工具不可用。

常用命令：

```bash
gitnexus analyze
gitnexus status
gitnexus analyze --force
gitnexus analyze --repair-fts
```

### 工具优先级

#### `context`（最常用）

用途：查看单个符号的结构化上下文。
适合：已知类名、函数名、变量名时。
重点看：

- incoming：谁依赖它
- outgoing：它依赖什么
- has_method：它有哪些方法
- extends / implements：继承或实现关系
- processes：参与哪些流程

结论：

- **已知具体符号时优先用它**
- 类级查询通常稳定
- 常见方法名容易重名，需配合 `file_path` 或 `uid` 消歧
- 不适合查枚举常量或属性访问型引用

#### `impact`（改动前优先）

用途：评估修改某个符号后的影响范围。
适合：修改类、Handler、Resource 之前。
重点看：

- risk
- byDepth
- affected_processes
- affected_modules

结论：

- **改动前优先使用**
- 对类级符号效果好
- 对枚举常量、属性访问、部分方法级目标不稳定
- 结果不全时必须补 grep

#### `cypher`（最灵活）

用途：做自定义图查询。
适合：

- `context` / `impact` 还不够
- 想查方法内部调用链
- 想按关系类型做精准追踪

结论：

- **方法级调用链追踪优先用它**
- 适合作为高级补充工具
- 简单问题不要先上 `cypher`

#### `query`

用途：按概念或主题找相关代码。
适合：还不知道具体类名或函数名时。

结论：

- 只在“概念模糊”时使用
- 结果质量不稳定，关键词太宽会混入无关内容
- **已知具体符号时跳过，直接用 `context`**

#### `detect_changes`

用途：把当前改动映射到受影响符号和流程。
适合：提交前检查风险。

结论：

- 提交前很有用
- 可先看 `risk_level`
- 对高风险符号再补 `impact`

#### `rename`

用途：跨文件安全重命名。
建议流程：

1. 先 `impact`
2. 再 `rename(dry_run=true)`
3. 复核低置信度编辑
4. 再正式执行

结论：

- 默认先预览
- 完成后要更新索引

#### `api_impact`

用途：修改 API handler 前做预影响评估。
适合：API 路由处理器改动前。

#### `route_map` / `shape_check` / `tool_map`

在 `bk-monitor` 这类 DRF Resource 后端仓库中，实测价值较低，可能返回空或只有弱相关结果。

结论：

- **不要依赖它们作为主工具**
- 优先使用 `context`、`impact`、`cypher`、grep

### 决策规则

#### 规则 1：精确文本问题优先 grep

以下场景优先 grep / 文本搜索：

- 字符串
- 字段名
- 枚举值
- 常量
- 配置键
- 属性访问型引用
- 某段具体实现

#### 规则 2：结构关系问题优先 GitNexus

以下场景优先 GitNexus：

- 谁依赖它
- 它依赖谁
- 谁调用了它
- 改了它会影响什么
- 它属于哪个流程
- 它有哪些方法/继承关系

#### 规则 3：复杂问题使用混合流程

推荐组合：

- **grep 定位符号，再 `context` 看结构**
- **`impact` 看影响面，再 grep 补枚举/属性访问引用**
- **`context` 看类关系，再 `cypher` 深挖方法调用链**
- **`detect_changes` 看提交风险，再 `impact` 复查高风险点**

### 面向 AI 的推荐工作流

#### 工作流 1：理解陌生代码

1. 确认索引可用
2. 如果不知道符号名，先 `query`
3. 找到关键符号后用 `context`
4. 需要方法调用链时用 `cypher`
5. 最后回到源码确认实现细节

#### 工作流 2：修改前评估风险

1. 锁定目标类或函数
2. 先 `context`
3. 再 `impact`
4. 对枚举/属性访问/字符串引用补 grep
5. 再开始改代码

#### 工作流 3：提交前检查

1. 运行 `detect_changes`
2. 看 `risk_level` 和 `changed_symbols`
3. 对高风险符号执行 `impact`
4. 必要时再回源码确认

#### 工作流 4：重命名

1. 用 `impact` 看影响范围
2. 用 `rename` dry run 预览
3. 复核文本编辑结果
4. 正式执行
5. 更新索引

### 实战结论摘要

- `context`：最常用，已知符号时首选
- `impact`：改动前必看，但对枚举/属性访问覆盖不全
- `cypher`：最适合补方法级调用链
- `query`：只在不知道具体符号时使用
- `detect_changes`：提交前检查很有价值
- `rename`：适合安全重命名，先 dry run
- `route_map` / `shape_check` / `tool_map`：在本仓库里不要抱太高预期

### 明确的限制

- 没有索引就不能用
- 索引过期会导致结果不准
- 方法级查询稳定性不如类级查询
- 属性访问、枚举常量、字符串引用覆盖不全
- 图谱结果不能替代源码确认

### 后续改造成 Skill 时建议保留的内容

只保留以下几类信息即可：

- GitNexus 与 grep 的分工
- 每个核心工具的触发条件
- 关键限制与盲区
- AI 的默认决策规则
- 推荐工作流

以下内容可以继续删减或拆到参考文件：

- 详细参数表
- 大段示例
- 冗长背景介绍
- 不适用于当前仓库的工具说明

### 一句话原则

**先用最便宜的方式定位问题，再用最合适的工具扩展上下文；结构关系看 GitNexus，精确匹配看 grep，最终以源码为准。**
