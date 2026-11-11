# 软件内签名更新

[返回首页](../README.md) · [文档导航](README.md) · [桌面客户端指南](wiki/Desktop-Client.md) · [版本更新与迁移](migration.md)

桌面客户端在 **Windows** 与 **macOS** 平台支持软件内在线检查、下载与验证更新；**Linux `.deb`** 与 **Python CLI** 则分别通过系统包管理器与 `install.sh` 升级。

---

## 各平台更新方式

| 平台 | 更新方式 | 说明 |
| --- | --- | --- |
| **Windows 10/11 x64** | 软件内检查更新 / 手动运行安装包 | 在侧栏「关于」页点击 **检查更新**，确认后自动下载、验签并启动安装器 |
| **macOS 13.5+ (arm64 / x64)** | 软件内检查更新 / 手动替换 `.dmg` | 在侧栏「关于」页点击 **检查更新**，确认后自动下载、验签并更新应用 |
| **Ubuntu 22.04+ x64** | `.deb` 系统包升级 | 从 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 下载新 `.deb`，执行 `sudo apt install ./YSU-Net_0.3.0_linux-x64.deb` |
| **Linux Python CLI** | 源码与安装脚本更新 | 在仓库目录执行 `ysu stop && git pull --ff-only && bash install.sh && ysu on` |

---

## 签名校验与安全机制

1. **手动触发**：客户端不会在后台静默下载或强制重启安装更新，所有更新检查与安装均由用户在「关于」页主动点击触发。
2. **Minisign 公钥验签**：每个正式发布的更新包都附带由维护者私钥生成的 Minisign 签名（`.sig`），并绑定目标版本号。客户端内置固定更新公钥（配置于 [`desktop/src-tauri/tauri.conf.json`](../desktop/src-tauri/tauri.conf.json)），下载后必须通过公钥签名与版本校验才会执行安装。
3. **固定可信域名**：更新清单（`latest.json`）与安装包仅允许从项目官方 GitHub Releases 的 HTTPS 地址下载。

---

## 差分传输与自动回退

为了减少升级下载体积，Windows 与 macOS 客户端支持**条件差分更新（`bsdiff40`）**：

- 当本机缓存有上一版本的完整安装包、且当前 Release 提供了对应的签名差分补丁（`.bsdiff`）时，客户端会优先下载体积更小的差分补丁。
- 下载完成后，客户端先校验差分补丁签名，在本地还原出新版本完整安装包，再对还原后的完整安装包执行第二次 Minisign 签名与 SHA256 校验。
- **一次自动回退**：如果本机没有旧版缓存、当前版本未提供差分补丁、或差分下载/还原失败，客户端会自动回退为下载并校验完整安装包，确保升级顺畅。
