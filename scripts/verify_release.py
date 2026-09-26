"""Extract and verify an AStockQuant Windows archive without launching a GUI."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from build_windows_release import FORBIDDEN, WINDOWS_PROGRAM_FILES


def verify_release(archive: Path) -> str:
    archive = Path(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='astock-release-check-') as temporary:
        root = Path(temporary)
        with ZipFile(archive) as source:
            if source.testzip() is not None:
                raise ValueError('压缩包文件损坏')
            names = source.namelist()
            if len(names) != len(set(names)) or not WINDOWS_PROGRAM_FILES.issubset(set(names)):
                raise ValueError('压缩包程序文件不完整或重复')
            for name in names:
                parts = Path(name).parts
                if (not name or name.startswith('/') or '..' in parts or
                        FORBIDDEN.intersection(parts) or name.endswith('/')):
                    raise ValueError(f'压缩包存在不安全路径：{name}')
            source.extractall(root)
        if 'APP_VERSION = "8.3.2"' not in (root / 'main.py').read_text(encoding='utf8'):
            raise ValueError('版本标识错误')
        subprocess.run([sys.executable, '-m', 'compileall', '-q', str(root)], check=True)
        subprocess.run([sys.executable, '-m', 'unittest', 'test_execution',
                        'test_tail_strategy', 'test_v8_offline', '-q'],
                       cwd=root, check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise ValueError('验证过程中安装包被修改')
    return digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    print('已验证 SHA-256:', verify_release(args.archive))
