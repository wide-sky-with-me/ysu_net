# 快速开始

[返回导航](Home.md) · [桌面客户端](Desktop-Client.md) · [命令行入口](CLI-Reference.md)

## 选择安装方式

- Windows 10 / 11 x64：下载桌面安装程序或便携 ZIP，见 [桌面客户端](Desktop-Client.md)。
- Ubuntu 22.04 及更新的 x86_64 桌面：可使用 `.deb` 或压缩包；服务器/无桌面环境使用命令行版。
- Linux 命令行：需要 Git、uv 和 Python 3.12 及以上；systemd 可选，没有用户总线时可使用前台守护。

发布基线为 [v0.1.0](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.1.0)，旧测试版保留供历史问题复现。安装包来自对应版本的 Assets，不要把仓库的 Source code ZIP 当成安装程序。

## Linux 命令行初次安装

```bash
git clone https://github.com/wide-sky-with-me/ysu_net.git
cd ysu_net
bash install.sh
export PATH="$HOME/.local/bin:$PATH"
ysu config account
ysu service
ysu doctor
```

账号密码仅在本机交互输入，不要粘贴到反馈帖或命令参数。安装不会自动登录或启动重连；请保留源码目录与 `.venv`。接入校园网后手动确认连接：

```bash
ysu login
ysu status
ysu on
```

`ysu on` 启动的是自动重连服务，不等于已经认证成功。可选 `ysu boot on` 控制自启；没有 systemd 时采用 [无服务安装方式](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md#常见使用场景)。远端机器的下线、切换与停止操作先阅读其影响，不要在唯一连接通道上盲目试验。

完整前提、PATH、自启、系统级安装、离线安装及浏览器依赖见 [README](https://github.com/wide-sky-with-me/ysu_net/blob/main/README.md) 与 [使用说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md)。更新/卸载见 [迁移说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/migration.md)。

## 最小自检

先做本地诊断，再在校园网中分别检查连接、状态和下线；每次只改变一个条件。桌面版按 [对应版本的功能说明](https://github.com/wide-sky-with-me/ysu_net/blob/v0.1.0/docs/desktop.md#功能) 验证。遇到问题按 [排障页](Troubleshooting.md) 分流，反馈前先 [脱敏](Privacy-and-Reporting.md)。
