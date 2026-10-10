"""配布HTMLの埋込値・リンクと全脚の数量会計を保存結果から確認する。"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re

WORK=Path(__file__).resolve().parent
ROOT=WORK.parents[1]
DEST=ROOT/'アルゴリズム調査/00010_候補２方式の現在セッション再生'
PAGE=DEST/'候補２方式の現在セッション再生.html'


def main() -> None:
    """機能: 金額・返済/未返済件数・埋込明細・リンクを独立に照合する。

    引数: なし。返り値: なし (None)。価格と枚数からの脚会計も照合する。
    """
    text=PAGE.read_text(encoding='utf-8')
    payload=json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>',text,re.S).group(1))
    source=json.loads((WORK/'結果_全体.json').read_text(encoding='utf-8'))
    failures=[]
    fields=0
    for row in source:
        symbol,method,session=row['銘柄'],row['方式'],row['セッション']
        shown=[t for t in payload['trades'] if t['symbol']==symbol]
        assert len(shown)==len(row['trades'])
        for t,s in zip(shown,row['trades']):
            for key,original in [('entry','新規時刻'),('exit','返済評価時刻'),('ep','新規価格'),('xp','返済評価価格'),('pnl','収支円')]:
                assert abs(t[key]-s[original])<1e-7
                fields+=1
            computed=(s['返済評価価格']-s['新規価格'])*s['方向']*s['枚数']*({'NK225':1000,'TOPIX':10000}[symbol])
            assert abs(computed-s['収支円'])<1e-7
        summary=payload['summaries'][f'{method}|{session}|{symbol}']
        closed=[t for t in shown if t['closed']]
        opened=[t for t in shown if not t['closed']]
        assert summary['closed_count']==len(closed) and summary['open_count']==len(opened)
        assert abs(summary['closed_net_yen']-sum(t['pnl'] for t in closed))<1e-7
        assert abs(summary['open_yen']-sum(t['pnl'] for t in opened))<1e-7
        assert abs(summary['net_yen']-sum(t['pnl'] for t in shown))<1e-7
    for target in re.findall(r'href="([^"]+)"',text):
        target=html.unescape(target)
        if target.startswith('#'):
            if not re.search(r'id="'+re.escape(target[1:])+r'"',text):
                failures.append(target)
        elif not target.startswith(('https:','http:')) and not (DEST/target.split('#')[0]).exists():
            failures.append(target)
    assert not failures,failures
    result=dict(合格=True,方式数=len(source),全脚=len(payload['trades']),脚の表示値比較=fields,
        不足リンク=failures,HTML_SHA256=hashlib.sha256(PAGE.read_bytes()).hexdigest())
    (WORK/'報告静的検査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
