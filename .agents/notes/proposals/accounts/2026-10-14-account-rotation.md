# 多账号热切换与流量轮换

日期：2026-10-14。状态：已实施并完成本轮离线与 Linux SDK 原生验收，真实校园网及 Windows/macOS 待验。范围：feat/rust-desktop 的 Rust 图形版及独立 Python CLI/守护、Qt 兼容引擎控制通道；不提交、推送或发布。

## 背景与选择

用户要求多账号热切换、流量为空时自动换号。已有认证只支持同账号运营商切换，单独替换用户名会把原在线账号当作他人；旧配置严格拒绝未知字段，直接嵌入账号数组会破坏回退。沿用[原生迁移决定](../desktop/2026-10-14-rust-desktop.md)的独立核验、未知不认证、失败恢复及短时配置写锁。

采用独立账号簿，当前 config.json 仍是活动凭据唯一权威来源；不添加第二个活动指针，不把两次文件替换宣称为原子事务。账号簿读出时，匹配活动用户名的凭据、服务与后端以 config 为准；离开当前账号前在短写锁中保存其最新快照，目标独立验证后才 CAS 提交活动配置，保留期间更新的无关计时参数。凭据/地址或候选被并发改动则停止提交，不覆盖新意图。

## 跨语言存储契约

路径为配置路径替换扩展名后的 `.accounts.json`，例如 config.json 对应 config.accounts.json。共同使用原配置 `<filename>.write.lock`；运行锁仍为配置替换扩展名的 `.lock`。目录 0700、文件 0600、UTF-8 JSON 原子替换；64 KiB 上限，最多 32 个保存账号，严格字段校验，重复 id/用户名不接受。

```json
{"version":1,"auto_switch":false,"accounts":[{"id":"0123456789abcdef0123456789abcdef","label":"测试账号 A","username":"fixture-a","password":"fixture-only","service":"校园网","backend":"api","enabled":true}]}
```

id 是 32 位小写十六进制不透明标识，不含路径；Python 可使用 uuid4().hex，Rust 使用已有 rand。账号用户名创建后保持不变，改账号使用新增/删除；label 可为空或最多 80 个字符。密码留空更新表示保留已有密码，新账号必须有密码。未入簿的有效当前配置以只读合成 id `current` 展示，保存或离开时正式入簿；原文件不因查看而迁移。活动账号不删除，先切换再删除。YSU_USER/YSU_PASS/YSU_SERVICE 环境覆盖存在时，账号切换停用，不把环境秘密隐式写入账号簿。

编辑活动账号的凭据更新仍以 config 的单文件原子提交为准；账号簿元数据失败须报告，读取时不得用旧镜像覆盖新活动凭据。所有密码只在私有存储与认证核心中存在；公开快照只给 password_set，不给密码。

## 原生 IPC 契约

保留已有命令，新增：

- `save_account`：对象包含可选 id、label、username、可选 password、service、backend、enabled；新账号 id 省略。
- `delete_account`：`{id}`，不删除当前账号；在执行时重新核验。
- `rotation`：`{enabled}`；默认 false，启用需至少两个有效启用账号并开启自动重连。关闭立即更新意图，保存失败不得恢复内存中的开启状态。
- `action` 新增 `name=switch_account,value=<id>`，进入现有串行队列，执行时重载与核验候选。

Snapshot 新增 accounts 对象：items（每项 id/label/username/service/backend/enabled/password_set/current）、auto_switch、environment_override、error（空字符串表示正常）、quota（state/message）、message。quota.state 为 unknown/available/zero_reported/unlimited；只公开当前账号信息。结构枚举、id 和公开用户名保持可回传，即使用户名恰好与密码相同也不替换；自由文本仍脱敏，任何快照和账号条目均不含密码字段。

## 切换与自动轮换

手动换号先查询状态；未知状态或在线账号不是当前活动账号时停止。显式 userId 优先于显示名称，外层业务矛盾同样使结果未知。记录真实原服务，确认下线后才登录候选，再独立核验目标账号和服务。仅确认成功且源配置/目标身份仍一致时保存活动凭据。失败时只有原先在线、状态可信且源及候选均未出现新意图，才尝试一次恢复原连接；恢复也要独立查询。原先离线不额外登录原账号。总时限包含查询、变更、核验和恢复，取消或超时显示未知。

