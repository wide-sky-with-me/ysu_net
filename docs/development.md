# 开发与测试说明

[返回首页](../README.md) · [文档导航](README.md) · [产品与架构](architecture.md) · [Tauri 桌面版说明](tauri-desktop.md)

本页面向项目维护者与贡献者，说明代码组织、单元测试与持续集成规范。

---

## 开发环境与依赖管理

### 1. Python CLI（Linux 命令行）

Python 端要求 **Python 3.12+**，使用 `uv` 管理锁定依赖（[`pyproject.toml`](../pyproject.toml) / [`uv.lock`](../uv.lock)）：

```bash
uv sync --locked --extra browser
```

- 默认依赖：`requests`、`urllib3`、`pycryptodome`（用于 Portal/CAS 加密与 HTTP 认证）。
- 可选依赖：
  - `browser`：`playwright`（用于浏览器模式认证）。
  - `captcha`：`ddddocr`（用于 CLI 离线验证码识别）。

### 2. Rust 桌面客户端（Tauri 2 + Svelte 5）

桌面端源码位于 [`desktop/`](../desktop/)，包含：
- 前端（[`desktop/src/`](../desktop/src/)）：Svelte 5 + TypeScript + Vite。
- 认证库（[`desktop/crates/ysu-auth/`](../desktop/crates/ysu-auth/)）：纯 Rust 校园网认证、自助服务、无感认证、验证码识别与 CDP 浏览器控制。
- 原生宿主（[`desktop/src-tauri/`](../desktop/src-tauri/)）：Tauri 2 运行器、后台调度、系统托盘与签名在线更新。

> **构建约定**：根据项目协作规则，Rust 编译与桌面安装包构建统一在 **GitHub Actions** 云端工作流中执行，不在本地运行 `cargo` 编译或前端生产打包。

---

## 测试与静态检查

### 1. Python 单元测试与社区文件检查

所有认证、多账号轮换、自助服务与无感自动续约逻辑均配有基于本地 Mock 的单元测试，无需连接真实校园网：

```bash
# 运行全部 Python 单元测试
PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests

# 检查安装/卸载脚本语法
bash -n install.sh uninstall.sh

# 检查文档链接、锚点、Issue 表单与敏感信息脱敏规则
.venv/bin/python scripts/check_community.py
git diff --check
```

### 2. 前端类型检查与 Vitest 单元测试

```bash
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run test:build
```

### 3. 云端 GitHub Actions 工作流

仓库包含 4 条自动化工作流：

| 工作流 | 文件 | 职责 |
| --- | --- | --- |
| **Test** | [`.github/workflows/test.yml`](../.github/workflows/test.yml) | 运行 Python 单元测试、CLI 打包构建与安装脚本检查 |
| **Community files** | [`.github/workflows/community.yml`](../.github/workflows/community.yml) | 检查公开文档链接、锚点、表单结构与脱敏规则 |
| **Headless Rust authentication** | [`.github/workflows/rust-auth.yml`](../.github/workflows/rust-auth.yml) | 在 Linux / Windows / macOS 四目标编译并测试 `ysu-auth` 与 `ysu-auth-probe` |
| **Native Rust desktop builds** | [`.github/workflows/tauri.yml`](../.github/workflows/tauri.yml) | 四平台桌面构建、Rust 单元回归、WebView 安装冒烟、浏览器预览验收与 `v*` 标签 Release 发布 |

---

## 版本同步要求

发布新版本时，以下文件中的版本号必须保持完全一致（由构建脚本与发布清单校验器自动核对）：

1. [`pyproject.toml`](../pyproject.toml) 与 [`uv.lock`](../uv.lock)
2. [`desktop/package.json`](../desktop/package.json) 与 [`desktop/package-lock.json`](../desktop/package-lock.json)
3. [`desktop/src-tauri/tauri.conf.json`](../desktop/src-tauri/tauri.conf.json)
4. [`desktop/src-tauri/Cargo.toml`](../desktop/src-tauri/Cargo.toml) 与 [`desktop/src-tauri/Cargo.lock`](../desktop/src-tauri/Cargo.lock)
5. [`desktop/crates/ysu-auth/Cargo.toml`](../desktop/crates/ysu-auth/Cargo.toml) 与 [`desktop/crates/ysu-auth/Cargo.lock`](../desktop/crates/ysu-auth/Cargo.lock)
6. [`packaging/release-notes.md`](../packaging/release-notes.md) 首段标题（`## YSU Net vX.Y.Z`）
