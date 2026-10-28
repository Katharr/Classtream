# Classtream Windows 局域网教学版

基于 [Mustafahubs/Classtream](https://github.com/Mustafahubs/Classtream) 的 Windows 教学部署版本。教师一键安装，学生通过固定 `/class` 网址直接观看，无需安装软件或证书。

## 快速开始

1. 教师机使用 Windows 10/11、Intel/AMD x64，连接教学局域网，并准备联网下载依赖或配套离线依赖包。
2. 下载本仓库 ZIP 并完整解压，双击根目录 **install.cmd**。自动准备 Python 3.14 x64、独立依赖环境、必要的微软 VC++ 运行库、网卡与防火墙。
3. 按提示设置教师密码；多网卡时选择学生可访问的教学网络；允许运行库或防火墙的管理员提示。
4. 登录自动打开的教师页，点击 **创建新课堂** 创建课堂，将面板里的 `http://教师当前IP:8080/class` 网址发给学生。
5. 学生用浏览器打开网址，输入姓名观看。

以后双击 **start.cmd** 上课，**stop.cmd** 下课。**check.cmd** 检查服务，停机后可用 **password.cmd** 改密。保持教师页在线。没有离线包时首次安装需要联网；首次密码、多网卡选择和管理员提示仍需教师操作。

下载慢或无法上网时，将配套的 `Classtream-Dependencies-Win64-Py314.zip` 解压，把其中 **offline 文件夹和 install.ps1** 一起放入本仓库的 **windows-lan** 目录，覆盖旧 `install.ps1`，再双击根目录 `install.cmd`。看到 `OFFLINE MODE` 即使用本地依赖。包内包含 Python、全部应用依赖、VC++ 运行库和可选 Caddy；只适用于 Windows x64 / Python 3.14。不要把 ZIP 原文件直接放进去，也不要复制其他教师的 `.venv` 或 runtime。

仓库只保存源码、脚本和说明，不上传依赖包。安装脚本自动检测 `windows-lan/offline`：存在时校验并使用离线依赖，不存在时自动在线下载。离线目录及 ZIP、wheel、EXE 均已加入 Git 忽略规则。

## 中文课堂界面

学生输入姓名即可进入；画面和全屏优先，课堂讨论按需展开。教师端按课堂管理、共享屏幕和共享权限组织，低频参数位于“更多设置”。升级后重启服务并刷新教师页和学生页。

设计依据与验收范围见[中文界面设计方案](docs/中文界面设计方案.md)。

## 本版功能

- 每次启动检测本机有效 IPv4；单一新地址自动更新，多候选地址时提示选择。HTTP 模式运行中监测 IP 变化并刷新教师页链接。
- 学生使用固定 `/class` 路径，课堂 token 更新后刷新同一网址即可。
- 修复局域网 HTTP 页面缺少 `crypto.randomUUID()` 和 Clipboard API 时的兼容问题。
- HTTP 教师后台仅允许回环访问；学生端不请求麦克风。屏幕、文字聊天与文件通过可信局域网使用。
- DXGI/GPU 桌面采集、Windows 高精度帧间等待、JPEG 免二次 WebSocket 压缩；不支持 DXGI 时回退 MSS。
- 默认 30 FPS 上限；JPEG 变化分块、独立光标和每客户端绘制确认，静态画面不重复发送整图。复用现有依赖，保留账户、课堂和共享权限；升级后教师与学生刷新页面。
- 可选 HTTPS/Caddy 模式保留在说明中；该模式需要另外解决浏览器证书信任。

HTTP 流量未加密，只用于可信教学局域网。学生知道固定网址即可进入当前课堂。本版不录制或同步传输系统声音，默认 HTTP 不提供麦克风发言。

## 使用说明

- [教师端部署与使用](windows-lan/教师端说明.md)
- [学生观看说明](windows-lan/学生端说明.md)
- [完整配置、HTTPS、迁移与排查](windows-lan/README.md)
- [真机验收单](windows-lan/真机验收.md)
- [上游原版说明](README.upstream.md)

## 源码与复现

上游源码保留在 `app/`。本次已验收的部署与适配代码位于 `windows-lan/`，其安装入口锁定安装 PyPI 的 Classtream 1.0.1 和依赖，再加载本仓库适配层，保持与已测试教学包一致。根目录 `.cmd` 是对应入口。原版 `classtream` CLI 的行为见上游说明。

仅使用 Python 标准库即可生成轻量同事分享包：

```powershell
python tools/build_windows_share.py
```

输出 `dist/Classtream-LAN-Share.zip` 和 SHA-256。构建采用文件白名单和独立默认配置，不携带 runtime、账户/课堂数据库、上传文件、私钥、.venv 或 Caddy 可执行文件；Caddy 仅在选择 HTTPS 后按需下载。

开发验证（安装应用依赖后额外安装测试客户端；Node.js 仅用于开发测试，不是教学部署依赖）：

```powershell
python -m pip install -r windows-lan/requirements-lock.txt httpx==0.28.1
python tests/verify_windows_adapter.py
python tests/verify_fast_capture.py
```

测试使用临时数据库。真实屏幕采集、另一台学生机、全班负载和完全空白 Windows 的系统级首装需按验收单检查。

维护者制作离线依赖包：在 Windows x64 / Python 3.14 下用 `python -m pip wheel --wheel-dir wheels -r windows-lan/requirements-lock.txt pip==26.2.2` 准备 wheel，再将固定版本的 Python、VC++、Caddy 官方安装文件放入 installers 目录，运行 `python tools/build_offline_dependencies.py --wheels wheels --installers installers`。构建器校验固定哈希并生成逐文件 SHA-256 清单。离线二进制文件不提交 Git，按配套 ZIP 分发；安装器可用 `-DependenciesOnly` 只准备和检查依赖，供临时目录验证，不配置网络、防火墙、密码或启动服务。

## 许可证

上游 Classtream 使用 [MIT 许可证](LICENSE)，保留原作者版权声明。新增部署脚本和适配层见 [windows-lan/LICENSE](windows-lan/LICENSE)。DXcam/comtypes 由 pip 安装，Caddy 相关许可证和校验记录在 `windows-lan/bin/`。
