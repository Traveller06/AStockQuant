"""Build a deterministic, flat Windows archive from an explicit program allowlist."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


WINDOWS_PROGRAM_FILES = frozenset({
    'main.py', 'tail_strategy.py', 'weekly_trend_page.py',
    'requirements.txt', 'README.txt', 'install.bat', 'run.bat',
    'test_execution.py', 'test_tail_strategy.py', 'test_v8_offline.py',
    '1_第一次双击_安装并打开.bat', '2_以后双击_启动软件.bat',
    '3_双击_离线自检.bat', '只看这里_v8.1_两步打开.txt', '只看这里_v8.2_两步打开.txt',
    'V8.1_周线选股说明.txt', 'V8.2_三级筛选说明.txt',
    'V8.2.1_过期行情更新说明.txt', '只看这里_v8.2.1_两步打开.txt',
    '只看这里_v8.3.0_两步打开.txt', '只看这里_v8.3.1_两步打开.txt',
    '只看这里_v8.3.2_两步打开.txt', '只看这里_v8.3.3_两步打开.txt', '只看这里_v8.3.4_两步打开.txt', '只看这里_v8.3.5_两步打开.txt',
})
FORBIDDEN = frozenset({'cache', 'v8_market_updates', 'tail_strategy_cache', 'tail_strategy_state.json',
                       'v8_state', 'v8_runs', 'research_sample.json',
                       'validation_snapshot_v1.json.gz', 'paper_account.json',
                       '.venv', '__pycache__', '.git', '.env'})


@dataclass(frozen=True)
class ReleaseReport:
    archive: Path
    sha256: str
    members: int


def build_release(repo_root: Path, destination: Path) -> ReleaseReport:
    root, destination = Path(repo_root), Path(destination)
    program = root / 'windows_app'
    files: dict[str, bytes] = {}
    for name in sorted(WINDOWS_PROGRAM_FILES):
        path = program / name
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f'发行程序文件缺失：{path}')
        files[name] = path.read_bytes()
    package = root / 'src' / 'astock_quant'
    for path in sorted(package.rglob('*.py')):
        if path.is_symlink():
            raise ValueError(f'禁止发行符号链接：{path}')
        name = 'astock_quant/' + path.relative_to(package).as_posix()
        files[name] = path.read_bytes()
    if any(FORBIDDEN.intersection(Path(name).parts) for name in files):
        raise ValueError('发行包包含运行数据或敏感文件')
    if b'APP_VERSION = "8.3.5"' not in files['main.py']:
        raise ValueError('主程序版本号不是8.3.5')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.building')
    if temporary.exists():
        raise FileExistsError(temporary)
    try:
        with ZipFile(temporary, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
            for name, content in sorted(files.items()):
                info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, content)
        blob = temporary.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise FileExistsError(f'已有不同内容的安装包，拒绝覆盖：{destination}')
            temporary.unlink()
        else:
            temporary.rename(destination)
        return ReleaseReport(destination, digest, len(files))
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build_release(Path(__file__).resolve().parents[1], args.output))
