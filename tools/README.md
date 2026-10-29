# 维护工具

工具集中在本目录；回归断言留在 `tests/`，运行代码留在 `windows-lan/`。

| 工具 | 用途 |
| --- | --- |
| `create_local_launcher.py` | 为仓库旁已有的 `teacher/` 生成唯一日常入口 `start.cmd`，不复制源码或数据 |
| `run_checks.py` | 运行隔离回归；`--suite browser` 使用 Edge 和合成课堂，`--suite stress` 运行压力测试 |
| `stream_fixture.py` | 仅监听 `127.0.0.1:18765` 的合成课堂，无真实桌面和课堂数据库 |
| `benchmark_stream.py` | 有限时长的进程内传输压力测试，不连接真实课堂 |
| `build_windows_share.py` | 通过白名单生成轻量分享包及 SHA-256 |
| `build_windows_release.py` | 生成不含依赖的版本化发布包和“先读我”，根目录 start.cmd 首次自动在线安装 |
| `build_offline_dependencies.py` | 打包已准备的 wheel 和经校验的官方安装器 |

在源码仓库目录执行：

```powershell
# 本机已有运行数据时，生成工作区唯一日常入口。
python tools/create_local_launcher.py

# 使用已安装应用依赖的 Python；测试依赖与生产环境隔离。
python -m pip install --target .dev-deps httpx2==2.16.0
python tools/run_checks.py
python tools/run_checks.py --suite stress

# 浏览器验证另需 Node.js、Playwright 和 Edge。
# 可用 CLASSTREAM_PLAYWRIGHT 指定已安装的 Playwright 包绝对路径。
python tools/run_checks.py --suite browser

# 仅手动调试合成课堂时运行；结束后按 Ctrl+C。
python tools/stream_fixture.py
```

`run_checks.py` 自动加载 `.dev-deps/`，清除本机课堂数据环境变量，并为每个浏览器测试创建、关闭独立合成服务。每项浏览器测试使用独立随机回环端口，不结束未知进程。截图和日志只写 `.artifacts/`，依赖和生成产物均不提交 Git。

压力测试的延迟是发布到合成 ASGI 接收者的时间，使用人工 ACK，不代表浏览器渲染或真实屏幕到屏幕的延迟。

发布文件只在本地生成，上传前需单独确认。主程序与离线依赖分别构建，不能混包：

```powershell
python tools/build_windows_release.py --version v1.0.0-lan.2 --output .artifacts/release/v1.0.0-lan.2/Classtream-LAN-v1.0.0-lan.2-Win64.zip
python tools/build_offline_dependencies.py --wheels wheels --installers installers --output .artifacts/release/v1.0.0-lan.2/Classtream-Dependencies-Win64-Py314.zip
python tests/verify_windows_release.py --directory .artifacts/release/v1.0.0-lan.2 --version v1.0.0-lan.2
powershell -NoProfile -ExecutionPolicy Bypass -File tests/verify_online_install.ps1 -ProjectZip .artifacts/release/v1.0.0-lan.2/Classtream-LAN-v1.0.0-lan.2-Win64.zip
powershell -NoProfile -ExecutionPolicy Bypass -File tests/verify_offline_install.ps1 -DependencyZip .artifacts/release/v1.0.0-lan.2/Classtream-Dependencies-Win64-Py314.zip -ProjectZip .artifacts/release/v1.0.0-lan.2/Classtream-LAN-v1.0.0-lan.2-Win64.zip
```

主包采用教学源码白名单，拒绝 offline、wheel、EXE、已安装环境、运行数据和私钥；默认配置与本机配置无关。离线包单独包含固定版本 wheel、官方安装器、逐文件校验清单及配套安装脚本。`READ-ME-FIRST.txt` 与主包内“先读我.txt”相同，可作为单独附件。构建应从已提交的干净源码进行，版本及提交记录在包内 `release.json`。
