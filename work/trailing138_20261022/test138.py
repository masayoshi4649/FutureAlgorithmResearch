"""市場資料を読まず、玉別利益追尾を独立した人工経路で検査する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import overlay138


HERE = Path(__file__).resolve().parent
CHECKS = []


def verify(condition, label):
    """
    機能: 外部で指定した期待結果と実際の出力を照合する。
    引数: condition(bool)は照合結果、label(str)は検査内容。
    返り値: None。不一致時はAssertionErrorを送出する。
    """
    assert bool(condition), label
    CHECKS.append(label)


def fixture(length=20, partial=None):
    """
    機能: 初回二枚と追加三枚、親最終返済の人工注文を作る。
    引数: length(int)は原行数、partial(int|None)は親の途中返済行。
    返り値: dictは人工原行配列と十列注文。市場ファイルは参照しない。
    """
    bid = np.full(length, 105.0)
    bid[1] = 100.0
    bid[-1] = 150.0
    orders = [[1, 0, 1, 1, 2, 101., 1, 1, 0, 77],
              [4, 3, 1, 1, 3, 106., 901, 1, 1, 115]]
    if partial is not None:
        orders.extend([[partial, partial-1, 1, -1, 1, bid[partial], 2, 0, 0, 38],
                       [partial, partial-1, 1, -1, 1, bid[partial], 2, 0, 1, 38]])
    for leg, qty in ((0, 2), (1, 3)):
        if partial is not None:
            qty -= 1
        orders.append([length-1, length-2, 1, -1, qty, bid[-1], 3, 0, leg, qty*385//10])
    return dict(times=np.arange(length, dtype=float), bid=bid, ask=bid+1,
                valid=np.ones(length, dtype=bool), atr=np.full(length, 20.),
                original=np.array(orders, dtype=float))


def reset_quotes(data, changes):
    """
    機能: 人工の買気配を差し替え、対応する売気配と元通知価格を揃える。
    引数: data(dict)は人工入力、changes(dict[int,float])は変更原行と価格。
    返り値: dictは同じ入力。買売気配差は一円とする。
    """
    for row, value in changes.items():
        data['bid'][row] = value
        data['ask'][row] = value+1
    for order in data['original']:
        row = int(order[0])
        order[5] = data['ask'][row] if order[3] > 0 else data['bid'][row]
    return data


def execute(data, activation=1., width=.5, tighten_at=0., tight_width=.5, protect=0):
    """
    機能: 金融資料を使わず人工の一親を検証対象へ渡す。
    引数: data(dict)、activation/width/tighten_at/tight_width(float)、protect(int)。
    返り値: ndarrayは検証対象が生成した十列注文。
    """
    args = [data[k] for k in ('times', 'bid', 'ask', 'valid', 'atr', 'original')]
    return overlay138.campaign(*args, activation, width, tighten_at, tight_width, protect)


def artificial_ledger(orders):
    """
    機能: 独立した数量台帳と現金会計で人工注文を検算する。
    引数: orders(ndarray)は十列の人工注文。
    返り値: tuple[float,float]は現金収支と各建玉の差額から求めた収支。
    """
    tickets = {}
    cash = 0.
    gains = 0.
    fees = 0.
    for order in orders:
        row, decision, parent, side, quantity = map(int, order[:5])
        price, new, leg, fee = order[5], int(order[7]), int(order[8]), int(order[9])
        assert decision < row and quantity > 0 and fee == quantity*385//10
        cash -= side*quantity*price*100.
        fees += fee
        key = (parent, leg)
        if new:
            assert key not in tickets or tickets[key][0] == 0
            tickets[key] = [quantity, price, side]
        else:
            old = tickets[key]
            assert old[0] >= quantity and old[2] == -side
            gains += old[2]*quantity*(price-old[1])*100.
            old[0] -= quantity
    assert all(ticket[0] == 0 for ticket in tickets.values())
    return cash-fees, gains-fees


def audit_invariants(data, result, label):
    """
    機能: 入口固定、初回維持、注文料、次正常行、完結会計を独立検査する。
    引数: data(dict)、result(ndarray)、label(str)は人工ケースと結果。
    返り値: None。各検査を一覧へ追加する。
    """
    old = data['original']
    verify(np.array_equal(result[result[:, 7] == 1], old[old[:, 7] == 1]), label+'・全入口固定')
    verify(np.array_equal(result[result[:, 8] != 1], old[old[:, 8] != 1]), label+'・初回玉固定')
    new_exits = result[result[:, 6] == 1381]
    verify(len(new_exits) <= 1, label+'・利益保護は一度だけ')
    for row in new_exits:
        fill, decision = map(int, row[:2])
        available = [i for i in range(decision+1, fill+1)
                     if data['valid'][i] and np.isfinite(data['bid'][i]) and np.isfinite(data['ask'][i])
                     and 0 < data['bid'][i] < data['ask'][i]]
        verify(bool(available) and available[0] == fill, label+'・次正常行でのみ返済')
        verify(row[5] == (data['ask'][fill] if row[3] > 0 else data['bid'][fill]), label+'・実気配約定')
    cash, gains = artificial_ledger(result)
    verify(abs(cash-gains) < 1e-8, label+'・全決済と独立二会計一致')


def main():
    """
    機能: 利益追尾の境界・優先順・数量・未来不参照を人工データで検査する。
    引数: なし。
    返り値: None。人工確認.jsonへソース指紋と全検査項目を保存する。
    """
    # ----------------------------------------
    # 未起動の損失は親出口へ委ね、追加前の極値を流用しない。
    d = reset_quotes(fixture(), {2: 200., 5: 125., 6: 90., 19: 80.})
    result = execute(d)
    verify(np.array_equal(result, d['original']), '追加前高値と起動未満19円の順行では独自返済なし')
    audit_invariants(d, result, '未起動')
    for activation in (0., -1.):
        result = execute(d, activation=activation)
        verify(np.array_equal(result, d['original']), f'起動{activation}の無効対照は元通知と完全一致')

    # ----------------------------------------
    # 起動と戻り幅の境界を事前に固定し、約定行は手計算する。
    d = reset_quotes(fixture(), {5: 126., 6: 117., 7: 116., 8: 115.})
    result = execute(d)
    exits = result[result[:, 6] == 1381]
    verify(len(exits) == 1 and np.array_equal(exits[0, :6], [8, 7, 1, -1, 3, 115.]),
           '20円で起動し10円戻り境界で予約した翌正常行に三枚返済')
    audit_invariants(d, result, '境界')
    mirror = {key: value.copy() for key, value in d.items()}
    mirror['bid'], mirror['ask'] = 400.-d['ask'], 400.-d['bid']
    mirror['original'][:, 3] *= -1
    mirror['original'][:, 5] = 400.-d['original'][:, 5]
    mirrored = execute(mirror)
    expected = result.copy()
    expected[:, 3] *= -1
    expected[:, 5] = 400.-expected[:, 5]
    verify(np.array_equal(mirrored, expected), '買い売り鏡像で全約定が対称')
    audit_invariants(mirror, mirrored, '売り鏡像')

    # ----------------------------------------
    # 高値更新で利益床は有利側に動き、追尾幅の段階短縮を検査する。
    d = reset_quotes(fixture(), {5: 136., 6: 131., 7: 146., 8: 137., 9: 136., 10: 135.})
    wide = execute(d, activation=1.5, width=1., tighten_at=0.)
    tight = execute(d, activation=1.5, width=1., tighten_at=2., tight_width=.5)
    verify(not np.any(wide[:, 6] == 1381) or wide[wide[:, 6] == 1381][0, 0] > 10,
           '幅20円対照は40円順行後の10円戻りで返さない')
    exits = tight[tight[:, 6] == 1381]
    verify(len(exits) == 1 and exits[0, 1] == 9 and exits[0, 0] == 10,
           '40円順行後に幅10円へ短縮して指定境界で予約')
    audit_invariants(d, tight, '段階短縮')

    # ----------------------------------------
    # 不正板は極値にも約定にも使わず、予約を保持して正常行を待つ。
    d = reset_quotes(fixture(), {5: 126., 6: 117., 7: 116., 8: 160., 9: 170., 10: 114.})
    d['valid'][8] = False
    d['bid'][9] = np.nan
    result = execute(d)
    exits = result[result[:, 6] == 1381]
    verify(len(exits) == 1 and exits[0, 0] == 10 and exits[0, 1] == 7,
           '欠測と無効行を二行越え次正常行で予約執行')
    audit_invariants(d, result, '欠測予約')
    d = reset_quotes(fixture(), {5: 200., 6: 115., 19: 110.})
    d['valid'][5] = False
    result = execute(d)
    verify(np.array_equal(result, d['original']), '無効行の高値は起動に利用しない')
    d = reset_quotes(fixture(), {5: 200., 6: 115., 19: 110.})
    d['ask'][5] = d['bid'][5]
    verify(np.array_equal(execute(d), d['original']), '同値の異常気配は起動に利用しない')

    # ----------------------------------------
    # 親返済は優先し、取消後も残玉だけが新たに返済予約可能。
    d = reset_quotes(fixture(length=9), {5: 126., 6: 117., 7: 116., 8: 115.})
    result = execute(d)
    verify(np.array_equal(result, d['original']), '親最終返済と独自予約約定の競合で二重返済しない')
    audit_invariants(d, result, '全返済優先')
    d = reset_quotes(fixture(partial=8), {5: 126., 6: 117., 7: 116., 8: 115., 9: 114.})
    result = execute(d)
    exits = result[result[:, 6] == 1381]
    verify(len(exits) == 1 and exits[0, 0] == 9 and exits[0, 1] == 8 and exits[0, 4] == 2,
           '親部分返済が予約を取消し残二枚を当行再予約して次行返済')
    audit_invariants(d, result, '部分返済優先')
    for protect in (1, 2, 3, 9):
        d = reset_quotes(fixture(partial=12), {5: 126., 6: 117., 7: 116., 8: 115.,
                                               9: 146., 10: 106., 11: 105.})
        result = execute(d, protect=protect)
        exits = result[result[:, 6] == 1381]
        verify(len(exits) == 1 and exits[0, 4] == min(3, protect), f'部分保護{protect}枚は上限内で一度のみ')
        final = result[(result[:, 8] == 1) & (result[:, 7] == 0)]
        verify(final[:, 4].sum() == 3, f'部分保護{protect}枚後も追加三枚を重複なく全返済')
        audit_invariants(d, result, f'部分保護{protect}')

    # ----------------------------------------
    # 起動した後のギャップ損、二円下限ではなく固定二十円Rを検証する。
    d = reset_quotes(fixture(), {5: 116., 6: 106., 7: 96., 19: 90.})
    result = execute(d, activation=.5, width=.5)
    exits = result[result[:, 6] == 1381]
    verify(len(exits) == 1 and exits[0, 5] == 96. and exits[0, 1] == 6,
           '利益床ゼロでも次板の飛び越しを負けとして約定する')
    audit_invariants(d, result, '飛び越し')
    d = reset_quotes(fixture(), {5: 121., 6: 100., 19: 110.})
    d['atr'][:] = 1.
    verify(np.array_equal(execute(d), d['original']), 'Rの下限20円未満のATRで15円順行は未起動')
    d = reset_quotes(fixture(), {5: 126., 6: 117., 7: 116., 8: 115.})
    d['atr'][1:] = 500.
    exits = execute(d)[execute(d)[:, 6] == 1381]
    verify(len(exits) == 1 and exits[0, 0] == 8, 'Rは初回判断行で固定し後のATR上昇を参照しない')

    # ----------------------------------------
    # 未来の価格と親終了価格を置換しても、置換前の注文は変えない。
    d = reset_quotes(fixture(partial=12), {5: 126., 6: 117., 7: 116., 8: 115., 9: 140., 10: 120.})
    for protect in (0, 1, 2):
        baseline = execute(d, protect=protect)
        for cut in (4, 5, 6, 7, 8, 11, 12, 15):
            changed = {key: value.copy() for key, value in d.items()}
            reset_quotes(changed, {row: 200.+row for row in range(cut+1, len(changed['times']))})
            alternative = execute(changed, protect=protect)
            verify(np.array_equal(baseline[baseline[:, 0] <= cut], alternative[alternative[:, 0] <= cut]),
                   f'未来置換・保護{protect}枚・原行{cut}までの約定不変')

    # ----------------------------------------
    # 追撃なし親・補完親は再生関数を通してもそのまま残る。
    d = reset_quotes(fixture(), {5: 126., 6: 117., 7: 116., 8: 115.})
    other = np.array([[2, 1, 10002, -1, 2, d['bid'][2], 1, 1, 2, 77],
                      [18, 17, 10002, 1, 2, d['ask'][18], 3, 0, 2, 77]], dtype=float)
    baseline = np.concatenate([d['original'], other])
    baseline = baseline[np.argsort(baseline[:, 0], kind='stable')]
    q = dict(bid=d['bid'], ask=d['ask'], quote_valid=d['valid'])
    config = dict(activation=1., width=.5, tighten_at=0., tight_width=.5, protect=1)
    result = overlay138.replay(d['times'], q, d['atr'], baseline, config)
    verify(np.array_equal(result[result[:, 2] == 10002], other), '補完親の売買と数量を維持')
    verify(np.array_equal(result[result[:, 7] == 1], baseline[baseline[:, 7] == 1]), '再生合算でも全入口同一')
    verify(abs(artificial_ledger(result)[0]-artificial_ledger(result)[1]) < 1e-8, '複数親を合算した独立会計一致')
    empty = overlay138.replay(d['times'], q, d['atr'], np.empty((0, 10)), config)
    verify(empty.shape == (0, 10), '空通知でも十列空配列')
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (HERE/'overlay138.py', HERE/'run138.py', Path(__file__))}
    evidence = dict(passed=True, checks=len(CHECKS), items=CHECKS, sources=hashes,
                    market_files_read=0, financial_replays=0, api=0,
                    scope='人工入力のみ。既知の市場成績を新たに測定した証拠ではない。')
    (HERE/'人工確認.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, checks=len(CHECKS), market_files_read=0, financial_replays=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
