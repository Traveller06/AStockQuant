"""Read-only verification of the approved v7.6.3 desktop archive."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


EXPECTED_SHA256 = 'dfc50da574d6a15b280ba65091e883cfd7047cc4238e3aca92badef970be540e'


def verify_v763_baseline(path: Path) -> subprocess.CompletedProcess[str]:
    path = Path(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    if before != EXPECTED_SHA256:
        raise ValueError('上传的 v7.6.3 安装包与审定基线不一致')
    with tempfile.TemporaryDirectory(prefix='astock-v763-verify-') as temporary:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                name = Path(member.filename)
                if name.is_absolute() or '..' in name.parts or member.is_dir():
                    raise ValueError('基线安装包包含不安全路径')
            archive.extractall(temporary)
        result = subprocess.run(
            [sys.executable, '-m', 'unittest', 'discover', '-s', temporary, '-p', 'test_*.py', '-q'],
            cwd=temporary, capture_output=True, text=True, check=False,
        )
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise RuntimeError('基线安装包在验证过程中发生改变')
    return result


if __name__ == '__main__':
    outcome = verify_v763_baseline(Path(sys.argv[1]))
    print(outcome.stderr, end='')
    raise SystemExit(outcome.returncode)
