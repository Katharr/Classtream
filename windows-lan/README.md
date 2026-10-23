# Classtream 局域网教学包 · HTTP 直接观看版

教师首次解压后双击 `install.cmd`；日常双击 `start.cmd`。学生打开 `http://教师机IP:8080/class`，输入姓名即可观看，不安装软件、证书或浏览器插件。默认 10 FPS。

操作说明见 `教师端说明.md`、`学生端说明.md`、`真机验收.md`。首次安装会识别各自电脑的地址，多网卡时需要选择。分享包中的 `192.0.2.1` 是占位地址，安装时自动替换，不要发给学生。

## 安装与运行

- 教师环境：Windows 10/11、Intel/AMD x64、桌面会话、现代 Chrome/Edge。学生使用现代浏览器。
- 首次安装需联网访问 Python.org、PyPI 及其下载站，缺少运行库时还需访问微软下载站。安装器优先复用已有 Python 3.14 x64，没有时下载固定 Python 3.14.9 官方安装程序并核对 SHA-256，为当前 Windows 用户安装；在本目录 `.venv` 建立独立环境。
- `requirements-lock.txt` 固定应用依赖，安装器固定 pip 26.2.2 并核对下载哈希。不修改原版 Classtream 安装文件。安装后会验证原生库导入和 Classtream 适配；OpenCV 无法加载时自动下载微软官方 VC++ x64 运行库，验证微软数字签名后安装，可能另需一次管理员确认。
- 安装器配置防火墙时需要 Windows 管理员确认，不关闭防火墙。学校策略禁止时需网管协助。
- 全新部署按提示设置教师密码；已有数据库保留原账户和密码。首次密码未设成功会阻止启动；误点 start.cmd 时也会引导安装。日常启动不需要联网或管理员权限。
- 不安装 Windows 服务，不设置开机自启。保持启动窗口和教师管理页在线。

## 默认 HTTP 模式

`config.json` 中 `mode` 为 `http`。一个 Python 服务监听所有本机 IPv4 的 `8080` 和回环地址 `127.0.0.1:8000`。教师打开 `http://127.0.0.1:8000/?host=admin`，学生打开局域网 `/class`。防火墙仅向 `LocalSubnet` 来源开放学生端口，不开放教师后台端口。

HTTP 模式的教师登录与管理 HTTP/WS 请求只允许回环来源，不信任 `X-Forwarded-For`。课堂画面、消息和文件通过 HTTP 明文传输，只用于可信教学局域网。知道固定网址的人可以进入当前课堂；这不是额外的课堂口令系统。

浏览器适配使用 `getRandomValues()` 生成 UUID v4，会话启动不依赖 `randomUUID()`；复制按钮兼容没有 Clipboard API 的浏览器，最后可手动复制。HTTP 模式隐藏语音区和发言按钮，不初始化麦克风。保留原版文字聊天、文件传输和屏幕权限功能，以真机验收为准；录制和同步传输系统声音不属于本包功能。

`/class` 每次打开读取当前课堂 token，页面和适配脚本不缓存。教师生成新课堂后，学生刷新相同网址。重新生成 token 不会阻止知道 `/class` 的人再次进入。

## 可选 HTTPS 模式

停机后把 `mode` 改为 `https`，保留 `https_port: 8443`，重新运行 `install.cmd`。缺少 Caddy 时安装器按需下载 2.11.7 官方 ZIP，校验 SHA-512；启动时还校验 exe SHA-256。默认分享 ZIP 不携带 Caddy 可执行文件，HTTP 不需要它。

学生入口变为 `https://教师IP:8443/class`，屏幕和语音使用 WSS，恢复原版语音入口。教师仍可用本机地址。Caddy 自动生成本地 CA；`runtime/student-setup.zip` 可用于学生或网管信任证书，导入后重启浏览器。**此模式不承诺学生零配置**；完整功能且无证书警告需学校另配域名与浏览器信任的证书。

切换模式不会删除数据或 CA。脚本创建或更新当前模式防火墙规则；旧模式规则保留，但没有对应监听就不提供服务。管理员可删除不再使用的本包规则。许可证和校验记录在 bin 目录。

## 迁移、备份与恢复

运行数据在 `runtime/data`。从旧 Classtream 迁移时先停止两套服务，且新数据库尚未创建，然后运行：

```powershell
.\.venv\Scripts\python.exe lan.py import-data --source "$env:USERPROFILE\.classtream"
```

已有目标数据库时导入器拒绝覆盖；请先备份，停机后将目标 `runtime/data` 改名保留，再导入。导入使用 SQLite 备份 API，包含已提交的 WAL，并复制 uploads；原目录保留。新电脑不要复制其他教师的 runtime 或 .venv；需要迁移个人课堂数据时再使用此功能。

停机后备份 `runtime/data`；HTTPS 另私下备份含 CA 私钥的 `runtime/caddy-data`。公开分享只用干净 ZIP，不能包含 `.venv`、runtime、数据库、上传文件或私钥。

恢复原版：停止本包，再运行原来的 `classtream`。原安装和数据目录保留，本包新数据不会回写原目录。建议网管设置 DHCP 地址保留；HTTP 模式会检测 IP 变化并更新链接，防火墙不再绑定某个旧 IP；公布新网址即可。

