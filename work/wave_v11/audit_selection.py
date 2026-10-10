"""学習終了後の損益を破壊しても選択が変わらないことを確認する。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import research

OUT = Path(__file__).resolve().parent


def main() -> None:
    """機能: ３思想×４学習範囲の全順位を将来列の極端な改変前後で比較する。

    引数: なし。返り値: None。選択の時系列境界に関する独立監査 JSON を保存する。
    """
    frame = pd.read_csv(OUT/'全条件_セッション集計.csv')
    conditions = json.loads((OUT/'条件一覧.json').read_text(encoding='utf-8'))
    final = json.loads((OUT/'最終選択.json').read_text(encoding='utf-8'))
    saved = json.loads((OUT/'時間順選択.json').read_text(encoding='utf-8')) + list(final['主選択'].values())
    if '銘柄別主選択' in final:
        saved += [r for per_symbol in final['銘柄別主選択'].values() for r in per_symbol.values()]
        saved += json.loads((OUT/'銘柄別時間順選択.json').read_text(encoding='utf-8'))
    reports = []
    for record in saved:
        train = record['学習']
        symbol = record.get('選択対象銘柄')
        baseline = research.choose(frame, conditions, train, record['思想'], symbol=symbol)
        assert {r['方式'] for r in baseline['全順位']} == {r['方式'] for r in record['全順位']}
        assert baseline['採用']['方式'] == record['採用']['方式']
        changed = frame.copy()
        future = ~changed.セッション.isin(train)
        if symbol:
            future |= ~changed.銘柄.eq(symbol)
        for i, column in enumerate(['費用倍ATR収支', '費用倍全行最大下落ATR', '設定最大枚数',
                                    '取引数', '収支円', '費用倍収支円']):
            changed.loc[future, column] = (np.arange(int(future.sum()))+1)*(1e8+i)
        observed = research.choose(changed, conditions, train, record['思想'], symbol=symbol)
        assert observed == baseline
        reports.append(dict(思想=record['思想'], 学習=train, 対象銘柄=symbol, 改変した対象外セル数=int(future.sum()),
                             全順位一致=True, 採用一致=True))
    result = dict(一致=True, 件数=len(reports), 改変='未来側と対象外銘柄の費用倍損益・DD・枚数上限・取引数・円損益を巨大値に置換',
                  限界='研究者が既知データを見て条件を設計した影響を消すものではない。コードの選択境界を検査する。', 検査=reports)
    (OUT/'未来結果改変の選択不変監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(一致=True, 件数=len(reports)), ensure_ascii=False))


if __name__ == '__main__':
    main()
