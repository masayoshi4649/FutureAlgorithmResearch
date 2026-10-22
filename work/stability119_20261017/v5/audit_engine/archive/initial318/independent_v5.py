"""市場を使わず、二脚NTの注文先後・孤立脚・費用と因果性を独立に検査する。"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
V5 = HERE.parent
ROOT = V5.parents[2]
EXPECTED = "8b35b81d9c735281e5c775008f328ae6f5686c83be78d22faccfa5cbd84492d8"
os.environ["NUMBA_CACHE_DIR"] = str(HERE / "private_numba_cache")
sys.dont_write_bytecode = True
sys.path.insert(0, str(V5))
import engine_v5 as engine

CHECKS = 0


# ----------------------------------------


def check(value: bool, description: str) -> None:
    """
    機能: 独立期待値との一致を検査し、不一致なら停止する。
    引数: value(bool) は検査条件、description(str) は内容。
    返り値: None。
    """
    global CHECKS
    assert bool(value), description
    CHECKS += 1


def near(actual: object, expected: object, description: str) -> None:
    """
    機能: 数値配列を有限誤差の範囲で比較する。
    引数: actual/expected(object) は数値、description(str) は内容。
    返り値: None。
    """
    check(np.allclose(actual, expected, atol=1e-7, rtol=1e-10, equal_nan=True), description)


def write(path: Path, value: dict) -> None:
    """
    機能: 所有領域に新しい監査証跡を保存する。
    引数: path(Path) は保存先、value(dict) は有限JSON。
    返り値: None。既存の成功及び失敗は上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def quotes(times: list[float], last: list[float], spread: float) -> dict:
    """
    機能: 指定した時計と現在値だけから人工の正常気配を作る。
    引数: times/last(list[float]) は時刻と価格、spread(float) は売買気配幅。
    返り値: dict は各商品自身の原row及び人工気配列。
    """
    p = np.asarray(last, float)
    n = len(p)
    return dict(row=np.arange(n, dtype=np.int64) * 7 + 2, time=np.asarray(times, float), last=p,
                bid=p - spread / 2., ask=p + spread / 2., bq=np.ones(n), aq=np.ones(n))


def replay(nk: dict, top: dict, clocks: list[float], history: np.ndarray | None = None,
           force: float = 1000., entry_end: float = 900.) -> tuple:
    """
    機能: 人工時計と固定した手計算モデルを核心へ渡す。
    引数: nk/top(dict)、clocks(list[float])、history(配列又はNone)、force/entry_end(float)。
    返り値: tuple は核心の保存注文・親・時価等。市場読取と金融効果の実測は行わない。
    """
    clock = np.asarray(clocks, float)
    if history is None:
        history = np.tile([0., 1., math.log(100.), .001], (len(clock), 1))
        history[0, 0] = 1.
    events = []
    for leg, q in enumerate((nk, top)):
        events.extend((float(t), leg, int(row), i) for i, (t, row) in enumerate(zip(q["time"], q["row"])))
    events.extend((float(t), 2, 0, i) for i, t in enumerate(clock))
    events.sort()
    return engine.replay(np.asarray([e[0] for e in events]), np.asarray([e[1] for e in events], np.int8),
        np.asarray([e[3] for e in events], np.int64), clock, history,
        nk["row"], nk["time"], nk["bid"], nk["ask"], nk["last"],
        top["row"], top["time"], top["bid"], top["ask"], top["last"], entry_end, force)


