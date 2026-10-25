# 2026-10-26 构建缓存清理记录

[开发说明](development.md) · [桌面验收导航](desktop-acceptance.md) · [项目构建约束](../AGENTS.md#构建执行位置)

## 范围与实际结果

用户要求清理构建垃圾、整理文档并提交改进。先按绝对路径盘点、核对所有权及无链接/重解析点，再执行22个精确目标；没有整删 build/dist、使用 git clean、跟随链接或停止现用客户端。

共删除 **7,520,497,617逻辑字节（约7.52 GB）**，不是物理可用空间实测值：

- Windows 独立退役构建 run 的 cargo-target、registry、索引锁、临时文件及编译源码快照：6,555,219,818字节。
- Linux 旧公开源码/依赖传输包、重复云端 ZIP/解包程序、前端 dist 与 Vite/Vitest 缓存：164,937,058字节。
- Linux Cargo registry 与缓存索引，在源码/依赖静态审阅完成后删除：800,340,741字节。

所有构建/产品测试继续只在 GitHub Actions；清理没有调用本机 Cargo、Rust 或前端生产构建，也没有为了清缓存重建软件。

## 保护与保留

现用 Windows 安装和三个真实 AppData 资料根不在删除集合。只核对公开安装程序哈希，未读取或备份真实配置正文，也未对运行中持续变化的 WebView 目录声称字节不变。当前程序仍为已验收云端包的 NSIS 载荷，SHA256 为 `0CF4CE3B426430082411B3BD4EA559367027844130F407F4C110E2B6519C91A7`；清理未关闭客户端、下线或重新登录。

保留正式发行资料、Git 对象/暂存区、SDK本体与二进制、Python/项目环境、签名相关保护目录，以及必要验收 JSON/摘要清单、云端 run/commit/artifact 身份、最新安装器和明暗原生截图、最终动效视频/采样证据。没有读取生产私钥或密码，也不能据此声称整个 build 内从未存在秘密。

删除的中间源码归档仅保留当时摘要清单；当前代码另已提交推送并有云端源码提交，但不把清单当作可恢复每份历史未提交工作树的完整备份。带日期历史报告中“保留”的旧应用备份已按此前用户指示删除，见[实际部署后的清理说明](windows-connection-motion-2026-10-25.md#临时资料与证据)，不改写历史当时结论。

## 本次证据

以下均是本机审计回执，不属于客户端分发或秘密备份；最后安装器仍保留一份公开副本，已复核与原云端安装器摘要相同。

```text
build/maintenance-20261025/cleanup-plan.json
build/maintenance-20261025/windows-input-evidence/
build/maintenance-20261025/windows-cleanup-receipt.json
build/maintenance-20261025/linux-generated-cleanup-receipt.json
build/maintenance-20261025/linux-registry-cleanup-receipt.json
```

媒体第二阶段只做候选盘点，没有执行批量历史截图裁剪，避免把唯一验收证据当垃圾删除。
