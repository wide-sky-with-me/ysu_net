# Shell 多账号验收

日期：2026-10-14（Asia/Shanghai）。范围：`feat/rust-desktop` 工作树中的 Shell/Python 命令行版；未提交、推送、部署或发布。使用方式见[账号操作指南](accounts.md#shell-版交互菜单)，设计取舍见[多账号决定](../.agents/notes/proposals/accounts/2026-10-14-account-rotation.md)。

## 实现与入口

主菜单新增 **16 多账号与自动换号**，既有编号保持不变。`ysu accounts` 和 `ysu accounts menu` 打开同一子菜单，支持新增、编辑、启停候选、确认后热切换、删除及自动换号开关。`save --enabled` 与 `--disabled` 互斥，未指定则保留原状态。

[账号菜单](../src/ysu_net/manager/account_menu.py)只负责展示、输入与确认，认证切换及轮换仍通过[现有 CLI](../src/ysu_net/manager/cli.py)和[所有者控制通道](../src/ysu_net/manager/control.py)。Shell 包装脚本保持原样，不新增认证实现或后台进程；旧 Qt 与 Rust 桌面行为未改动。本轮未重建桌面包，也未用此前原生验收代替本轮 Shell 证据。

## 本轮结果

| 检查 | 结果 |
| --- | --- |
| Python 完整离线回归 | 413 项通过，其中新增 Shell 回归 20 项 |
| 真实 Shell/PTY | 已生成的实际包装脚本，从仓库外目录执行；账号增改删、候选开关、取消换号、关闭轮换均通过 |
| 终端密码与权限 | 密码输入未回显，空密码保留；账号簿为 0600；公开 JSON 无密码字段 |
| 后台操作 | 菜单转交锁所有者，不重启 systemd，不从 CLI 并发认证；未确认结果保持失败状态 |
| 自动轮换前提 | 无自动管理所有者时开启失败且不启动服务；环境覆盖阻止换号和开启轮换，仍可关闭 |
| 控制超时回归 | 固定时钟与事件同步后，原断言重复 100 次通过 |
| 包装与锁文件 | 离线 wheel 构建、模块逐字节核对、入口校验、锁文件检查通过 |
| Shell 与改动检查 | 安装/卸载脚本语法、空白及文档本地链接检查通过 |

真实 Shell 测试使用标准库伪终端，执行安装器实际生成的 Bash 包装内容，保留真实 Python 模块路由与配置文件操作。子进程显式阻断网络和服务操作；没有校园认证或真实账号参与。后台切换/轮换的终端路由由离线用例核对，真实文件控制通道与守护线程执行由完整回归中的既有集成用例覆盖，不能把模拟认证称作校园网实测。

## 复现与修复

修改前新增的三项入口断言实际失败：无动作 `accounts` 被参数解析挡住，`--enabled` 未识别，主菜单 16 未分派。原始失败保存在本地 `dist/shell-accounts-validation/before.log`；对应断言保留在[Shell 回归](../tests/test_shell_accounts.py)。

首次完整回归中，[控制测试](../tests/test_multi_accounts_control.py)的“已开始后超时”用例失败，单项立即复测通过。该测试把请求的 60 毫秒真实时限与消费线程调度绑定，负载下请求可能先过期，尚未进入其要测试的 running 分支。本轮仅修正测试同步：请求开始前冻结注入时钟，等待处理器事件后推进时钟越过原截止点，再检查 running、最终未确认及不重放断言。没有延长生产超时、放宽断言或修改控制核心。首次失败日志保留为 `python-tests-first.log`，最终完整回归与重复验证分别为 `python-tests.log`、`control-timeout-stress.log`。

当前测试进程退出仍报告既有 `ResourceWarning: gc: 1 uncollectable objects at shutdown`，测试退出码为 0；本轮没有修复或隐去该警告。

## 命令与产物

在仓库根目录执行：

```bash
PYTHONPATH=src:tests .venv/bin/python -B -m unittest tests.test_shell_accounts -v
QT_QPA_PLATFORM=offscreen .venv/bin/python -B -m unittest discover -s tests -v
uv build --wheel --offline --out-dir dist/shell-accounts-validation/packages
uv lock --check --offline
bash -n install.sh uninstall.sh
git diff --check
```

本地日志与 wheel 位于 `dist/shell-accounts-validation/`。wheel 内 `account_menu.py`、`cli.py`、`ui.py` 已与当前源码逐字节核对，`ysu` 入口为 `ysu_net.manager.cli:main`。开发包 SHA256：`5e42f47e77f1865c5eb71fed943871543508aa94b970e97110a3441ef71741d2`；未安装、上传或发布。

## 待验范围

真实校园网热切换、实际流量零报告与套餐精度、真实服务升级后接管、长期守护运行仍待现场验证。Windows/macOS 桌面不属于本轮 Shell 改动；其已有验收边界仍见[此前账号轮换记录](account-rotation-validation.md)。
