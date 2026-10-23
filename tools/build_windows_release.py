"""Build a clean, self-contained Windows release from reviewed source files."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

from build_windows_share import ROOT, FILES, DEFAULTS
from build_offline_dependencies import INSTALLERS, PIP_HASH


README = """Classtream Windows 局域网教学版 {version}

一、先看这里
适用 Windows 10/11、Intel/AMD 64 位教师机。
完整解压整个 ZIP 到长期保留的文件夹，不要在压缩软件里直接运行。
本包已包含离线依赖，不用另下载或复制依赖包。
请保留 windows-lan 文件夹的位置和名称，入口依赖它。

二、首次使用
1. 教师机接入学生可以访问的教学局域网。
2. 双击本目录 install.cmd，看到 OFFLINE MODE 表示使用内置依赖。
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
windows-lan/offline/      本包内置的离线依赖，不要移动
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


def build(dependencies, output, version):
    payloads = {}
    for name in FILES:
        path = ROOT / 'windows-lan' / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing or unsupported source: {path}')
        data = (json.dumps(DEFAULTS, indent=2) + '\n').encode() if name == 'config.json' else path.read_bytes()
        if path.suffix in ('.cmd', '.ps1'):
            data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        payloads['windows-lan/' + name] = data
    with zipfile.ZipFile(dependencies) as z:
        if z.testzip() is not None or len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('Damaged or duplicate dependency ZIP entries')
        manifest = json.loads(z.read('offline/manifest.json'))
        payloads['windows-lan/offline/manifest.json'] = z.read('offline/manifest.json')
        if (manifest['schema_version'], manifest['platform'], manifest['python'], manifest['pip']) != (1, 'win_amd64', '3.14', '26.2.2'):
            raise ValueError('Incompatible dependency manifest')
        expected = {'offline/manifest.json', 'install.ps1', '离线依赖使用说明.txt'}
        for entry in manifest['files']:
            name = entry['path']
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name:
                raise ValueError('Unsafe dependency path')
            key = 'offline/' + name
            if key in expected:
                raise ValueError('Duplicate manifest entry')
            expected.add(key)
            data = z.read(key)
            if hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError(f'Dependency checksum mismatch: {name}')
            payloads['windows-lan/' + key] = data
        if set(z.namelist()) != expected:
            raise ValueError('Unexpected files in dependency ZIP')
        if z.read('install.ps1').replace(b'\r\n', b'\n') != payloads['windows-lan/install.ps1'].replace(b'\r\n', b'\n'):
            raise ValueError('Dependency installer differs from source')
    if payloads['windows-lan/offline/requirements-lock.txt'].replace(b'\r\n', b'\n') != payloads['windows-lan/requirements-lock.txt'].replace(b'\r\n', b'\n'):
        raise ValueError('Dependency lock differs from source')
    for name, (algorithm, digest) in INSTALLERS.items():
        if hashlib.new(algorithm, payloads['windows-lan/offline/installers/' + name]).hexdigest() != digest:
            raise ValueError(f'Official installer checksum mismatch: {name}')
    if hashlib.sha256(payloads['windows-lan/offline/wheels/pip-26.2.2-py3-none-any.whl']).hexdigest() != PIP_HASH:
        raise ValueError('pip checksum mismatch')
    for name in ('install.cmd', 'start.cmd', 'stop.cmd', 'check.cmd', 'password.cmd', 'LICENSE'):
        payloads[name] = (ROOT / name).read_bytes()
    payloads['先读我.txt'] = README.format(version=version).replace('\n', '\r\n').encode('utf-8-sig')
    for name, data in payloads.items():
        if not name.startswith('windows-lan/offline/') and b'PRIVATE KEY-----' in data:
            raise ValueError(f'Private key marker: {name}')
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
    parser.add_argument('--dependencies', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    build(args.dependencies, args.output, args.version)
