# Third-party notices

AStockQuant original code is distributed under GPL-3.0-only; see LICENSE.
The project-level license does not replace third-party copyrights or terms.

Runtime dependencies are installed separately by pip, not vendored into this
Python-source Windows ZIP. Consult each installed package distribution's
LICENSE/COPYING/NOTICE and package metadata for its applicable version:

- PySide6 / Qt for Python and its Qt components: https://www.qt.io/licensing/
- pyqtgraph: https://github.com/pyqtgraph/pyqtgraph
- pandas: https://github.com/pandas-dev/pandas
- NumPy: https://github.com/numpy/numpy
- Requests: https://github.com/psf/requests
- AKShare: https://github.com/akfamily/akshare
- BaoStock: https://pypi.org/project/baostock/
- AKShare's transitive dependencies (including py-mini-racer when used) retain their own notices.

The Sina transport adapter documents its protocol reference to AKShare; its
runtime decoder is imported from the installed AKShare package. No third-party
license headers have been removed in this release preparation.

vn.py, RQAlpha, Qlib and easytrader are architectural references described in the
README, not a claim that those complete projects are incorporated or relicensed.
Future additions of their code must preserve and comply with their licenses.

Market data is obtained from external providers; this repository and its ZIP do
not include downloaded historical data, personal holdings, broker credentials,
or a grant of data redistribution rights.
