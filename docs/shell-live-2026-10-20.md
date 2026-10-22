# Shell 真实网络复测（2026-10-20）

[返回首页](../README.md) · [使用与配置](usage.md) · [开发验证](development.md) · [更新安装](migration.md)

## 结论与范围

2026-10-19 至 2026-10-20（Asia/Shanghai），在用户指定的校内 Linux 主机通过 SSH 完成隔离测试。基线为 `b163a9244ee2a48253aed35f0504c4beb0d4ed50`，修复版为其上的未提交工作树，不代表正式发行版。

- 两处客户端问题已修复，并在目标主机复现后复测：空原始服务字段误判、旧同名脚本遮蔽安装命令。
- 校园网真实登录、独立状态/身份/服务核验、账户查询、诊断、退出后重连及前台守护停止均通过。
- 中国移动实际登录未通过：门户返回账号同时在线数量已达上限，退出码 `4` / `session_limit`。修复版切换失败后自动恢复校园网，且保留原服务配置；没有踢下其他设备或继续重复尝试。
- 最终为提供的测试账号保持校园网在线，独立外网 HTTPS 返回 `200`。测试凭据、进程和远端临时目录均已清理，未正式部署命令或 systemd 服务。

这次结果不修改[早期真实验收](live-test.md)与[历史部署验收](deployment-test.md)的结论；历史移动上线成绩不等于本次账号当前可上线。

## 测试环境与隔离

目标为 Linux x86_64、Python 3.12.3，API 后端。目标没有现成的 `ysu` 命令、项目用户配置或 `ysu-net.service`。测试使用当前 Python 源码的私有副本、独立 HOME/XDG 目录及临时 venv；调用正式安装模块的 `--no-service` 分支生成三个 Shell 包装器，没有执行完整的远端 uv 引导或正式安装。

依赖复用本地 venv 的已安装发行物，未在目标联网安装包：requests 2.34.2、urllib3 2.7.0、pycryptodome 3.23.0；运行源码摘要与实际版本另存于本地忽略的构建产物。测试配置文件为 `0600`，父目录为 `0700`；TTY 密码输入未回显。报告不保留账号、密码、IP/MAC、会话或原始认证响应。

起始连接属于另一账号；用户明确同意断开该主机连接后使用提供的账号测试。会改变网络的流程以独立会话运行，设置命令与总时限，并在收尾核验可用连接。没有改动 DNS、网卡、开机自启、linger、原有命令或其他用户进程。

## 复现与修复

| 问题 | 修复前证据 | 修复与边界 |
| --- | --- | --- |
| 空原始服务字段 | 门户 `service=校园网`、`realServiceName=null`，独立查询已在线且账号匹配，但 `login`、`doctor --network` 和切换返回 `2` | Python 与 Rust 将 JSON `null` 视为字段缺失；有效备用字段可核验。未知非 null 原始字段、类型异常及冲突仍失败；账号证据继续严格校验 |
| 同名脚本遮蔽 | 从目标用户主目录运行安装命令执行旧同名脚本，因旧浏览器依赖缺失返回 `1`；从独立目录正常 | 包装器使用 Python `-P -m`，不让当前目录抢先提供同名模块。保留原目录、旧文件、显式环境和三个别名行为 |

服务字段的当前规则见[使用说明](usage.md#命令)；包装器边界与已安装用户的更新要求见[开发说明](development.md#模块职责)和[迁移说明](migration.md#更新当前安装)。

实现：[Python 服务解析](../src/ysu_net/auth/common.py)、[Python 账号证据](../src/ysu_net/manager/account_switching.py)、[Rust 状态解析](../desktop/crates/ysu-auth/src/protocol.rs)、[Rust 账号核验](../desktop/crates/ysu-auth/src/lib.rs)、[包装器](../src/ysu_net/manager/install.py)。原生账户运行器复用 Rust AuthClient，无重复字段解析需要修改。

## 修复版真实复测

本轮自动化记录 36 项检查：35 项通过，移动上线 1 项因门户并发上限未通过；这不表示移动登录成功。

| 项目 | 实际结果 |
| --- | --- |
| 主目录启动 | 无测试观察器环境时执行 `ysu --help` 返回 `0`，不再执行旧脚本 |
| TTY 配置与菜单 | 隐藏密码输入、主菜单说明、错误编号、多账号菜单与服务选择通过 |
| 非交互入口 | 帮助、脱敏账号列表与本地 doctor 返回 `0` |
| 校园网全新认证 | 先下线并独立确认离线，再登录返回 `0`；另一次状态查询确认提供账号与校园网服务 |
| 重复登录与联网诊断 | 重复 `login`、`doctor --network` 均返回 `0` |
| 账户与流量 | `info --raw` 合法，账户 HTTP `200`，额度分类为 `available`；未记录原始数值或个人信息 |
| 外部访问 | 独立 HTTPS 请求返回 `200`，保持证书校验 |
| 移动切换与恢复 | `switch 中国移动` 返回 `4`；仅记录错误分类，确认为 `session_limit`。随后独立查询确认校园网已恢复，活动服务配置未变 |
| 真实重连 | 再下线并确认离线后执行 `daemon --once` 返回 `0`，日志为重连成功；独立查询确认账号与校园网服务 |
| 前台守护生命周期 | 持有运行锁时并发 `login` 返回 `2`；SIGTERM 后守护返回 `0`，网络连接保留 |
| 最终状态与清理 | 校园网在线且账号匹配，外网 HTTPS `200`；临时凭据清空、无测试工作进程、远端临时目录删除；原配置和永久服务仍未创建 |

移动原因通过测试期子进程观察器读取并立即分类 stderr 得到，仅落盘固定标记 `session_limit`，不保存原文、不改变命令参数、返回值或认证逻辑。正常离线 `status=1` 不是认证错误。初轮诊断脚本对成功输出中的“证书”字样存在过宽分类，未将该启发式当作 TLS 故障；修复版独立 HTTPS 与联网诊断均成功。

## 离线回归与未覆盖项

| 检查 | 结果 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests` | 344 tests，6.448s，全部通过 |
| `bash -n install.sh uninstall.sh` | 通过 |
| `git diff --check` | 通过 |
| Rust auth `cargo test --offline --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml` | 73 passed，7 ignored（宿主 Chromium 用例未执行） |
| Rust auth `cargo fmt --manifest-path desktop/crates/ysu-auth/Cargo.toml --check` | 通过 |
| 原生 `account_runtime::tests` | 编译阶段缺少 `dbus-1.pc` / libdbus 开发依赖，退出 `101`；没有执行用例或安装系统依赖 |

新增 [31 场景共享样本](../tests/fixtures/online-service.json)，覆盖 Python/Rust 普通服务解析与更严格的账号证据；另有 API/browser mock 登录、联网诊断、服务与账号切换、失败恢复、轮换观测三个阶段，以及两个 scope × 三个别名的同名模块/包真实子进程回归。

先用新断言复现旧实现失败，再修复。并行开发中的一次全量运行曾因新增浏览器模拟用例漏 mock CAS UI 而失败，补全 mock 后执行上述最终全量命令通过。浏览器模拟通过不等于真实浏览器认证验收。

本轮未覆盖完整远端安装脚本、正式 systemd 注册/自启、服务器重启、长稳运行、真实浏览器/验证码、其他运营商和 Windows/macOS 原生构建。仅验证多账号菜单与离线回归，没有用多个真实账号或主动耗尽额度。目标已清理临时安装，需要正式使用时仍需按[安装与更新流程](migration.md)部署。

未提交、未推送，用户原有桌面样式和预览断言改动保持原样。
