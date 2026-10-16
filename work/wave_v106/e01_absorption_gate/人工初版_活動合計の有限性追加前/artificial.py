"""表示維持の公開述語だけを、実価格・金融なしの人工原行で反証する。"""

from copy import deepcopy

import numpy as np

import catalog
import common
import feature
import gate
import known_policy
import votes


def fixture(side: int = 1) -> tuple:
    """
    機能: 元窓の初行と公開後同時計行を含む人工原行を作る。
    引数: side(int)は買い+1又は反射した売り-1。
    返り値: tuple[dict,int]は人工配列と公開原行。相場結果は含まない。
    """
    times = np.array([0, 20, 21, 25, 30, 30, 31, 40, 80, 80, 81], dtype=float)
    n = len(times)
    raw = dict(raw_seq=np.arange(n, dtype=np.int64), price_time_s=times,
               bid=np.full(n, 100.), ask=np.full(n, 101.), last=np.full(n, 101.),
               bid_qty=np.full(n, 10.), ask_qty=np.full(n, 10.),
               volume_delta=np.array([0, 0, 0, 3, 3, 3, 0, 0, 3, 3, 3], dtype=float),
               volume_delta_usable=np.ones(n, bool), volume_reset_reason=np.zeros(n, np.uint16),
               best_quantity_valid=np.ones(n, bool), price_row_valid=np.ones(n, bool),
               price_transition_valid=np.ones(n, bool), execution_to_raw_index=np.arange(n))
    raw['price_transition_valid'][0] = False
    if side < 0:
        bid, ask = raw['bid'].copy(), raw['ask'].copy()
        bq, aq = raw['bid_qty'].copy(), raw['ask_qty'].copy()
        raw.update(bid=1000-ask, ask=1000-bid, last=1000-raw['last'], bid_qty=aq, ask_qty=bq)
    return raw, 8


def observe(raw: dict, row: int, side: int) -> tuple:
    """
    機能: 人工配列から元W60票と新述語を純数学で測る。
    引数: raw(dict)、row/side(int)は人工入力と公開終点・側。
    返り値: tuple[dict,dict]は元票と新観測。金融・旧JITは実行しない。
    """
    context = votes.context(raw)
    base = votes.measure(raw, context, row, catalog.WINDOW, side)
    value = feature.measure(raw, context, row, side, base)
    return base, value


