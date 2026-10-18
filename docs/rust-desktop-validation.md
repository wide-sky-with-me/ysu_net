# Rust 桌面验收：2026-10-14

日期与时区：2026-10-14，Asia/Shanghai；最终包核对时间 18:05:38。分支 `feat/rust-desktop`，版本 `0.1.0`。本记录只适用于本轮 Rust 源码和下列包，不替换[历史旁车验收](tauri-validation.md)。未提交、推送、发布或安装客户端。

[当前运行指南](tauri-desktop.md) · [迁移决策](../.agents/notes/proposals/desktop/2026-10-14-rust-desktop.md) · [视觉来源与预览](rust-desktop-design.md)

## 环境与范围

宿主为 WSL2 / Ubuntu 24.04，原生构建与 WebView 验收使用既有 Ubuntu 22.04 Docker SDK；实际编译器 `rustc 1.99.0 (b940084d7 2026-09-28)`、Node 24.21、系统 Google Chrome 154.0.8037.97。没有安装宿主 SDK。构建需要 Node，认证与运行管理由 Rust 实现，二者不是同一依赖范围。

协议测试仅访问回环样本，不读取真实账户配置、不访问校园网。原生演示验收通过 `YSU_SDK_NETWORK=none` 禁网，使用隔离临时配置。真实 Chromium 测试调用系统浏览器但使用独立临时资料目录，不复用个人会话。

## 已执行检查

- 前端：Svelte/TypeScript 检查 0 错误、0 警告；Vitest 23 项、原生构建入口测试 5 项通过，Vite 生产构建通过。
- 真实 Chrome 预览：两套脚本均通过；设计回归 8 组行为、19 个布局样本，覆盖设置页签、焦点循环、密码清空、忙碌时关闭重连及退出、主题和紧凑布局；页面异常、控制台错误和外部请求为 0。完整命令与截图只在[设计记录](rust-desktop-design.md)维护。
- Rust 认证：普通回归 49 项通过，7 项依赖系统 Chromium 的测试在普通运行中被忽略；随后显式运行这 7 项，全部通过，不能只用普通成绩代替。覆盖完整 CAS 与下线、验证码/风控不提交、子资源伪 SID、Drop/取消/CDP 关闭及进程和资料目录回收。
- Rust 原生运行器与存储：39 项通过，含串行操作、未知状态、账号核验、锁、取消、偏好竞争、配置边界和独立复核。两份 Rust 清单的格式检查通过。
- 保留的 Python 全回归：246 项通过；解释器退出时另有 `ResourceWarning: gc: 1 uncollectable objects at shutdown`，不记为无警告运行。
- Linux：锁定依赖的生产构建、deb 打包、解包后二进制的原生 WebView 自检与生命周期测试通过。包未安装；四平台 CI 定义不等于四平台实测。
- 收尾：10 份当前文档/决策的本地链接、社区检查、actionlint、uv 离线锁校验、两份 Rust 格式检查及 `git diff --check` 通过。actionlint 曾指出浏览器路径导出会掩盖探测退出码，已拆分赋值/导出并复测。

最终 Rust 复测命令（仓库根目录）：

```sh
bash build/tauri-sdk.sh cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml
bash build/tauri-sdk.sh env CARGO_TARGET_DIR=/workspace/build/rust-auth-target \
  cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml
YSU_AUTH_CHROMIUM_PATH="$(command -v google-chrome)" \
  build/rust-auth-target/debug/deps/ysu_auth-ec63fd9348b78879 --ignored --test-threads=1
```

最后一行运行本轮实际生成的测试程序；重建后文件名以 Cargo 输出为准。普通开发环境也可直接运行指南中的 `cargo test ... -- --ignored --test-threads=1`。

日志：[运行器 39 项](../build/rust-desktop-runtime-final.log)、[认证 49 项](../build/rust-auth-final.log)、[真实 Chromium 7 项](../build/rust-auth-chromium-final.log)、[最终构建](../build/rust-desktop-bundle-final.log)。独立认证验证器还将完整 API/CAS 案例连续重放 100 次，全部通过；该次数是验证器交接证据，未混入父会话最终测试计数。

## 失败复现与修正

独立原生复核保留了修正前的失败：快照回调重入时超时、改计时/TLS 解除认证暂停、密码与运营商名称相同时破坏结构字段、公开等待时间显示原始浮点抖动。[修正前日志](../build/rust-desktop-review-before.log)为 4 项失败，最终对应回归均通过。

追加复核证明单个认证库方法的限时不足以约束原生层的“变更 + 独立核验”及整轮重连：[修正前总超时日志](../build/rust-desktop-deadline-before.log)中两项失败，最终共享总预算的两项回归通过，超时显示未知而不是虚构离线。

