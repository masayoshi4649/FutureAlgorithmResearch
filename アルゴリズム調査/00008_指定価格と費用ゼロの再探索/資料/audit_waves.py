"""説明用の指定波照合を原取引と秒単位の重なりから確認する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent


def main() -> None:
    """機能: 指定波の集計と全期間損益を独立再計算する。

    引数: なし。返り値: None: 説明資料の監査結果を保存する。
    """
    trades = json.loads((OUT/'学習代表_全取引.json').read_text(encoding='utf-8'))
    waves = json.loads((OUT/'指定した４波の照合.json').read_text(encoding='utf-8'))
    frozen = json.loads((OUT/'現在照合_凍結記録.json').read_text(encoding='utf-8'))
    checked = []
    for row in waves['区間']:
        assert row['方式'] == frozen['selected_by_symbol'][row['銘柄']]
        start = int(datetime.fromisoformat(row['指定開始']).timestamp())
        end = int(datetime.fromisoformat(row['指定終了']).timestamp())
        side = 1 if row['指定方向'] == 'ロング' else -1
        matched = [t for t in trades if t['銘柄'] == row['銘柄'] and t['方式'] == row['方式']
                   and t['セッション'] == row['セッション'] and t['方向'] == side
                   and t['新規時刻'] < end and t['返済評価時刻'] > start]
        seconds = set()
        for t in matched:
            assert t['新規時刻'] == int(t['新規時刻']) and t['返済評価時刻'] == int(t['返済評価時刻'])
            seconds.update(range(max(start, int(t['新規時刻'])), min(end, int(t['返済評価時刻']))))
        multiplier = 1000 if row['銘柄'] == 'NK225' else 10000
        total = sum(t['方向']*(t['返済評価価格']-t['新規価格'])*multiplier for t in matched)
        np.testing.assert_allclose(row['同方向保有分'], len(seconds)/60)
        np.testing.assert_allclose(row['指定区間内保有割合'], len(seconds)/(end-start))
        np.testing.assert_allclose(row['該当脚の最終収支円'], total)
        assert row['該当脚数'] == len(matched)
        checked.append(dict(銘柄=row['銘柄'], セッション=row['セッション'], 同方向重複秒数=len(seconds),
                            該当脚数=len(matched), 全保有期間収支円=total))
    negative = next(r for r in checked if r['銘柄'] == 'NK225' and r['セッション'] == '2026-09-23_Day')
    assert negative['該当脚数'] == 1 and negative['全保有期間収支円'] == -80000
    result = dict(成功=True, 波銘柄組合せ数=len(checked), 集計=checked,
                  評価意味='方向一致の保有時間の重なり。値幅捕捉率・正答率ではなく、損益は窓外を含む該当脚全期間。',
                  条件再選択=False, API取得数=0,
                  説明ソースSHA256=hashlib.sha256((OUT/'wave_examples.py').read_bytes()).hexdigest())
    (OUT/'指定波照合の独立監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
