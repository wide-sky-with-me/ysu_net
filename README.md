# ysu-net-login

燕山大学校园网登录脚本（auth1.ysu.edu.cn / cer.ysu.edu.cn）。

本目录包含两种实现：
- `ysu_api.py`：纯 API（requests）版，适合无浏览器/无图形环境。
- `ysu_browser.py`：Playwright 无头浏览器版，适合直接复刻真实浏览器行为（更接近“手动网页登录”）。

## 快速开始

### 1) 安装依赖

```bash
pip install -r requirements.txt
```

若使用 `ysu_browser.py`，还需要安装浏览器运行时：

```bash
python -m playwright install chromium
```

### 2) 配置账号密码

推荐使用环境变量：

```bash
export YSU_USER="你的账号"
export YSU_PASS="你的密码"
```

### 3) 使用（纯 API 版）

```bash
python ysu_api.py login --service 校园网
python ysu_api.py info
python ysu_api.py logout
```

### 4) 使用（无头浏览器版）

```bash
python ysu_browser.py login --service 校园网
python ysu_browser.py info
python ysu_browser.py logout
```

## 交互式模式

两个脚本都支持：
- `--interactive`：缺少账号/密码时交互输入
- `shell` 子命令：进入 REPL，支持 `login/info/logout/exit`

示例：

```bash
python ysu_api.py shell
python ysu_browser.py shell
```

## 配置项

两种实现共用同一套环境变量（也可通过命令行参数覆盖）：

- `YSU_USER`：账号
- `YSU_PASS`：密码
- `YSU_BASE`：Portal 根地址（默认 `https://auth1.ysu.edu.cn`）
- `YSU_CAS_HOST`：CAS 根地址（默认 `https://cer.ysu.edu.cn`）
- `YSU_TIMEOUT`：requests 版超时秒数（默认 `25`，仅 `ysu_api.py` 使用）
- `YSU_VERIFY_TLS`：是否校验证书（`1/true/yes` 开启；默认关闭）
- `YSU_PORTAL_UA`：自定义 User-Agent（可选）
- `YSU_VERSION`：拼接到查询参数里的 `version` 值（默认 `this is a git-commit`）
- `YSU_SAVE_DEBUG_FILES`：是否允许把调试 HTML/图片/抓包文件写入当前目录（默认关闭）

## 校园网认证流程

典型流程可以理解为两段：

1. **Portal 网关侧会话（auth1）**
   - 访问 `auth1` 的入口页会触发一段重定向，最终得到 `sessionId/flowSessionId`。
   - 后续对 `/eportal/...` 的接口（查询在线、选择服务、上线、下线）都围绕这个会话进行。

2. **统一认证（CAS，cer）**
   - 当 `auth1` 判断当前会话需要认证时，会把你重定向到 `cer` 的 CAS 登录页。
   - 登录成功后会带着票据回跳到 `auth1`，`auth1` 继续走到 `serviceSelection` 节点，然后调用：
     - `serviceLogin`（选择运营商/服务）
     - `userOnline`（发起上线）

下线（logout）本质是调用 `auth1` 的 `/eportal/network/offline`，网关生效可能有延迟，因此脚本会轮询在线状态确认是否离线。

## 安全说明

- 不要把账号/密码硬编码到脚本里，建议仅通过环境变量或交互输入。
- `--debug` 可能输出请求信息；调试落盘文件默认关闭，需要显式开启 `YSU_SAVE_DEBUG_FILES=1` 或 CLI 参数。

## 常见问题

- **提示 IP 被冻结 / 找不到登录框**
  - 这是 CAS 风控页面，等一段时间或切换网络再试。

- **已发起下线但仍显示在线**
  - 网关侧可能存在延迟；可稍等再 `info` 查询，或重试 `logout`。
