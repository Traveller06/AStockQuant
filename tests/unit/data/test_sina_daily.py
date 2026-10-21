import pandas as pd
import pytest


def test_qfq_divides_prices_without_creating_factor_only_trading_days():
    from astock_quant.data.sina_daily import normalize_sina_daily
    rows = [{'date': '2026-09-24', 'open':20,'high':22,'low':18,'close':20,'volume':1000},
            {'date': '2026-09-30', 'open':10,'high':11,'low':9,'close':10,'volume':2000}]
    frame = normalize_sina_daily(rows, [['2026-09-23','2'],['2026-09-29','1']], 2026)
    assert list(frame.date.dt.strftime('%Y-%m-%d')) == ['2026-09-24','2026-09-30']
    assert frame.close.tolist() == [10.,10.]
    assert frame.volume.tolist() == [10.,20.]


def test_missing_qfq_factor_is_rejected_instead_of_labelling_raw_prices_adjusted():
    from astock_quant.data.sina_daily import normalize_sina_daily
    rows = [{'date':'2026-09-24','open':10,'high':11,'low':9,'close':10,'volume':1000}]
    with pytest.raises(ValueError, match='复权'):
        normalize_sina_daily(rows, [], 2026)


def test_transport_parses_factor_assignment_and_disables_proxy(monkeypatch):
    import json
    import py_mini_racer
    from astock_quant.data.sina_daily import fetch_sina_daily
    rows = [{'date':'2026-09-30','open':10,'high':11,'low':9,'close':10,'volume':1000}]
    class Decoder:
        def eval(self, source): pass
        def call(self, function, encoded):
            assert encoded == 'encoded_daily_fixture'
            return rows
    class Response:
        def __init__(self,text): self.text = text
        def raise_for_status(self): pass
    class Session:
        trust_env = True
        def get(self,url,timeout,headers):
            assert not self.trust_env and timeout <= 18
            if url.endswith('qfq.js'):
                return Response('var factor = {"data":[["2026-09-29","1"]]};\n')
            return Response('var bars = "encoded_daily_fixture"; var other = "trailer";\n')
    monkeypatch.setattr(py_mini_racer,'MiniRacer',Decoder)
    frame = fetch_sina_daily('bj920002', Session(), 2026)
    assert frame.close.tolist() == [10.]
    assert frame.date.dt.strftime('%Y-%m-%d').tolist() == ['2026-09-30']


def test_index_fallback_decodes_actual_bar_dates_without_stock_adjustment(monkeypatch):
    import py_mini_racer
    from astock_quant.data.sina_daily import fetch_sina_index
    class Decoder:
        def eval(self, source): pass
        def call(self, function, encoded):
            return [{'date':'2026-09-30','open':'4000','high':'4010','low':'3990','close':'4005','volume':'1000'}]
    class Response:
        text = 'var index = "encoded_index_fixture"; var other = "trailer";'
        def raise_for_status(self): pass
    class Session:
        trust_env = True
        def get(self,url,**kwargs):
            assert not self.trust_env and '/sh000300/hisdata/klc_kl.js' in url
            return Response()
    monkeypatch.setattr(py_mini_racer,'MiniRacer',Decoder)
    frame = fetch_sina_index('sh000300',Session(),2026)
    assert frame.close.tolist() == [4005]
    assert frame.date.dt.strftime('%Y-%m-%d').tolist() == ['2026-09-30']


@pytest.mark.parametrize('response', ['<html>error</html>', 'var bars = 42;', 'var bars = "abc" + dangerous();', 'var bars = "";'])
def test_encoded_assignment_rejects_invalid_payload(response):
    from astock_quant.data.sina_daily import _encoded_assignment
    with pytest.raises(ValueError):
        _encoded_assignment(response)


def test_encoded_assignment_preserves_escaped_content_and_ignores_trailing_code():
    from astock_quant.data.sina_daily import _encoded_assignment
    import json
    encoded = 'abc;"quote"=end'
    assert _encoded_assignment('var bars = ' + json.dumps(encoded) + '; throw new Error("never execute");') == encoded
