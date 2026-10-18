# 产品入口与项目架构

[返回首页](../README.md) · [命令行使用](usage.md) · [桌面开发](tauri-desktop.md) · [开发验证](development.md)

## 两个产品

项目分为 **Shell 命令行版** 与 **Tauri 图形版**。Windows、Linux、macOS 是图形版的发行目标，不是三套产品。当前原生迁移在 `feat/rust-desktop` 开发，尚未替换正式发布附件。

| 产品 | 入口 | 认证实现与运行时 |
| --- | --- | --- |
| Shell 命令行版 | `ysu`、`python -m ysu_net` | Python；Shell 负责安装和命令包装，不复制 Bash 认证 |
| Tauri 图形版 | `ysu-net` / 系统应用图标 | Svelte 界面 + Rust 原生后台 + Rust 认证库；无 Python/Node 认证旁车 |

`ysuon`、`ysuoff` 是 CLI 快捷方式。旧 `ysu-gui` / `python -m ysu_net.gui` 仍启动已发布 Qt 兼容客户端；`python -m ysu_net.desktop` 是保留的旧 JSONL 原型，不再由新图形版启动或打包。Vite、浏览器演示和原生演示都是开发验收入口，不另行分发为 Web 产品。

新的桌面认证实现替代此前 Python 旁车方案，原因和保留范围见 [Rust 桌面决策](../.agents/notes/proposals/desktop/2026-10-14-rust-desktop.md)。Qt 和旁车源码保留作回退与语义对照，不表示当前架构继续依赖它们。

## 代码边界

```text
ysu_net/
├── install.sh / uninstall.sh        CLI 安装、卸载
├── src/ysu_net/
│   ├── auth/                       Python CLI 认证、账户解析
│   ├── manager/                    CLI、配置、锁、守护与 systemd
│   ├── gui/                        旧 Qt 兼容界面、旧引擎与偏好
│   └── desktop/                    保留的 Python JSONL 原型
├── desktop/
│   ├── src/                        三平台共用 Svelte 界面与 IPC 类型
│   ├── crates/ysu-auth/             Rust Portal/CAS、状态、切换、账户、CDP
│   ├── src-tauri/src/               Rust 后台、配置、窗口、托盘、自启
│   └── scripts/desktop.mjs          Node/Rust 原生构建入口
├── packaging/                      构建及浏览器、原生验收工具
├── tests/                          Python CLI 与兼容源码回归
└── docs/                           当前说明与独立的历史验收
```

[前端](../desktop/src/App.svelte)不处理认证协议或持久化密码。[原生后台](../desktop/src-tauri/src/runtime.rs)串行调度认证与重连，[认证库](../desktop/crates/ysu-auth/src/lib.rs)负责协议及结果核验，[配置层](../desktop/src-tauri/src/storage.rs)负责兼容存储和锁。[Tauri 主程序](../desktop/src-tauri/src/main.rs)集中系统集成；平台差异不扩散为三份界面。

两种语言不再共享同一认证执行器；变更协议时必须同时评估 Python 与 Rust，通过对应回归维护相同状态、账户和失败恢复语义。未知状态不当作离线，认证成功不以提交表单或收到 IPC 确认为依据。行为细节见[桌面运行语义](tauri-desktop.md#运行语义)与[CLI 开发](development.md)。

## 配置与进程

新桌面沿用 CLI 的配置字段、默认路径和运行锁协议。配置写锁与认证/守护运行锁分开，保存设置不争夺整个守护生命周期。共享配置不表示同时启用两套自动重连：同一配置只由一个运行器管理。多账号权威、账号簿与 Python 文件控制通道的适用范围集中见[多账号说明](accounts.md)。

CLI 的 Linux systemd 服务面向无桌面运行；图形版的托盘和用户登录自启面向桌面会话。配置目录、演示隔离、退出与自启行为集中见[桌面说明](tauri-desktop.md)，安装器仍按[CLI 安装方式](../README.md#快速开始)工作。

## 构建与发行边界

| 链路 | 职责 | 入口 |
| --- | --- | --- |
| Python CLI 分发 | wheel / 源码包；保留现有安装器和依赖 | [pyproject.toml](../pyproject.toml)、`uv build` |
| Rust 桌面构建 | 本平台原生程序及安装包，不冻结 Python | [desktop.mjs](../desktop/scripts/desktop.mjs)、[Tauri CI](../.github/workflows/tauri.yml) |
| Qt 兼容构建 | 已发布版本与回退；不是新架构 | [build.py](../packaging/build.py)、[旧发布工作流](../.github/workflows/desktop.yml) |

Tauri CI 定义跨平台构建和离线验收，只上传 Artifacts；定义存在不代表对应系统已经跑通。`v*` 标签仍连接旧 Qt 发布流程，本轮不切换发行、不提交、不推送。

新旧 Linux 包暂用相同 `ysu-net` 包名和 `0.1.0` 版本，旧 Windows Qt 主程序也叫 `ysu-net.exe`；名称不证明架构，也不表示两包适合并排安装。发行前仍需处理版本、升级/回退、既有自启项与签名。当前构建产物仅用于开发验收，不执行本机安装或替换。

## 文档归属

首页负责两个产品的导航，架构页负责边界，桌面说明负责构建和运行语义，[设计说明](rust-desktop-design.md)负责视觉依据。带日期的验收只对应当时源码与样本；此前 Python/Qt 的校内成绩和旧旁车包不作为 Rust 桌面验收证据。
