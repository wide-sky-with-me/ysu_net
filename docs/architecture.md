# 产品形态与系统架构

[返回首页](../README.md) · [文档导航](README.md) · [桌面端说明](tauri-desktop.md) · [开发说明](development.md)

**YSU Net** 采用“一套配置规范、双端独立实现”的架构设计：

1. **跨平台桌面客户端（Windows / Linux / macOS）**：采用 Tauri 2 + Svelte 5 + Rust 原生实现，面向图形界面用户，开箱即用，不依赖 Python 或 Node 运行时。
2. **Linux 命令行与守护服务（`ysu`）**：采用 Python 3.12 + `systemd` 实现，面向 Linux 终端、服务器、WSL 与自动化脚本场景。

两端共用相同的配置文件格式（`config.json`、`config.accounts.json`、`config.nosense.json`）与一致的门户认证语义。

---

## 模块划分

```text
ysu_net/
├── src/ysu_net/                 # Linux Python CLI 与后台守护实现
│   ├── auth/
│   │   ├── api.py               # Portal + CAS 纯 HTTP 认证实现
│   │   ├── browser.py           # Playwright 浏览器认证实现（可选）
│   │   ├── selfservice.py       # 校园网自助服务 (/self)：设备、7天无感认证与服务设置
│   │   ├── common.py            # 密码加密、HTML 表单解析与状态模型
│   │   ├── dns_fallback.py      # 校园网门户/CAS 域名备用 IP 解析
│   │   └── quota.py             # 套餐剩余流量解析与零流量判定
│   └── manager/
│       ├── cli.py               # `ysu` 命令行入口与交互式菜单
│       ├── daemon.py            # 后台自动重连、零流量换号与无感自动续约守护
│       ├── accounts.py          # 多账号池存储 (config.accounts.json) 与候选排序
│       ├── account_switching.py # 账号热切换、零流量轮换与无感认证交接
│       └── config.py            # 主配置、无感续约配置 (config.nosense.json) 与进程文件锁
├── desktop/                     # 跨平台 Tauri + Rust 桌面客户端
│   ├── crates/ysu-auth/         # 纯 Rust 认证核心库（Portal/CAS、自助服务、无感认证、ONNX 验证码、CDP 浏览器）
│   ├── src-tauri/               # Tauri 原生宿主（任务调度、自动重连、多账号轮换、无感续约、托盘、在线更新）
│   └── src/                     # Svelte 5 + TypeScript 桌面界面
└── packaging/                   # 云端构建、更新清单签名校验与冒烟验收脚本
```

---

## 核心业务流程

### 1. 门户登录与状态核验

1. **预检与引导**：请求门户首页查询当前会话与在线状态；若由 `/eportal/redirect.jsp` 下发旧式 `http://auth1.ysu.edu.cn/portal/portal-main?...` 跳转，发送前本地升级为 `https://` 以保留 `customPageId`/`userIp`/`ssid`/`nasIp` 参数；若处于离线 Captive 引导状态，仅单次只读探测跳转目标后以 `sessionId` 驱动工作流节点（`authenticate → serviceSelection → finish`）。
2. **统一身份认证（CAS）**：通过 `/cas-sso/clientredirect?client_name=sidadapter` 拉取 `cer.ysu.edu.cn` 登录页，可优先复用未过期的 `CASTGC` 会话（30 分钟有效）跳过账密提交；需要表单认证时仅围绕选中的密码表单解析 `#pwdEncryptSalt`（AES-128/192/256-CBC）与 `#captchaDiv` 并检测 DOM 可见风控文本；触发验证码且已配置本地模型时最多提交 2 次（首轮与 1 次换图重试），连续登录失败达 3 次或返回退出码 `4` 时自动暂停后台重连。
3. **服务选择与上线**：CAS 回调门户后提交目标运营商（校园网 / 中国移动 / 中国联通 / 中国电信）完成上线；下线前预先获取 `/sam` 会话 Cookie 保证真实下线生效。
4. **独立复核**：每次登录、下线或切换运营商后，均通过新的无 Cookie 状态查询确认在线身份与服务是否一致。

### 2. 设备自助服务与 7 天无感认证

1. **OAuth2 委托登录与会话隔离**：校园网内部按应用隔离维护四组会话边界（CAS `/authserver` 的 `CASTGC`/`XSRF-TOKEN`/`JSESSIONID`、门户 `/eportal` `JSESSIONID`、`/sam` `JSESSIONID` 与 `/self`/OAuth2 根路径 `SESSION`）；访问 `/self/index` 先初始化会话并通过 `/oauth2/authorization/custom-self` 经统一身份认证完成委托授权（可复用 `CASTGC`）。
2. **无感认证与自动续约**：
   - 调用 `/self/setting/noSense` 开启 7 天 MAC 无感认证，调用 `/self/mac/unbind` 取消绑定，调用 `/self/setting/net` 修改默认上网服务。
   - 后台守护（Python `NoSenseRenewer` 与 Rust `Worker`）按账号读取 `config.nosense.json`：单个账号查询成功后的常态网络巡检间隔为 **6 小时**（瞬时异常 **30 分钟** 重试，需人工介入异常则暂停），当目标设备的无感有效期剩余不足 24 小时或已过期时，自动执行「解绑 → 重新绑定 7 天」。
3. **多账号换号交接**：当手动切换账号或因零流量自动轮换账号时，自动在下线前解绑旧账号的本机 MAC 无感认证，并在新账号上线后重新绑定本机无感认证、同步迁移自动续约规则。

---

## 安全与可靠性边界

- **最小权限存储**：所有包含密码、账号池或自助服务会话的本地文件均以 `0600` 权限原子写入；前端快照与日志绝不包含明文密码、Cookie 或票据参数。
- **跨进程互斥锁**：认证、下线、切换账号与后台重连均通过文件锁串行化；同一台设备上建议只启用桌面客户端或 CLI 服务中的一套自动管理。
- **受限导航与证书校验**：严格校验 HTTPS 证书与校园网主机白名单，仅对已知的校园网同源门户跳转做协议规范化，防止凭据发往非预期地址。
