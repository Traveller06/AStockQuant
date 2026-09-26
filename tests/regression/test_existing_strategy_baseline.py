"""Validate the uploaded v7.6.3 archive without modifying it."""

from pathlib import Path

from scripts.verify_v763_baseline import verify_v763_baseline


ARCHIVE = Path('/workspace/scratch/08ddc3994218/upload/AStockQuant_v7_6_3_空分钟缓存修复_双击版.zip')


def test_uploaded_legacy_program_passes_its_own_suite():
    result = verify_v763_baseline(ARCHIVE)
    assert result.returncode == 0, result.stderr
    assert 'Ran 63 tests' in result.stderr
