import json
import pytest


def response(content, pages=2, total=2):
    from types import SimpleNamespace
    return SimpleNamespace(text='callback('+json.dumps([{'totalPages':pages,'totalElements':total,'content':content}])+');', raise_for_status=lambda:None)


def test_bse_pages_are_assembled_without_proxy_and_verified():
    from astock_quant.data.market_universe import fetch_bse_universe
    class Connection:
        trust_env=True
        def post(self,url,data,timeout,headers):
            assert not self.trust_env and timeout <= 18
            page=int(data['page'])
            return response([{'xxzqdm': '920002' if page==0 else '920003', 'xxzqjc':'样本甲' if page==0 else '样本乙'}])
    assert [r['code'] for r in fetch_bse_universe(Connection())] == ['920002','920003']


def test_repeated_bse_page_is_rejected_instead_of_being_complete():
    from astock_quant.data.market_universe import fetch_bse_universe
    class Connection:
        def post(self,*args,**kwargs): return response([{'xxzqdm':'920002','xxzqjc':'样本'}])
    with pytest.raises(ValueError,match='重复|完整'):
        fetch_bse_universe(Connection())


def test_official_48_column_payload_schema_uses_known_code_and_name_positions():
    from astock_quant.data.market_universe import fetch_bse_universe
    record={f'field{i}': '' for i in range(48)}
    record['field38']='920002'; record['field40']='样本'
    class Connection:
        def post(self,*args,**kwargs): return response([record],pages=1,total=1)
    assert fetch_bse_universe(Connection()) == [{'code':'920002','name':'样本'}]
