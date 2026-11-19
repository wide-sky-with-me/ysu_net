# 软件内签名更新

[返回首页](../README.md) · [文档导航](README.md) · [桌面客户端指南](wiki/Desktop-Client.md) · [版本更新与迁移](migration.md)

桌面客户端在 **Windows** 与 **macOS** 平台支持软件内在线检查、下载与验证更新；**Linux `.deb`** 与 **Python CLI** 则分别通过系统包管理器与 `install.sh` 升级。

---

## 各平台更新方式

| 平台 | 更新方式 | 说明 |
| --- | --- | --- |
| **Windows 10/11 x64** | 软件内在线更新 / 手动运行安装包 | 启动时自动后台检查并弹窗提醒（可在「设置」开关自动检查或自动下载安装），也可在「关于」页手动点击 **检查更新** |
| **macOS 13.5+ (arm64 / x64)** | 软件内在线更新 / 手动替换 `.dmg` | 启动时自动后台检查并弹窗提醒（可在「设置」开关自动检查或自动下载安装），也可在「关于」页手动点击 **检查更新** |
| **Ubuntu 22.04+ x64** | `.deb` 系统包升级 | 从 [GitHub Releases Latest](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 下载最新 `.deb`，执行 `sudo apt install ./YSU-Net_*_linux-x64.deb` |
| **Linux Shell CLI (`ysu`)** | 源码与安装脚本更新 | 在仓库目录执行 `ysu stop && git pull --ff-only && UV_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple" bash install.sh && ysu on` |

---

## 签名校验与安全机制

1. **可控的更新策略**：默认开启启动后台单次检查并弹窗提醒（支持「立即更新」「暂不提醒」与「忽略此版本」）；自动下载安装默认关闭，仅当用户在「设置 → 外观与启动」主动开启或在弹窗/「关于」页确认后才执行安装，且从不强制中断当前会话重启。
2. **Minisign 公钥验签**：每个正式发布的更新包都附带由维护者私钥生成的 Minisign 签名（`.sig`），并绑定目标版本号。客户端内置固定更新公钥（配置于 [`desktop/src-tauri/tauri.conf.json`](../desktop/src-tauri/tauri.conf.json)），下载后必须通过公钥签名与版本校验才会执行安装。
3. **固定可信域名**：更新清单（`latest.json`）与安装包仅允许从项目官方 GitHub Releases 的 HTTPS 地址下载。

---

## 差分传输与自动回退

为了减少升级下载体积，Windows 与 macOS 客户端支持**条件差分更新（`bsdiff40`）**：

- 当本机缓存有上一版本的完整安装包、且当前 Release 提供了对应的签名差分补丁（`.bsdiff`）时，客户端会优先下载体积更小的差分补丁。
- 下载完成后，客户端先校验差分补丁签名，在本地还原出新版本完整安装包，再对还原后的完整安装包执行第二次 Minisign 签名与 SHA256 校验。
- **一次自动回退**：如果本机没有旧版缓存、当前版本未提供差分补丁、或差分下载/还原失败，客户端会自动回退为下载并校验完整安装包，确保升级顺畅。
