"""早期保護の有効注文水準と既成立時の次行成行を実データで確認する。"""

from __future__ import annotations

from copy import deepcopy
import sys

import numpy as np

from independent_audit import ROOT, same, save, sha


EARLY = ROOT / 'work/wave_v49/early'
sys.path.insert(0, str(EARLY))
import run as early


def check_orders(ready: dict, result: dict) -> dict:
    """機能: 前行有効計画から全注文価格を独立に照合する。

    引数: ready/result (dict)。返り値: 注文照合数と既成立件数 (dict)。
    """
    shadow = result['shadow']
    raw = shadow['plans']
    active = raw[:, 0] != 0
    valid = active & np.isfinite(raw[:, 33])
    planned_markets = 0
    for z in range(3):
        levels = raw[:, 12 + z]
        direction = raw[:, 0] if z == 2 else -raw[:, 0]
        positions = np.flatnonzero(valid & np.isfinite(levels))
        expected = direction[positions] * (ready['last'][positions] - levels[positions]) >= -1e-8
        np.testing.assert_array_equal(raw[positions, 15 + z].astype(bool), expected)
        planned_markets += int(sum(expected))
    market_orders = 0
    for order in result['orders']:
        i, source, _, side, _, fill, reason, opening = order
        i = int(i)
        plan = shadow['execution_plans'][i]
        assert source < i
        if opening:
            assert plan[33] < i and plan[21] == side and plan[27] == source
            expected = ready['last'][i] if plan[26] else plan[22]
            assert plan[26] or side * (ready['last'][i] - plan[22]) >= -1e-8
        elif reason in (30, 31, 32):
            expected = ready['last'][i]
        elif plan[18]:
            assert plan[18] == reason and plan[19] == source
            expected = ready['last'][i]
        else:
            assert plan[33] < i
            z = 0 if reason in (1, 11) else 1 if reason == 2 else 2 if reason == 7 else -1
            assert z >= 0, reason
            trigger_side = plan[0] if z == 2 else -plan[0]
            flag = bool(plan[15 + z])
            assert flag or trigger_side * (ready['last'][i] - plan[12 + z]) >= -1e-8
            expected = ready['last'][i] if flag else plan[12 + z]
            market_orders += int(flag)
        same(fill, expected, '前行有効注文の約定価格')
    return dict(注文数=len(result['orders']), 既成立予約行数=planned_markets,
                既成立条件の次行成行約定数=market_orders, 全注文価格一致=True,
                全条件線が前行までに有効=True, 既成立条件の過去水準約定なし=True)


def check() -> dict:
    """機能: 初期幅縮小・早期追跡・建値保護・時間失敗の代表八口座を再確認する。

    引数: なし。返り値: 独立注文監査 (dict)。
    """
    early.source.initialize()
    proof = []
    for identifier in ('E01', 'E05', 'E09', 'E10'):
        variant = next(v for v in early.catalog() if v['id'] == identifier)
        spec = deepcopy(next(s for s in early.source.followup.catalog('new') if s['id'] == early.BASE_ID))
        spec['id'] += '__' + identifier
        for key, ready in early.source.INPUTS.items():
            if key[0] != early.source.NEW:
                continue
            columns, valid = early.source.replay.new_columns(spec, key)
            base, config = early.configs(spec, ready, variant)
            actual = early.play(spec, ready, columns, valid, base, config)
            proof.append(dict(条件=identifier, session=key[0], symbol=key[1], **check_orders(ready, actual[0])))
            del actual
    assert len(proof) == 8
    # ----------------------------------------
    # 実ナイトでは既成立予約が無いので、15分失敗時の後付停止線を人工経路で確認する。
    variant = next(v for v in early.catalog() if v['id'] == 'E10')
    selected = next(r for key,r in early.source.INPUTS.items() if key[1] == 'TOPIX')
    _, config = early.configs(spec, selected, variant)
    par = np.asarray([config[name] for name in early.old_engine.PARAMS], float)
    stamp = np.asarray([1200., 1201., 1250., 2102., 2103., 3000., 3001.])
    price = np.asarray([100., 103., 102., 95., 94., 94., 94.])
    state = np.asarray([1, 1, 1, 0, 0, 0, 0], np.int8)
    artificial = []
    for reflected in (False, True):
        prices = 300. - price if reflected else price
        states = -state if reflected else state
        values = early.old_engine.simulate(stamp, prices, np.repeat(10., 7), np.repeat(10., 7),
            states, states, 1., 0., 3000., 99999., par, True, 10, 0, False,
            np.ones(7, np.bool_), 0., 3600.)
        shadow = dict(zip(early.shadow_api.FIELDS, values))
        orders = shadow['orders']
        assert len(orders) == 2 and orders[-1, 0] == 4
        expected = 206. if reflected else 94.
        assert orders[-1, 5] == expected and orders[-1, 1] == 3
        assert shadow['plans'][3, 15] == 1
        artificial.append(dict(売り=reflected, 次観測返済価格=expected,
                              過去の停止水準ではない=True, 全合格=True))
    output = dict(全合格=True, 代表口座数=8, 検査=proof,
                  時間失敗の既成立人工検査=artificial,
                  実装SHA256=sha(EARLY/'run.py'),
                  限定='全352口座の会計検算に加えた、代表8口座の前行注文水準の独立再判定。')
    save('早期保護の既成立注文監査.json', output)
    return output


if __name__ == '__main__':
    print(check())
