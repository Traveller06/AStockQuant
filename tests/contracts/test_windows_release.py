from pathlib import Path
import zipfile
import json
import hashlib

from scripts.build_windows_release import build_release


def test_release_has_flat_installable_layout_and_no_user_data(tmp_path):
    root = Path(__file__).resolve().parents[2]
    archive = tmp_path / 'release.zip'
    report = build_release(root, archive)
    with zipfile.ZipFile(archive) as source:
        names = set(source.namelist())
        assert {'main.py', 'tail_strategy.py', 'weekly_trend_page.py',
                'astock_quant/__init__.py', '1_第一次双击_安装并打开.bat',
                '2_以后双击_启动软件.bat', '3_双击_离线自检.bat'} <= names
        assert {'LICENSE', 'BUILDING.md', 'THIRD_PARTY_NOTICES.md', 'SOURCE_INFO.txt'} <= names
        assert source.read('LICENSE') == (root / 'LICENSE').read_bytes()
        assert b'GPL-3.0-only' in source.read('SOURCE_INFO.txt')
        assert b'v8.3.6-preview.1' in source.read('SOURCE_INFO.txt')
        assert 'APP_VERSION = "8.3.6"' in source.read('main.py').decode()
        assert {'只看这里_v8.2_两步打开.txt', 'V8.2_三级筛选说明.txt', '只看这里_v8.2.1_两步打开.txt', 'V8.2.1_过期行情更新说明.txt'} <= names
        forbidden = {'cache', 'v8_history_snapshots', 'v8_market_updates', 'tail_strategy_cache', 'tail_strategy_state.json',
                     'v8_state', 'v8_runs', 'research_sample.json',
                     'validation_snapshot_v1.json.gz', 'paper_account.json', '.venv'}
        assert not {part for name in names for part in Path(name).parts} & forbidden
        assert all(not name.startswith('windows_app/') for name in names)
        original = json.loads((root / 'release/v8.3.5-original-payload-sha256.json').read_text(encoding='utf8'))
        assert len(original) == 75
        # Keep the original manifest immutable. Only this data-recovery module changes behavior;
        # the desktop entry point and two launchers may change their version text only.
        version_only = {'main.py', '1_第一次双击_安装并打开.bat', '2_以后双击_启动软件.bat', 'test_tail_strategy.py'}
        for name, digest in original.items():
            if name == 'astock_quant/desktop/full_market_scanner.py':
                continue
            payload = source.read(name)
            if name in version_only:
                payload = payload.replace(b'8.3.6', b'8.3.5')
            assert hashlib.sha256(payload).hexdigest() == digest, name
        assert 'astock_quant/desktop/history_snapshots.py' in names
    assert report.members == len(names)