认证验证器实际复现 CAS 全局密码选择器命中无关表单，以及同名不同路径 Cookie 无序导致错误 XSRF。修正保持原断言：表单按可见账号与密码配对；Cookie 使用成熟 `cookie_store` 做匹配、最长路径优先；新增 32 轮确定性路径/域/过期回归。失败诊断不输出 Cookie、密码或令牌。关键实现及测试反链见迁移决策。

## 最终 Linux 包与原生证据

[Linux amd64 deb](../desktop/src-tauri/target/release/bundle/deb/YSU%20Net_0.1.0_amd64.deb)：3,807,146 字节（3.63 MiB）。SHA256：`cf299a718a15730669153ef7c9e15685d0730546a49475e7ce1efe04996a1c33`。

[包元数据](../dist/rust-native-validation/package.json)记录二进制、主锁文件哈希和核对时间；[文件清单](../dist/rust-native-validation/package-contents.txt)没有 Python、Node、Chromium 或 ysu-core 认证运行时。解包 ELF 的最高 GLIBC 符号为 2.34；这不是下调发行基线的证据，实际 SDK 与动态依赖基线仍为 Ubuntu 22.04 / glibc 2.35、WebKitGTK 4.1、GTK3、AppIndicator。

最终执行的原生命令：

```sh
bash build/tauri-sdk.sh node desktop/scripts/desktop.mjs --bundles deb
dpkg-deb --extract 'desktop/src-tauri/target/release/bundle/deb/YSU Net_0.1.0_amd64.deb' dist/rust-desktop-linux-final
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh dbus-run-session -- xvfb-run -a \
  -s '-screen 0 1280x900x24' env LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1 \
  build/tauri-venv/bin/python packaging/tauri_smoke.py \
  --binary dist/rust-desktop-linux-final/usr/bin/ysu-net --output dist/rust-native-validation --capture-desktop
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh dbus-run-session -- xvfb-run -a \
  env LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1 \
  build/tauri-venv/bin/python packaging/tauri_linux_lifecycle.py \
  --binary dist/rust-desktop-linux-final/usr/bin/ysu-net --output dist/rust-native-validation
```

[完整进程树验收](../dist/rust-native-validation/acceptance.json)及[原生核心报告](../dist/rust-native-validation/native-report.json)确认渲染、登录、下线、切换、账户、重连、后台存活、窗口销毁/重建及退出清理。观测进程为 Rust 主程序与 WebKit 网络/渲染进程，包含 Linux `comm` 名称截断，不出现认证旁车。[生命周期报告](../dist/rust-native-validation/linux-lifecycle.json)另外确认无托盘最小化回退、单实例和原生关闭。测试 D-Bus 输出了忽略未知子进程的提示；脚本退出码为 0，自己启动的应用进程均已清理。

软件渲染、离线演示的短采样：可见窗口完整进程树 RSS 363.19 MiB、PSS 221.97 MiB；后台保留网络上下文时 RSS 182.06 MiB、PSS 123.89 MiB。采样约 0.65 秒，单核口径 CPU 为 0%，不是稳态、真实认证峰值或跨版本性能比较。Rust 减少认证运行时与包体积，不代表 WebKit 内存消失。

[最终原生截图](../dist/rust-native-validation/native-visible.png)已实际看图核对。旧旁车 deb 另存[历史包](../build/tauri-history/YSU%20Net_0.1.0_sidecar_amd64.deb)，保留 SHA256 `4253aded76ae2600f88dca0c7909de2af530f896f8785b06d5dbe1fd5baf9aa2`；没有改写冻结历史结论。

## 未验与交付边界

Windows/macOS 构建和实机、对应平台锁与 Job 行为、真实托盘与登录自启、校园 API/CDP 端到端、签名/公证、安装升级和回退均未执行。Windows Job API 仅经过源码与 windows-sys 0.61.2 文档核对；真实多级 OOPIF 未构造，递归 session/初始化 ACK 场景使用 mockCDP。声明最低 Rust 1.90 未用该编译器执行，实际为 1.99。

SDK 缺少 cargo-clippy，Clippy 命令未成功执行，未据此声明 lint 通过。浏览器操作会立即请求终止所属进程树，OS 等待及资料删除由持有树与资料目录的原生回收器继续处理；OS 故障下的回收重试不属于操作限时内硬完成保证。

新旧 GUI 包使用同一应用身份与版本，本轮不宣称可并行安装，不操作旧自启，不删除 Qt/旁车回滚源码，不生成 Release。[跨平台 CI](../.github/workflows/tauri.yml)新增 Linux 显式 Chromium 回归并只上传附件；尚未触发远端工作流。
