"""気配約定・注文手数料・期限・場内返済を、実データ損益とは無関係な合成価格で確認する。"""

import json
from pathlib import Path

import numpy as np

from engine import execute
from fees import order_fee


HERE = Path(__file__).resolve().parent


def make_case(symbol: str = 'TOPIX', side: int = 1) -> tuple[dict, dict, np.ndarray]:
    """機能: 一秒ごとの時計・固定スプレッド・一回の入口から合成入力を作る。

    引数: symbol(str) は数量と費用の契約、side(int) は売買方向。
    返り値: ready/quotes/signals(tuple)。本当の相場データは参照しない。
    """
    times = np.arange(7205, dtype=float)
    seq = np.arange(len(times), dtype=np.int64)
    ready = dict(time_s=times, seq=seq, start=0., limit=7200., session='合成_Day', symbol=symbol, tick=1.)
    quotes = dict(time_s=times.copy(), seq=seq.copy(), mid=np.full(len(times), 100.),
                  bid=np.full(len(times), 99.), ask=np.full(len(times), 101.))
    return ready, quotes, np.asarray([[0., float(side), 5.]])


def set_price(quotes: dict, begin: int, mid: float) -> None:
    """機能: 指定行以降の合成中値と両気配を同じ幅で移動させる。

    引数: quotes(dict)、begin(int)、mid(float)。
    返り値: なし(None)。スプレッドは2のまま維持する。
    """
    quotes['mid'][begin:] = mid
    quotes['bid'][begin:] = mid - 1.
    quotes['ask'][begin:] = mid + 1.


