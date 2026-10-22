"""早期候補の確定足と期限直前の発注を独立した人工経路で監査する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import early139


HERE = Path(__file__).resolve().parent
CHECKS = []


def check(condition, label):
    """
    機能: 独立に決めた期待値へ照合する。
    引数: condition(bool)、label(str)は結果と内容。
    返り値: None。不一致は例外。
    """
    assert bool(condition), label
    CHECKS.append(label)


def main():
    """
    機能: 初期準備・未確定足・期間境界の新規約定を人工入力で確認する。
    引数: なし。
    返り値: None。早期入口_独立人工確認.jsonへ結果を保存する。
    """
    times = np.array([0., 59., 60., 119., 120., 179., 180., 239., 240.])
    price = np.array([100., 101., 102., 105., 104., 106., 107., 108., 109.])
    good = np.ones(len(times), bool)
    features = early139._minute_features(times, price, good, 0., .5)
    check(np.all(~np.isfinite(features[:6, 0])), '三足確定前に短ATRを公開しない')
    check(abs(features[6, 0]-7./3.) < 1e-10 and features[6, 7] == 3, '三確定足の真の値幅一四二からATRを計算')
    future = price.copy()
    future[6:8] = [999., 998.]
    changed = early139._minute_features(times, future, good, 0., .5)
    check(np.array_equal(features[:8], changed[:8], equal_nan=True), '現在足の極端な変化を確定前ATRへ混ぜない')
    check(features[8, 0] != changed[8, 0], '次足境界に達してから直前足の変化を採用する')
    times2 = times.copy()
    times2[6:] += 180.
    reset = early139._minute_features(times2, price, good, 0., .5)
    check(reset[6, 7] == 0 and not np.isfinite(reset[6, 0]), '欠測で連続足数をリセットする')
    # ----------------------------------------
    # 期限直前の発注は、期限後でも返済予定時刻より前の正常板で約定する。
    times = np.arange(30., dtype=float)
    bid = np.full(30, 100.)
    ask = bid+1.
    good = np.ones(30, bool)
    market = np.zeros((30, 12))
    market[17:, [4, 6]] = .1
    market[17:, [5, 7]] = .3
    market[:, 11] = 1.
    minute = np.ones((30, 9))
    phase = np.zeros(30, np.int64)
    args = [times, bid, ask, good, (bid+ask)/2., np.ones(30), market, minute, minute,
            phase, 0., 20., 25., 0, .05, .2, 2., 30., .25, .5, .1, 600.]
    orders = early139._candidates(*args)
    check(len(orders) == 1 and np.array_equal(orders[0, :2], [20., 19.]), '十九秒判断の新規は期限二十秒の気配で消えず約定')
    good[20:22] = False
    delayed = early139._candidates(*args)
    check(len(delayed) == 1 and np.array_equal(delayed[0, :2], [22., 19.]), '期限を越え二枚の異常板後でも次正常板まで保持')
    no_new = market.copy()
    no_new[:20, 4:8] = 0.
    args[6] = no_new
    check(len(early139._candidates(*args)) == 0, '期限後に初めて成立した支持は新規発注しない')
    result = dict(status='合格', count=len(CHECKS), checks=CHECKS, market_files_read=0,
                  source_sha256=hashlib.sha256((HERE/'early139.py').read_bytes()).hexdigest(),
                  test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'早期入口_独立人工確認.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status='合格', count=len(CHECKS)), ensure_ascii=False))


if __name__ == '__main__':
    main()
