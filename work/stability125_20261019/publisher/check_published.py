"""公開生成済みHTMLの埋込件数とJavaScript抽出を確認する。"""

import json
from pathlib import Path
import re

import publisher125 as P


def main() -> None:
    """
    機能: 公開HTMLだけから全件・診断・代表集計を検査し実行部を抽出する。
    引数: なし。
    返り値: None。実Chromeの描画確認は行わない。
    """
    text=P.TARGET.read_text(encoding='utf-8')
    data=json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>',text,re.S).group(1))
    assert len(data['rows'])==984 and len(data['specs'])==12
    assert len(data['diagnosis']['items'])==6
    assert all(r['fees']==0 for r in data['rows'])
    assert all(len([r for r in data['rows'] if r['method']==spec['id'] and r['symbol']==s])==41
               for spec in data['specs'] for s in ('TOPIX','NK225'))
    logic=re.search(r'<script>(.*?)</script>',text,re.S).group(1)
    (P.HERE/'公開HTML実行部.js').write_text(logic,encoding='utf-8')
    projection={family:{symbol:{k:data['metrics'][method][symbol][k]
        for k in ('net','mean','median','mean_width','mean_price_pct','red','active_zero','participation')}
        for symbol in ('TOPIX','NK225')} for family,method in data['family_picks'].items()}
    proof=dict(passed=True,html_sha256=P.sha(P.TARGET.read_bytes()),records=984,selections=24,rows_per_selection=41,
        diagnostic_items=6,all_fees_zero=True,family_picks=data['family_picks'],projection=projection,financial_replay=0,
        original_market_reads=0,Chrome描画='未実行、根担当が別途確認')
    (P.HERE/'公開HTMLの静的全件確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
