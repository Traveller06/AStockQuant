from astock_quant import __version__
from astock_quant.app.bootstrap import create_application


def test_package_version_and_bootstrap_contract():
    assert __version__ == "8.0.0"
    assert callable(create_application)
