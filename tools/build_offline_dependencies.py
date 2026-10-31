"""Package prepared Windows wheels and verified official installers, without downloads."""
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = {
    "python-3.14.9-amd64.exe": (
        "sha256", "a247a0b612244a803f507b39fb7121e3602e4160d59c3b99d98e735289c53394"),
    # Official Microsoft-signed VC++ runtime used for this tested dependency pack.
    "vc_redist.x64.exe": (
        "sha256", "843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c"),
    "caddy_2.11.7_windows_amd64.zip": (
        "sha512", "c308154504e53755958ffc62d8a2657ab17eefd6dd25c45dbb2c3d93d29519971f77ca652f7d0f2bcb7f980b9ba3822478865e29969d0272d7613550a43152b1"),
}
PIP_HASH = "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
INSTRUCTIONS = """Classtream Windows x64 离线依赖包（Python 3.14）

放在哪里：
主程序 ZIP 不包含依赖，默认由 start.cmd 首次联网安装。
不能联网时，使用本独立附件，按以下步骤放入程序目录。
1. 先停止正在进行的安装，完整解压本依赖 ZIP。
2. 把 offline 文件夹和 install.ps1 一起复制到原来含 install.ps1、
   requirements-lock.txt 的目录；同名 install.ps1 选择替换。
   - GitHub 仓库下载版：放进 Classtream-main\\windows-lan\\。
   - Win64 发布版：放进 Classtream-LAN\\windows-lan\\。
   - 轻量同事分享版：放进 Classtream-LAN\\。
   不要只把 ZIP 文件放进去，也不要多套一层 offline\\offline。
3. 双击原来的 start.cmd，首次会自动安装；也可运行 install.cmd。
   出现 OFFLINE MODE 表示已校验并使用本地依赖，不下载 Python/PyPI/VC++。

正确的结构：
  install.cmd
  install.ps1              <- 本包附带的新版脚本
  requirements-lock.txt    <- 原教学包已有
  offline\\
    manifest.json
    requirements-lock.txt
    wheels\\               <- requirements-lock.txt 中的依赖 + pip
    installers\\           <- Python、VC++、可选 HTTPS 的 Caddy

适用 Windows 10/11 Intel/AMD 64 位；不适用 ARM64、32 位 Windows 或其他 Python 小版本。
不复制别人的 .venv、runtime 或账号数据。已有 .venv 由脚本检查兼容性。
教师仍需接入教学局域网，按提示选择网卡、设置密码、批准防火墙/运行库管理员请求。
微软运行库签名仍需通过本机信任检查，学校策略和系统组件缺失需网管处理。
内置 Python 安装器已校验官方 SHA-256；无 Python 的全新 Windows 系统首装仍需真机验收。

包括可选 HTTPS 的 Caddy 官方 ZIP；默认 HTTP 不使用它。学生仍不安装任何东西。
保留各依赖 wheel 内的许可证、官方安装器自带许可及教学包 bin 中的 Caddy 许可。
文件损坏或锁定依赖版本不匹配时脚本会明确报错，不会悄悄联网替代。
需要恢复联网安装时，把 offline 文件夹改名后重新运行 install.cmd。
"""


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--installers", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" /
                        "Classtream-Dependencies-Win64-Py314.zip")
    args = parser.parse_args()
    lock = (ROOT / "windows-lan/requirements-lock.txt").read_bytes()
    expected = {normalize(name): version for name, version in re.findall(
        r"^([A-Za-z0-9_.-]+)==([^\s;]+)\s*$", lock.decode("utf-8-sig"), re.M)}
    expected["pip"] = "26.2.2"
    payloads = {"requirements-lock.txt": lock}
    found = {}
    for path in sorted(args.wheels.glob("*.whl")):
        if path.is_symlink():
            raise ValueError(f"Unsupported symlink: {path}")
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                raise ValueError(f"Damaged wheel: {path.name}")
            names = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError(f"Wheel metadata missing: {path.name}")
            metadata = BytesParser().parsebytes(z.read(names[0]))
        name, version = normalize(metadata["Name"]), metadata["Version"]
        if name in found or expected.get(name) != version:
            raise ValueError(f"Unexpected wheel: {path.name}")
        found[name] = version
        payloads["wheels/" + path.name] = path.read_bytes()
    if found != expected:
        raise ValueError(f"Missing wheels: {expected.keys() - found.keys()}")
    if hashlib.sha256(payloads["wheels/pip-26.2.2-py3-none-any.whl"]).hexdigest() != PIP_HASH:
        raise ValueError("pip wheel checksum mismatch")
    for name, (algorithm, digest) in INSTALLERS.items():
        path = args.installers / name
        if path.is_symlink():
            raise ValueError(f"Unsupported symlink: {path}")
        data = path.read_bytes()
        if hashlib.new(algorithm, data).hexdigest() != digest:
            raise ValueError(f"Official installer checksum mismatch: {name}")
        payloads["installers/" + name] = data
    manifest = dict(schema_version=1, platform="win_amd64", python="3.14", pip="26.2.2",
                    files=[dict(path=name, sha256=hashlib.sha256(data).hexdigest())
                           for name, data in sorted(payloads.items())])
    payloads["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    files = {"offline/" + name: data for name, data in payloads.items()}
    files["install.ps1"] = (ROOT / "windows-lan/install.ps1").read_bytes().replace(
        b"\r\n", b"\n").replace(b"\n", b"\r\n")
    files["离线依赖使用说明.txt"] = INSTRUCTIONS.replace("\n", "\r\n").encode("utf-8-sig")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            z.writestr(entry, data, compresslevel=6)
    with zipfile.ZipFile(args.output) as z:
        if z.testzip() is not None or set(z.namelist()) != set(files):
            raise ValueError("Archive verification failed")
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".zip.sha256").write_text(
        f"{digest}  {args.output.name}\n", encoding="ascii")
    print(f"Built {args.output}: {len(found)} wheels, {len(INSTALLERS)} installers, "
          f"{args.output.stat().st_size / 1024**2:.1f} MiB")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
