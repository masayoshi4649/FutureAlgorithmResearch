"""市場結果を読まず、純人工984行で表示データの欠落と構文を確かめる。"""

import importlib.util
import json
from pathlib import Path
import re

import publisher125 as P


def main() -> None:
    """
    機能: 固定十二条件と純人工の二商品四十一場からHTMLを生成する。
    引数: なし。
    返り値: None。原市場・実測結果・金融エンジンを読まない。
    """
    path=P.HERE.parent/'catalog125.py'
    spec=importlib.util.spec_from_file_location('publisher_artificial_catalog',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    methods=module.specifications();scenes=[f'人工_{i:02}' for i in range(41)]
    rows=[]
    for index,method in enumerate(methods):
        for symbol in ('TOPIX','NK225'):
            for j,scene in enumerate(scenes):
                net=(j%5-2)*1000+index*10
                rows.append(dict(symbol=symbol,session=scene,method=method['id'],net=net,profit=max(0,net)+500,
                    loss=max(0,-net)+500,entry_quantity=5,win_quantity=5 if net>0 else 0,loss_quantity=5 if net<0 else 0,
                    forced_groups=1,signal_groups=0,normal_groups=1,proxy_groups=0,fees=0,max_long=5,max_short=0,
                    rate_components=dict(capacity_notional=40000000,reference_price=4000.)))
    result=dict(passed=True,rows=rows,specs=methods,sessions=scenes)
    data=P.make_data(result,None)
    rendered=P.build_html(data,'純人工の表示検査・金融再生0・実測結果ではありません。')
    block=re.search(r'<script id="report-data" type="application/json">(.*?)</script>',rendered,re.S)
    embedded=json.loads(block.group(1))
    assert len(embedded['rows'])==984 and len(embedded['sessions'])==41 and len(embedded['metrics'])==12
    assert set(embedded['family_picks'])=={'A','B','C'}
    assert all(len([r for r in embedded['rows'] if r['method']==m['id'] and r['symbol']==s])==41
               for m in methods for s in ('TOPIX','NK225'))
    assert '<script src=' not in rendered and 'fetch(' not in rendered
    (P.HERE/'人工生成確認.html').write_text(rendered,encoding='utf-8')
    (P.HERE/'人工生成確認.js').write_text(re.search(r'<script>(.*?)</script>',rendered,re.S).group(1),encoding='utf-8')
    proof=dict(passed=True,records=984,methods=12,sessions=41,products=2,financial_replay=0,actual_result_reads=0,
        original_market_reads=0,確認=['全984行をJSON収録','全24商品条件ごと41行','三家族代表','外部script/fetchなし'],
        source_sha256=P.sha((P.HERE/'publisher125.py').read_bytes()))
    (P.HERE/'純人工の生成確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
