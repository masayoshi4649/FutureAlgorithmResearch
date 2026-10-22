"""v3の初期予算・順行増加・次原row返済を自作素材で確認する。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import engine_v3 as subject

CHECKS = []


def check(name: str, passed: bool) -> None:
    """
    機能: 合成検査の成否を記録する。
    引数: name(str)、passed(bool) は内容と期待への一致。
    返り値: None。不一致で停止する。
    """
    CHECKS.append(dict(項目=name, 合格=bool(passed)))
    assert passed, name


def fixture(symbol: str = 'TOPIX', side: int = 1, mode: int = 2,
            offsets: list[float] | None = None, times: list[float] | None = None,
            exits: list[bool] | None = None) -> tuple:
    """
    機能: 実建値を中心とする正常BBOと公開行を作る。
    引数: symbol(str)、side/mode(int)、offsets/times/exits(任意配列) は人工経路。
    返り値: tuple はbars/quotes/policy/settings。実市場とは無関係。
    """
    top = symbol == 'TOPIX'
    center, risk, tick = (4000., 5., .5) if top else (60000., 100., 10.)
    path = [-tick, -tick, .5*risk, .6*risk, risk, 1.1*risk, 1.5*risk, 1.6*risk, 1.1*risk, risk] if offsets is None else offsets
    b = center+np.asarray(path, float)
    a = b+tick
    if side == -1:
        b, a = 2*center-a, 2*center-b
    n = len(b)
    t = np.arange(n, dtype=float) if times is None else np.asarray(times, float)
    bars = dict(valid=np.ones(n, bool), anchor=(b+a)/2, pub_raw_row=np.arange(n, dtype=np.int64),
                pub_price_time_s=t.copy(), t_s=t.copy())
    quotes = dict(row=np.arange(n, dtype=np.int64), time=t, bid=b, ask=a)
    entry = np.zeros(n, np.int8)
    entry[0] = side
    closing = np.zeros(n, bool) if exits is None else np.asarray(exits, bool)
    policy = dict(entry=entry, exit_long=closing.copy(), exit_short=closing.copy(),
                  width=np.full(n, risk), valid=np.ones(n, bool))
    settings = dict(quantity=10 if top else 20, multiplier=1000. if top else 10., fee=41.8 if top else 11.,
                    allocation_mode=mode, trail_multiple=.5, entry_end=10000., close_time=20000.,
                    entry_mode=0, execution_mode=0, guard=2)
    return bars, quotes, policy, settings


def run(material: tuple) -> dict:
    """
    機能: 実注文の一括料金と親・場現金をDecimal料金で独立に検算する。
    引数: material(tuple) は合成入力。
    返り値: dict は人工実行結果。
    """
    answer = subject.run_policy(*material)
    orders, parents, s = answer['orders'], answer['parents'], answer['summary']
    oc, pc = subject.ORDER_COLUMNS, subject.PARENT_COLUMNS
    fee = Decimal(str(material[3]['fee']))
    costs = [int((Decimal(int(r[oc.index('quantity')]))*fee).to_integral_value(rounding=ROUND_FLOOR)) for r in orders]
    check('各注文の全数量floor手数料', np.array_equal(orders[:, oc.index('fee')], costs))
    check('全支払手数料', abs(sum(costs)-s['fees']) < 1e-7)
    if s['unclosed'] == 0:
        check('親の費用後損益と現金', abs(parents[:, pc.index('net')].sum()-s['realized']) < 1e-5)
    check('上限以内の実保有', bool(np.all(orders[:, oc.index('basket_quantity_after')] <= material[3]['quantity'])))
    check('判断行と実約定行が異なる', bool(np.all(orders[:, oc.index('fill_raw_row')] > orders[:, oc.index('decision_raw_row')])))
    return answer


def main() -> None:
    """
    機能: 3配分・買売・追加gap・撤回競合・失効・接頭を純素材で検査する。
    引数: なし。
    返り値: None。成功又は失敗の源指紋付き証跡を保存する。
    """
    source = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (HERE/'engine_v3.py', Path(__file__))}
    success, error = False, None
    try:
        for symbol in ('TOPIX', 'NK225'):
            for side in (1, -1):
                for mode in (0, 1, 2):
                    answer = run(fixture(symbol, side, mode))
                    s = answer['summary']
                    check('実初回数量'+str((symbol, side, mode)), s['initial_quantity_min'] ==
                          (10 if symbol == 'TOPIX' else 20) * (1 if mode == 1 else .2))
                    if mode == 2:
                        q = answer['orders'][answer['orders'][:, 1] != 3, 7].tolist()
                        check('20/40/70/100の累計数量'+str((symbol, side)), q == ([2., 2., 3., 3.] if symbol == 'TOPIX' else [4., 4., 6., 6.]))
                        check('三回追加の実counter'+str((symbol, side)), s['add_fills'] == 3)
                    else:
                        check('固定配分は追加なし'+str((symbol, side, mode)), s['add_fills'] == 0)
        # ----------------------------------------
        # 追加後に悪化しても先に実fillし、損失を当初予算へ丸めない。
        made = fixture(offsets=[-.5, -.5, 2.5, -10.5, -20.])
        actual = run(made)
        p = actual['parents'][0]
        check('悪化した追加も実約定する', actual['orders'][:, 1].tolist() == [1., 2., 3.])
        check('追加と全返済は別原row', actual['orders'][:, 3].tolist() == [1., 3., 4.])
        check('当初予算を増やさない', abs(p[15]-10166.) < 1e-7)
        check('gapの予算超過損失を保持', abs(p[19]+60333.) < 1e-7)
        check('不利追加で停止線は後退しない', p[22] >= 3995.)
        made = fixture(offsets=[-.5, -.5, 2.5, 3., 2.], exits=[False, False, True, False, False])
        actual = run(made)
        check('撤回待ちでも先行追加の実fillを消さない', actual['orders'][:, 1].tolist() == [1., 2., 3.])
        check('追加同行の撤回返済は禁止', actual['orders'][:, 3].tolist() == [1., 3., 4.])
        check('家族撤回の理由を維持', int(actual['parents'][0, 20]) == 4)
        made = fixture(offsets=[-.5, -.5, 2.5, 2.5, 2.5], times=[0., 1., 2., 63., 64.])
        actual = run(made)
        check('追加60秒失効を記録', actual['summary']['canceled'] == 1 and actual['summary']['add_fills'] == 0)
        check('同じ失効段階を再利用しない', actual['summary']['pending_entry_or_add'] == 0)
        check('EOF玉は架空完結しない', actual['summary']['unclosed'] == 2 and len(actual['parents']) == 0)
        made = fixture(mode=1, offsets=[-.5, -.5, -2., -2.5])
        actual = run(made)
        check('全配分共通の小円場予算', actual['summary']['session_loss_budget_yen'] == 20000.)
        check('FULLは親R前に場予算で返済する', int(actual['parents'][0, 20]) == 5
              and actual['parents'][0, 8]-actual['orders'][-1, 9] < 5.)
        # ----------------------------------------
        # 後のquoteを除いた接頭では、既実注文だけが同一である。
        made = fixture()
        full = run(made)
        for n in (1, 2, 3, 4, 6, 8):
            b, q, p, setting = made
            small = run(({k: v[:n].copy() for k, v in b.items()}, {k: v[:n].copy() for k, v in q.items()},
                         {k: v[:n].copy() for k, v in p.items()}, dict(setting)))
            np.testing.assert_allclose(small['orders'], full['orders'][full['orders'][:, 3] < n], atol=1e-7, rtol=0)
            np.testing.assert_allclose(small['equity'], full['equity'][:n], atol=1e-7, rtol=0, equal_nan=True)
            check('未来接尾に依存しない'+str(n), True)
        check('源開始終端一致', source == {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source})
        success = True
    except Exception as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
    proof = dict(全合格=success, source_SHA256=source, 検査数=len(CHECKS), 検査=CHECKS, error=error,
                 原市場=0, 保存cache=0, 既金融本文=0, 新金融=0, API=0,
                 留保='同じ資金管理思想は旧00097/98で検証済み。今回は新入口・幅・段階・40場の再対照であり新発明ではない。')
    proof['市場前の訂正'] = ['初版はNumbaのfloat(bool)型エラーで経済実行前停止。当時源とFalseをarchive保全。1.0/0.0格納へ修正。',
        '根の設計訂正で場予算を全配分共通の最初R×scout枚数×倍率の2倍に変更。旧cap場予算を実測後に変更したものではない。']
    target = HERE/'初回円予算固定と順行増加及び費用後建値の純人工_v2.json'
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=success, 検査数=len(CHECKS), error=error), ensure_ascii=False))
    assert success, error


if __name__ == '__main__':
    main()
