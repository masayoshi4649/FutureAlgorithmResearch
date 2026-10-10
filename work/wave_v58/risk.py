"""元の実取引における初期保護線の距離と損失分類を集計する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import numpy as np


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v57'


def main() -> None:
    """機能: 実際に採用された入口の時点だけを使い、保護線との距離を集計する。

    引数: なし。返り値: なし(None)。将来の価格から入口を選び直さない。
    """
    result = json.loads((OLD / '売買結果.json').read_text(encoding='utf8'))
    features = pickle.loads((OLD / 'features.pkl').read_bytes())
    signals = pickle.loads((OLD / '判断.pkl').read_bytes())
    inputs = pickle.loads((OLD.parent / 'wave_v55/clean_inputs.pkl').read_bytes())
    output = []
    for method in result['methods']:
        if not method['primary']:
            continue
        for symbol in ('TOPIX', 'NK225'):
            distances, risk_ratios, immediates, spreads = [], [], 0, []
            for account in method['accounts']:
                if account['symbol'] != symbol:
                    continue
                key = account['session'], symbol
                ready, frame, rows = inputs[key], features[key], signals[(key, method['id'])]
                tick = ready['tick']
                by_seq = {int(ready['seq'][int(r[0])]): r for r in rows}
                for order in account['orders']:
                    if order[4] != 1:
                        continue
                    row = by_seq[int(order[2])]
                    i = int(np.searchsorted(ready['seq'], order[3]))
                    assert ready['seq'][i] == order[3]
                    distance = order[5] * (frame['mid'][i] - row[3])
                    distances.append(distance / tick)
                    risk_ratios.append(min(row[2], distance) / row[2])
                    spreads.append((frame['ask'][i] - frame['bid'][i]) / tick)
                    immediates += distance <= 0
            values = np.asarray(distances)
            output.append(dict(手法=method['id'], 銘柄=symbol, 入口数=len(values),
                               壁保護線距離中央値呼値=float(np.median(values)),
                               壁保護線距離2呼値以下割合=float(np.mean(values <= 2.)),
                               初期保護距離と追跡幅の比中央値=float(np.median(risk_ratios)),
                               新規約定時に壁保護線割れ件数=int(immediates),
                               気配差中央値呼値=float(np.median(spreads))))
    (HERE / '元手法の初期保護線.json').write_text(json.dumps(dict(
        説明='主条件で実際に建てた行の中値と、入口で既知だった固定壁保護線の距離。短い距離が損失原因かは、この集計だけでは判定しない。',
        集計=output), ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
