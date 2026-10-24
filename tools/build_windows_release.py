"""Build a clean Windows release without bundled dependencies from reviewed source files."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from build_windows_share import ROOT, FILES, DEFAULTS


README = """Classtream Windows 局域网教学版 {version}

一、先看这里
适用 Windows 10/11、Intel/AMD 64 位教师机。
完整解压整个 ZIP 到长期保留的文件夹，不要在压缩软件里直接运行。
本包不含离线依赖。首次安装默认联网下载。
如需离线安装，请从同一个 Release 单独下载 Classtream-Dependencies-Win64-Py314.zip。
解压依赖 ZIP，把其中 offline 文件夹和 install.ps1 一起复制到本包的 windows-lan 目录，
替换同名脚本，再运行根目录 install.cmd。不要直接把依赖 ZIP 放进程序目录。
请保留 windows-lan 文件夹的位置和名称，入口依赖它。

二、首次使用
1. 教师机接入学生可以访问的教学局域网。
2. 双击本目录 install.cmd；默认 ONLINE MODE，另配离线依赖后为 OFFLINE MODE。
3. 按提示设置教师密码（用户名 admin），多网卡时选择教学网卡。
4. 按需批准微软运行库和防火墙的管理员提示。
5. 登录自动打开的教师页面，点击 New Link 创建课堂。
6. 把面板显示的 http://教师当前IP:8080/class 发给学生。
学生使用浏览器输入姓名观看，不安装软件、插件或证书。

三、日常使用
start.cmd     开始上课，自动检测当前 IP
stop.cmd      下课停止服务
check.cmd     检查服务状态
password.cmd  停止服务后修改教师密码
教师管理页和服务窗口在上课期间保持打开。
学生地址以本机启动窗口 Student 一行或教师面板为准。
教师管理入口：http://127.0.0.1:8000/?host=admin

四、文件放在哪里
windows-lan/              程序、配置和详细说明
windows-lan/offline/      仅在另行解压离线依赖包后出现，本 ZIP 不包含
windows-lan/教师端说明.md  详细教师使用说明
windows-lan/学生端说明.md  学生观看说明
windows-lan/真机验收.md    部署验收单
windows-lan/runtime/      安装运行后生成的日志及课堂数据
windows-lan/.venv/        安装后生成的独立 Python 环境
LICENSE                   上游许可；适配代码许可见 windows-lan/LICENSE

五、使用范围与排查
默认 HTTP 不加密，仅用于可信教学局域网，不传输系统声音或麦克风。
默认 60 FPS（目标上限）；实际帧率取决于采集、编码和网络。
多学生高帧率受教师出口网络限制，需要时可降低 config.json 中的 fps。
离线依赖会校验完整性；出现错误请重新完整解压，不要复制其他教师的 .venv。
首次安装仍可能需要管理员确认，系统签名信任检查受本机策略影响。
全新 Windows 的 Python/VC++ 系统级首装仍需按验收单现场确认。
安装失败保留 windows-lan/runtime/install.log，供排查。
本包只含默认配置；请勿把安装后的 runtime、.venv 或账户数据再分享给别人。
"""


def build(output, version):
    payloads = {}
    for name in FILES:
        path = ROOT / 'windows-lan' / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing or unsupported source: {path}')
        data = (json.dumps(DEFAULTS, indent=2) + '\n').encode() if name == 'config.json' else path.read_bytes()
        if path.suffix in ('.cmd', '.ps1'):
            data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        payloads['windows-lan/' + name] = data
    for name in ('install.cmd', 'start.cmd', 'stop.cmd', 'check.cmd', 'password.cmd', 'LICENSE'):
        payloads[name] = (ROOT / name).read_bytes()
    payloads['先读我.txt'] = README.format(version=version).replace('\n', '\r\n').encode('utf-8-sig')
    for name, data in payloads.items():
        if b'PRIVATE KEY-----' in data:
            raise ValueError(f'Private key marker: {name}')
    for name in payloads:
        if 'offline' in Path(name).parts or Path(name).suffix.lower() in {'.zip', '.whl', '.exe', '.db', '.key', '.pem'}:
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
    print(f'Built and verified: {output}\n{len(payloads)} files; {output.stat().st_size:,} bytes\nSHA256 {digest}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    build(args.output, args.version)
