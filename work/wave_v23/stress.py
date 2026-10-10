"""過去価格から作った単純な方向信号による、注文管理単体の合成ストレス。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from audit_core import check_accounting


def synthetic_ready(pattern: str, day: int, symbol: str) -> tuple[dict, np.ndarray]:
    """機能: 既知の人工価格経路と、過去 20 分の値動きによる方向信号を作る。

    引数: pattern (str)、day (int)、symbol (str)。
    返り値: 原本形式入力と因果的な単純方向信号 (tuple[dict, ndarray])。
    ATR は相場開始前から既知の一定幅と仮定し、市場推定精度は検証対象にしない。
    """
    seconds = np.arange(0., 24901., 10.)
    elapsed = seconds / 24600.
    base = 4000.
    ripple = 3. * np.sin(seconds / 110.)
    if pattern == '毎日下落':
        delta = -60 * elapsed + ripple
        base -= 60 * day
    elif pattern == '毎日上昇':
        delta = 60 * elapsed + ripple
        base += 60 * day
    elif pattern == '滑らかな単調下落':
        delta = -60 * elapsed
        base -= 60 * day
    elif pattern == '滑らかな単調上昇':
        delta = 60 * elapsed
        base += 60 * day
    elif pattern == '下落後の大回復':
        delta = np.where(elapsed <= .55, -90 * elapsed / .55, -90 + 110 * (elapsed - .55) / .45) + ripple
    elif pattern == '上昇後の大反落':
        delta = -np.where(elapsed <= .55, -90 * elapsed / .55, -90 + 110 * (elapsed - .55) / .45) + ripple
    elif pattern == '往復レンジ':
        delta = 14 * np.sin(seconds / 700.) + 3 * np.sin(seconds / 70.)
    elif pattern == '変動拡大と反転':
        delta = (3 + 22 * elapsed) * np.sin(seconds / 1100.) + 3 * np.sin(seconds / 80.)
    else:
        raise ValueError('未定義の人工経路です')
    scale = 1. if symbol == 'TOPIX' else 20.
    tick = .5 * scale
    price = np.round((base + delta) * scale / tick) * tick
    start = 1800000000. + day * 86400.
    ready = dict(symbol=symbol, session=f'人工_{day + 1:02d}_Day', time_s=start + seconds,
                 last=price, atr=np.full(len(price), 10. * scale), seq=np.arange(len(price)),
                 tick=tick, start=start, limit=start + 24600., us_open=start + 60000.)
    direction = np.zeros(len(price), dtype=np.int8)
    # 現在から 20 分前までに観測した価格だけで判定する。未来の人工形状は使わない。
    past_change = price[120:] - price[:-120]
    direction[120:] = np.where(np.abs(past_change) >= 2 * scale, np.sign(past_change), 0).astype(np.int8)
    return ready, direction


def run_synthetic(engine, managers, configurations: list[dict] | None = None) -> dict:
    """機能: 8 経路を 10 セッションずつ、順方向と誤方向の信号で再生する。

    引数: engine/managers (module)、configurations (list[dict]|None) は管理条件の候補。
    返り値: 各条件の人工経路別損益・最大下落・会計検算 (dict)。
    """
    specifications = managers.manager_catalog() if configurations is None else configurations
    patterns = ['毎日下落', '毎日上昇', '下落後の大回復', '上昇後の大反落', '往復レンジ',
                '変動拡大と反転', '滑らかな単調下落', '滑らかな単調上昇']
    rows = []
    for spec in specifications:
        for symbol in ('TOPIX', 'NK225'):
            for pattern in patterns:
                for mode, sign in [('過去方向へ追随', 1), ('過去方向に逆らう', -1)]:
                    daily, drawdowns, winning, losing, qty_max, trade_count = [], [], [], [], 0, 0
                    for day in range(10):
                        ready, direction = synthetic_ready(pattern, day, symbol)
                        config = managers.make_config(spec, symbol, ready)
                        result = engine.run(ready, direction * sign, config, detail=True)
                        check_accounting(ready, result, config)
                        unit = ready['atr'][0]
                        daily.append(float(result['stats'][0] / unit))
                        drawdowns.append(float(result['stats'][1] / unit))
                        winning.append(float(np.maximum(result['trades'][:, 10], 0.).sum() / unit))
                        losing.append(float(-np.minimum(result['trades'][:, 10], 0.).sum() / unit))
                        qty_max = max(qty_max, int(max(result['stats'][2:4])))
                        trade_count += len(result['trades'])
                    rows.append(dict(管理ID=spec['id'], 管理名=spec['name'], 銘柄=symbol, 経路=pattern,
                                     単純信号=mode, セッション数=10, 合計ATR枚=float(sum(daily)),
                                     総利益ATR枚=float(sum(winning)), 総損失ATR枚=float(sum(losing)),
                                     最悪セッションATR枚=float(min(daily)), 最大時価下落ATR枚=float(max(drawdowns)),
                                     黒字セッション数=int(sum(value > 0 for value in daily)),
                                     最大片方向枚数=qty_max, 返済件数=trade_count, 日別ATR枚=daily))
    return dict(評価対象='注文管理単体の合成ストレス。実際の板・足の信号全体の成績ではない。',
                前提='価格は人工。ATR は既知の一定幅。方向は現在と 20 分前の価格のみから判定。費用 0・指定価格約定。',
                単位='価格損益 ÷ 当日の既知ATR。数量を掛けたATR枚なので、管理間のリスク差も併せて読む。',
                合格=True, 原本不変=True, API取得回数=0, 結果=rows)


if __name__ == '__main__':
    import engine
    import managers

    output = run_synthetic(engine, managers)
    target = Path(__file__).resolve().parent / '合成ストレス.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(保存=str(target), 結果件数=len(output['結果'])), ensure_ascii=False))