def order_account(result: tuple) -> None:
    """
    機能: 人工の全注文を手数料と建玉元本から独立に集計する。
    引数: result(tuple) は核心の一回の人工返却。
    返り値: None。全親の費用・gross・現金と数量を照合する。
    """
    orders, parents, _, _, cash, _, gross, fees, counts = result
    total_gross, total_fees = np.zeros(2), np.zeros(2)
    for leg, (multiplier, fee) in enumerate(((10., 11.), (1000., 41.8))):
        own = orders[orders[:, 1] == leg]
        near(own[:, 9], np.floor(own[:, 4] * fee + 1e-9), "各脚各注文の円未満切捨て")
        check(np.all(own[:, 6] > own[:, 5]), "新規返済とも判断と同clock約定禁止")
        near(own[:, 13], own[:, 6] - own[:, 5], "注文待ち秒数")
        total_fees[leg] = sum(own[:, 9])
        held = 0
        for parent in np.unique(own[:, 0]):
            legs = own[own[:, 0] == parent]
            entry = legs[legs[:, 2] == 1]
            close = legs[legs[:, 2] == 2]
            check(len(entry) == 1 and len(close) <= 1, "各親各脚は一新規一返済以内")
            first = entry[0]
            if len(close):
                last = close[0]
                near(last[4], first[4], "全数量返済")
                near(last[3], -first[3], "返済は反対売買")
                check(last[6] > first[6], "返済は新規後の価格時計")
                total_gross[leg] += first[3] * (last[8] - first[8]) * first[4] * multiplier
            else:
                held += first[4]
        near(counts[4 + leg], held, "未返済脚数量")
    near(gross, total_gross, "全親を含む脚別gross")
    near(fees, total_fees, "全親を含む脚別費用")
    near(cash, total_gross - total_fees, "脚別現金")
    for parent in parents:
        own = orders[orders[:, 0] == parent[0]]
        for leg in range(2):
            near(parent[24 + leg], sum(own[own[:, 1] == leg, 9]), "各親の脚別費用")
        near(parent[26] + parent[27], parent[28], "親の二脚純損益和")


# ----------------------------------------


