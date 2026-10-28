# 本地开发与部署

- Windows 教学版的唯一维护位置是 `windows-lan/`。不要向工作区的 `teacher/` 复制 Python、JS、CSS 或安装脚本。
- `app/` 保留上游代码；当前教学版安装锁定的 PyPI `classtream==1.0.1`，通过 `windows-lan/compat.py` 等适配层修改行为。修改 `app/` 不会自动影响这条部署路径。
- 本机唯一日常入口是工作区根目录的 `start.cmd`，直接运行 `windows-lan/lan.py launch --home teacher`。不要新增本机操作入口；关闭窗口停止，再次双击自动清理本项目旧服务并重启。仓库及便携包中的部署脚本供安装/分发使用。
- `CLASSTREAM_HOME` 保存 `config.json`、`.venv/`、`runtime/`、`bin/caddy.exe`；Python 模块、前端资源和 PowerShell 脚本始终从 `windows-lan/` 加载。
- 修改源码后重启服务，教师与学生刷新页面。不要提交本机配置、账户、数据库、证书或依赖环境。
- 分享包只由 `python tools/build_windows_share.py` 的白名单生成。不要打包本机 `teacher/`。
- 目录/启动调整运行 `python tests/verify_deployment_layout.py` 、`python tests/verify_startup_recovery.py` 和 `python tests/verify_windows_adapter.py`。测试需要匹配 Starlette 的测试客户端依赖；不使用真实课堂数据。

- 可复用维护代码集中在 `tools/`，生成日志和截图放 `.artifacts/`；不新增阶段性方案、源码副本或日期命名的临时脚本。工作区根入口由 `tools/create_local_launcher.py` 重建。
