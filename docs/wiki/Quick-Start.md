# 快速开始

[返回导航](Home.md) · [桌面客户端](Desktop-Client.md) · [命令行速查](CLI-Reference.md) · [常见问题排障](Troubleshooting.md)

在开始前，请先确认设备已接入燕山大学校园网有线或无线网络（能够访问校园网门户 `auth1.ysu.edu.cn`）。

---

## 方式一：桌面客户端（Windows / Ubuntu / macOS）

1. **下载安装**：前往 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 下载对应系统的安装包：
   - **Windows 10/11 x64**：运行 `YSU-Net_0.3.0_windows-x64-setup.exe` 完成安装。
   - **Ubuntu 22.04+ x64**：执行 `sudo apt install ./YSU-Net_0.3.0_linux-x64.deb`。
   - **macOS 13.5+**：按芯片架构选择 `macos-arm64.dmg`（Apple 芯片）或 `macos-x64.dmg`（Intel），拖入「应用程序」。首次打开若提示无法打开，可在终端运行 `sudo xattr -rd com.apple.quarantine "/Applications/YSU Net.app"`。
2. **填写账号**：打开客户端，进入侧栏 **设置 → 账号**，输入学号/工号与密码，选择默认运营商（校园网 / 中国移动 / 中国联通 / 中国电信）并保存。
3. **一键连接**：回到 **连接** 页点击 **立即连接**，并按需开启 **自动重连**。
4. **开启 7 天无感认证（可选）**：进入侧栏 **设备** 页，点击 **读取设备**，在「无感认证（7天）」区域点击 **开启本机 7 天无感认证** 并勾选 **到期前自动续约**，即可免去每周重复认证。

更多桌面端功能请参阅 [桌面客户端指南](Desktop-Client.md)。

---

## 方式二：Linux 命令行 (`ysu`)

### 1. 安装

```bash
git clone https://github.com/wide-sky-with-me/ysu_net.git
cd ysu_net
bash install.sh                  # 如需自动识别验证码可加 --captcha
export PATH="$HOME/.local/bin:$PATH"
```

### 2. 配置账号与运营商

```bash
ysu config account               # 交互输入学号/工号与密码
ysu service                      # 选择运营商：校园网 / 中国移动 / 中国联通 / 中国电信
```

### 3. 登录并开启自动守护

```bash
ysu on                           # 立即登录并开启后台自动重连
ysu status                       # 查看当前连接状态与守护运行情况
ysu info                         # 查看套餐与剩余流量
```

### 4. 开启 7 天无感认证与自动续约（推荐）

```bash
# 为本机开启 7 天无感认证，并开启到期前 24 小时后台自动续约
ysu self nosense current --service 中国联通 --auto-renew
```

### 5. 断开连接

```bash
ysu off                          # 停止后台自动重连并下线当前校园网连接
```

更多命令行用法见 [命令行速查](CLI-Reference.md) 与 [完整手册](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md)。
