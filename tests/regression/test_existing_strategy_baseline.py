"""Validate the uploaded v7.6.3 archive without modifying it."""

from pathlib import Path
import os
import pytest

from scripts.verify_v763_baseline import verify_v763_baseline


ARCHIVE = Path(os.environ.get('ASTOCK_V763_ARCHIVE', '/workspace/scratch/08ddc3994218/upload/AStockQuant_v7_6_3_空分钟缓存修复_双击版.zip'))


@pytest.mark.skipif(not ARCHIVE.is_file() and 'ASTOCK_V763_ARCHIVE' not in os.environ,
                    reason='Optional historical v7.6.3 upload is absent; set ASTOCK_V763_ARCHIVE to run its 63-test audit')
def test_uploaded_legacy_program_passes_its_own_suite():
    result = verify_v763_baseline(ARCHIVE)
    assert result.returncode == 0, result.stderr
    assert 'Ran 63 tests' in result.stderr
