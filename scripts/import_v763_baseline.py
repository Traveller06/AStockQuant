"""Import exactly the approved v7.6.3 program files without replacing existing files."""

import hashlib
from pathlib import Path
import sys
import zipfile

from verify_v763_baseline import EXPECTED_SHA256


PROGRAM_FILES = frozenset({
    'main.py', 'tail_strategy.py', 'test_execution.py', 'test_tail_strategy.py',
    'requirements.txt', 'README.txt', 'install.bat', 'run.bat',
    '1_第一次双击_安装并打开.bat', '2_以后双击_启动软件.bat',
    'V7.3.1_修复说明.txt', 'V7.3.2_一键核实包说明.txt', 'V7.5_世坤因子说明.txt',
    'V7.6.1_代理修复说明.txt', 'V7.6.2_多源行情修复说明.txt',
    'V7.6.3_空分钟缓存修复说明.txt', 'V7.6_尾盘两日短线说明.txt',
    '升级安装_v7.3.txt', '只看这里_两步打开.txt', 'V7.3_核验报告.md',
})


def import_baseline(archive: Path, destination: Path) -> tuple[str, ...]:
    archive, destination = Path(archive), Path(destination)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError('v7.6.3 安装包校验失败')
    with zipfile.ZipFile(archive) as source:
        if set(source.namelist()) != PROGRAM_FILES:
            raise ValueError('安装包文件集合不符合审核基线')
        if destination.exists() and any(destination.iterdir()):
            raise FileExistsError('目标目录已有文件，拒绝覆盖')
        destination.mkdir(parents=True, exist_ok=True)
        for name in sorted(PROGRAM_FILES):
            (destination / name).write_bytes(source.read(name))
    return tuple(sorted(PROGRAM_FILES))


if __name__ == '__main__':
    print(f'导入 {len(import_baseline(Path(sys.argv[1]), Path(sys.argv[2])))} 个已核验程序文件')
