# CAS 回调风险提示只检查文档文本

日期：2026-10-28。状态：修复源码已实施，云端与真实复测待执行；当次结果归[0.2.3 发布记录](../../../../docs/desktop-release-0.2.3.md)。范围：三平台共用 Rust API 登录表单及 CAS 回调；Browser 已依据页面交互状态处理，Python 没有这项整页字符串拒绝。

## 证据与选择

候选 6b80a80 在 21 可查询在线和离线，登录在 cas_callback / interaction_required 停止；同机 Shell 随后成功恢复原连接。只读探测确认正常门户主页面与无票据回调页均返回 HTTPS 同源 HTTP 200，其脚本含 noSupport，文档文本没有风险词。旧 risk_page 对原始 HTML 子串扫描，将正常资源引用当成了服务拒绝。

使用已有 scraper 解析 HTML，迭代收集文档文本，排除 script、style、noscript、template 与注释 / 属性；保留原风险词及真实提示拒绝。它不是完整 CSS 可见性计算，不执行脚本。回调仍必须成功返回配置门户同源；之后必须通过流程节点、动作业务信封和独立身份 / 服务查询，文档文本无风险词本身不能证明登录成功。来源异常与提示拒绝分别保留 redirect_blocked / business_rejected 分类，不记录页面或会话。

未选择删除全部风险保护，因为真实挑战仍应在服务动作前停止；未选择只删除 noSupport，因为相同问题也会发生在脚本内的其他提示字典；未选择复用账户展示的截断文本，因为 2048 字符上限会漏掉文档尾部挑战。新增文本缓冲受原响应大小限制，迭代遍历保持深层 DOM 的栈安全。

## 实现与验证

实现位于[protocol.rs](../../../../desktop/crates/ysu-auth/src/protocol.rs)。[合同回归](../../../../desktop/crates/ysu-auth/src/live_contract_tests.rs)把正常 noSupport 脚本放入完整 CAS / 登录 / 退出夹具，另保留真实标题 / 文本 / 跨标签提示的拒绝及零服务提交断言；[夹具](../../../../desktop/crates/ysu-auth/src/tests.rs)仅新增可配置回调 body。当前文档归[桌面语义](../../../../docs/tauri-desktop.md#离线-captive-与-cas-表单开发源码云端待验)。

样本来自服务器内存分类，仅导出固定布尔值，没有保存真实页面、Cookie、账号或 URL 参数。真实首轮失败已恢复原移动连接和守护；修复的云端与真实验证必须分别记录，不能用只读页面分类冒充修复后登录通过。
