"""Inspect/extract a private T03 retirement export with the preserved installation key."""

import argparse
from pathlib import Path, PurePosixPath
import sys
import io
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from migrations.v3_retirement import decrypt_export

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("export", type=Path)
parser.add_argument("--secret-key-file", type=Path, required=True)
parser.add_argument(
    "--destination",
    type=Path,
    help="New private directory; existing destinations are refused",
)
args = parser.parse_args()
if args.export.is_symlink() or args.secret_key_file.is_symlink():
    parser.error("拒绝读取符号链接")
raw = decrypt_export(args.export.read_bytes(), args.secret_key_file.read_text().strip())
with zipfile.ZipFile(io.BytesIO(raw)) as archive:
    if args.destination is None:
        for item in archive.infolist():
            print(f"{item.filename}\t{item.file_size}")
    else:
        args.destination.mkdir(mode=0o700, parents=False, exist_ok=False)
        for item in archive.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in item.filename:
                raise ValueError("导出文件路径不安全")
            target = args.destination.joinpath(*name.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(archive.read(item))
            target.chmod(0o600)
        print("历史导出已完整解密到指定私有目录")