def main() -> None:
    """機能: 合成の期待値・優先順・未来切断・費用境界を照合する。

    引数: なし。
    返り値: なし(None)。日本語の合格証跡を保存する。
    """
    checks = []
    for qty, expected in ((1, 41), (2, 83), (3, 125), (5, 209), (10, 418), (20, 836)):
        assert order_fee('TOPIX', qty) == expected and order_fee('NK225', qty) == 11 * qty
        checks.append(f'一注文の端数切捨て・{qty}枚')
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            for minutes in (30, 45, 60):
                ready, quotes, signals = make_case(symbol, side)
                main_result = execute(ready, quotes, signals, 1, minutes, True)
                reference = execute(ready, quotes, signals, 1, minutes, False)
                qty, value = (5, 1000.) if symbol == 'TOPIX' else (10, 10.)
                assert main_result['cycles'] == reference['cycles'] == 1
                assert main_result['gross_pnl'] == -2 * qty * value
                assert main_result['fees'] == reference['fees'] == 2 * order_fee(symbol, qty)
                assert reference['gross_pnl'] == 0 and reference['net'] == -reference['fees']
                assert main_result['trades'][0, 9] == 4
                assert main_result['trades'][0, 17] == (minutes * 60 + 1) / 60.
                checks.append(f'{symbol}方向{side}・{minutes}分期限の次行約定・独立価格・両道費用')
    # ----------------------------------------
    # 早期返済と実際の建値、気配の判定、追跡の起動を個別に点検する。
    ready, quotes, signals = make_case()
    set_price(quotes, 10, 96.)
    set_price(quotes, 11, 95.)
    stopped = execute(ready, quotes, signals, 1, 30, True)
    middle = execute(ready, quotes, signals, 1, 30, False)
    assert stopped['trades'][0, 9] == 1 and stopped['trades'][0, 1] == 11
    assert stopped['trades'][0, 4] == 101. and stopped['trades'][0, 5] == 94.
    assert middle['trades'][0, 1] == 12.
    checks.append('実ask建値とbid損切り・最低保有なし・中値再生は別判断')
    ready, quotes, signals = make_case()
    set_price(quotes, 10, 110.)
    profit = execute(ready, quotes, signals, 1, 60)
    assert profit['trades'][0, 9] == 2 and profit['trades'][0, 1] == 11
    checks.append('固定1.5幅利確の次行約定')
    ready, quotes, signals = make_case()
    set_price(quotes, 10, 107.5)
    set_price(quotes, 20, 108.)
    rounded = execute(ready, quotes, signals, 1, 60, False)
    assert rounded['trades'][0, 9] == 2 and rounded['trades'][0, 1] == 21.
    checks.append('1.5幅の呼値切上げを中値参考でも同じ境界で適用')
    ready, quotes, signals = make_case()
    set_price(quotes, 10, 107.)
    set_price(quotes, 20, 111.)
    set_price(quotes, 30, 105.)
    set_price(quotes, 31, 104.)
    trail = execute(ready, quotes, signals, 2, 45)
    assert trail['trades'][0, 9] == 3 and trail['trades'][0, 1] == 31.
    assert trail['trades'][0, 5] == 103.
    mirrored = {name: value.copy() for name, value in quotes.items()}
    mirrored['mid'], mirrored['bid'], mirrored['ask'] = 200 - quotes['mid'], 200 - quotes['ask'], 200 - quotes['bid']
    reverse = execute(ready, mirrored, np.asarray([[0., -1., 5.]]), 2, 45)
    assert trail['net'] == reverse['net'] and trail['trades'][0, 1] == reverse['trades'][0, 1]
    checks.append('1幅順行後だけ起動する追跡・売買鏡像')
    ready, quotes, signals = make_case()
    set_price(quotes, 10, 106.)
    set_price(quotes, 20, 101.)
    no_activation = execute(ready, quotes, signals, 2, 30)
    assert no_activation['trades'][0, 9] == 4
    checks.append('1幅未達では追跡を始めない')
    # ----------------------------------------
    # 場内期限、最後の新規、休止、価格情報の未来切断を確認する。
    ready, quotes, signals = make_case()
    forced = execute(ready, quotes, np.asarray([[4000., 1., 5.]]), 1, 60)
    assert forced['trades'][0, 9] == 5 and forced['trades'][0, 1] == 7141.
    checks.append('場内期限60秒前判断・期限以内返済')
    cancelled = execute(ready, quotes, np.asarray([[6899., 1., 5.]]), 1, 60)
    assert cancelled['cycles'] == 0 and cancelled['fees'] == 0 and cancelled['candidate_audit']['cancelled_at_fill'] == 1
    checks.append('次行で最終5分に入った新規は取消・費用なし')
    cooled = execute(ready, quotes, np.asarray([[0., 1., 5.], [1804., 1., 5.], [2102., 1., 5.]]), 1, 30)
    assert cooled['cycles'] == 2 and cooled['candidate_audit']['cooldown'] == 1
    checks.append('返済後5分休止と境界一致の再開')
    for size in (1, 10, 1000, 1802, 2000, 7150):
        part = dict(ready)
        for name in ('seq', 'time_s'):
            part[name] = ready[name][:size]
        part_quotes = {name: value[:size] for name, value in quotes.items()}
        shortened = execute(part, part_quotes, signals, 1, 30, finish=False)
        full = execute(ready, quotes, signals, 1, 30)
        np.testing.assert_array_equal(shortened['orders'], full['orders'][full['orders'][:, 3] < size])
        np.testing.assert_array_equal(shortened['trades'], full['trades'][full['trades'][:, 13] < size])
        checks.append(f'入力切断{size}行の既約定・既返済一致')
    allowed_gap = np.asarray([0, 1, 1000, 7140, 7210])
    allowed_ready = dict(ready, time_s=allowed_gap.astype(float), seq=np.arange(5))
    allowed_quotes = dict(time_s=allowed_ready['time_s'], seq=allowed_ready['seq'], mid=np.full(5, 100.), bid=np.full(5, 99.), ask=np.full(5, 101.))
    gap_fill = execute(allowed_ready, allowed_quotes, np.asarray([[0., 1., 5.]]), 1, 60)
    assert gap_fill['trades'][0, 1] == 7210 and gap_fill['trades'][0, 11] == 7140
    checks.append('任意運用期限後でも監視区間終端前の次実観測行で返済・判断時刻不変')
    gap_indices = np.asarray([0, 1, 1000, 7140, 7500])
    bad_ready = dict(ready, time_s=gap_indices.astype(float), seq=np.arange(5))
    bad_quotes = dict(time_s=bad_ready['time_s'], seq=bad_ready['seq'], mid=np.full(5, 100.), bid=np.full(5, 99.), ask=np.full(5, 101.))
    try:
        execute(bad_ready, bad_quotes, np.asarray([[0., 1., 5.]]), 1, 60)
    except ValueError as error:
        assert '終端以上' in str(error)
    else:
        raise AssertionError('場内返済不能を検出しませんでした')
    checks.append('監視区間の排他的終端以後になる観測空白は補間せず停止')
    result = {'合格': True, '合成検査数': len(checks), '検査': checks, '実データ損益参照': False}
    (HERE / '売買器の合成監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
