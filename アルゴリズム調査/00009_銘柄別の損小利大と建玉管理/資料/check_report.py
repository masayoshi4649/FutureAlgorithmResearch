"""暗色報告の埋込データ・脚会計・資料リンクを確認する。"""

from __future__ import annotations

import hashlib
import json
import re

import numpy as np

import report


def main() -> None:
    """機能: HTMLの全表示セルを各脚から再計算し、リンクとJSを抽出する。

    引数: なし。返り値: なし (None)。確認JSONを今回資料へ保存する。
    """
    path=report.DEST/report.PAGE
    text=path.read_text(encoding='utf-8')
    data=json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>',text,re.S)[1])
    count=0
    for key,summary in data['summaries'].items():
        method,session,symbol=key.split('|')
        pair=data['methods'][method]['engine']=='pair'
        part=[t for t in data['trades'] if t['method']==method and t['session']==session and (pair or t['symbol']==symbol)]
        expected=[sum(max(0,t['pnl']) for t in part if t['closed']),sum(min(0,t['pnl']) for t in part if t['closed']),
                  sum(t['pnl'] for t in part if t['closed']),sum(t['pnl'] for t in part if not t['closed']),sum(t['pnl'] for t in part)]
        actual=[summary[c] for c in ['profit_yen','loss_yen','closed_net_yen','open_yen','net_yen']]
        np.testing.assert_allclose(expected,actual,atol=1e-6)
        count+=1
    for t in data['trades']:
        expected=t['side']*t['qty']*t['multiplier']*(t['xp']-t['ep'])
        np.testing.assert_allclose(t['pnl'],expected,atol=1e-5)
    missing=[]
    for href in re.findall(r'href="([^"]+)"',text):
        if not href.startswith(('http:','https:','#')) and not (path.parent/href.split('#')[0]).exists():
            missing.append(href)
    assert not missing,missing
    script=re.search(r'<script>(.*?)</script>',text,re.S)[1]
    (report.WORK/'表示構文確認.js').write_text(script,encoding='utf-8')
    result=dict(合格=True,方式数=len(data['methods']),セッション数=len(data['sessions']),脚数=len(data['trades']),
                表示集計一致セル=count,不足リンク=missing,HTML_SHA256=hashlib.sha256(path.read_bytes()).hexdigest())
    (report.WORK/'報告静的検査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
