# 用户级远端部署验收

## 结论

已将增强版提交至 GitHub `origin/main`，原校内服务器从仓库拉取并完成正式用户级安装。`ysu-net.service` 当前由用户 systemd 管理，状态为 `active/running`，自启为 `enabled`，`Linger=yes`，中国移动保持在线。

验收代码提交为 `6e1733e`（此前基线为 `1860ed4`）。后续文档提交不改变本次验收的运行代码。

## 部署方式

源码来源：`https://github.com/wide-sky-with-me/ysu_net.git`。

| 项目 | 实际部署 |
| --- | --- |
| 环境 | 原校内 Ubuntu 24.04 主机，普通用户安装 |
| 源码与虚拟环境 | `~/.local/share/ysu-net/app` 及其 `.venv` |
| Python | 项目虚拟环境使用系统 Python 3.12.3 |
| 依赖 | 用户目录安装 uv；`bash install.sh` 按 `uv.lock` 安装 |
| 命令 | `~/.local/bin/ysu`、`ysuon`、`ysuoff` |
| 服务单元 | `~/.config/systemd/user/ysu-net.service` |
| 账号配置 | `~/.config/ysu-net/config.json`，文件权限 `0600`，目录 `0700` |
| 默认服务 | 中国移动，API 后端，TLS 校验开启 |
| 自启与用户生命周期 | `ysu boot on`；`loginctl enable-linger` 成功 |

安装前没有同路径的项目、管理命令、账号配置或同名服务；此前 `Linger=no`。没有覆盖其他项目，也没有修改系统级认证服务。

此次属于正式部署，账号密码按用户部署要求保存在远端私有配置。它们没有进入 Git、测试报告、命令行参数、服务单元或验收日志。此前临时实测“不持久化凭据”的结论仅适用于临时测试阶段。

uv 安装采用 `UV_NO_MODIFY_PATH=1`，没有改写用户 shell 配置；随后以清洁环境启动新的 Bash 登录 shell，确认 `ysu` 可直接解析到用户命令目录。

## 真实验收

验收辅助进程脱离 SSH 运行，输出仅记录脱敏结果。下线后启动服务置于恢复路径中，避免依赖 SSH 持续连接。

| 验收项 | 实际结果 |
| --- | --- |
| 远程仓库拉取 | 克隆成功，代码提交与本地推送提交一致 |
| 首次安装 | `install.sh` 返回 0，注册用户级服务 |
| 诊断 | `ysu doctor --network` 返回 0，全部检查通过 |
| 启动和自启 | `ysu on`、`ysu boot on` 返回 0，服务 active、enabled |
| 生命周期 | `Linger=yes`，服务位于用户管理器的 app.slice，而非当前 SSH session.scope |
| 并发保护 | 后台运行时手动 `ysu login` 返回 2，未争抢认证流程 |
| 保持连接的停止 | `ysu stop` 后服务 inactive，中国移动仍在线 |
| 真正下线 | `ysu off` 后独立状态确认离线 |
| 实际守护重连 | 重新 `ysu on` 后由真实 systemd 守护进程登录，独立确认中国移动上线 |
| 崩溃恢复 | 对本项目服务主进程发送 SIGKILL；systemd 自动拉起新 PID，`NRestarts=1`，保持在线 |
| 重装幂等 | 再执行 `install.sh` 成功，账号配置逐字节未变，服务继续运行 |
| 日志 | `ysu logs -n 20` 返回 0；journal 可见“重连成功”，检查未发现账号或密码 |
| 交互体验 | 真实终端运行 `ysu` 显示中文菜单、服务及账号配置状态，输入 0 正常退出 |
| 新登录终端 | 清洁环境 Bash 登录 shell 中 `command -v ysu` 成功 |
| 权限 | 配置目录 700、配置文件 600 |
| 最终状态 | 服务 active/running、enabled，中国移动在线 |

本地提交前 114 项离线测试及 `git diff --check` 均通过。测试刻意制造的一次 SIGKILL 是故障注入验收，不是运行中发现的自发崩溃。

## 验收边界

已验证后台服务本身、真实重连、异常退出自动恢复、日志、用户级安装与重复安装。未重启服务器，也未主动断开最后一个 SSH 会话，因此重启后启动及最后会话退出后的存续只完成配置核查，不列为实际重启/登出验收。长期稳定性、可选浏览器及其他运营商未在本次部署测试中覆盖。

## 管理与回滚

日常使用 `ysu status` 查询连接，`ysu logs -f` 跟随日志，`ysu doctor --network` 检查运行环境。

保留当前网络连接、停止自动重连：

```bash
ysu stop
ysu boot off
```

若需要卸载用户命令和服务：

```bash
bash ~/.local/share/ysu-net/app/uninstall.sh
```

默认卸载保留账号配置、源码及虚拟环境，不自动下线当前网络连接。`linger` 是用户管理器设置，不由卸载器撤销；如需恢复本次部署前状态，并确认没有其他用户后台任务依赖它，可另行执行 `loginctl disable-linger "$USER"`。

更新部署时建议先 `ysu stop` 保留网络连接，再在项目目录执行 `git pull --ff-only`、`bash install.sh`，完成检查后 `ysu on`。账号配置位于仓库外，不随 Git 更新覆盖。
