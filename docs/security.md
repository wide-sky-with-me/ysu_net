# 隐私与脱敏规则

[返回首页](../README.md) · [文档导航](README.md) · [支持与反馈](../SUPPORT.md) · [安全问题报告](../SECURITY.md)

**YSU Net** 仅在本机存储校园网配置，并在你主动连接、查询或执行后台自动重连/续约时与校园网门户及统一身份认证通信，不附带任何远程遥测或第三方统计上报。

---

## 本地凭据保护

- **最小权限存储**：主配置 `config.json`、多账号池 `config.accounts.json`、无感自动续约配置 `config.nosense.json` 与自助服务会话缓存 `self-session.json` 在 Unix 系统上均按 `0600` 权限创建（目录按 `0700` 创建），仅当前用户可读写。
- **前端与日志隔离**：桌面客户端推送给前端界面的状态快照不包含明文密码；普通运行日志与本地调试记录仅保留脱敏的状态与错误分类，不写入密码、Cookie 或票据参数。
- **更新安全校验**：桌面端在线更新仅信任官方 GitHub Releases 的 HTTPS 下载地址，并强制校验内置 Minisign 公钥签名。

---

## 公开反馈的脱敏清单

在提交公开 Issue、Discussion 或 Pull Request 前，请对照以下清单检查正文、日志片段与截图：

1. **移除账号与身份信息**：将真实学号/工号、姓名、手机号或邮箱替换为 `<ACCOUNT>`、`<NAME>` 等占位符，切勿粘贴任何明文或密文密码。
2. **移除会话与票据**：不要粘贴 Cookie（如 `CASTGC`、`SESSION`、`SAM_OPERATE_COOKIE`）、`ticket`、`sessionId`、`userIndex` 或包含上述查询参数的完整 URL。
3. **移除设备与个人路径**：将本机 IP、MAC 地址、主机名、Wi-Fi SSID 或宿舍位置替换为 `<IP>`、`<MAC>`；将个人主目录路径统一简化为 `~/`。
4. **切勿直接上传原始文件**：不要上传 `config.json`、`config.accounts.json`、`config.nosense.json`、`self-session.json`、浏览器 HAR 抓包、`--raw` 原始输出或未裁剪打码的整屏截图。
5. **截图打码**：如需提供界面截图，请先裁剪无关区域，并使用不透明色块完全覆盖学号、姓名、IP 与 MAC 地址后再导出图片。

如发现凭据泄漏或安全缺陷，请通过 [GitHub 私密漏洞报告](https://github.com/wide-sky-with-me/ysu_net/security/advisories/new) 联系维护者（详见 [SECURITY.md](../SECURITY.md)）。
