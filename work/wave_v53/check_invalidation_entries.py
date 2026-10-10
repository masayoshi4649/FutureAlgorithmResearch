"""確定終値に対して逆側だった失敗線が、実際の新規注文へ進んだか照合する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import sys

import numpy as np

import signals


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'wave_v52/measurement'))
from quotes import load_inputs_only


def main() -> None:
    """機能: 指摘6候補だけを固定台帳・判断時価格・距離拒否条件へ対応付ける。

    引数: なし。返り値: なし(None)。戦略条件や既存結果は変更しない。
    """
    cases = json.loads((HERE / '失敗線監査詳細.json').read_text(encoding='utf8'))
    results = json.loads((HERE / '売買結果.json').read_text(encoding='utf8'))
    inputs = load_inputs_only()
    features = pickle.loads((HERE / '特徴.pkl').read_bytes())
    decisions = pickle.loads((HERE / '判断.pkl').read_bytes())
    methods = {row['id']: row for row in results['methods'] if row['id'].startswith(('T10_', 'AUTO_'))}
    rows = []
    for case in cases:
        key = (case['session'], case['symbol'])
        ready, frame = inputs[key], features[key]
        raw_index = int(np.searchsorted(ready['seq'], case['seq']))
        assert ready['seq'][raw_index] == case['seq']
        feature_index = int(np.flatnonzero(frame.seq.to_numpy() == case['seq'])[0])
        choices, feature_rows = signals.candidates(frame)
        actual_price = float(ready['last'][raw_index])
        distance = case['side'] * (actual_price - case['invalidation'])
        variants = []
        for method, source in methods.items():
            family = source['family']
            confirmation = source['confirmation']
            array = decisions[(key, family, confirmation)]
            directive = array[feature_index]
            assert directive[0] == raw_index
            selected = 'T10'
            if family == 'AUTO':
                _, trace = signals.make_decisions(frame, choices, feature_rows, family, confirmation)
                selected = trace[feature_index]['選択']
            account = next(row for row in source['accounts'] if (row['session'], row['symbol']) == key)
            orders = np.asarray(account['orders'], dtype=float).reshape(-1, 13)
            matches = orders[(orders[:, 4] == 1) & (orders[:, 2] == case['seq'])]
            position_at_decision = float(np.sum(orders[orders[:, 3] <= case['seq'], 5] * orders[orders[:, 3] <= case['seq'], 6]))
            accepted = len(matches) > 0 and selected == 'T10'
            variants.append(dict(手法=method, 選択入口=selected, T10を選択=selected == 'T10',
                                 候補方向=int(directive[2]), 確認後方向=int(directive[1]),
                                 判断時点の実保有枚数=position_at_decision,
                                 同判断行の新規注文数=int(len(matches)), T10新規約定=accepted,
                                 新規約定行=[int(order[3]) for order in matches],
                                 新規約定価格=[float(order[7]) for order in matches]))
        rows.append(dict(**case, decision_last=actual_price, decision_mid=float(frame.mid.iloc[feature_index]),
                         decision_distance=distance, distance_guard_rejects=distance <= 0,
                         methods=variants))
    result = dict(対象候補数=len(rows), 判断価格で距離非正=sum(row['distance_guard_rejects'] for row in rows),
                   T10として実際に新規約定した件数=sum(item['T10新規約定'] for row in rows for item in row['methods']),
                   解釈='候補足の確定中値closeと、注文判断行の現在最終価格は別。engineは後者から失敗線への距離が非正なら拒否する。無約定でも保有中・休止中・確認不成立が先に該当する可能性があり、全件の直接原因を距離拒否と断定しない。',
                   戦略変更なし=True, 記録=rows)
    (HERE / '失敗線候補の約定照合.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps({key: value for key, value in result.items() if key != '記録'}, ensure_ascii=False))
    for row in rows:
        print(row['session'], row['symbol'], row['seq'], row['close'], row['decision_last'], row['decision_distance'],
              [(x['手法'], x['選択入口'], x['確認後方向'], x['判断時点の実保有枚数'], x['T10新規約定']) for x in row['methods']])


if __name__ == '__main__':
    main()
