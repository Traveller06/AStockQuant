from pathlib import Path
import zipfile

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
        assert 'APP_VERSION = "8.1.0"' in source.read('main.py').decode()
        forbidden = {'cache', 'tail_strategy_cache', 'tail_strategy_state.json',
                     'v8_state', 'v8_runs', 'research_sample.json',
                     'validation_snapshot_v1.json.gz', 'paper_account.json', '.venv'}
        assert not {part for name in names for part in Path(name).parts} & forbidden
        assert all(not name.startswith('windows_app/') for name in names)
    assert report.members == len(names)
