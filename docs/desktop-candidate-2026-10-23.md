# 0.2.1 桌面候选本地验收（2026-10-23）

本记录对应 `feat/rust-desktop` 上、以 `6f220a4` 为基线的本轮候选工作树；相应源码随本记录提交。结论仅为 Linux 本地构建与离线验收，不表示已发布 0.2.1、启用在线更新源或完成真实校园网认证。

当前行为见[桌面说明](tauri-desktop.md)、[界面设计](rust-desktop-design.md)与[软件更新](updates.md)；托盘并发与生命周期选择见[既有决策](../.agents/notes/implemented/desktop/2026-10-15-tray-control.md)。

## 环境与实际结果

构建使用基于[项目 SDK](../packaging/tauri.Dockerfile)的 Ubuntu 22.04 x64 容器、Rust 1.99.0、Node 24.21.0；浏览器回归使用隔离配置的宿主 Chromium 154。Rust 验证和普通原生冒烟运行于无外网容器，HTTP / CDP 数据来自本地夹具；安装容器仅为 apt 获取公开依赖联网，应用仍显式使用 Demo。

| 检查 | 实际结果与边界 |
| --- | --- |
| 前端类型检查、单测与生产构建 | 无错误 / 警告，144 个单测通过，Vite 产物生成 |
| 构建入口测试 | 8 个通过，包含签名构建参数与无认证旁车约束 |
| Python 全量回归 | 356 个通过，包含社区文档检查；不是现场认证 |
| Rust 认证库 | 83 个通过，7 个依赖浏览器的专门用例默认忽略，本轮未显式启用 |
| Rust 原生桌面 | 最终代码 132 个通过，含托盘状态 / 图标及 25 个更新测试 |
| 浏览器界面 | 圆润界面、原页面、多账号三个回归脚本通过；320 / 390 / 700 宽度、主题、焦点与密码清理无报告溢出或脚本错误，未发外部请求 |
| Linux 原生冒烟 | 核心 IPC、模拟连接 / 下线 / 切换、账号、颜色持久化、托盘结构与关闭窗口后操作、销毁 / 重建及宿主丢失恢复通过；所属进程清理通过 |
| Linux 窗口生命周期 | 无托盘最小化回退、单实例和真实 X11 关闭请求通过，进程清理通过 |
| 最终 deb 安装 | 全新临时 SDK 容器安装、菜单文件校验、图标 / 路径检查、从 `/usr/bin/ysu-net` 运行完整离线冒烟、卸载及入口清理通过；不修改宿主安装 |
| Python 分发包 | wheel 与源码包生成，包名 / 0.2.1 版本及 CLI 模块结构核对通过；交付前按最终提交重新生成源码包 |

Linux 产物为 `YSU Net_0.2.1_amd64.deb`，约 4 MiB。包控制信息确认为 `ysu-net / 0.2.1 / amd64`，依赖包含 `xdg-utils`、`libayatana-appindicator3-1`、`libwebkit2gtk-4.1-0`、`libgtk-3-0`，未因添加打开网页依赖而丢失 GUI 依赖。本机原始 JSON、截图与交付校验文件保存在 `dist/tray-package-20261023/`，不入源码仓库。

## 失败、修复与复测

- 原生更新测试首次构建被既有 root 所有的、已忽略的 Tauri 生成 schema 阻止（权限错误）。确认实际路径和忽略规则后，仅把生成目录与四个 schema 的所有者恢复为构建用户，未递归修改源码权限；同一命令复测通过。
- 首次隔离 deb 安装因测试容器覆盖了系统账号库，导致 dpkg 找不到 `messagebus` / `_apt` 而失败。改为保留镜像原账号库、只添加隔离测试用户；安装 / 启动 / 卸载复测通过。GTK 修正后重新构建的最终包另行重复该验收并通过。
- 首次 GTK 菜单截图发现图标标题可见文字停在“正在读取状态”，但文字 getter 已返回新状态。核对锁定的 muda 0.20.0：图标项可见文字是组合容器内的 AccelLabel，通用文字 setter / getter 操作外层 MenuItem，缓存值不能证明实际绘制。保持图标标题静态，将动态状态与身份交给普通菜单项；增加标题及摘要断言后重跑最终原生测试、重建、截图和安装验证，均通过。最终截图人工核对可见的“已连接”摘要与流量，不只依赖 getter。
- 只读审查还发现原生 `target=_blank` 发布页链接没有新窗口处理器。改用无 URL 参数的原生命令与官方 Rust opener，普通网页保留链接、Demo 禁止调用。真实 Tauri IPC 路由及隔离 Linux fake-xdg 调度测试通过；未以浏览器 Mock 冒充系统浏览器加载成功。

## 可复用验收入口

以下 Rust / 打包命令在构建容器内执行；前端与浏览器命令按[开发说明](tauri-desktop.md#构建前提)准备对应环境。

```bash
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run test:build
cargo test --locked --offline --manifest-path desktop/crates/ysu-auth/Cargo.toml
cargo test --locked --offline --manifest-path desktop/src-tauri/Cargo.toml
npm --prefix desktop run native:build -- --bundles deb
```

原生验收使用 [tauri_smoke.py](../packaging/tauri_smoke.py) 与 [Linux 生命周期脚本](../packaging/tauri_linux_lifecycle.py)，必须使用独立会话总线 / Xvfb 显示器；软件包安装步骤沿用 [CI 的隔离安装验收](../.github/workflows/tauri.yml)。本机临时容器包装脚本不是仓库对外入口。

## 未覆盖与发布边界

- 本机没有构建或执行 Windows / macOS 新包，也没有验证其实际托盘点击、高 DPI、系统浏览器交接或原位升级；远端 CI 以对应运行结果为准。
- 未进行真实校园网登录、下线、账号 / 运营商切换、轮换、物理断网恢复或长稳验收。所有本轮原生动作成功字段均属 Demo。
- 更新签名验证采用独立测试公钥和不可执行文本；没有访问真实更新 feed、安装远端更新或验证生产签名密钥配对。Linux deb 的包管理安装不等于软件内更新。
- 原生菜单结构读取与 GTK 截图不等于三平台真实面板鼠标验收。原生进程短时采样不是稳态性能基准，本记录不据此宣称资源占用改善。
- 本轮授权为构建与推送开发分支，不额外创建发布标签、变更远端 Secret、上传正式 Release 或更改签名密钥。