def main() -> None:
    """
    機能: 少数の手計算人工で二脚NTの執行とモデル因果性を検査する。
    引数: なし。原市場・保存結果・原cacheは読まない。
    返り値: None。源指紋付き証跡を所有領域に保存する。
    """
    source = V5 / "engine_v5.py"
    check(hashlib.sha256(source.read_bytes()).hexdigest() == EXPECTED, "閉鎖核心源一致")
    near(engine.choose_quantities(100000., 1000., 1.), (1., 1., 0.), "整数ヘッジ同率では最小元本")
    qn, qt, error = engine.choose_quantities(100000., 1000., 2.)
    near((qn, qt, error), (1., 2., 0.), "β付き元本でヘッジ")
    qn, qt, error = engine.choose_quantities(1., 1000., 1.)
    check(qn == qt == 0 and np.isnan(error), "上限内の誤差5%組がなければ不参加")

    cases = {}
    for direction, start in (("NK売TOP買", 101000.), ("NK買TOP売", 99000.)):
        nk = quotes([0., 0., 1., 10., 11., 70.], [start, start, start, 100000., 100000., 100000.], 2.)
        top = quotes([0., 0., 2., 12., 70.], [1000.] * 5, .02)
        result = replay(nk, top, [0., 1.5, 2.5, 60.])
        order_account(result)
        orders, parents, curve = result[:3]
        near(orders[:, 6], [1., 2., 11., 12.], "二脚の非同時新規と非同時返済:" + direction)
        near(curve[1, 4:6], [-1., 0.] if start > 100000. else [1., 0.], "片脚時間帯の実保有")
        near(curve[1, 1:4], [-11., -31., -42.], "孤立脚の現金と返済費込みMTM")
        near(result[4], [9958., -102.], "両方向の脚別実現現金")
        near(parents[:, 28], [9856.], "両方向で手計算した組純利益")
        near(parents[:, 30], [2.], "新規及び返済の孤立時間総和")
        cases[direction] = dict(net=float(result[4].sum()), orders=len(orders))

    nk = quotes([0., 1., 60., 61., 121.], [101000.] * 5, 2.)
    top = quotes([0., 60., 70., 121.], [1000.] * 4, .02)
    result = replay(nk, top, [0., 60., 120.])
    order_account(result)
    near(result[0][:, 1:3], [[0., 1.], [0., 2.]], "期限と同clockの第二脚を取消して片脚だけ返済")
    near(result[0][:, 6], [1., 61.], "期限の次clock返済")
    near(result[4], [-42., 0.], "孤立脚を損失なしに戻したことにしない")
    check(result[8][2] == 1 and result[1][0, 29] == 1 and result[1][0, 5] == 4, "片脚timeoutの取消と親診断")

    result = replay(quotes([0., 70.], [101000.] * 2, 2.), quotes([0., 70.], [1000.] * 2, .02), [0., 60.])
    order_account(result)
    check(len(result[0]) == len(result[1]) == 0 and result[8][1] == 1 and result[8][2] == 2, "全未約定は取消で終わり勝ち親なし")

    result = replay(quotes([0., 1., 3.], [101000.] * 3, 2.), quotes([0., 2., 3.], [1000.] * 3, .02), [0., 2.], force=2., entry_end=1.9)
    order_account(result)
    near(result[0][:, 6], [1., 3.], "場末同clockの未約定脚を入れず保有脚を次clockで返済")
    check(result[1][0, 5] == 5 and result[8][2] == 1, "場末孤立脚返済と取消")

    result = replay(quotes([0., 1.], [101000.] * 2, 2.), quotes([0., 2.], [1000.] * 2, .02), [0., 2.], force=2., entry_end=1.9)
    order_account(result)
    check(result[8][4] == 1 and result[1][0, 1] == 0 and np.isnan(result[1][0, 16]), "EOF未返済を価格補完で実決済にしない")
    near(result[4].sum() + result[5].sum(), -42., "EOFの未清算返済費込み参考時価")

    nk = quotes([0., 1., 3., 4., 70.], [101000., 101000., 105000., 106000., 106000.], 2.)
    top = quotes([0., 2., 5., 70.], [1000.] * 4, .02)
    result = replay(nk, top, [0., 60.])
    order_account(result)
    near(result[4].sum(), -50144., "外側反証後も次気配gap損失を消さない")
    check(result[1][0, 5] == 2 and -result[1][0, 28] > result[1][0, 10], "予定利益額は最大損失保証ではない")

    nk = quotes([0., 1., 2., 3., 70.], [101000.] * 5, 2.)
    nk["bid"][2:], nk["ask"][2:] = 100000., 103000.
    top = quotes([0., 4., 70.], [1000.] * 3, .02)
    result = replay(nk, top, [0., 60.])
    order_account(result)
    check(result[1][0, 5] == 3 and result[1][0, 29] == 1, "第二脚成立前もcash損失反証が作用")
    near(result[4].sum(), -20032., "気配拡幅時の孤立脚損失")

    nk = quotes([0., 1., 10., 11., 59., 61., 70., 71., 130.],
                [101000., 101000., 100000., 100000., 101000., 101000., 100000., 100000., 100000.], 2.)
    top = quotes([0., 2., 12., 59., 62., 72., 130.], [1000.] * 7, .02)
    history = np.tile([1., 1., math.log(100.), .001], (3, 1))
    result = replay(nk, top, [0., 60., 120.], history)
    order_account(result)
    check(len(result[0]) == 8 and len(result[1]) == 2, "中心再到達後の二親を受理")
    near(result[4].sum(), 19712., "複数親の累積現金を最終親へリセットしない")
    near(result[7], [44., 164.], "複数親の全注文累積手数料")
    short_nk = {key: value[nk["time"] <= 65].copy() for key, value in nk.items()}
    short_top = {key: value[top["time"] <= 65].copy() for key, value in top.items()}
    prefix = replay(short_nk, short_top, [0., 60.], history[:2])
    near(prefix[0], result[0][result[0][:, 6] <= 65], "prefixまでの実注文不変")
    near(prefix[2], result[2][:2], "prefixまでの現金・MTM・保有・DD不変")
    near(prefix[3], result[3][:2], "prefixまでのモデル・受理不変")
    changed_nk = {key: value.copy() for key, value in nk.items()}
    for key in ("last", "bid", "ask"):
        changed_nk[key][nk["time"] > 65] *= 2.
    alternate = replay(changed_nk, top, [0., 60., 120.], history)
    near(alternate[0][alternate[0][:, 6] <= 65], prefix[0], "未来置換でも過去注文不変")
    near(alternate[2][:2], prefix[2], "未来置換でも過去時価不変")

    nk = quotes([0., 1., 3., 4., 59., 65., 119., 121., 130., 131.],
                [101000., 101000., 105000., 106000., 106000., 100000., 101000., 101000., 100000., 100000.], 2.)
    top = quotes([0., 2., 5., 59., 65., 119., 122., 132.], [1000.] * 8, .02)
    history = np.tile([1., 1., math.log(100.), .001], (3, 1))
    history[1, 2] = math.log(110.)
    result = replay(nk, top, [0., 60., 120.], history)
    order_account(result)
    near(result[3][:, 12], [1., 0., 1.], "損切り後は当初固定中心の到達まで再武装を禁止")
    check(result[3][1, 15] == 1 and result[3][1, 16] == 0, "新モデル中心が動いても古いarm参照を保持")

    center_price = 100000. * math.exp(-.01)
    nk = quotes([0., 1., 10., 11., 70.], [100000., 100000., center_price, center_price, center_price], 2.)
    top = quotes([0., 2., 12., 70.], [1000.] * 4, .02)
    history = np.tile([0., 2., math.log(100000.) - 2. * math.log(1000.) - .01, .001], (2, 1))
    history[0, 0] = 1.
    result = replay(nk, top, [0., 60.], history)
    order_account(result)
    near(result[0][:, 4], [1., 2., 1., 2.], "β2でTOP枚数二倍を入口時固定")
    near(result[0][:, 9], [11., 83., 11., 83.], "41.8円二枚の各注文は83円")
    near(result[4].sum(), (99999. - (center_price + 1.)) * 10. - .02 * 2. * 1000. - 188., "β2整数ヘッジの手計算純損益")

    nk = quotes([0., 1., 3., 4., 70.], [100000., 100000., 110000., 110000., 110000.], 2.)
    top = quotes([0., 2., 3., 5., 70.], [1000., 1000., 1100., 1100., 1100.], .02)
    history = np.tile([0., 1., math.log(99.), .001], (2, 1))
    history[0, 0] = 1.
    same_clock = replay(nk, top, [0., 60.], history)
    order_account(same_clock)
    check(same_clock[1][0, 5] == 2, "同clockの共通上昇でもNK先観測中間残差で外側判定が発生する")
    near(same_clock[1][0, 33], 0., "同clock問題の素材は整数ヘッジ誤差0")
    near(same_clock[4].sum(), -144., "同clock共通上昇の順序仮定による不要返済は費用損")

    times = np.arange(70, dtype=float) * 60.
    x = 1000. * np.exp(np.arange(70) * .0001)
    residual = .0002 * np.sin(np.arange(70) * .71)
    nk = dict(t_s=times, valid=np.ones(70, bool), close=100. * x * np.exp(residual), pub_price_time_s=times + 60.)
    top = dict(t_s=times, valid=np.ones(70, bool), close=x.copy(), pub_price_time_s=times + 60.)
    for method in ("ratio_mr", "ols_mr"):
        for lookback in (30, 60):
            clocks = np.asarray([lookback * 60., (lookback + 1) * 60.])
            history = engine.model_history(nk, top, clocks, method, lookback)
            check(np.all(history[:, 0] == 1), "過去連続足からモデルが得られる")
            past_nk = {key: value.copy() for key, value in nk.items()}
            past_nk["close"][lookback:] *= 2.
            replaced = engine.model_history(past_nk, top, clocks[:1], method, lookback)
            near(replaced, history[:1], "未来の価格置換で既モデル不変")
            delayed = {key: value.copy() for key, value in nk.items()}
            delayed["pub_price_time_s"][lookback - 1] = clocks[0] + .001
            check(engine.model_history(delayed, top, clocks[:1], method, lookback)[0, 0] == 0, "足時計が過去でも未公開なら未知")
            invalid = {key: value.copy() for key, value in nk.items()}
            invalid["valid"][lookback - 2] = False
            check(engine.model_history(invalid, top, clocks[:1], method, lookback)[0, 0] == 0, "空足を飛ばして連続学習しない")

    check(hashlib.sha256(source.read_bytes()).hexdigest() == EXPECTED, "人工後も閉鎖核心源不変")
    write(HERE / "二脚独立約定と孤立脚会計及び過去公開モデルの独立人工_v2.json", dict(全合格=True,
        検査数=CHECKS, engine_SHA256=EXPECTED, 監査源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        市場読取=0, 保存結果読取=0, cache読取=0, 金融効果の実測=0, cases=cases,
        同clock仮定の注意="NK/TOPが同clockで同率上昇しても、NK先の中間残差が外側判定を作る。真の受信順は不明。根の固定可否判断が必要。",
        留保="源整合の純人工。実市場の収益性又は未知成功の証拠には数えない。"))
    print(json.dumps(dict(全合格=True, 検査数=CHECKS), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        write(HERE / "False.json", dict(全合格=False, 検査数=CHECKS, 型=type(exc).__name__, 例外=str(exc),
                                        engine_SHA256=EXPECTED, 市場読取=0, 保存結果読取=0, cache読取=0))
        raise
