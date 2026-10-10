"""実データ損益の計算前に、追加玉・予算・期限・費用の売買会計を人工経路で検査する。"""

import json
from pathlib import Path

import numpy as np

import engine


HERE = Path(__file__).resolve().parent


def example(prices: list[float], symbol: str = 'TOPIX', side: int = 1, mode: str = 'A1',
            minutes: int = 5, signals_at: tuple = (1,), quote_mode: bool = True, exit_mode: int = 0) -> dict:
    """機能: 指定した中値経路だけの小さな人工口座を作って再生する。

    引数: prices(list[float])、symbol/mode(str)、side/minutes(int)、signals_at(tuple)、quote_mode(bool)。
    返り値: 人工経路の売買結果(dict)。原本ファイル・APIを使用しない。
    """
    mids = np.array(prices, float)
    if side < 0:
        mids = 2000. - mids
    times = np.arange(len(mids), dtype=float) * 60.
    seq = np.arange(len(mids), dtype=np.int64)
    ready = dict(seq=seq, time_s=times, start=0., limit=times[-1] - 240., tick=1., symbol=symbol, session='2026-09-21_Day')
    quotes = dict(seq=seq, time_s=times, mid=mids, bid=mids - .5, ask=mids + .5)
    config = dict(fraction=.01, initial_fraction=.2 if mode == 'A0' else .5, pyramid=mode == 'A2',
                  cooldown_minutes={'A0': 30, 'A1': 10, 'A2': 0}[mode], minutes=minutes, exit_mode=exit_mode)
    signals = np.array([(i, side, 10.) for i in signals_at], float).reshape(-1, 3)
    return engine.execute(ready, quotes, signals, config, quote_mode)


def main() -> None:
    """機能: 方向鏡像・気配/中値・段階追加・停止・期限を合成ケースで検査する。

    引数: なし。
    返り値: なし(None)。証跡JSONを保存し、失敗したら例外で停止する。
    """
    checks = []
    flat = [1000.] * 31
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            for quote_mode in (True, False):
                result = example(flat, symbol, side, quote_mode=quote_mode)
                assert result['cycles'] == 1 and result['reasons']['初回からの保有期限']['cycles'] == 1
                assert result['hold_min_minutes'] == 6.
                assert result['gross'] < 0 if quote_mode else result['gross'] == 0
                checks.append(f'{symbol}_{side}_{quote_mode}_期限と費用')
                trend = [1000.] * 3 + [1012., 1022., 1032., 1042., 1042., 1030.] + [1030.] * 22
                result = example(trend, symbol, side, 'A2', 60, quote_mode=quote_mode)
                entries = result['orders'][result['orders'][:, 4] != 2]
                unit = 1 if symbol == 'TOPIX' else 2
                np.testing.assert_array_equal(entries[:, 6], np.array([5, 2, 2, 1]) * unit)
                assert result['max_long_qty' if side > 0 else 'max_short_qty'] == 10 * unit
                assert result['cycles'] == 1 and result['lot_trades'] == 4 and result['additions'] == 3
                assert result['reasons']['順行後の追跡返済']['cycles'] == 1
                assert result['trades'][-1, 8] < 0 and np.all(result['trades'][:, 22] == 120.)
                checks.append(f'{symbol}_{side}_{quote_mode}_追加と保護線')
                budget = [1000.] * 3 + [920.] * 28
                result = example(budget, symbol, side, 'A2', 60, (1, 8), quote_mode)
                assert result['halted'] and result['cycles'] == 1
                assert result['reasons']['日内損失予算']['cycles'] == 1 and result['candidate_audit']['halted'] == 1
                checks.append(f'{symbol}_{side}_{quote_mode}_予算と再参加停止')
    result = example([1000.] * 3 + [1012.] * 28, mode='A2', minutes=5)
    assert result['additions'] == 1 and result['hold_max_minutes'] == 6
    assert result['reasons']['初回からの保有期限']['cycles'] == 1
    checks.append('追加で初回期限を延長しない')
    result = example(flat, mode='A0', minutes=5, signals_at=(1, 10))
    assert result['cycles'] == 1 and result['candidate_audit']['cooldown'] == 1
    checks.append('低積極度の休止')
    result = example(flat, mode='A2', minutes=5, signals_at=(1, 10))
    assert result['cycles'] == 2 and result['candidate_audit']['cooldown'] == 0
    checks.append('高積極度の再参加')
    result = example(flat, mode='A1', minutes=240)
    assert result['reasons']['場内返済']['cycles'] == 1
    checks.append('長期期限でも場内返済')
    for side in (1, -1):
        small = example([1000.] * 3 + [1006.] * 28, side=side, minutes=60, exit_mode=1)
        assert small['reasons']['固定回収']['cycles'] == 1
        checks.append(f'{side}_半幅固定回収')
        protection = example([1000.] * 3 + [1006., 1002., 1001., 1001.] + [1001.] * 24,
                             side=side, minutes=60, exit_mode=2)
        assert protection['reasons']['費用を含む建値保護']['cycles'] == 1
        assert protection['net'] < 0  # 次行の飛越えで保護価格を割る場合も現実どおり損失になる。
        checks.append(f'{side}_保護線は次行利益の保証ではない')
    record = {'合格': True, '検査数': len(checks), '検査': checks, '実データ損益計算': False,
              '価格': '全て人工データ', '将来値使用': False}
    (HERE / '売買器の合成監査.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    main()
