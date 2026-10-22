"""実市場を読まず、v2執行の固定価格・期限・局所会計と旧対照を検査する。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
V2 = HERE.parent
OWNER = V2.parent
ROOT = OWNER.parents[1]
os.environ['NUMBA_CACHE_DIR'] = str(V2 / 'numba_audit')
sys.dont_write_bytecode = True
sys.path.insert(0, str(OWNER))
import engine119 as old
sys.path.insert(0, str(V2))
import engine_v2 as new

CHECKS = []


def check(name: str, passed: bool) -> None:
    """
    機能: 独立した期待の成否を保存し、不一致で停止する。
    引数: name(str)、passed(bool) は内容と成否。
    返り値: None。不一致はAssertionError。
    """
    CHECKS.append(dict(項目=name, 合格=bool(passed)))
    assert passed, name


def same(name: str, actual: object, expected: object) -> None:
    """
    機能: NaNを未知として配列又は数値を比較する。
    引数: name(str)、actual/expected(object) は観測値と期待値。
    返り値: None。市場値又は金融結果は取得しない。
    """
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-7, equal_nan=True, err_msg=name)
    check(name, True)


def fixture(bid: list[float], ask: list[float], pubs: list[int], entries: list[int],
            times: list[float] | None = None, lasts: list[float] | None = None,
            anchors: list[float] | None = None, exits: list[bool] | None = None,
            side: int = 1, **settings: object) -> tuple:
    """
    機能: 原rowと価格時計を持つ人工気配・公開足・一政策を生成する。
    引数: bid/ask(list[float])、pubs/entries(list[int])、任意時計とLast、side(int)、設定上書き。
    返り値: tuple[dict,dict,dict,dict] はbars/quotes/policy/settings。
    """
    b, a = np.asarray(bid, float), np.asarray(ask, float)
    t = np.arange(len(b), dtype=float) if times is None else np.asarray(times, float)
    l = (b+a)/2 if lasts is None else np.asarray(lasts, float)
    anchor = np.full(len(pubs), 1000.) if anchors is None else np.asarray(anchors, float)
    if side == -1:
        b, a, l, anchor = 2000-a, 2000-b, 2000-l, 2000-anchor
    pr = np.asarray(pubs, np.int64)
    bars = dict(valid=np.ones(len(pr), bool), anchor=anchor, pub_raw_row=pr,
                pub_price_time_s=t[pr], t_s=t[pr].copy())
    quotes = dict(row=np.arange(len(b), dtype=np.int64), time=t, bid=b, ask=a, last=l)
    closing = np.asarray([False]*len(pr) if exits is None else exits, bool)
    policy = dict(entry=side*np.asarray(entries, np.int8), exit_long=closing.copy(), exit_short=closing.copy(),
                  width=np.full(len(pr), 10.), valid=np.ones(len(pr), bool))
    config = dict(quantity=3, multiplier=1000., fee=41.8, exit_mode=1, entry_mode=0, guard=0,
                  entry_end=1e9, close_time=1e9, order_tick=.25, execution_mode=0, observed_tick=.5)
    config.update(settings)
    return bars, quotes, policy, config


def run(material: tuple, subject: object = new) -> dict:
    """
    機能: 合成入力だけを実装へ渡し、Decimal料金と親・場会計を独立照合する。
    引数: material(tuple) は人工素材、subject(object) は旧又は新源。
    返り値: dict は人工結果。未清算を完結へ昇格しない。
    """
    result = subject.run_policy(*material)
    s, ledger = result['summary'], result['ledger']
    q, m, fee = material[3]['quantity'], material[3]['multiplier'], Decimal(str(material[3]['fee']))
    for i, leg in enumerate(ledger):
        units = int(leg[6])
        outfee = int((units*fee).to_integral_value(rounding=ROUND_FLOOR))
        infee = int((q*fee).to_integral_value(rounding=ROUND_FLOOR))*units/q
        same('実返済料floor'+str(i), leg[11], outfee)
        same('新規料の部分配賦'+str(i), leg[10], infee)
        same('気配価格の実脚損益'+str(i), leg[12], leg[5]*(leg[8]-leg[7])*units*m-infee-outfee)
        check('新規後の返済原row'+str(i), leg[2] > leg[1])
    if s['unclosed'] == 0:
        same('完結全脚と場現金', np.sum(ledger[:, 12]), s['realized'])
        same('完結場と親P/L', s['profit']-s['loss'], s['net'])
    return result


def baseline() -> None:
    """
    機能: 旧の二新規・三出口・予算有無がexecution0で同じことを確かめる。
    引数: なし。
    返り値: None。新規v2条件を旧対照同値へ混ぜない。
    """
    for side in (1, -1):
        for entry_mode in (0, 1):
            for exit_mode in (0, 1, 2):
                for guard in (0, 1):
                    made = fixture([999.5, 997.5, 1010., 1011., 1015., 1002., 1003., 990., 989.],
                                   [1000., 998., 1010.5, 1011.5, 1015.5, 1002.5, 1003.5, 990.5, 989.5],
                                   [0, 3, 6], [1, 0, -1], side=side,
                                   entry_mode=entry_mode, exit_mode=exit_mode, guard=guard)
                    a, b = run(made, old), run(made, new)
                    for key in ('ledger', 'equity', 'position'):
                        same('旧対照'+str((side, entry_mode, exit_mode, guard))+key, a[key], b[key])
                    for key in a['summary']:
                        same('旧対照集計'+key, a['summary'][key], b['summary'][key])
                    check('旧対照に新診断の値を捏造しない', b['summary']['protected_fallbacks'] ==
                          b['summary']['protected_wait_rows'] == b['summary']['rejected_entries'] == 0)


def protected_cases() -> None:
    """
    機能: 返済保護の固定線・待機損失・30秒・場末・EOFを独立期待で確認する。
    引数: なし。
    返り値: None。返済待ちを利益へ変えない。
    """
    for side in (1, -1):
        # ----------------------------------------
        # 後のLastへ線を動かすとrow2で執行してしまうため、固定線を検査できる。
        made = fixture([999.5, 999.5, 998., 999.], [1000., 1000., 998.5, 999.5],
                       [0, 1, 2], [1, 0, 0], lasts=[1000., 1000., 998., 999.],
                       anchors=[1000., 1000., 998.], exits=[False, True, False],
                       side=side, execution_mode=2)
        actual = run(made)
        check('保護指値は後Lastへ再設定しない'+str(side), actual['ledger'][:, 2].tolist() == [3.])
        check('保護待ちの不利な観測も数える'+str(side), actual['summary']['protected_wait_rows'] == 1)
        same('保護待機中も清算含損を保持'+str(side), actual['equity'][2], -6250.)
        # ----------------------------------------
        # 30秒より僅か前は待機し、等号で成行へ戻す。後の回復へ約定を移さない。
        made = fixture([999.5, 999.5, 980., 970., 1005.], [1000., 1000., 980.5, 970.5, 1005.5],
                       [0, 1], [1, 0], times=[0., 1., 30.999, 31., 40.],
                       lasts=[1000., 1000., 980., 970., 1005.], exits=[False, True],
                       side=side, execution_mode=2)
        actual = run(made)
        check('30秒等号で成行かつ後の回復へ移さない'+str(side), actual['ledger'][:, 2].tolist() == [3.])
        same('ギャップと待機で損失が増える'+str(side), actual['summary']['net'], -90250.)
        check('期限fallbackの計数'+str(side), actual['summary']['protected_fallbacks'] == 1)
        made = fixture([999.5, 999.5, 980.], [1000., 1000., 980.5], [0, 1, 2], [1, 0, 0],
                       times=[0., 1., 20.], lasts=[1000., 1000., 980.], exits=[False, True, False],
                       side=side, execution_mode=2)
        actual = run(made)
        check('EOF保護中は未返済のまま'+str(side), actual['summary']['unclosed'] == 3 and not len(actual['ledger']))
        same('EOFでも保護中の含損を隠さない'+str(side), actual['summary']['net'], -60250.)
        made = fixture([999.5, 999.5, 970.], [1000., 1000., 970.5], [0, 1], [1, 0],
                       times=[0., 1., 10.], lasts=[1000., 1000., 970.], exits=[False, True],
                       side=side, execution_mode=2, close_time=10.)
        actual = run(made)
        check('場末は30秒前でも既保護を成行へ'+str(side), actual['ledger'][:, 2].tolist() == [2.])


def entry_cases() -> None:
    """
    機能: 新規の当時審査と固定cap・失効・同時計後row・bit分離を確認する。
    引数: なし。
    返り値: None。将来気配を使って公開時の採否を変えない。
    """
    for side in (1, -1):
        made = fixture([999.5, 1001.5, 1000.25, 1002.], [1000., 1002., 1000.75, 1002.5],
                       [0, 2], [1, 0], exits=[False, True], side=side, execution_mode=1)
        actual = run(made)
        check('cap外の後quoteだけで取消さず後crossを待つ'+str(side), actual['ledger'][:, 1].tolist() == [2.])
        same('cap価格より有利な実BBOを採用'+str(side), actual['ledger'][0, 7], 1000.75 if side == 1 else 999.25)
        check('新規だけ保護なら返済を待たない'+str(side), actual['ledger'][:, 2].tolist() == [3.] and actual['summary']['protected_wait_rows'] == 0)
        for time, expected in ((60., 1), (60.001, 0)):
            made = fixture([999.5, 1001.5, 1000.], [1000., 1002., 1000.5],
                           [0], [1], times=[0., 5., time], side=side, execution_mode=1)
            actual = run(made)
            check('60秒最大待機の境界'+str((side, time)), actual['summary']['fills'] == expected)
        made = fixture([998., 999.5], [1002., 1000.], [0], [1], side=side, execution_mode=1)
        actual = run(made)
        check('当時wideは未来回復を見ず拒否'+str(side), actual['summary']['rejected_entries'] == 1 and actual['summary']['fills'] == 0)
        made = fixture([999.5, 999.5, 1001.], [1000., 1000., 1001.5],
                       [0, 1], [1, 0], times=[0., 0., 0.], exits=[False, True], side=side, execution_mode=3)
        actual = run(made)
        check('同時計の別原rowで新規と返済が可能'+str(side), actual['ledger'][:, 1].tolist() == [1.] and actual['ledger'][:, 2].tolist() == [2.])
        made = fixture([999.5], [1000.], [0], [1], side=side, execution_mode=3)
        check('同じ原rowの約定は禁止'+str(side), run(made)['summary']['fills'] == 0)
    # ----------------------------------------
    # 返済だけ保護するbitは、旧の新規成行を審査拒否しない。
    wide = fixture([998., 998.], [1002., 1002.], [0], [1], execution_mode=2)
    check('返済保護bitは新規審査bitでない', run(wide)['summary']['fills'] == 1)


def exits_and_prefix() -> None:
    """
    機能: 対称±R・半幅追尾・上益停止なしと、未来接尾が既約定へ混じらないことを確認する。
    引数: なし。
    返り値: None。接頭の未完了を完了成績へ昇格しない。
    """
    for side in (1, -1):
        for path, expected, reason in (([999.5, 999.5, 1010., 1011.], 32750., 2),
                                       ([999.5, 999.5, 990., 989.], -33250., 1)):
            made = fixture(path, [p+.5 for p in path], [0], [1], side=side, exit_mode=5)
            actual = run(made)
            same('対称±Rは次quoteで約定'+str((side, reason)), actual['summary']['net'], expected)
            check('対称±Rの理由'+str((side, reason)), int(actual['ledger'][0, 13]) == reason)
        made = fixture([999.5, 999.5, 1010., 1012., 1007., 1006.],
                       [1000., 1000., 1010.5, 1012.5, 1007.5, 1006.5],
                       [0], [1], side=side, exit_mode=4)
        actual = run(made)
        same('一幅arm後の半幅trailing'+str(side), actual['summary']['net'], 17750.)
        check('trailingは判断後のrowで返済'+str(side), actual['ledger'][:, 2].tolist() == [5.])
    made = fixture([999.5, 999.5, 1019.], [1000., 1000., 1019.5], [0], [1], exit_mode=3, guard=2)
    actual = run(made)
    check('guard2は上益1.5Rで停止しない', actual['summary']['halted'] == 0 and actual['summary']['unclosed'] == 3)
    made = fixture([999.5, 999.5, 980., 979.], [1000., 1000., 980.5, 979.5], [0], [1], exit_mode=3, guard=2)
    actual = run(made)
    check('guard2は清算費用込−2Rで停止', actual['summary']['halted'] == 5 and int(actual['ledger'][0, 13]) == 5)
    full = fixture([999.5, 1001.5, 1000.25, 998., 980., 970., 1005.],
                   [1000., 1002., 1000.75, 998.5, 980.5, 970.5, 1005.5],
                   [0, 2, 3, 4], [1, 0, 0, 0], times=[0., 1., 2., 3., 10., 33., 40.],
                   anchors=[1000., 1000., 998., 980.], exits=[False, True, False, False], execution_mode=3)
    actual = run(full)
    for length in (1, 2, 3, 4, 5, 6):
        bars, quotes, policy, settings = full
        good = bars['pub_raw_row'] < length
        cut = ({k: v[good].copy() for k, v in bars.items()},
               {k: v[:length].copy() for k, v in quotes.items()},
               {k: v[good].copy() for k, v in policy.items()}, dict(settings))
        short = run(cut)
        same('未来接尾によらない公開資産'+str(length), short['equity'], actual['equity'][good])
        same('未来接尾によらない既返済'+str(length), short['ledger'], actual['ledger'][actual['ledger'][:, 2] < length])


def main() -> None:
    """
    機能: SOURCE_ONLY範囲の独立人工を実行し、成功又は失敗を源指紋と共に保存する。
    引数: なし。市場、元cache、過去金融本文は読まない。
    返り値: None。登録・金融実行はしない。
    """
    sources = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in (V2/'engine_v2.py', OWNER/'engine119.py', Path(__file__))}
    success, error = False, None
    try:
        for module in (old, new):
            cache = Path(module.replay._cache._impl.locator.get_cache_path()).resolve()
            check('JITは専用v2監査領域'+module.__name__, cache.is_relative_to(V2/'numba_audit'))
        baseline()
        entry_cases()
        protected_cases()
        exits_and_prefix()
        now = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}
        check('監査対象源は開始終端同一', now == sources)
        success = True
    except Exception as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
    proof = dict(全合格=success, 検査数=len(CHECKS), source_SHA256=sources, 検査=CHECKS, error=error,
                 実市場=0, 原cache=0, 既金融本文=0, 新金融=0, API=0,
                 範囲='新旧純人工のみ。execution0旧同値、新規bit1/返済bit2、価格時計30秒は壁時計保証でない。正式計画全体は別監査。')
    target = HERE/'事前価格制限と期限返済及び旧同値の独立純人工.json'
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=success, 検査数=len(CHECKS), error=error), ensure_ascii=False))
    assert success, error


if __name__ == '__main__':
    main()