自动换号随自动重连后台运行，默认关闭；只对配置所属的在线账号读取流量，在账户读取前后独立确认同一账号和服务。门户展示不是精确计量接口：以门户明确剩余流量字段及其显式单位为依据，数值零记为 zero_reported，不声称精确字节耗尽；连续两次独立观测报告零后才轮换。缺字段、裸零无单位、余额为零、已用流量为零、负数、无穷、无限量、HTTP/业务失败、身份不明均不触发。必要时在当前说明明确舍入显示的限制。

后台流量检查间隔至少 60 秒；零值证据绑定原活动身份及自动管理代次，过期、停用/重新开启即作废，prepare 在短写锁内对比预期源，避免重载为新账号后沿用旧证据。按列表顺序选择启用且有凭据的候选，一轮最多尝试一个。已报告零或切换失败的候选冷却至少 15 分钟，凭据变化/显式手动操作可重新尝试；全部不可用则停止轮换并等待，不循环撞登录。验证码/交互错误不作为流量耗尽信号。下线同时关闭自动管理，忙碌时仍可关闭重连/轮换或退出；watch 通知合并时用代次变化取消旧任务，而非只看最终布尔值。

## CLI 与兼容入口

CLI 提供 accounts 列表/保存/删除/切换/自动轮换开关，密码由终端 getpass 读取，不放参数或输出。复用同一账号簿与分类样本。守护持有生命周期锁时，热切换经其所属控制通道处理并返回核验结果，而不是去锁或单改配置；旧所有者未实现该通道时报告未确认，不假报成功。Qt 兼容引擎继续读取旧 config，并已接入同一控制通道；旧 Qt 不另做新视觉界面。Rust 后台保持自身 IPC，不消费 Python 文件通道。

Shell 补齐（2026-10-14）：主菜单 16、无动作 `ysu accounts` 与 `accounts menu` 接入交互账号管理，原菜单编号保持兼容；`--enabled` 与 `--disabled` 互斥，可恢复候选启用状态。账号菜单只适配展示与确认，换号和轮换继续进入既有 CLI/所有者通道，避免再造 Bash 认证或第二个后台进程。密码仍由原 getpass 保存路径处理，账号值与选项通过参数边界分开；非终端菜单仅提示用法，机器接口继续用显式子命令。

## 替代方案与代价

未选把整个账号数组写进旧 Config：旧严格解析器和旧发行版读取即失败。未选第二个 active_id 权威文件：跨文件指针容易分叉。未选只保存目标用户名：无下线/登录/核验，不构成热切换。未选把缺失额度、余额零或登录失败当耗尽：现有门户并不总返回流量。未选逐个无限试号：会形成来回切换与交互重试。

代价是两种语言保留各自调度实现，使用同一 JSON 与行为样本约束；门户缺少额度时仍须手动换号。显示零可能舍入，因此保守双观测仍不等同精确字节证据。Windows/macOS、真实校园流量、真实托盘和旧服务升级控制需分别验收。

## 验证与反链

实现位于 [Rust 账号存储](../../../../desktop/src-tauri/src/accounts.rs)、[原生调度](../../../../desktop/src-tauri/src/account_runtime.rs)、[账号界面](../../../../desktop/src/components/AccountBook.svelte)、[Python 存储](../../../../src/ysu_net/manager/accounts.py)与[调度](../../../../src/ysu_net/manager/account_switching.py)。

[原生状态机回归](../../../../desktop/src-tauri/src/account_runtime_tests.rs)、[Python 审查回归](../../../../tests/test_multi_accounts_review.py)及[84 项共享额度样本](../../../../tests/fixtures/account-quota.json)约束实现。Shell 适配见[账号菜单](../../../../src/ysu_net/manager/account_menu.py)与[Shell 回归](../../../../tests/test_shell_accounts.py)。
