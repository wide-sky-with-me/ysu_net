# 21 的 Shell 登录、退出与版本对照

日期：2026-10-28。状态：21 的现有客户端与正式 v0.2.2 Shell API 均完成真实离线登录、在线退出及独立状态核验；原连接和自动重连后台已恢复。这不是 Rust 桌面或新增 DNS 回退实现的验收。

## 环境与来源

用户在[123 复测](portal-123-review-2026-10-27.md#2026-10-28-shell-登录与退出再测)后要求换到 Windows SSH 配置中的 21，再明确要求先用 Windows 登录、追加当前 WSL 密钥。Windows 端登录成功后只追加 WSL 公钥，保留其他 authorized_keys；WSL BatchMode 及 `21` / `yhr21` 别名已验证。未转移私钥或保存本次输入的 SSH 密码，原 Windows 主机密钥记录保留；远端用户目录中的既有校园网配置本次未改。

21 为 Ubuntu 24.04 / x86_64，已有 Python 3.12.3、Shell 客户端和运行中的用户级 ysu-net.service。门户及 CAS 系统 DNS 均正常，无代理环境变量。初始独立查询确认在线，实际身份及“中国移动”服务与 21 自己保存的配置一致。

| 对照入口 | 实际来源 |
| --- | --- |
| 现有 `ysu` | 安装元数据为 0.1.0，18 个 Python 文件中 9 个与 v0.1.0 标签一致、9 个不同；完整源码指纹已保存，不能将其称为未修改的正式 v0.1.0 |
| 隔离的 v0.2.2 | 正式云端 wheel，SHA256 为 `b19e8665fdd213991ed951cf55275898ba3738d7d97b7a3b783d355a99122a1c`；25 个源码文件与标签逐字节一致，与 123 对照使用同一个 wheel |

云端 wheel 仅解包到本次私有临时目录，使用现有解释器和依赖，未覆盖原安装。实际模块版本为 Requests 2.34.2、urllib3 2.7.0、PyCryptodome 3.23.0；这些是运行时版本核对，不是依赖逐字节来源验证。两端读取同一份 21 配置，API 后端、中国移动服务、HTTPS 域名和证书校验一致。

## 命令与实际结果

主流程在 UTC 02:42:42 至 02:42:54（北京时间 10:42:42 至 10:42:54）执行。控制进程先脱离 SSH 会话，暂时 `systemctl --user stop ysu-net.service`，待自动重连停止后才做变更，finally 恢复连接及原后台。

现有安装通过正常 `ysu` 包装命令调用；云端包通过其正式模块入口调用：

```bash
# 仅示意本次已核验云端包的远端运行方式，变量不含凭据。
PYTHONPATH="$TRACE_OBSERVER:$CLOUD_SRC" "$APP/.venv/bin/python" -P -m ysu_net login
PYTHONPATH="$TRACE_OBSERVER:$CLOUD_SRC" "$APP/.venv/bin/python" -P -m ysu_net logout
```

| 阶段 | 操作退出码 | 随后的独立状态查询 |
| --- | --- | --- |
| 原连接准备下线：现有 `ysu logout` | 0 | status=1，明确 offline |
| 现有 `ysu login` | 0 | status=0，online，身份和服务均匹配 |
| 现有 `ysu logout` | 0 | status=1，明确 offline |
| 隔离 v0.2.2 `login` | 0 | status=0，online，身份和服务均匹配 |
| 隔离 v0.2.2 `logout` | 0 | 现有客户端独立 status=1，明确 offline |
| 现有 `ysu login` 恢复原连接 | 0 | status=0，online，身份和服务均匹配 |

三次新登录的 CAS 密码 POST 均返回 302，serviceLogin 的 data.authResult 均为 success，userOnline 的 data.online 均为 true；最终仍以独立状态及身份 / 服务配对为准。实际记录三次 offline API POST，分别为准备下线、现有客户端退出和云端客户端退出，均有后续明确 offline，不是已离线时的空操作。

主流程观察到 137 次应用请求尝试、3 次 CAS 密码 POST、3 次 offline API POST；此数不包含流程前后的额外独立探测，也不是抓包计数。被动观察器记录闭集状态、角色和计数，每个认证子进程最多允许一次密码 POST；保留原请求头、Cookie、跳转和表单逻辑，没有 DNS 地址覆盖，所有观察到的 HTTPS 请求均开启证书校验。存在观察器插桩，不能宣称完全无插桩运行。

## 收尾与边界

原客户端源码及持久配置前后逐字节一致，未安装 / 替换系统 Python 或依赖、编译程序、注册新服务或修改 DNS。恢复原用户服务后，UTC 02:44:32 再次用现有客户端独立确认 online、身份 / 移动服务均匹配，后台 active，WSL 密钥登录正常。

控制进程已退出，远端临时云端包 / 观察器 / 收据目录及 Windows 临时固定指纹文件已删除；保留原客户端、公钥追加和 WSL 免密别名。本地忽略目录 `build/shell-cycle-21-20261028/` 保存源码指纹、脚本、脱敏主收据、摘要及收尾记录，不存凭据、原页面或会话值。

21 与 123 的条件不同：21 使用本机保存的中国移动配置且系统 DNS 正常，123 使用此前授权的 111 校园网配置且系统 DNS 失败。即使同一个正式 v0.2.2 wheel 在 21 成功，也不能据此把 123 的服务拒绝单独归因于机器、DNS 或账号，更不能宣称 Rust 原生客户端已通过。本轮没有在 123 再次认证；Rust / 新 DNS 回退源码仍待独立云端构建及产品验收。

同日随后按用户要求新增第二账号进行的直接 / 守护持锁双向换号，另见[账号池实测](account-pool-21-review-2026-10-28.md)；它使用独立临时账号簿，原连接与后台均已恢复，不改写本文前一轮的条件和成绩。

随后对本文保存的正式 CLI 轨迹进行[跳转专项复核](portal-redirect-parity-2026-10-28.md)，区分离线 captive 与在线 HTTP main → HTTPS 两条路径，并补齐 Rust 开发源码的共用导航接线；这次复核没有新增登录 / 下线，也没有 Rust 运行结果。
