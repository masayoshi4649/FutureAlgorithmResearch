"""市場ファイルを使わず、複数段と玉別追尾の因果性を独立した経路で検査する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import engine139
from audit139 import conditions, ledger


HERE = Path(__file__).resolve().parent
CHECKS = []


def check(condition, label):
    """
    機能: 期待値との一致を記録する。
    引数: condition(bool)は検査結果、label(str)は検査内容。
    返り値: None。不一致の場合は例外。
    """
    assert bool(condition), label
    CHECKS.append(label)


def fixture(length=80, partial=None):
    """
    機能: 二市場支持と元親の通知を持つ人工入力を作る。
    引数: length(int)は行数、partial(int|None)は親半数返済行。
    返り値: dictは市場ファイルに依存しない配列。
    """
    times = np.arange(length, dtype=float)
    bid = np.full(length, 1006.)
    bid[1] = 1000.
    market = np.zeros((length, 12))
    market[:, [4, 6]] = .1
    market[:, [5, 7]] = .3
    market[:, 8] = times-.5
    market[:, 11] = 1.
    orders = [[1, 0, 1, 1, 10, 1001., 1, 1, 0, 385]]
    if partial is not None:
        orders.append([partial, partial-1, 1, -1, 5, bid[partial], 2, 0, 0, 192])
    orders.append([length-1, length-2, 1, -1, 5 if partial is not None else 10,
                   bid[-1], 3, 0, 0, 192 if partial is not None else 385])
    return dict(times=times, quotes=dict(bid=bid, ask=bid+1, quote_valid=np.ones(length, bool)),
                atr=np.full(length, 20.), market=market, phase=np.ones(length, np.int64),
                core=np.array(orders, dtype=float))


def prices(data, values):
    """
    機能: 指定行から次の指定まで価格を変更し、元親約定も一致させる。
    引数: data(dict)は人工入力、values(dict[int,float])は切替行と買気配。
    返り値: dictは変更後の同じ入力。
    """
    for row, price in sorted(values.items()):
        data['quotes']['bid'][row:] = price
        data['quotes']['ask'][row:] = price+1
    for order in data['core']:
        row = int(order[0])
        order[5] = data['quotes']['ask'][row] if order[3] > 0 else data['quotes']['bid'][row]
    return data


def run(data, **changes):
    """
    機能: 事前固定の人工条件で一親を試し、独立会計を必ず通す。
    引数: data(dict)は人工入力、changes(dict)は条件差分。
    返り値: ndarrayは十列注文。
    """
    config = dict(initial=2, target=5, increments=[3], steps=[.25],
                  support_hold=2., min_after_initial=0., risk_floor=20.,
                  fee_tenths=385, multiplier=100)
    config.update(changes)
    result = engine139.replay(**data, config=config)
    q = data['quotes']
    ledger(result, data['times'], q['bid'], q['ask'], q['quote_valid'],
           config['fee_tenths'], config['multiplier'])
    conditions(result, data['times'], q['bid'], q['ask'], q['quote_valid'], data['atr'], data['market'], config)
    return result


def clone(data):
    """
    機能: 人工入力の全配列を独立コピーする。
    引数: data(dict)は人工入力。
    返り値: dictは変更が元へ伝わらないコピー。
    """
    return {key: {k: v.copy() for k, v in value.items()} if isinstance(value, dict)
            else value.copy() for key, value in data.items()}


def main():
    """
    機能: 複数段、玉別利益、競合、再追加の境界と鏡映・接頭を検査する。
    引数: なし。
    返り値: None。人工確認_独立.jsonを保存する。
    """
    d = fixture()
    simple = run(d)
    added = simple[(simple[:, 7] == 1) & (simple[:, 8] > 0)]
    check(len(added) == 1 and np.array_equal(added[0, :5], [5, 4, 1, 1, 3]), '新peerと二秒支持後の次行に三枚追加')
    check(np.all(simple[:, 9] == np.floor(simple[:, 4]*38.5)), '注文ごとの料金切捨て')
    # ----------------------------------------
    # 段ごとに新観測と待機が必要。同じ行で全段が執行されない。
    d = prices(fixture(), {2: 1016.})
    stepped = run(d, increments=[1, 1, 1], steps=[.25, .5, .75])
    added = stepped[(stepped[:, 7] == 1) & (stepped[:, 8] > 0)]
    check(np.array_equal(added[:, 0], [5., 9., 13.]), '三段の支持確認は前段約定後から再起算')
    check(np.array_equal(added[:, 8], [1., 2., 3.]), '各段は別UIDで一枚ずつ')
    delayed = clone(d)
    delayed['times'][3:] += 30.
    delayed['market'][:, 8] = delayed['times']-.5
    gap = run(delayed, increments=[1, 1, 1], steps=[.25, .5, .75])
    check(gap[(gap[:, 7] == 1) & (gap[:, 8] == 1)][0, 0] == 6, '十五秒超の欠測で支持持続を再起算')
    equal_peer = clone(d)
    equal_peer['market'][:, 8] = equal_peer['times']-1.
    delayed_peer = run(equal_peer, increments=[1, 1, 1], steps=[.25, .5, .75])
    check(delayed_peer[(delayed_peer[:, 7] == 1) & (delayed_peer[:, 8] == 1)][0, 0] == 6, '前段約定と同秒peerを新しい支持へ数えない')
    for split in range(2, 30):
        future = clone(d)
        future['quotes']['bid'][split:] += 300.
        future['quotes']['ask'][split:] += 300.
        for order in future['core']:
            if order[0] >= split:
                order[5] += 300.
        changed = run(future, increments=[1, 1, 1], steps=[.25, .5, .75])
        check(np.array_equal(stepped[stepped[:, 0] < split], changed[changed[:, 0] < split]), f'未来{split}行以後の変更で過去注文不変')
    # ----------------------------------------
    # 自分の約定より前の高値では起動せず、初回は元の出口を守る。
    d = prices(fixture(), {2: 1100., 3: 1006., 7: 1015., 9: 990.})
    out = run(d, exit_activation=[0., 1.], exit_width=[1., .5])
    check(not np.any(out[:, 6] == 1391), '追加前高値と追加自身の未達順行で利益追尾しない')
    d = prices(fixture(), {6: 1027., 7: 1017., 8: 1016.})
    out = run(d, exit_activation=[0., 1.], exit_width=[1., .5])
    trail = out[out[:, 6] == 1391]
    check(len(trail) == 1 and np.array_equal(trail[0, :6], [8, 7, 1, -1, 3, 1016]), '追撃自身20円順行と10円戻りで次気配返済')
    check(np.array_equal(out[out[:, 8] == 0], simple[simple[:, 8] == 0]) is False, '人工価格変更は親最終価格へも反映')
    check(not np.any((out[:, 8] == 0) & (out[:, 6] >= 1390)), '追撃だけの利益保護は初回玉へ伝播しない')
    # ----------------------------------------
    # 後の段ほど狭い利益追尾が同じ高値から異なる戻りで順に発動する。
    d = prices(fixture(), {6: 1011., 10: 1016., 14: 1057., 15: 1052., 16: 1051.,
                          17: 1047., 18: 1046., 19: 1042., 20: 1041.})
    out = run(d, increments=[1, 1, 1], steps=[.25, .5, .75],
              exit_activation=[0., 1., 1., 1.], exit_width=[1., .75, .5, .25])
    exits = out[out[:, 6] == 1391]
    check(np.array_equal(exits[:, [0, 1, 8]], [[16., 15., 3.], [18., 17., 2.], [20., 19., 1.]]),
          '後玉ほど狭幅の利益追尾が三段を別々の境界で返す')
    d = prices(fixture(), {6: 1037., 7: 1032., 8: 1047., 9: 1037., 10: 1036.})
    wide = run(d, exit_activation=[0., 1.5], exit_width=[1., 1.])
    tight = run(d, exit_activation=[0., 1.5], exit_width=[1., 1.],
                tighten_at=[0., 2.], tight_width=[1., .5])
    check(not np.any(wide[:, 6] == 1391), '広幅対照は四十円順行後の十一円戻りを維持')
    check(tight[tight[:, 6] == 1391][0, 0] == 10, '二R順行後に幅を半分へ変更する境界')
    changed_atr = clone(d)
    changed_atr['atr'][1:] = 500.
    unchanged = run(changed_atr, exit_activation=[0., 1.5], exit_width=[1., 1.],
                    tighten_at=[0., 2.], tight_width=[1., .5])
    check(np.array_equal(tight, unchanged), 'Rは初回判断行で固定し保有後ATRへ置換しない')
    # ----------------------------------------
    # 約定は次正常行。利確線を割り込んだ約定を利益へ水増ししない。
    d = prices(fixture(), {6: 1027., 7: 1017., 8: 1016.})
    d['quotes']['quote_valid'][8] = False
    d['quotes']['bid'][9] = np.nan
    d['quotes']['ask'][9] = np.nan
    out = run(d, exit_activation=[0., 1.], exit_width=[1., .5])
    trail = out[out[:, 6] == 1391]
    check(len(trail) == 1 and trail[0, 0] == 10 and trail[0, 1] == 7, '無効板二行を飛ばし発注保持')
    d = prices(fixture(), {6: 1027., 7: 1017., 8: 980.})
    out = run(d, exit_activation=[0., 1.], exit_width=[1., .5])
    trail = out[out[:, 6] == 1391]
    check(trail[0, 5] == 980., '利益保護注文が次板で損失約定する現象を保持')
    d = prices(fixture(), {6: 980.})
    stopped = run(d, stop_width=[1., .5], exit_activation=[0., 1.], exit_width=[1., .5])
    check(len(stopped[stopped[:, 6] == 1392]) == 2 and not np.any(stopped[:, 6] == 1391),
          '独自損切りと順行後利益保護の理由を分離')
    d = prices(fixture(), {6: 1027., 7: 1017., 8: 1016., 10: 1050., 11: 1020.})
    partial_profit = run(d, exit_activation=[0., 1.], exit_width=[1., .5], profit_take=1)
    check(len(partial_profit[partial_profit[:, 6] == 1391]) == 1 and
          partial_profit[partial_profit[:, 6] == 1391][0, 4] == 1, '部分利益保護は一枚を一度だけ返済')
    # ----------------------------------------
    # 元親の全返済は玉別予約より優先し、二重返済しない。
    d = prices(fixture(length=9), {6: 1027., 7: 1017., 8: 1016.})
    out = run(d, exit_activation=[0., 1.], exit_width=[1., .5])
    check(not np.any(out[:, 6] == 1391), '親全返済と玉別予約の競合は親優先')
    d = prices(fixture(partial=8), {6: 1027., 7: 1017., 8: 1016., 9: 1015.})
    out = run(d, exit_activation=[0., 1.], exit_width=[1., .5])
    trail = out[out[:, 6] == 1391]
    check(len(trail) == 1 and trail[0, 0] == 9 and trail[0, 4] == 2, '親半数返済後は残二枚だけ再予約')
    # ----------------------------------------
    # 初回を待つ指定は部分返済だけを遅らせ、親最終返済には従う。
    d = prices(fixture(partial=20), {2: 1016.})
    waited = run(d, increments=[1, 1, 1], steps=[.25, .5, .75], initial_wait=True)
    normal = run(d, increments=[1, 1, 1], steps=[.25, .5, .75])
    check(not np.any((waited[:, 0] == 20) & (waited[:, 8] == 0)), '初回waitは親部分返済を回避')
    check(normal[(normal[:, 0] == 20) & (normal[:, 8] == 0)][0, 4] == 1, '通常初回は半数へ減少')
    check(waited[(waited[:, 0] == 79) & (waited[:, 8] == 0)][0, 4] == 2, '初回waitでも親最終で全返済')
    check(sum(normal[(normal[:, 0] == 20) & (normal[:, 7] == 0), 4]) == 2, '総量比例では五枚を三枚へ減らす')
    legacy = run(d, increments=[1, 1, 1], steps=[.25, .5, .75], partial_allocation='legacy')
    check(sum(legacy[(legacy[:, 0] == 20) & (legacy[:, 7] == 0), 4]) == 1, '旧玉別丸めでは初回一枚だけ返済する違いを保持')
    # ----------------------------------------
    # 利確後の再追加には新極値と退出後支持が必要。新しいUIDはpeakを継承しない。
    d = prices(fixture(), {6: 1027., 7: 1017., 8: 1016., 12: 1033., 17: 1032., 18: 1031.})
    config = dict(exit_activation=[0., 1., 1.], exit_width=[1., .5, .5],
                  recycle_rounds=1, cooldown=2., recycle_step=.25)
    out = run(d, **config)
    readds = out[out[:, 6] == 1393]
    check(len(readds) == 1 and readds[0, 0] == 13 and readds[0, 4] == 3 and readds[0, 8] == 2, '利確後新高値で新UIDに三枚を再追加')
    check(not np.any((out[:, 8] == 2) & (out[:, 6] == 1391)), '再追加は旧玉のpeakを継承せず小戻りでは未起動')
    blocked = clone(d)
    blocked['market'][9:, 8] = 7.
    out_blocked = run(blocked, **config)
    check(not np.any(out_blocked[:, 6] == 1393), '退出より古いpeer支持を再追加へ流用しない')
    d = prices(fixture(), {6: 1027., 7: 1017., 8: 980., 12: 1050.})
    out_loss = run(d, **config)
    check(not np.any(out_loss[:, 6] == 1393), '利益追尾が実損失約定なら再追加creditを付けない')
    # ----------------------------------------
    # 売買鏡像と商品倍率を変えても方向・数量の状態遷移は対称。
    d = prices(fixture(), {6: 1027., 7: 1017., 8: 1016., 12: 1033., 17: 1032.})
    out = run(d, **config)
    mirrored = clone(d)
    mirrored['quotes']['bid'] = 3000.-d['quotes']['ask']
    mirrored['quotes']['ask'] = 3000.-d['quotes']['bid']
    mirrored['market'][:, [4, 5, 6, 7]] *= -1
    mirrored['core'][:, 3] *= -1
    mirrored['core'][:, 5] = 3000.-d['core'][:, 5]
    reflected = run(mirrored, **config)
    expected = out.copy()
    expected[:, 3] *= -1
    expected[:, 5] = 3000.-expected[:, 5]
    check(np.array_equal(reflected, expected), '売買鏡像で新規・利確・再追加が完全対称')
    topix = run(d, **config, fee_tenths=418, multiplier=1000)
    check(np.array_equal(topix[:, :9], out[:, :9]), '料金倍率の変更だけで機械的な方向判定を変えない')
    check(np.all(topix[:, 9] == np.floor(topix[:, 4]*418/10)), 'TOPIX注文料金の整数化')
    result = dict(status='合格', count=len(CHECKS), checks=CHECKS,
                  engine_sha256=hashlib.sha256((HERE/'engine139.py').read_bytes()).hexdigest(),
                  test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), market_files_read=0)
    (HERE/'人工確認_独立.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status=result['status'], checks=len(CHECKS)), ensure_ascii=False))


if __name__ == '__main__':
    main()
