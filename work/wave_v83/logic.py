"""相場の型を人工的に固定し、注文手法が引き受けるリスクを切り分ける。"""
from pathlib import Path
import json
import numpy as np
from engine import run
from catalog import NAMES

HERE = Path(__file__).resolve().parent


def paths():
    """
    機能: 同じ始値から横ばい・一方向・往復・途中反転を作る。
    引数: なし。
    返り値: dict[str,ndarray]。実相場の推定や候補選抜には用いない。
    """
    x = np.arange(1200, dtype=float)
    step = np.floor(x / 10)
    triangle = 16 - np.abs((step % 64) - 32)
    return {
        '無変動': np.full(len(x), 1000.),
        '上昇一方向': 1000 + step,
        '下落一方向': 1000 - step,
        '繰り返す往復': 1000 + triangle - triangle[0],
        '大きな上昇後に全戻し': 1000 + np.where(step < 55, step, 110 - step),
        '小往復を含む上昇': 1000 + np.floor(step / 3) + 4 * ((step % 6) - 3),
    }


def main():
    """
    機能: 12家族を同じ幅4呼値・変数1で人工経路へ適用する。
    引数: なし。
    返り値: None。費用なしと費用ありの結果をJSONへ保存する。
    """
    records = []
    for label, p in paths().items():
        n = len(p)
        t = np.arange(n, dtype=float)
        for spread, fee, mode in ((0., 0., '値動きだけ'), (1., .0418, '気配差1呼値と片道料金あり')):
            record = (t, p, p - spread / 2, p + spread / 2, np.arange(n), np.arange(n, dtype=np.int32),
                      np.ones(n, bool), np.ones(n, bool), 1., 0., float(n), float(n - 100))
            for family in range(12):
                orders, trades, curve, stats, events = run(record, family, 4, 1, 10, 1000., fee * 1000, 0., 0, 0.)
                assert np.sum(stats[4:8]) == 0
                records.append(dict(経路=label, 費用=mode, family=family, 手法=NAMES[family],
                                    損益円=float(curve[-1]), 決済脚数=len(trades),
                                    手数料円=float(orders[:, 8].sum()),
                                    最大清算時価下落=float(np.max(np.maximum.accumulate(np.r_[0., curve])[1:] - curve))))
    out = HERE / 'theory/人工相場による注文手法の性質.json'
    out.write_text(json.dumps(dict(用途='候補を選ぶテストではなく、注文手法が利益に換える値動きと弱点を説明する対照。人工経路に時間予測の入力はしない。',
                                  条件='呼値1・幅4・上限10・倍率1000、variant1共通。実データの金額とは比較しない。',
                                  rows=records), ensure_ascii=False, indent=2), encoding='utf-8')
    print('人工6経路・12家族・2費用条件の144対照を保存しました。')


if __name__ == '__main__':
    main()
