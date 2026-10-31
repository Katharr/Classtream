"""Build a clean Windows release without dependencies; first launch installs online."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import subprocess

from build_windows_share import ROOT, FILES, DEFAULTS


README = """Classtream Windows 局域网教学版 {version}

一、下载与开始
适用 Windows 10/11、Intel/AMD 64 位教师机；学生只需浏览器。
完整解压整个 ZIP 到长期保留的文件夹，不要在压缩软件里直接运行。
主程序包不含依赖，首次启动默认联网下载 Python 和应用依赖；日常启动无需联网。
双击根目录 start.cmd。首次自动准备独立 Python 环境、设置教师密码（用户名 admin）、
选择教学网卡并配置防火墙；按提示批准必要的系统安装和管理员请求。
已有兼容 Python 时直接复用；没有时下载并校验官方 Python 3.14.9 安装程序。
首次初始化需要几分钟；不需要手工运行 pip。

没有外网：另行下载同一 Release 的 Classtream-Dependencies-Win64-Py314.zip，完整解压，
把其中 offline 文件夹和 install.ps1 一起放入本包 windows-lan/，替换同名脚本，
再双击根目录 start.cmd。看到 OFFLINE MODE 表示已校验并使用离线依赖。
不要直接把 ZIP 文件放进去，也不要多套一层 offline/offline。

二、开始上课
1. 教师机接入学生能够访问的教学局域网，等待启动窗口显示 READY。
2. 登录自动打开的教师页；顶部课堂名菜单中选择“创建新课堂”。
3. 点击右上角“邀请学生”，把 http://live.local 发给学生；名称打不开时使用窗口内的 IP 备用地址。
4. 学生用浏览器打开即可观看，系统自动分配动物昵称，无需安装软件或证书。
教师本机入口：http://127.0.0.1:8000/?host=admin（仅本机可用）。
学生网址以启动窗口 Student 一行或“邀请学生”为准，不使用占位地址 192.0.2.1。

三、日常操作
双击根目录 start.cmd 开始上课；保持启动窗口和教师页面在线。
关闭启动窗口或按 Ctrl+C 停止；再次双击 start.cmd 自动检查、回收本项目旧进程并重启。
主画面默认展开，讨论、成员和设置按需打开。放大、缩小、适应窗口分别排列在底部。
底部“冻结学生画面”只冻结学生画面，教师预览继续；点击“恢复学生画面”继续共享。
右上角“设置 → 快捷键设置与帮助”管理按键；底部“更多”搜索操作。
升级服务后，教师与学生按 Ctrl+F5 刷新页面。
维护脚本及详细说明位于 windows-lan/；日常只需根目录 start.cmd。

四、文件与数据
start.cmd                  唯一日常启动入口
windows-lan/               教学程序及配置；不要更名或单独移动
windows-lan/offline/        仅在另行解压离线依赖后出现，本主程序包不包含
windows-lan/.venv/          首次初始化生成的本机独立依赖环境
windows-lan/runtime/        首次运行生成的账户、课堂数据及日志
windows-lan/教师端说明.md   详细说明
windows-lan/学生端说明.md   学生使用说明
windows-lan/真机验收.md     部署验收单
release.json               版本、源码提交与默认安装模式
LICENSE                    上游许可；适配层许可见 windows-lan/LICENSE

五、升级与排查
不要覆盖当前正在运行的目录。先关闭旧版窗口，备份原 runtime/data 和 config.json；
在新目录完成安装。需要保留账号/数据时，按 windows-lan/README.md 的迁移步骤操作。
不复制旧 .venv，不把个人数据库、上传文件、密码或证书发给他人。
独立 Classtream-Dependencies-Win64-Py314.zip 包含 Python、全部 wheel、VC++ 及可选 Caddy。
使用离线依赖时，缺少/损坏文件或版本不匹配会报错，不会自动改用联网安装。
安装日志：windows-lan/runtime/install.log；运行日志：windows-lan/runtime/backend.log。
默认 HTTP、30 FPS（目标上限），用于可信教学局域网，不传输系统声音或麦克风。
系统首装、运行库和防火墙可能需要管理员确认；全新 Windows 首装按验收单现场确认。
本包不包含任何本机账号、数据库、上传文件、证书或已安装环境。
"""


def build(output, version):
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT):
        raise ValueError('Commit tracked source changes before building a release')
    payloads = {}
    for name in FILES:
        path = ROOT / 'windows-lan' / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing or unsupported source: {path}')
        data = (json.dumps(DEFAULTS, indent=2) + '\n').encode() if name == 'config.json' else path.read_bytes()
        if path.suffix in ('.cmd', '.ps1'):
            data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        payloads['windows-lan/' + name] = data
    for name in ('start.cmd', 'LICENSE'):
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing or unsupported source: {path}')
        data = path.read_bytes()
        if name.endswith('.cmd'):
            data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        payloads[name] = data
    readme = README.format(version=version)
    payloads['先读我.txt'] = readme.replace('\n', '\r\n').encode('utf-8-sig')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    payloads['release.json'] = (json.dumps(dict(
        version=version, source_commit=commit, default_install='online',
        dependencies_bundled=False), indent=2) + '\n').encode('utf-8')
    for name, data in payloads.items():
        if b'PRIVATE KEY-----' in data:
            raise ValueError(f'Private key marker: {name}')
        if any(part in ('offline', '.venv', 'runtime', 'teacher') for part in Path(name).parts) or Path(name).suffix.lower() in {'.zip', '.whl', '.exe', '.db', '.key', '.pem'}:
            raise ValueError(f'Forbidden release payload: {name}')
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = 'Classtream-LAN/'
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, data in sorted(payloads.items()):
            info = zipfile.ZipInfo(prefix + name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, data, compresslevel=6)
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None or set(z.namelist()) != {prefix + n for n in payloads}:
            raise ValueError('Release archive verification failed')
        for name, data in payloads.items():
            if z.read(prefix + name) != data:
                raise ValueError(f'Release content mismatch: {name}')
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{digest}  {output.name}\n', encoding='ascii')
    output.with_name('READ-ME-FIRST.txt').write_bytes(payloads['先读我.txt'])
    print(f'Built and verified: {output}\n{len(payloads)} files; {output.stat().st_size:,} bytes\nSHA256 {digest}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    build(args.output, args.version)