## 排查

`check.cmd` 检查页面、UUID 兼容脚本、WS/WSS 与管理接口限制；HTTPS 还严格检查证书链和 IP SAN。此检查不代替学生真机和全班负载验收。

| 现象 | 处理 |
| --- | --- |
| 8000 被占用 | 先停止旧 Classtream，或改 backend_port；不要结束不认识的进程。 |
| 8080 被占用 | 改 http_port，重跑安装入口更新防火墙，公布新网址。 |
| 学生打不开 | 核对网络与 IP，检查防火墙、访客 Wi-Fi/AP 隔离；跨子网需网管调整来源范围。 |
| 地址跳到 HTTPS | 使用完整 http:// 链接；学校强制仅 HTTPS 时交网管处理。 |
| 地址栏“不安全” | 是 HTTP 未加密提示，不是证书错误页。本模式不要求绕过证书拦截。 |
| 无课堂 / 教师离线 | 教师登录并保持页面在线，New Link 创建课堂后学生刷新。 |
| 姓名串用 | 教师用 127.0.0.1，学生用局域网 IP；共享电脑核对姓名。 |
| 画面卡顿 | 看 backend.log，检查共享权限；先用 10 FPS、JPEG 质量 50–70，逐步增加学生数。 |
| 旧 ready 标记 | 先 stop.cmd；确认无本包进程后才移除异常关机留下的 runtime/ready.json。 |
| 安装失败 | 看 runtime/install.log，网络恢复后重试；不清空课堂数据。VC++ 安装日志为 runtime/vc-runtime-install.log；Windows N 版如缺少媒体组件需补装系统 Media Feature Pack。 |

每个学生接收独立 JPEG 帧流，容量取决于画面变化、分辨率和网络。10 FPS 是分享包默认配置值，不保证所有学生实际帧率。

采集优先使用 DXcam 0.3.0 / Windows DXGI，按显示器真实坐标匹配输出；不支持或运行中失败时自动回退 MSS。新增依赖 comtypes 1.4.17 与 DXcam 均由安装入口自动安装。高帧率下使用 Python 高精度计时等待，避免 Windows asyncio 小额等待实际约 15.6 毫秒的问题；已压缩的 JPEG 不再叠加 WebSocket deflate。

设置 60 表示上限。发布测试在 2560×1600 桌面输出 1280×800、JPEG 质量 70 时，本机完整服务接收约 52 FPS（含预热），预热后约 56 FPS；这是本机测试，不代表学生物理网络或全班结果。该画面每个学生约需 65 Mbps，百兆出口不能承载多台这样的流。课件教学可先用 20–30 FPS；全班高帧率需要评估出口带宽与视频压缩传输，不能仅依靠提高配置值。

后端日志出现 Capture monitor=…: dxgi 表示使用新采集；MSS fallback 表示兼容回退。FPS 元信息附带采集/编码/发送耗时和真实新采集帧数，便于排查。

## 版本与来源

- Classtream 1.0.1：[原项目](https://github.com/Mustafahubs/Classtream)，MIT；由 pip 安装，适配层严格检查版本和代码特征，不支持直接升级。
- 自动安装 Python 3.14.9：[官方发布和 SHA-256](https://www.python.org/downloads/release/python-3149/)。已在 Python 3.14.3 x64 的全新虚拟环境中，31 项基础依赖禁用缓存下载并通过安装入口检查，另 2 项 GPU 采集依赖安装和整包回归通过。Python 3.14.9 官方安装程序已实际下载并核对哈希和签名；无 Python 的全新 Windows 系统首装仍需目标机验收。
- DXcam 0.3.0：[原项目](https://github.com/ra1nty/DXcam)，MIT；comtypes 1.4.17 由 pip 自动安装。
- 可选 Caddy 2.11.7：[官方发布](https://github.com/caddyserver/caddy/releases/tag/v2.11.7)，Apache-2.0。
- 自有启动与兼容脚本采用 MIT 许可，见 LICENSE。

## 网络地址自动跟随（HTTP）

公开 8080 监听 0.0.0.0；防火墙仅开放 TCP 8080、来源 LocalSubnet、任意本机地址，127.0.0.1:8000 仍为本机后台。运行中约每 3–6 秒检测状态为 Up、IPv4 为 Preferred 的网卡，排除 Deprecated、断开、回环和自分配地址。当前地址失效且只有一个有效替代地址时，自动更新 config.json、ready.json 和教师页固定链接；不重启采集，不需重新登录或重复管理员确认。学生需使用教师公布的新网址，旧 IP 不能自动跳到已不存在的地址。

每次 start.cmd 启动前都会检测本机当前有效 IP：原地址仍有效则保留；只有一个新地址则自动更新；多个候选地址则在启动窗口提示选择。运行中无网络时保留原地址等待恢复，多个有效替代地址时先保留，重新启动后选择教学网卡。可选 HTTPS 模式仍需停机并重跑安装入口更新绑定和防火墙。本功能跟随真实本机 IP，不提供校园 DNS 别名或固定域名。
