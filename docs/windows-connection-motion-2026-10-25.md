# 2026-10-25 云端连接动效包本机部署验收

[源码阶段验收](desktop-connection-motion-2026-10-25.md) · [现行界面规则](rust-desktop-design.md) · [构建工作流](../.github/workflows/tauri.yml) · [构建位置约束](../AGENTS.md#构建执行位置)

本页是源码阶段之后的实际部署证据。仍为 0.2.1 开发构建，不是新的正式 Release；没有打标签或访问更新签名材料。

## 云端来源

用户再次明确“不要本地编译”后，停止本机编译尝试并核实无自有编译进程；之后没有再启动本地 Cargo/Rust 或前端生产构建。此前本机尝试失败，未用于安装。编译位置限制已写入项目规则，云端失败不允许回退本地编译。

源码快照提交到独立分支 `build/connection-motion-20261025-134517`，未移动当前开发分支或改动用户暂存区。最终提交 `b8ccec867a4e947f5ca0c04383b9378b320e3cb4` 的 [GitHub Actions 40202126204](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40202126204) 全部通过：Windows、Linux、macOS arm64/x64。分支构建不进入发布签名或 Release 步骤。

前两次云端 Linux 浏览器验收分别暴露新脚本的 CI 输出目录不匹配、云端缺少 ffmpeg。只修正工作流目录、证据保留路径及云端编码器依赖，没有删除或放宽动效断言。最终云端功能、构建、浏览器和原生验收通过。

Windows artifact `12601484769` 经 GitHub ZIP 摘要校验后安全解包；确认 run、branch、commit、Windows job 和当前源码快照一致。安装辅助器拒绝非成功云端产物，未使用本机失败构建的缓存二进制。

```text
GitHub artifact ZIP SHA256: 6f3b7fa34eb7cbf18851e62f35254dd670a37acd340995fed13a6d89f5b2359e
云端 NSIS 安装包 SHA256: f5e916c6ad6200655d84212f83402bfa4fb37493dbb96519bde127468b0b1bfe
安装后程序 SHA256: 0CF4CE3B426430082411B3BD4EA559367027844130F407F4C110E2B6519C91A7
```

## 安装与原生结果

安装载荷只允许 Tauri 的 UNK→NSS 包类型标记差异，并校验完整预期字节哈希。更新前后308个现用资料文件字节相同，账号、偏好及快捷方式保留；主题仍为 system、强调色仍为 blue。没有自动启动正常资料、真实登录或下线。

实际安装程序在全新隔离 Demo 资料中启动，先确认 Demo，再通过受控在线快照检验真实 WebView2 渲染：深色509帧、浅色513帧跨完整光环周期，图标、SVG、标题及卡片最大几何变化均为0；双环时间与相位推进、同状态不重启、侧栏不循环、无溢出、光环不跨入标题。动态减少动效立即停止并可恢复；离线与未知没有在线循环。在线快照为渲染夹具，**不代表真实校园网认证或实时流量**。

首次原生观察脚本把合法的 undefined 结果误读为 value；仅修正 CDP 适配并使用新隔离目录复测，产品源码/二进制未改动。成功后自有窗口与回环调试监听均关闭，正常资料未打开。原生系统最小化和长稳未新增覆盖；源码阶段的隐藏事件测试仍是模拟。

## 临时资料与证据

按用户确认，在完整验收与证据复制后，预览、复核精确绝对路径和无重解析点，再删除本次临时旧程序/配置备份及两个隔离测试目录；共839文件、118406007字节，空父目录也已清理。删除后再次确认308个现用文件哈希及当前安装程序未变。备份不再保留，不应据清理前报告假定可恢复。

旧安装辅助器的 `localRebuild` 字段是开发部署命名遗留，不能用来判断编译位置；本次来源以已核对的云端 run、commit、artifact 摘要和云端安装包为准。

```text
build/cloud-connection-motion-20261025/：源码快照、云端运行/失败日志、已校验产物
build/connection-motion-20261025/cloud-build-state.json：云端产物身份
build/connection-motion-20261025/windows-install-state.json：安装与资料保留
build/connection-motion-20261025/windows-native-ui-state.json：原生动效复测
build/connection-motion-20261025/windows-final-verification.json：清理前完整复核
build/connection-motion-20261025/temporary-backup-cleanup.json：临时资料清理后完整性
 dist/connection-motion-20261025/windows/：复制后的云端安装器及明暗原生截图
```
