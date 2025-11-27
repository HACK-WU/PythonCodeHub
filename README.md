# PythonCodeHub 

PythonCodeHub 是一个收集日常开发中可复用Python代码片段的仓库。无论您是需要快速解决特定问题，还是寻找代码灵感，这个库都能为您提供帮助。

## 为什么需要这个仓库？

在日常开发中，我们经常遇到：

- 重复编写相似的代码
- 忘记之前解决过的问题的解决方案
- 在不同项目中复制粘贴代码片段

PythonCodeHub 旨在解决这些问题，提供一个集中的、经过验证的代码库。

## 开发环境设置

### 安装依赖

```bash
# 使用 uv 安装依赖（推荐）
uv sync

# 或使用 pip
pip install -e .
```

### Pre-commit 配置

本项目使用 pre-commit 进行代码质量检查。配置已优化以平衡代码质量和开发效率。

```bash
# 安装 pre-commit hooks
pre-commit install
pre-commit install --hook-type commit-msg

# 首次运行检查所有文件
pre-commit run --all-files
```

**快速参考**：
- 📖 [完整配置说明](.pre-commit-config-guide.md)
- 🚀 [快速参考卡片](.pre-commit-quick-reference.md)

**核心检查**（自动运行）：
- ✅ Ruff 代码检查和格式化
- ✅ 配置文件格式验证
- ✅ 提交信息规范检查

**可选检查**（手动触发）：
- ⚠️ 拼写检查：`pre-commit run codespell --all-files`
- ⚠️ 敏感信息检查：`pre-commit run ip --all-files`

## 贡献指南

欢迎贡献您的代码片段！请遵循以下步骤：

1. Fork 本仓库
2. 创建新的分支 (`git checkout -b feature/your-feature`)
3. 提交您的代码 (`git commit -am 'Add some feature'`)
4. 推送到分支 (`git push origin feature/your-feature`)
5. 创建 Pull Request

### 代码要求

- 每个代码片段应该是一个独立的.py文件
- 包含清晰的文档注释和示例用法
- 遵循 PEP 8 规范（通过 Ruff 自动检查）
- 避免依赖外部库（除非必要）

### 提交信息规范

提交信息应遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```bash
# 格式
<type>(<scope>): <subject>

# 示例
feat(hash): 添加 MD5 哈希工具函数
fix(string): 修复字符串截断问题
docs: 更新 README 文档
```

**允许的类型**：`feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`, `build`

------

**Happy Coding!** 让我们一起构建一个强大的Python代码资源库！
