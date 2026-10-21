"""Bounded, proxy-free BSE membership adapter; protocol follows AKShare."""
from __future__ import annotations

import json


def fetch_bse_universe(connection=None) -> list[dict[str, str]]:
    import requests
    owned = connection is None
    connection = connection or requests.Session()
    connection.trust_env = False
    try:
        def page(number):
            response = connection.post('https://www.bse.cn/nqxxController/nqxxCnzq.do',
                data={'page':str(number),'typejb':'T','xxfcbj[]':'2','xxzqdm':'',
                      'sortfield':'xxzqdm','sorttype':'asc'}, timeout=18,
                headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bse.cn/nq/listedcompany.html'})
            response.raise_for_status()
            text = response.text
            blocks = json.loads(text[text.find('['):text.rfind(']')+1])
            if not isinstance(blocks,list) or len(blocks)!=1:
                raise ValueError('北交所列表响应结构不完整')
            return blocks[0]
        first = page(0)
        pages = int(first['totalPages'])
        if not 1 <= pages <= 100:
            raise ValueError('北交所列表分页数量无效')
        rows, seen = [], set()
        for number in range(pages):
            block = first if number==0 else page(number)
            if int(block['totalPages']) != pages or not block.get('content'):
                raise ValueError('北交所列表分页不完整')
            for record in block['content']:
                code = record.get('xxzqdm') or record.get('zqdm') or record.get('证券代码')
                name = record.get('xxzqjc') or record.get('zqjc') or record.get('证券简称')
                if not code or not name:
                    # AKShare's documented 48-field response assigns these positions.
                    if len(record) != 48:
                        raise ValueError('北交所列表字段无法识别')
                    fields = list(record.values()); code, name = fields[38], fields[40]
                code, name = str(code).strip(), str(name).strip()
                if len(code)!=6 or not code.isdigit() or not code.startswith(('4','8','9')) or not name or name.isdigit():
                    raise ValueError('北交所股票代码或名称无效')
                if code in seen:
                    raise ValueError('北交所分页重复，列表不完整')
                seen.add(code); rows.append({'code':code,'name':name})
        expected = first.get('totalElements')
        if expected is not None and int(expected)!=len(rows):
            raise ValueError(f'北交所列表不完整：{len(rows)}/{expected}')
        return rows
    finally:
        if owned:
            connection.close()