def run() -> None:
    """
    機能: 売買対称・数量維持・価格順序・未知・公開接頭の人工反例を検査する。
    引数: なし。
    返り値: None。所有域へ人工証跡を一回保存し、入力測定は開始しない。
    """
    checks = []
    values = []
    for side in (1, -1):
        raw, row = fixture(side)
        opposite, quantity, support = ('ask', 'ask_qty', 'bid') if side > 0 else ('bid', 'bid_qty', 'ask')
        base, original = observe(raw, row, side)
        assert original['eligible'] and original['known'] and original['hit']
        assert original['episode_start_raw_row'] == 2 and original['touch_rows'] == [3, 4, 5, 8]
        assert original['touch_activity_volume'] == 12 and original['touch_activity_to_initial_ratio'] == 1.2
        checks.append(f'{side}:基本成立4接触')
        values.append(original)

        changed = deepcopy(raw)
        changed[quantity][4] = 9.
        value = observe(changed, row, side)[1]
        assert value['known'] and not value['hit'] and value['minimum_quantity'] == 9.
        checks.append(f'{side}:一瞬数量減少後回復でも不成立')

        changed = deepcopy(raw)
        changed[support][4] += side*.5
        value = observe(changed, row, side)[1]
        assert value['known'] and not value['hit'] and value['maximum_support_advance'] == .5
        checks.append(f'{side}:一瞬支持順行後戻りでも不成立')

        changed = deepcopy(raw)
        changed[opposite][6] += side
        if side < 0:
            changed[support][6] += 2.
        value = observe(changed, row, side)[1]
        assert value['known'] and not value['hit'] and value['episode_start_raw_row'] == 7
        assert value['touch_rows'] == [8]
        checks.append(f'{side}:価格変更後の尾部だけ1接触')

        changed[quantity][6] = np.nan
        changed['best_quantity_valid'][6] = False
        changed['price_row_valid'][6] = False
        changed['price_transition_valid'][7] = False
        value = observe(changed, row, side)[1]
        assert value['known'] and not value['hit'] and value['episode_start_raw_row'] == 7
        checks.append(f'{side}:尾部外数量未知とeの遷移資格は不使用')

        changed = deepcopy(raw)
        changed['price_transition_valid'][2] = False
        assert observe(changed, row, side)[1]['hit']
        checks.append(f'{side}:窓内尾部初行eの外側遷移は不使用')

        changed = deepcopy(raw)
        changed['volume_delta'][4:6] = 0
        changed['volume_delta'][3] = changed['volume_delta'][8] = 5
        value = observe(changed, row, side)[1]
        assert value['known'] and value['hit'] and value['touch_rows'] == [3, 8]
        checks.append(f'{side}:古いLast反復とゼロ出来高は数えない')

        assert value['touch_activity_volume'] == 10 and value['touch_activity_to_initial_ratio'] == 1
        checks.append(f'{side}:2更新で公表出来高差がQ0と等しければ成立')
        changed['volume_delta'][3] = 4
        value = observe(changed, row, side)[1]
        assert value['known'] and not value['hit'] and value['touch_count'] == 2
        assert value['touch_activity_volume'] == 9
        checks.append(f'{side}:2更新でも公表出来高差がQ0未満なら不成立')

        changed = deepcopy(raw)
        changed['volume_delta'][:] = 0
        changed['volume_delta'][2] = 1
        changed['volume_delta'][8] = 100
        value = observe(changed, row, side)[1]
        assert value['eligible'] and value['known'] and not value['hit'] and value['touch_count'] == 1
        assert value['touch_activity_volume'] == 100
        checks.append(f'{side}:一更新の大量活動だけでは不成立')

        changed = deepcopy(raw)
        for j in (3, 4, 5, 8):
            changed['last'][j] = float(changed[opposite][j])+side
        value = observe(changed, row, side)[1]
        assert value['eligible'] and value['known'] and not value['hit'] and value['touch_count'] == 0
        checks.append(f'{side}:方向票でもLastが逆価格と違えば接触0')

        changed = deepcopy(raw)
        changed['volume_delta'][:] = 0
        changed['volume_delta'][2:4] = 1
        value = observe(changed, row, side)[1]
        assert value['eligible'] and value['known'] and not value['hit'] and value['touch_rows'] == [3]
        checks.append(f'{side}:e自身の元票を新接触へ数えない')

        for bad in ('数量', '支持価格', '出来高差欠測', '出来高reset', '価格時計欠測', '価格時計逆行', '原連番断裂', '尾部遷移'):
            changed = deepcopy(raw)
            if bad == '数量':
                changed[quantity][4] = np.nan
                changed['best_quantity_valid'][4] = changed['price_row_valid'][4] = False
            elif bad == '支持価格':
                changed[support][4] = np.nan
                changed['price_row_valid'][4] = False
            elif bad == '出来高差欠測':
                changed['volume_delta'][4] = np.nan
            elif bad == '出来高reset':
                changed['volume_delta_usable'][4] = False
                changed['volume_reset_reason'][4] = 32
            elif bad == '価格時計欠測':
                changed['price_time_s'][4] = np.nan
            elif bad == '価格時計逆行':
                changed['price_time_s'][4] = 24
            elif bad == '原連番断裂':
                changed['raw_seq'][4] += 10
            else:
                changed['price_transition_valid'][4] = False
            value = observe(changed, row, side)[1]
            assert not value['known'] and value['hit'] is None
            checks.append(f'{side}:尾部{bad}は未知')

        changed = deepcopy(raw)
        changed[opposite][6] = np.nan
        value = observe(changed, row, side)[1]
        assert not value['known'] and value['reason'] == 302
        checks.append(f'{side}:未知逆価格の区間境界を推定しない')

        prefix = {name: value[:row+1].copy() for name, value in raw.items()}
        assert observe(prefix, row, side)[1] == original
        changed = deepcopy(raw)
        changed[quantity][row+1:] = 0
        changed[support][row+1:] += side*10
        assert observe(changed, row, side)[1] == original
        checks.append(f'{side}:公開後同時計原行と将来変更は未使用')

        feed = np.array([[row, row, 0, side, 5, raw['last'][row], 0, 1, 0, 1]], dtype=float)
        accepted, reasons = gate.mask(feed, len(raw['raw_seq']), {row: base}, {row: original})
        assert not accepted[row] and reasons[row] == 501 and np.all(accepted[:row])
        unknown = dict(original, known=False, hit=None)
        a, b = gate.mask(feed, len(raw['raw_seq']), {row: base}, {row: unknown})
        x, y = known_policy.mask(feed, len(raw['raw_seq']), {row: base}, 'KNOWN_VETO')
        np.testing.assert_array_equal(a, x)
        np.testing.assert_array_equal(b, y)
        checks.append(f'{side}:公開行だけ追加拒否と追加未知の元同値')

    assert values[0]['touch_rows'] == values[1]['touch_rows']
    assert values[0]['maximum_support_advance'] == values[1]['maximum_support_advance']
    common.write(common.HERE/'表示維持述語と元公開門の人工検査.json', dict(
        全合格=True, 確認数=len(checks), 確認項目=checks,
        固定定義=catalog.definition(), source_SHA256=common.sources(),
        元数学clone=True, 大型入力読取=0, 原NPZ=0, 原板=0, 新金融=0, API=0))
    print(f'表示維持の純人工{len(checks)}項目合格、金融0、大型入力0', flush=True)


if __name__ == '__main__':
    run()
