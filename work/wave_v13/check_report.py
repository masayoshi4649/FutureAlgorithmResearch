"""配布HTMLの埋込値・全脚・参照リンクを静的に確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

import report


def main() -> None:
    """機能: 報告の数値変換とファイル参照を検査する。

    引数: なし。返り値: なし (None)。
    """
    page = report.DEST/report.PAGE
    text = page.read_text(encoding='utf-8')
    chart = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', text, re.S)[1])
    trades = pd.DataFrame(chart['trades'])
    compared = 0
    for key, summary in chart['summaries'].items():
        method, session, symbol = key.split('|')
        part = trades[trades.method.eq(method) & trades.session.eq(session) & trades.symbol.eq(symbol)]
        closed = part[part.closed]
        expected = [closed.pnl.clip(lower=0).sum(), closed.pnl.clip(upper=0).sum(), closed.pnl.sum(),
                    part.loc[~part.closed, 'pnl'].sum(), len(closed), int((~part.closed).sum())]
        actual = [summary[c] for c in ['profit_yen', 'loss_yen', 'closed_net_yen', 'open_yen', 'closed_count', 'open_count']]
        np.testing.assert_allclose(expected, actual, atol=1e-6)
        compared += 1
    missing = []
    for href in re.findall(r'href="([^"]+)"', text):
        if href.startswith(('http:', 'https:', '#')):
            continue
        if not (page.parent/href.split('#')[0]).exists():
            missing.append(href)
    assert not missing, missing
    script = re.search(r'<script>(.*?)</script>', text, re.S)[1]
    (report.WORK/'表示構文確認.js').write_text(script, encoding='utf-8')
    result = dict(合格=True, 埋込方式数=len(chart['methods']), セッション数=len(chart['sessions']),
                  図解全脚数=len(trades), 図解集計一致セル=compared, 不足リンク=missing,
                  HTML_SHA256=hashlib.sha256(page.read_bytes()).hexdigest())
    (report.WORK/'報告静的検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
