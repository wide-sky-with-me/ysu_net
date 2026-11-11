# 更新、卸载与旧版迁移

[返回首页](../README.md) · [文档导航](README.md) · [命令与配置](usage.md) · [软件内签名更新](updates.md)

本页说明桌面客户端与 Linux 命令行工具的升级方法、卸载步骤以及旧版本迁移注意事项。

---

## 升级桌面客户端（v0.3.0）

升级时原有的账号配置（`config.json`）、多账号池（`config.accounts.json`）、无感自动续约配置（`config.nosense.json`）与界面偏好（`gui.json`）均自动保留，无需重新填写密码。

- **Windows 10 / 11 x64**：
  - 在客户端侧栏 **关于** 页点击 **检查更新**，确认后即可下载并完成升级；
  - 或前往 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 下载 `YSU-Net_0.3.0_windows-x64-setup.exe` 直接运行覆盖安装。
- **macOS 13.5+（Apple 芯片 / Intel）**：
  - 在客户端侧栏 **关于** 页点击 **检查更新** 完成升级；
  - 或下载对应架构的 `.dmg`（`macos-arm64.dmg` 或 `macos-x64.dmg`），退出旧程序后将 `YSU Net.app` 拖入「应用程序」替换。若首次打开提示“已损坏，无法打开”，在终端执行：
    ```bash
    sudo xattr -rd com.apple.quarantine "/Applications/YSU Net.app"
    ```
- **Ubuntu 22.04+ x64**：
  - 下载 `YSU-Net_0.3.0_linux-x64.deb`，执行：
    ```bash
    sudo apt install ./YSU-Net_0.3.0_linux-x64.deb
    ```

### 从早期版本迁移提示

- **v0.2.0 升级**：`v0.2.0` 尚无软件内更新入口，请直接从 GitHub Releases 手动下载安装新版。
- **v0.1.0（旧版 Qt 客户端）升级**：自 `v0.2.0` 起桌面版已全面迁移为 Tauri 原生架构。Windows 用户请先在系统设置中卸载旧版 Inno Setup 安装的 0.1.0 客户端，再安装新版 NSIS 安装程序。

---

## 升级 Linux 命令行工具 (`ysu`)

在原克隆的仓库目录中执行以下命令即可完成升级（保留全部已保存账号与无感自动续约配置）：

```bash
ysu stop
git pull --ff-only
bash install.sh                # 若启用了验证码识别或浏览器模式，请对应加上 --captcha / --browser
ysu doctor
ysu on
```

如果使用的是系统级安装（`--system`），请对应执行：

```bash
sudo systemctl stop ysu-net.service
git pull --ff-only
sudo env PATH="$PATH" bash install.sh --system
sudo ysu on
```

---

## 卸载说明

### 1. 卸载桌面客户端

- **Windows**：在「设置 → 应用 → 已安装的应用」中找到 **YSU Net** 点击卸载。
- **Ubuntu / Debian**：执行 `sudo apt remove ysu-net`。
- **macOS**：退出客户端后，将「应用程序」中的 **YSU Net.app** 移至废纸篓。
- 如需一并清理本地保存的账号配置，可手动删除配置目录（Windows 为 `%APPDATA%\ysu-net`，Linux / macOS 为 `~/.config/ysu-net`）。

### 2. 卸载 Linux 命令行工具

在项目目录下运行 `uninstall.sh`：

```bash
bash uninstall.sh                                  # 卸载用户级命令与服务，保留账号配置
bash uninstall.sh --purge                          # 同时删除本地账号配置目录
sudo env PATH="$PATH" bash uninstall.sh --system   # 卸载系统级服务与命令
```

卸载脚本会先停止后台服务，但不会主动断开当前已建立的校园网连接；如需在卸载前下线，请先运行 `ysu off`。
