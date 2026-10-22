"""v5の相対回帰と対立する相対順行仮説だけを、市場を使わず独立反証する。"""

import ast
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
V7 = HERE.parent
BASE = V7.parent
ROOT = BASE.parents[1]
EXPECTED = '0d5737139f9b710706af48c2c498b28ed3e14625164b293e98ec39d9ad146353'
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'private_numba_cache')
sys.path.insert(0, str(V7))
import engine_v7 as engine

CHECKS = 0


# ----------------------------------------


def check(condition: bool, label: str) -> None:
    """
    機能: 人工の独立期待値を照合し、不一致で停止する。
    引数: condition(bool) は判定、label(str) は内容。
    返り値: None。
    """
    global CHECKS
    assert bool(condition), label
    CHECKS += 1


def near(actual: object, expected: object, label: str) -> None:
    """
    機能: 保存可能な数値及びNaNを許容誤差で照合する。
    引数: actual/expected(object)、label(str) は期待値と説明。
    返り値: None。
    """
    check(np.allclose(actual, expected, atol=1e-7, rtol=1e-10, equal_nan=True), label)


def write(path: Path, value: dict) -> None:
    """
    機能: 新規の監査証跡だけを所有領域へ保存する。
    引数: path(Path) は保存先、value(dict) は有限JSON。
    返り値: None。既存結果は上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def quote(times: list[float], prices: list[float], spread: float) -> dict:
    """
    機能: 市場を読まず人工の正常気配を作る。
    引数: times/prices(list[float])、spread(float) は時計・現在値・気配幅。
    返り値: dict は各脚自身の原行と気配。
    """
    p = np.asarray(prices, float)
    return dict(row=np.arange(len(p), dtype=np.int64) * 7 + 2, time=np.asarray(times, float),
                last=p, bid=p - spread / 2., ask=p + spread / 2., bq=np.ones(len(p)), aq=np.ones(len(p)))


def replay(nk: dict, top: dict, mode: int, clocks: list[float] | None = None,
           history: np.ndarray | None = None, force: float = 1000., end: float = 900.) -> tuple:
    """
    機能: 人工の固定モデルと各脚独立時計を核心へ接続する。
    引数: nk/top(dict)、mode(int)、clocks(list|None)、history(ndarray|None)、force/end(float)。
    返り値: tuple は注文・親・曲線等。市場の金融効果を測定しない。
    """
    clocks = np.asarray([0., 60.] if clocks is None else clocks, float)
    if history is None:
        history = np.tile([0., 1., math.log(99.), .001], (len(clocks), 1))
        history[0, 0] = 1.
    events = [(float(t), leg, int(row), i) for leg, q in enumerate((nk, top))
              for i, (t, row) in enumerate(zip(q['time'], q['row']))]
    events += [(float(t), 2, 0, i) for i, t in enumerate(clocks)]
    events.sort()
    return engine.replay(np.asarray([r[0] for r in events]), np.asarray([r[1] for r in events], np.int8),
        np.asarray([r[3] for r in events], np.int64), clocks, history,
        nk['row'], nk['time'], nk['bid'], nk['ask'], nk['last'],
        top['row'], top['time'], top['bid'], top['ask'], top['last'], end, force, mode)


def account(result: tuple) -> None:
    """
    機能: 全人工注文のgross・注文料金・親会計とstrict時計を独立に確認する。
    引数: result(tuple) は核心の人工返却。
    返り値: None。
    """
    orders, parents = result[:2]
    gross, fees, held = np.zeros(2), np.zeros(2), np.zeros(2)
    for leg, (multiplier, unit_fee) in enumerate(((10., 11.), (1000., 41.8))):
        own = orders[orders[:, 1] == leg]
        check(np.all(own[:, 6] > own[:, 5]), '各脚新規返済はstrict後の時計')
        near(own[:, 9], np.floor(own[:, 4] * unit_fee + 1e-9), '各脚各注文の切捨て費用')
        fees[leg] = sum(own[:, 9])
        for parent in np.unique(own[:, 0]):
            parts = own[own[:, 0] == parent]
            entry, close = parts[parts[:, 2] == 1], parts[parts[:, 2] == 2]
            check(len(entry) == 1 and len(close) <= 1, '一親一脚の全量新規返済')
            if len(close):
                near(close[0, 3:5], [-entry[0, 3], entry[0, 4]], '反対売買の全量返済')
                gross[leg] += entry[0, 3] * (close[0, 8] - entry[0, 8]) * entry[0, 4] * multiplier
            else:
                held[leg] += entry[0, 4]
    near(result[4], gross - fees, '全脚累積現金')
    near(result[6], gross, '全脚累積gross')
    near(result[7], fees, '全脚累積費用')
    near(result[8][4:6], held, 'EOF未返済数量')
    for parent in parents:
        own = orders[orders[:, 0] == parent[0]]
        near(parent[24:26], [sum(own[own[:, 1] == leg, 9]) for leg in range(2)], '親の費用を全注文と照合')
        near(parent[26] + parent[27], parent[28], '親の二脚純損益和')


# ----------------------------------------


def main() -> None:
    """
    機能: 二つの順行出口とその共通執行を、小人工及び源差分で独立確認する。
    引数: なし。
    返り値: None。市場・既存結果・cacheの読取及び金融効果測定は0。
    """
    source = V7 / 'engine_v7.py'
    check(hashlib.sha256(source.read_bytes()).hexdigest() == EXPECTED, '根の閉鎖核心一致')
    old_tree = ast.parse((BASE / 'v5/engine_v5.py').read_text(encoding='utf-8'))
    new_tree = ast.parse(source.read_text(encoding='utf-8'))
    old_functions = {node.name: node for node in old_tree.body if isinstance(node, ast.FunctionDef)}
    new_functions = {node.name: node for node in new_tree.body if isinstance(node, ast.FunctionDef)}
    for name in ('_quotes', 'model_history', 'choose_quantities', '_mark', '_parent'):
        check(ast.dump(old_functions[name], include_attributes=False) == ast.dump(new_functions[name], include_attributes=False),
              'v5から入力/過去モデル/整数ヘッジ/費用評価を変更しない:' + name)
    cases = []
    for side in (1, -1):
        center = math.log(99. if side == 1 else 101.)
        for mode in (0, 1):
            if mode == 0:
                times = [0., 0., 1., 3., 4., 70.]
                values = [100000., 100000., 100000., 100000. + side * 201., 100000. + side * 300., 100000. + side * 300.]
                expected_times, expected_net, reason = [1., 2., 4., 7.], 2856., 2
            else:
                times = [0., 0., 1., 3., 4., 5., 6., 70.]
                values = [100000., 100000., 100000., 100000. + side * 201., 100000. + side * 400., 100000. + side * 250., 100000. + side * 250., 100000. + side * 250.]
                expected_times, expected_net, reason = [1., 2., 6., 7.], 2356., 7
            nk, top = quote(times, values, 2.), quote([0., 0., 2., 7., 70.], [1000.] * 5, .02)
            history = np.asarray([[1., 1., center, .001], [0., 1., center, .001]])
            result = replay(nk, top, mode, history=history)
            account(result)
            near(result[0][:, 6], expected_times, '方向対称の非同時新規・固定線又は残差追尾返済')
            near(result[4].sum(), expected_net, '順行二出口の方向対称手計算純利益')
            check(result[1][0, 5] == reason, '相対順行の退出理由')
            near(result[1][0, 2], side, 'δの方向へNKを建てる')
            cases.append(dict(side=side, mode=mode, net=float(result[4].sum()), reason=reason))

    nk = quote([0., 1., 3., 4., 70.], [100000., 100000., 98800., 98800., 98800.], 2.)
    top = quote([0., 2., 5., 70.], [1000.] * 4, .02)
    result = replay(nk, top, 0)
    account(result)
    check(result[1][0, 5] == 1, 'mode0の当初中心到達は逆行撤退')
    near(result[4].sum(), -12144., 'mode0もgap超過を損失枠へ丸めない')

    nk = quote([0., 1., 3., 4., 70.], [100000., 100000., 99899., 99899., 99899.], 2.)
    result = replay(nk, top, 1)
    account(result)
    check(result[1][0, 5] == 6, 'mode1の固定δから逆σで撤退')
    near(result[4].sum(), -1154., 'mode1の逆σと次気配料金損失')

    nk = quote([0., 1., 3., 4., 70., 71., 130.], [100000., 100000., 110000., 110000., 111000., 111000., 111000.], 2.)
    top = quote([0., 2., 3., 5., 70., 72., 130.], [1000., 1000., 1100., 1100., 1100., 1100., 1100.], .02)
    result = replay(nk, top, 0)
    account(result)
    near(result[0][:, 6], [1., 2., 71., 72.], '共通10%上昇では退出せず実際の相対順行を待つ')
    near(result[4].sum(), 9856., '共同snapshotでの手計算純利益')
    near(result[8][6], 144., '同clock中間の架空DDを含めない')
    prefix_nk = {key: value[nk['time'] <= 5].copy() for key, value in nk.items()}
    prefix_top = {key: value[top['time'] <= 5].copy() for key, value in top.items()}
    prefix = replay(prefix_nk, prefix_top, 0, clocks=[0.])
    near(prefix[0], result[0][result[0][:, 6] <= 5.], '完了clockまでのprefix注文不変')
    near(prefix[2], result[2][:1], '完了clockまでのprefix清算資産不変')
    changed = {key: value.copy() for key, value in nk.items()}
    for key in ('last', 'bid', 'ask'):
        changed[key][nk['time'] > 5] *= .7
    alternate = replay(changed, top, 0)
    near(alternate[0][alternate[0][:, 6] <= 5.], prefix[0], '未来置換で過去注文を変更しない')
    near(alternate[2][:1], prefix[2], '未来置換で過去公開曲線を変更しない')

    for mode in (0, 1):
        nk = quote([0., 1., 60., 61., 121.], [100000.] * 5, 2.)
        top = quote([0., 60., 70., 121.], [1000.] * 4, .02)
        result = replay(nk, top, mode, clocks=[0., 60., 120.])
        account(result)
        near(result[0][:, 1:3], [[0., 1.], [0., 2.]], '両modeで期限同clockの第二脚を先取消')
        near(result[0][:, 6], [1., 61.], '両modeで孤立脚は次clock返済')
        near(result[4].sum(), -42., '両modeで孤立脚の純費用損失')
        result = replay(quote([0., 1.], [100000.] * 2, 2.), quote([0., 2.], [1000.] * 2, .02), mode,
                        clocks=[0., 2.], force=2., end=1.9)
        account(result)
        check(result[8][4] == 1 and result[1][0, 1] == 0, '両modeで場末EOF未返済を実決済にしない')
        near(result[4].sum() + result[5].sum(), -42., '両modeのEOF清算費込み参考時価')

    history = np.asarray([[1., 1., math.log(99.), .00001], [0., 1., math.log(99.), .00001]])
    nq, tq = quote([0., 1., 70.], [100000.] * 3, 2.), quote([0., 2., 70.], [1000.] * 3, .02)
    x0, x1 = replay(nq, tq, 0, history=history), replay(nq, tq, 1, history=history)
    check(x0[8][0] == 1 and x1[8][0] == 0, '費用資格をabsδAと2σAで区別し小σを救済しない')
    near(x1[3][0, 9], 20., 'mode1の予定順行額は2σA')
    near(x0[1][0, 10], abs(math.log(100.) - math.log(99.)) * 1000000., 'mode0の円停止枠はabsδA')
    check(hashlib.sha256(source.read_bytes()).hexdigest() == EXPECTED, '人工後も閉鎖核心不変')
    binding = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in (source, V7 / 'run_v7.py', V7 / 'plan_v7.py')}
    write(HERE / '相対順行二出口と共同clock及び因果執行の独立人工.json', dict(全合格=True, 検査数=CHECKS,
        engine_SHA256=EXPECTED, economic_sources=binding, 監査源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cases=cases, 市場読取=0, 保存結果読取=0, cache読取=0, 金融効果の測定=0,
        留保='v5との対立仮説の源整合だけを確認。旧net符号反転又は未知成功として扱わない。'))
    print(json.dumps(dict(全合格=True, 検査数=CHECKS), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        write(HERE / 'False.json', dict(全合格=False, 検査数=CHECKS, 型=type(exc).__name__, 例外=str(exc),
                                      engine_SHA256=EXPECTED, 市場読取=0, 保存結果読取=0, cache読取=0))
        raise
