# 主题配色修订验收

日期：2026-10-17。范围：三平台共用的 Svelte 色板与配色回归；外部参考及当前取舍见[设计说明](rust-desktop-design.md)。不改变布局、字体、文案、偏好格式或认证/账号/轮换行为。

## 调整与范围

将各主题的带色背景、正文、箭头和阴影收回为稳定中性灰阶，取消工作区光晕和品牌渐变；强调色仅用于品牌、关键操作、焦点及选中反馈。浅色为浅灰画布和白卡片，深色为中性石墨分层。重新校准既有六种强调色，默认标识仍为 `teal`，兼容已保存选择；成功、警告和错误色值保持原样。

产品源码只改[基础色板](../desktop/src/app.css)、[强调色样式](../desktop/src/accents.css)和[色标定义](../desktop/src/lib/accents.ts)。两项配色脚本更新目标色值，增加中性表面不随色改变、无背景图层、开启开关对比、次级文字/强调文字悬停对比和实际未选运营商悬停检查；原有行为断言与 4.5:1 / 3:1 标准保留。组件、协议、演示逻辑及原生源码的[范围核对](../dist/theme-refinement-validation/scope-check.json)通过。

## 已完成验证

执行 `npm --prefix desktop run check`、`test`、`test:build`、`build`：零错误、零警告，82 项单元测试及 5 项构建入口测试通过，见[前端日志](../dist/theme-refinement-validation/frontend-build.log)。随后仅调整 CSS 悬停色与测试脚本，再生产构建；最终样式及构建日志见[浏览器首轮日志](../dist/theme-refinement-validation/browser-validation.log)。

在 `with_server.py` 管理的 `http://127.0.0.1:1423/` 生产预览中实际执行：

- `color_palette_preview.py --accent <各色> --output dist/theme-refinement-validation/palettes/<各色>`：六色各 72/72，共 432 项通过；覆盖浅深模式、文字/控件、选中与未选中悬停、紧凑窗口。最低文字对比 4.637:1，最低非文字对比 3.152:1。
- `accent_themes_preview.py --output dist/theme-refinement-validation/accents-accepted`：186/186，包括原有选色/保存失败/系统模式/键盘/强制色及新增中性色约束；见[选色报告](../dist/theme-refinement-validation/accents-accepted/accent-ui-report.json)。
- `ui_review_preview.py --output dist/theme-refinement-validation/review`：32/32；`clean_desktop_preview.py --output dist/theme-refinement-validation/pages`：74 个布局与 12 对文字对比通过，见[页面回归](../dist/theme-refinement-validation/review/review-report.json)和[布局报告](../dist/theme-refinement-validation/pages/clean-desktop-report.json)。

实际看图复核[默认浅色](../dist/theme-refinement-validation/palettes/teal/connection-light-1000.png)、[默认深色](../dist/theme-refinement-validation/palettes/teal/connection-dark-1000.png)、[海蓝连接](../dist/theme-refinement-validation/palettes/blue/connection-light-1000.png)、[海蓝设置](../dist/theme-refinement-validation/accents-accepted/settings-blue-light.png)、[玫瑰深色设置](../dist/theme-refinement-validation/accents-accepted/settings-rose-dark.png)、[琥珀深色](../dist/theme-refinement-validation/palettes/amber/connection-dark-1000.png)及[紫罗兰浅色](../dist/theme-refinement-validation/palettes/violet/connection-light-1000.png)。

`packaging/tauri_web_smoke.py --url http://127.0.0.1:1423/ --browser /usr/bin/google-chrome --output dist/theme-refinement-validation/web-accepted` 通过，见[浏览器报告](../dist/theme-refinement-validation/web-accepted/browser-report.json)与[复测日志](../dist/theme-refinement-validation/web-final.log)。所有浏览器报告均无页面错误、控制台错误和外部请求，网页存储为空。[背景图层实测](../dist/theme-refinement-validation/background-layer-evidence.json)确认多层结果为 `none, none`。

Linux release 构建通过：`YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true node desktop/scripts/desktop.mjs --no-bundle`，见[原生构建日志](../dist/theme-refinement-validation/native-build.log)。将 release 二进制复制为[本轮验收程序](../dist/theme-refinement-validation/bin/ysu-net)，在无网络 SDK 的 `dbus-run-session` / `xvfb-run` 中执行 `packaging/tauri_smoke.py --capture-desktop`，退出码 0。[原生验收报告](../dist/theme-refinement-validation/native/acceptance.json)为 `ok:true`，偏好保存/磁盘重读/非法写入不变/恢复、IPC、账号、窗口重建、后台托盘操作及进程清理通过，无认证旁车。完整配色矩阵来自 Chrome，不据此声称原生全状态视觉、辅助功能或真实桌面托盘实机验收。

原生构建前后六个前端文件的 SHA-256 相同，见[一致性记录](../dist/theme-refinement-validation/native-assets-check.json)。[色板差异](../dist/theme-refinement-validation/palette-changes.diff)、[源码哈希](../dist/theme-refinement-validation/palette-source-sha256.json)及[布局/协议未扩散核对](../dist/theme-refinement-validation/palette-only-check.json)保存实际修改范围。

## 失败与复测

候选预检发现浅色青色与琥珀在选中底上的文字对比分别为 4.429:1、4.245:1；加深这两个自定义强调值后再进入构建验收，未降低阈值。通用悬停底也改为更浅的中性灰，以保持强调文字可读。[候选记录](../dist/theme-refinement-validation/candidate-contrast.json)保留失败数据，不冒充最终色值。

首轮选色回归为 174/186，失败的均为新增无背景光晕检查：测试错误地要求 `backgroundImage` 整串等于 `none`，而多层无图背景会被浏览器序列化为 `none, none`。修正为逐层检查全部为 `none`，仍排除任何图片/渐变；产品样式未变，复测 186/186，见[复测日志](../dist/theme-refinement-validation/browser-accepted.log)。

同轮 smoke 首次遗漏显式 `--url`，误用脚本默认 1420 而超时；此前色板、选色、页面与布局均已通过。仅为 smoke 指定正确 1423 地址后复测，保留首次日志，不重复刷新已通过成绩。

## 验证边界

所有浏览器场景使用构建后的离线样例，未读取真实账户配置或发起校园认证。Windows/macOS 原生、系统自启实机、长期运行及性能比较未执行；共享源码不等同于对应平台实机通过。Shell、Qt 与 Rust 业务未变，未重复其单元回归；未安装、发布、提交或推送。既有验收目录、截图与哈希清单保持原貌。
