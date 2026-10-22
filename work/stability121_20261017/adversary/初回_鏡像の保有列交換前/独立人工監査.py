"""固定間隔・利確後再割当を人工気配だけで独立に検査する。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
ENGINE = BASE / 'engine121.py'
OLD = ROOT / 'work/stability120_20261017/recovery_e1/engine120e1.py'
CHECKS = []


def load(path: Path, name: str):
    """
    機能: 市場を読むことなく単一経済SOURCEを私有名で読み込む。
    引数: path(Path)はSOURCE、name(str)は衝突しないmodule名。
    返り値: moduleは人工に限って使用する実装。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    """
    機能: 小SOURCEの指紋を計算する。
    引数: path(Path)はSOURCE。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok, label: str) -> None:
    """
    機能: 独立期待の合否を記録し不一致を止める。
    引数: ok(bool)、label(str)は命題と内容。
    返り値: None。
    """
    assert bool(ok), label
    CHECKS.append(label)


def fixture(last, bid=None, ask=None, cap=10, spacing=3., trail=5., reset=True,
            entry_end=None, close_time=None, times=None, rows=None) -> tuple:
    """
    機能: 人工Lastと人工BBOから固定TOPIX条件を組み立てる。
    引数: last/bid/ask/times/rows(配列またはNone)、cap(int)、spacing/trail(float)、
        reset(bool)、entry_end/close_time(floatまたはNone)。
    返り値: tupleはengine.replayへの人工引数。
    """
    x = np.asarray(last, dtype=float)
    n = len(x)
    b = x.copy() if bid is None else np.asarray(bid, dtype=float)
    a = b + .5 if ask is None else np.asarray(ask, dtype=float)
    t = np.arange(n, dtype=float) if times is None else np.asarray(times, dtype=float)
    r = np.arange(n, dtype=np.int64) if rows is None else np.asarray(rows, dtype=np.int64)
    cutoff = float(n - 3) if entry_end is None else float(entry_end)
    close = float(n - 2) if close_time is None else float(close_time)
    return (r, t, x, b, a, cap, 1000., 41.8, .5, 1., 2, trail, spacing,
            reset, 0., cutoff, close, max(n + 2., float(np.nanmax(t)) + 2.))


def orders_of(output, kind=None, side=None) -> np.ndarray:
    """
    機能: 人工注文を型と実売買符号で抽出する。
    引数: output(tuple)、kind/side(intまたはNone)。
    返り値: ndarrayは抽出注文。
    """
    o = output[0]
    mask = np.ones(len(o), dtype=bool)
    if kind is not None:
        mask &= o[:, 1] == kind
    if side is not None:
        mask &= o[:, 2] == side
    return o[mask]


def independent_account(args: tuple, output: tuple, name: str) -> None:
    """
    機能: 注文だけからUID・現金・在庫清算時価・全行DDを独立に積み上げる。
    引数: args(tuple)は人工気配、output(tuple)は保存対象配列、name(str)は例名。
    返り値: None。玉別完結損益・次正常行fill・費用floorも照合する。
    """
    rows, times, last, bid, ask, cap, mult, fee = args[:8]
    start, _, _, end = args[-4:]
    fee_one = int(Decimal(str(fee)).to_integral_value(rounding=ROUND_FLOOR))
    o, lots, curve, summary = output
    normal = []
    watermark = -math.inf
    rejected = 0
    for i in range(len(rows)):
        finite = all(math.isfinite(float(v)) for v in (times[i], last[i], bid[i], ask[i]))
        if not finite or not (start <= times[i] <= end and times[i] >= watermark
                              and last[i] > 0 and 0 < bid[i] <= ask[i]):
            rejected += 1
            continue
        normal.append(i)
        watermark = float(times[i])
    mapping = {int(rows[i]): i for i in normal}
    byrow = {}
    for order in o:
        byrow.setdefault(int(order[4]), []).append(order)
        check(int(order[4]) > int(order[3]), name + ':同原行fillなし')
        next_rows = [int(rows[i]) for i in normal if rows[i] > order[3]]
        check(bool(next_rows) and next_rows[0] == int(order[4]), name + ':最初次正常行fill')
        qi = mapping[int(order[4])]
        xp = ask[qi] if order[2] == 1 else bid[qi]
        check(order[7] == xp and order[8] == fee_one, name + ':実売買BBOと注文料floor')
    active = {}
    completed = {}
    cash = realized = paid = high = drawdown = minimum = 0.
    max_long = max_short = 0
    expected_curve = []
    curve_clock = -math.inf
    equity = 0.
    for i in normal:
        raw = int(rows[i])
        for order in byrow.get(raw, []):
            uid, kind, side, price = int(order[0]), int(order[1]), int(order[2]), float(order[7])
            if kind == 1:
                check(uid not in active and uid not in completed, name + ':UID新規一回')
                active[uid] = (side, price, int(order[10]), raw, float(times[i]))
                cash -= fee_one
            else:
                check(uid in active, name + ':保有のあるUIDだけ返済')
                old_side, entry, rung, erow, etime = active.pop(uid)
                net = old_side * (price - entry) * mult - 2 * fee_one
                check(side == -old_side and order[16] == net, name + ':返済符号と純損益')
                check(int(order[10]) == rung, name + ':既存玉の段数保持')
                completed[uid] = (net, old_side * (price-entry) * mult,
                                  old_side, entry, price, erow, raw, etime, float(times[i]))
                cash += old_side * (price - entry) * mult - fee_one
                realized += net
            paid += fee_one
        long = sum(v[0] == 1 for v in active.values())
        short = sum(v[0] == -1 for v in active.values())
        check(long <= cap and short <= cap, name + ':片側上限')
        max_long, max_short = max(max_long, long), max(max_short, short)
        equity = cash + sum(side * ((bid[i] if side == 1 else ask[i]) - entry) * mult
                            - fee_one for side, entry, *_ in active.values())
        high = max(high, equity)
        minimum = min(minimum, equity)
        drawdown = max(drawdown, high - equity)
        row = [raw, times[i], equity, cash, realized, long, short, high - equity]
        if times[i] >= curve_clock + 60.:
            expected_curve.append(row)
            curve_clock = times[i]
    if normal:
        expected_curve.append(row)
    check(np.allclose(curve, np.asarray(expected_curve), rtol=0, atol=1e-8,
                      equal_nan=True), name + ':清算時価全curve')
    check(len(lots) == len(completed), name + ':完結玉件数')
    for lot in lots:
        net, gross, side, entry, exitp, erow, xrow, etime, xtime = completed[int(lot[0])]
        expected = [side, entry, exitp, gross, 2 * fee_one, net, erow, xrow, etime, xtime]
        actual = lot[[1, 6, 10, 11, 12, 13, 4, 8, 5, 9]]
        check(np.array_equal(actual, expected), name + ':完結玉建値と費用')
    positives = sum(max(v[0], 0.) for v in completed.values())
    negatives = sum(max(-v[0], 0.) for v in completed.values())
    actual = summary[[0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 15, 16, 17]]
    expected = [equity, cash, positives, negatives, paid, len(completed), len(active),
                max_long, max_short, drawdown, minimum, rejected, 1., len(active)*fee_one]
    check(np.allclose(actual, expected, rtol=0, atol=1e-8, equal_nan=True), name + ':独立末尾会計')


def run() -> dict:
    """
    機能: 固定人工と旧源対照でSOURCEだけの独立判定を作る。
    引数: なし。
    返り値: dictは合格・検査数・SOURCE指紋と観測範囲。
    """
    begin = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in (ENGINE, OLD)}
    new = load(ENGINE, 'adversary_fixed121')
    old = load(OLD, 'adversary_previous120e1')
    cases = []

    # ----------------------------------------
    # 純粋な順行階段と売鏡像。LastとBBOは別々に反転する。
    path = [3990, 3993, 3993, 3996, 3996, 3999, 3999, 4002, 4002, 4005, 4005, 4005]
    a = fixture(path, entry_end=9, close_time=10)
    buy = new.replay(*a)
    entries = orders_of(buy, 1, 1)
    check(np.array_equal(entries[:4, 3], [1, 3, 5, 7]), '3/6/9/12ptの判断原行')
    check(np.array_equal(entries[:4, 17], [3993, 3996, 3999, 4002]), '第一段3ptと独立3pt間隔')
    mirror = list(a)
    mirror[2], mirror[3], mirror[4] = 8000-a[2], 8000-a[4], 8000-a[3]
    sell = new.replay(*mirror)
    mirrored_entries = orders_of(sell, 1, -1)
    check(np.array_equal(entries[:, [3, 4, 10]], mirrored_entries[:, [3, 4, 10]]), '売鏡像の判断と段数')
    check(np.array_equal(8000-entries[:, 7], mirrored_entries[:, 7]), '売鏡像の実fillBBO')
    check(np.array_equal(buy[3], sell[3]), '上下鏡像の全会計')
    cases.extend([('純買階段', a, buy), ('純売階段', tuple(mirror), sell)])

    # ----------------------------------------
    # 新安値は空き段だけを追従させ、旧玉は3993.5のまま残る。
    a = fixture([3990, 3993, 3993, 3980, 3980, 3986, 3986, 3986, 3986],
                entry_end=6, close_time=7)
    out = new.replay(*a)
    e = orders_of(out, 1, 1)
    check(np.array_equal(e[:2, 17], [3993., 3986.]), '新安値後のrank1は3980+6')
    first = out[1][out[1][:, 0] == e[0, 0]][0]
    check(first[6] == 3993.5 and first[4] == 2 and first[2] == 0, '旧玉の建値UID段数不変')
    cases.append(('新安値と旧建値', a, out))

    # ----------------------------------------
    # 下位slotが損失で残る中、上位slotの正利確からrank0へ戻す。
    a = fixture([3990, 3993, 3993, 3980, 3980, 3986, 3986, 3994, 3994,
                 3989, 3989, 3992, 3992, 3995, 3995, 3995, 3995],
                entry_end=14, close_time=15)
    reset = new.replay(*a)
    original = list(a); original[13] = False
    noreset = new.replay(*original)
    e = orders_of(reset, 1, 1)
    check(any(row[3] == 11 and row[17] == 3992. and row[10] == 0 for row in e),
          '利確後の空き最初は物理slotに依存せず+3pt')
    check(not any(row[3] == 11 for row in orders_of(noreset, 1, 1)),
          '旧reset対照では同じ3992から再参加しない')
    first = reset[1][reset[1][:, 0] == 1][0]
    check(first[6] == 3993.5 and first[9] == 16 and first[14] == 9,
          '正利確再割当が損失側既存玉を消さない')
    check(not any(row[3] == 10 and row[2] == 1 for row in orders_of(reset, 1)),
          '利確実行原行の同方向新規禁止')
    cases.extend([('利確再割当あり', a, reset), ('利確再割当なし', tuple(original), noreset)])

    # ----------------------------------------
    # Lastと気配の乖離で、追尾判断行に同方向の別新規が予約される境界。
    lp = [3990, 3993, 3993, 4005, 4010, 4010, 4010, 4010]
    bp = [3990, 3993, 3993, 4005, 4000, 4000, 4000, 4000]
    a = fixture(lp, bid=bp, entry_end=6, close_time=6)
    reset = new.replay(*a)
    original = list(a); original[13] = False
    noreset = new.replay(*original)
    check(any(row[3] == 4 and row[4] == 5 for row in orders_of(noreset, 1, 1)),
          '取消対照で到達可能な旧新規予約が存在')
    check(not any(row[3] == 4 and row[4] == 5 for row in orders_of(reset, 1, 1)),
          '正利確後は同方向旧予約をfillより先に取消')
    check(reset[3][14] > noreset[3][14], '再割当取消を件数に残す')
    cases.extend([('同原行旧予約取消', a, reset), ('旧予約fill対照', tuple(original), noreset)])
    bad = list(a)
    bad[3] = np.asarray([3990, 3993, 3993, 4005, 4000, 3993, 3993, 3993.], dtype=float)
    bad[4] = bad[3] + .5
    bad_noreset = list(bad); bad_noreset[13] = False
    damaged = new.replay(*bad)
    check(any(row[14] == 1 and row[13] < 0 for row in damaged[1]),
          '判断時利益が次気配で損失になる例は実損保存')
    check(all(np.array_equal(x, y, equal_nan=True) for x, y in
              zip(damaged, new.replay(*bad_noreset))), '実fill損失では正利確resetしない')
    cases.append(('利確判断後の実損', tuple(bad), damaged))

    # ----------------------------------------
    # 旧unit=1の全配列同値、非空JIT、保有を残す未来接頭を固定乱数で確認。
    rng = np.random.default_rng(12120261017)
    baseline_cases = 0
    for cap in (1, 3, 10):
        for k in range(6):
            x = 4000. + np.cumsum(rng.integers(-8, 9, 80)) * .5
            b = x - .5
            a = fixture(x, bid=b, cap=cap, spacing=1., trail=1., reset=False,
                        entry_end=75, close_time=77)
            current = new.replay(*a)
            previous_args = a[:9] + (.00025, 2, 1.) + a[-4:]
            previous = old.replay(*previous_args)
            check(previous[3][16] == 1., '旧源の固定幅1pt資格')
            check(all(np.array_equal(x, y, equal_nan=True) for x, y in zip(current, previous)),
                  '旧e1 ROTATEとの全四配列exact同値')
            baseline_cases += 1
            cases.append((f'旧基準{cap}_{k}', a, current))
    for cap in (2, 10):
        for spacing, trail, reset in ((3., 5., False), (3., 5., True), (1., 5., False)):
            x = 4000. + np.cumsum(rng.integers(-8, 9, 140)) * .5
            a = fixture(x, cap=cap, spacing=spacing, trail=trail, reset=reset,
                        entry_end=130, close_time=135)
            fast = new.replay(*a)
            plain = new.replay.py_func(*a)
            check(len(fast[0]) > 0, '通常高速比較は実売買を伴う')
            check(all(np.array_equal(x, y, equal_nan=True) for x, y in zip(fast, plain)),
                  '非空通常JIT全配列exact同値')
            cut = 85
            prefix_args = tuple(v[:cut] if i < 5 else v for i, v in enumerate(a))
            prefix = new.replay(*prefix_args)
            check(np.array_equal(prefix[0], fast[0][fast[0][:, 4] < cut], equal_nan=True),
                  '未来接尾辞なしの注文接頭一致')
            check(np.array_equal(prefix[1], fast[1][fast[1][:, 8] < cut], equal_nan=True),
                  '未来接尾辞なしの完結玉接頭一致')
            check(prefix[3][13] - prefix[3][5] == prefix[3][8], '接頭EOFで未返済を架空清算しない')
            cases.append((f'通常高速{cap}_{spacing}_{trail}_{reset}', a, fast))
    for name, args, output in cases:
        independent_account(args, output, name)
    end = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in (ENGINE, OLD)}
    check(begin == end, 'SOURCE開始終端不変')
    return dict(passed=True, engine_sha256=sha(ENGINE), source_SHA256=begin,
                inspections=len(CHECKS), checks=CHECKS, synthetic_accounts=len(cases),
                baseline_exact_accounts=baseline_cases,
                scope='TOPIXの固定価格幅・ROTATEの人工だけ。実データ成績の検証ではない。',
                oracle='手記した閾値・鏡像・予約取消期待と、保存注文だけからのDecimal費用floor・UID・BBO・全行時価DDの独立積上げ。',
                original_market_reads=0, saved_market_cache_reads=0, API=0,
                financial_replays=0, registry_changes=0)


if __name__ == '__main__':
    target = HERE / '固定段間隔と方向別再割当の独立人工.json'
    assert not target.exists(), '既存の判定証跡を上書きしません'
    try:
        result = run()
    except Exception as exc:
        result = dict(passed=False, error=repr(exc), checks=CHECKS,
                      inspections=len(CHECKS), engine_sha256=sha(ENGINE),
                      original_market_reads=0, saved_market_cache_reads=0,
                      API=0, financial_replays=0, registry_changes=0)
        target.with_name('独立人工の初回False.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'], inspections=result['inspections'],
                          synthetic_accounts=result['synthetic_accounts'],
                          engine_sha256=result['engine_sha256'], proof_sha256=sha(target)),
                     ensure_ascii=False))
