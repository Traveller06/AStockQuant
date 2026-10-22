"""Synthetic regressions: incompatible caches must not block valid fresh history."""
from datetime import date
import json

import pandas as pd
import pytest

from astock_quant.desktop.full_market_scanner import FullMarketScanner

TARGET = date(2026, 10, 21)


def bars(periods=200):
    return pd.DataFrame({'open': 10., 'high': 11., 'low': 9., 'close': 10., 'volume': 100.},
                        index=pd.bdate_range(end=TARGET, periods=periods))


def scanner(root, fetch):
    return FullMarketScanner(root, universe_loader=lambda: ([], ''), history_fetcher=fetch)


def cache(root, name, frame):
    path = root / name / '600000.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index_label='date')
    return path, path.read_bytes()


@pytest.mark.parametrize('problem', ['ratio', 'overlap', 'zero', 'broken_file'])
def test_valid_fresh_history_recovers_without_mutating_existing_files(tmp_path, problem):
    old = bars().iloc[:-1].copy()
    if problem == 'ratio':
        old.iloc[0, old.columns.get_loc('close')] = 8.
    elif problem == 'overlap':
        old = old.iloc[:2]
    elif problem == 'zero':
        old.iloc[0, old.columns.get_loc('open')] = 0.
    path, before = cache(tmp_path, 'cache', old)
    if problem == 'broken_file':
        path.write_text('broken', encoding='utf8')
        before = path.read_bytes()
    overlay, overlay_before = cache(tmp_path, 'v8_market_updates', bars().iloc[-20:-1])
    calls = []
    result = scanner(tmp_path, lambda code: calls.append(code) or bars())._history('600000', TARGET)
    pd.testing.assert_frame_equal(result, bars(), check_freq=False)
    assert calls == ['600000']
    assert path.read_bytes() == before and overlay.read_bytes() == overlay_before
    manifests = list((tmp_path / 'v8_history_snapshots' / '600000').glob('*.json'))
    assert len(manifests) == 1
    metadata = json.loads(manifests[0].read_text(encoding='utf8'))
    assert metadata['adjustment_basis'] == 'qfq' and metadata['rows'] == 200
    assert metadata['reason'] and metadata['sha256']
    reused = scanner(tmp_path, lambda code: pytest.fail('validated snapshot should be reused'))._history('600000', TARGET)
    pd.testing.assert_frame_equal(reused, bars(), check_freq=False)


@pytest.mark.parametrize('problem', ['stale', 'zero', 'nan', 'inf', 'duplicate', 'range_index', 'inconsistent'])
def test_invalid_fresh_history_never_replaces_bad_cache(tmp_path, problem):
    old = bars().iloc[:2]
    path, before = cache(tmp_path, 'cache', old)
    fresh = bars()
    if problem == 'stale': fresh = fresh.iloc[:-1]
    elif problem == 'zero': fresh.iloc[0, 0] = 0.
    elif problem == 'nan': fresh.iloc[0, 0] = float('nan')
    elif problem == 'inf': fresh.iloc[0, 0] = float('inf')
    elif problem == 'duplicate': fresh = pd.concat([fresh, fresh.iloc[-1:]])
    elif problem == 'range_index': fresh = fresh.reset_index(drop=True)
    elif problem == 'inconsistent': fresh.iloc[0, 1] = 5.
    with pytest.raises(ValueError):
        scanner(tmp_path, lambda code: fresh)._history('600000', TARGET)
    assert path.read_bytes() == before
    assert not list((tmp_path / 'v8_history_snapshots').glob('*/*.json'))


def test_corrupt_snapshot_is_ignored_and_retained(tmp_path):
    cache(tmp_path, 'cache', bars().iloc[:2])
    scanner(tmp_path, lambda code: bars())._history('600000', TARGET)
    snapshot = next((tmp_path / 'v8_history_snapshots' / '600000').glob('*.csv'))
    snapshot.write_text('corrupt', encoding='utf8')
    calls = []
    result = scanner(tmp_path, lambda code: calls.append(code) or bars())._history('600000', TARGET)
    assert len(result) == 200 and calls == ['600000']
    assert snapshot.read_text(encoding='utf8') == 'corrupt'
    assert len(list(snapshot.parent.glob('*.json'))) == 2


def test_short_independent_history_is_not_extended_by_unverifiable_old_prices(tmp_path):
    cache(tmp_path, 'cache', bars().iloc[:2])
    result = scanner(tmp_path, lambda code: bars(38))._history('600000', TARGET)
    assert len(result) == 38
