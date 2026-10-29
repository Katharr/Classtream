# Classtream Windows 局域网教学版

基于 [Mustafahubs/Classtream](https://github.com/Mustafahubs/Classtream) 的 Windows 教学部署版本。教师一键安装，学生通过固定 `/class` 网址直接观看，无需安装软件或证书。

## 快速开始

1. 教师机使用 Windows 10/11、Intel/AMD x64，连接教学局域网。
2. 下载 Release 中的 **Classtream-LAN-版本号-Win64.zip**，完整解压后双击根目录 **start.cmd**。主程序包不含依赖，首次自动联网准备 Python 3.14 x64、独立依赖环境和必要的微软 VC++ 运行库。
3. 按提示设置教师密码；多网卡时选择学生可访问的教学网络；允许运行库或防火墙的管理员提示。
4. 登录自动打开的教师页，在顶部课堂名菜单中选择 **创建新课堂**，点击右上角 **邀请学生**，将 `http://教师当前IP:8080/class` 发给学生。
5. 学生用浏览器打开即可观看，系统自动分配昵称。

以后双击 **start.cmd** 上课，关闭启动窗口或按 Ctrl+C 下课；再次双击自动回收本项目旧进程并重启。保持教师页在线。没有离线包时首次安装需要联网；首次密码、多网卡选择和管理员提示仍需教师操作。维护脚本位于 `windows-lan/`。GitHub 自动生成的 Source code 是开发源码，教师部署请使用版本化 Win64 附件。

下载慢或无法上网时，将配套的 `Classtream-Dependencies-Win64-Py314.zip` 解压，把其中 **offline 文件夹和 install.ps1** 一起放入本仓库的 **windows-lan** 目录，覆盖旧 `install.ps1`，再双击根目录 `start.cmd`。看到 `OFFLINE MODE` 即使用本地依赖。包内包含 Python、全部应用依赖、VC++ 运行库和可选 Caddy；只适用于 Windows x64 / Python 3.14。不要把 ZIP 原文件直接放进去，也不要复制其他教师的 `.venv` 或 runtime。

仓库只保存源码、脚本和说明，不上传依赖包。安装脚本自动检测 `windows-lan/offline`：存在时校验并使用离线依赖，不存在时自动在线下载。离线目录及 ZIP、wheel、EXE 均已加入 Git 忽略规则。

## 中文课堂界面

学生打开课堂即可进入，由系统随机分配小浣熊、小熊猫等 20 种可爱动物昵称，不提供自定义或改名入口。同一课堂中刷新、重连和切换屏幕保持昵称，超过 20 人时添加数字后缀避免重名；服务重启后重新分配。课堂讨论默认允许发言、面板默认收起，教师可全体禁言或单独禁言学员；禁言期间仍可观看和阅读讨论，教师可继续发言。解除全体禁言保留单独禁言，新课堂恢复允许讨论。共享画面占据主区域；顶部课堂名提供课堂管理，在线人数打开成员列表，设置、讨论按需展开。放大、缩小、适应窗口分别显示在底部。升级后重启服务并刷新教师页和学生页。

课堂行为与使用说明见[课堂使用与快捷键](docs/课堂使用与快捷键.md)。

教师端提供“冻结学生画面 / 恢复学生画面”和“更多”快捷操作搜索。按 `?` 或进入“设置 → 快捷键设置与帮助”查看、修改网页按键，管理 Windows 全局冻结/解除。默认登录并连接课堂后自动启用，在 PPT、IDE 或浏览器后台也可使用；`Ctrl+Alt+Shift+H` 冻结、`Ctrl+Alt+Shift+R` 解除冻结，占用时必须换键。启用偏好及按键会保存在本机，服务重启后重新登录连接课堂即可恢复；手动关闭也会记住。完整说明见[课堂使用与快捷键](docs/课堂使用与快捷键.md)。

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

### 本机开发：源码与运行数据分离

本地维护工作区的布局及启动关系见 [目录结构与维护约定](docs/目录结构与维护约定.md)。`windows-lan/` 是教学适配层的唯一源码；旁边的 `teacher/` 只保存本机数据。工作区根目录只保留一个 `start.cmd` 日常入口，直接加载本仓库源码；先检查端口并清理本项目残留，再启动。关闭窗口停止，再次双击重启，修改后刷新页面。

启动器支持环境变量 `CLASSTREAM_HOME`，用于指定 `config.json`、`.venv/`、`runtime/` 和 `bin/caddy.exe` 所在目录；未指定时维持原便携包布局。安装、网卡跟随、改密及防火墙设置均使用这个目录。前端资源和适配脚本始终从源码目录加载。

上游源码保留在 `app/`。本次已验收的部署与适配代码位于 `windows-lan/`，其安装入口锁定安装 PyPI 的 Classtream 1.0.1 和依赖，再加载本仓库适配层，保持与已测试教学包一致。根目录 `.cmd` 是对应入口。原版 `classtream` CLI 的行为见上游说明。

仅使用 Python 标准库即可生成轻量同事分享包：

```powershell
python tools/build_windows_share.py
```

输出 `dist/Classtream-LAN-Share.zip` 和 SHA-256。构建采用文件白名单和独立默认配置，不携带 runtime、账户/课堂数据库、上传文件、私钥、.venv 或 Caddy 可执行文件；Caddy 仅在选择 HTTPS 后按需下载。

开发验证（安装应用依赖后额外安装测试客户端；Node.js 仅用于开发测试，不是教学部署依赖）：

```powershell
python -m pip install -r windows-lan/requirements-lock.txt
python -m pip install --target .dev-deps httpx2==2.16.0
python tools/run_checks.py
```

工具用途、浏览器测试和压力测试见 [维护工具](tools/README.md)。测试使用临时数据库。真实屏幕采集、另一台学生机、全班负载和完全空白 Windows 的系统级首装需按验收单检查。

维护者制作离线依赖包：在 Windows x64 / Python 3.14 下用 `python -m pip wheel --wheel-dir wheels -r windows-lan/requirements-lock.txt pip==26.2.2` 准备 wheel，再将固定版本的 Python、VC++、Caddy 官方安装文件放入 installers 目录，运行 `python tools/build_offline_dependencies.py --wheels wheels --installers installers`。构建器校验固定哈希并生成逐文件 SHA-256 清单。离线二进制文件不提交 Git，按配套 ZIP 分发；安装器可用 `-DependenciesOnly` 只准备和检查依赖，供临时目录验证，不配置网络、防火墙、密码或启动服务。

## 许可证

上游 Classtream 使用 [MIT 许可证](LICENSE)，保留原作者版权声明。新增部署脚本和适配层见 [windows-lan/LICENSE](windows-lan/LICENSE)。DXcam/comtypes 由 pip 安装，Caddy 相关许可证和校验记录在 `windows-lan/bin/`。
