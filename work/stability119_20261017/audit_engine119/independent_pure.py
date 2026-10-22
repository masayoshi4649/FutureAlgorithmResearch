"""市場値を使わず、119の因果執行と費用会計を独立した人工期待値で検査する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
ROOT = OWNER.parents[1]
CHECKS = 0
CASES = []


# ----------------------------------------


def digest(path: Path) -> str:
    """
    機能: 監査した小さい実装源の指紋を求める。
    引数: path(Path) は実装源。
    返り値: str はSHA256。市場値又は金融結果は対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(value: bool, name: str) -> None:
    """
    機能: 独立した人工期待条件の一致を数える。
    引数: value(bool) は条件、name(str) は不一致時の説明。
    返り値: None。不一致はAssertionErrorとして残す。
    """
    global CHECKS
    assert bool(value), name
    CHECKS += 1


def close(actual: float, expected: float, name: str) -> None:
    """
    機能: 円額・価格の人工期待値を比較する。
    引数: actual/expected(float) は観測値と期待値、name(str) は説明。
    返り値: None。
    """
    check(abs(actual - expected) <= 1e-6, f"{name}: {actual} != {expected}")


def fixture(bid: list[float] | np.ndarray, ask: list[float] | np.ndarray,
            publications: list[int], entries: list[int], widths: list[float] | None = None,
            exits: list[bool] | None = None, valid: list[bool] | None = None,
            times: list[float] | None = None, anchor: list[float] | None = None,
            direction: int = 1, **overrides: object) -> tuple[dict, dict, dict, dict]:
    """
    機能: 原rowに対応する正常気配と公開足の純人工入力を作る。
    引数: bid/ask(配列)、publications/entries(list[int])、任意の純人工列と設定上書き。
    返り値: tuple[dict,dict,dict,dict] はbars・quotes・policy・settings。
    """
    bid, ask = np.asarray(bid, dtype=float), np.asarray(ask, dtype=float)
    n, m = len(bid), len(publications)
    qt = np.arange(n, dtype=float) if times is None else np.asarray(times, dtype=float)
    pr = np.asarray(publications, dtype=np.int64)
    pt = qt[pr] if n else pr.astype(float)
    bars = dict(valid=np.ones(m, dtype=bool), anchor=np.full(m, 1000.) if anchor is None else np.asarray(anchor, dtype=float),
                pub_raw_row=pr, pub_price_time_s=pt, t_s=pt.copy())
    quotes = dict(row=np.arange(n, dtype=np.int64), time=qt, bid=bid, ask=ask)
    policy = dict(entry=direction * np.asarray(entries, dtype=np.int8),
                  exit_long=np.asarray(exits if exits is not None else [False] * m, dtype=bool),
                  exit_short=np.asarray(exits if exits is not None else [False] * m, dtype=bool),
                  width=np.asarray(widths if widths is not None else [100.] * m, dtype=float),
                  valid=np.asarray(valid if valid is not None else [True] * m, dtype=bool))
    settings = dict(quantity=3, multiplier=1000., fee=41.8, exit_mode=1, entry_mode=0,
                    guard=0, entry_end=1e10, close_time=1e10)
    settings.update(overrides)
    return bars, quotes, policy, settings


def run(engine: object, f: tuple[dict, dict, dict, dict]) -> dict:
    """
    機能: 人工入力だけを実装へ渡し、共通会計不変量を確認する。
    引数: engine(object) は源を変更しない私有import、f(tuple) は人工入力。
    返り値: dict は人工結果。
    """
    result = engine.run_policy(*f)
    s, ledger = result["summary"], result["ledger"]
    close(s["profit"] - s["loss"], sum(ledger[:, 12]), "親損益の総和")
    close(s["fees"], sum(ledger[:, 9]) - s["realized"], "全新規・返済手数料")
    check(np.all(ledger[:, 2] > ledger[:, 1]), "新規より後の返済row")
    check(s["closed_quantity"] == int(sum(ledger[:, 6])), "返済枚数")
    if s["unclosed"] == 0:
        close(s["net"], s["realized"], "全返済後の評価と現金")
        close(s["net"], s["profit"] - s["loss"], "全返済親会計")
    return result


def main() -> None:
    """
    機能: 因果執行・費用・親会計・EOF・prefix不変を純人工で敵対的に検査する。
    引数: なし。
    返り値: None。市場入力・既金融結果・APIは読まない。
    """
    names = [OWNER / "engine119.py", OWNER / "input119.py", ROOT / "work/topix10pt_20261016/input.py", Path(__file__)]
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in names}
    spec = importlib.util.spec_from_file_location("_audit119_engine_source_only", OWNER / "engine119.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)

    f = fixture([999.], [1000.], [0], [1])
    r = run(engine, f)
    check(r["summary"]["fills"] == 0 and len(r["ledger"]) == 0, "同row約定禁止")
    close(r["summary"]["net"], 0., "未約定は無利益")
    f = fixture([999., 999.], [1000., 1000.], [0], [1], times=[0., 0.])
    r = run(engine, f)
    check(r["summary"]["fills"] == 1 and r["summary"]["unclosed"] == 3, "同時計後続rowは約定")
    check(len(r["ledger"]) == 0 and r["summary"]["parents"] == 0, "EOF参考評価は実返済へ化けない")
    close(r["summary"]["realized"], -125., "3枚新規手数料切捨て")
    close(r["summary"]["net"], -3250., "EOFは未返済損失と予定返済手数料を含む")
    CASES.append("同row禁止・同時計後続row・EOF未清算・評価損失と予定返済費用")

    for d in (1, -1):
        b, a = np.array([999., 999., 1010.]), np.array([1000., 1000., 1011.])
        if d == -1:
            b, a = 2000. - a, 2000. - b
        r = run(engine, fixture(b, a, [0, 1], [1, 0], exits=[False, True], direction=d))
        check(r["ledger"][:, 1].tolist() == [1.] and r["ledger"][:, 2].tolist() == [2.], "判断次原row約定")
        close(r["summary"]["net"], 29750., "売買対称と往復250円")
        close(r["summary"]["fees"], 250., "片道125円を二回")
    CASES.append("買ask・売bid・売買対称・一注文単位の費用切捨て")

    f = fixture([999., 999.5, 1010., 1011., 1012.], [1000., 1000., 1011., 1012., 1013.],
                [0, 3], [1, 0], widths=[10., 10.], exits=[False, True], exit_mode=2)
    r = run(engine, f)
    check(r["ledger"][:, 6].tolist() == [1., 2.], "3枚の1枚半減・2枚残返済")
    check(r["ledger"][:, 13].tolist() == [8., 4.], "半減理由と反対条件返済")
    close(sum(r["ledger"][:, 10]), 125., "新規費用按分の総和")
    close(sum(r["ledger"][:, 11]), 124., "分割返済41円と83円")
    close(r["summary"]["net"], 34751., "親一組の純利益")
    check(r["summary"]["parents"] == 1 and r["summary"]["wins"] == 1, "分割を二勝へ水増ししない")
    CASES.append("奇数枚半減・entryfee按分・分割費用丸め・親単位会計")

    r = run(engine, fixture([999., 999., 1010.], [1000., 1000., 1011.], [0, 1], [1, 0],
                            exits=[False, True], valid=[True, False], widths=[100., np.nan]))
    check(r["summary"]["unclosed"] == 0 and r["ledger"][0, 13] == 4., "入口不適格でも既知出口が作用")
    CASES.append("入口資格と保有中出口を分離")

    r = run(engine, fixture([999., 999.5, 990., 980.], [1000., 1000., 991., 981.], [0], [1],
                            widths=[5.], quantity=1))
    close(r["summary"]["net"], -20082., "損切り閾値でなく次正常気配")
    check(r["ledger"][0, 2] == 3. and r["ledger"][0, 13] == 1., "stop判断row2からrow3約定")
    r = run(engine, fixture([999., 999.5, 980., 960.], [1000., 1000., 981., 961.], [0], [1],
                            widths=[5.], quantity=1, guard=1))
    close(r["summary"]["net"], -40082., "場損失予算を超えるギャップ約定")
    check(r["summary"]["halted"] == 5 and r["ledger"][0, 13] == 5., "予算は発注閾値")
    CASES.append("逆指値ギャップ・場予算超過・判断後次値による損失")

    r = run(engine, fixture([999., 998.5, 997.], [1000., 999., 998.], [0], [1],
                            widths=[10.], entry_mode=1, times=[0., 10., 181.]))
    check(r["summary"]["fills"] == 0 and r["summary"]["canceled"] == 1, "指値期限超過は到達前取消")
    r = run(engine, fixture([999., 997.], [1000., 997.5], [0], [1], widths=[10.], entry_mode=1))
    close(r["summary"]["net"], -3250., "到達指値998円と売bid997円で参考評価")
    r = run(engine, fixture([999., 999.], [1000., 1000.], [0], [1], times=[0., 61.]))
    check(r["summary"]["fills"] == 0 and r["summary"]["canceled"] == 1, "成行新規の60秒期限")
    r = run(engine, fixture([999., 999.], [1000., 1000.], [0], [1], times=[0., 50.], entry_end=50.))
    check(r["summary"]["fills"] == 0 and r["summary"]["canceled"] == 1, "新規締切は発注済み新規も取消")
    CASES.append("指値未達・反対気配到達・指値の保守的建値・新規期限取消")

    # ----------------------------------------
    # 注文商品の刻みへ買いは下、売りは上へ丸め、丸め前価格の到達で約定しない。
    for tick, rounded, multiplier, fee in ((.25, 999.25, 1000., 41.8), (5., 995., 10., 11.)):
        raw_limit = 999.4
        between = (raw_limit + rounded) / 2.
        buy_bid = np.asarray([999., between - .5, rounded - .5, rounded + 1.])
        buy_ask = np.asarray([1000., between, rounded, rounded + 1.5])
        for d in (1, -1):
            qb, qa = (buy_bid, buy_ask) if d == 1 else (2000. - buy_ask, 2000. - buy_bid)
            f = fixture(qb, qa, [0, 2], [1, 0], widths=[3., 3.], exits=[False, True], direction=d,
                        entry_mode=1, order_tick=tick, multiplier=multiplier, fee=fee)
            r = run(engine, f)
            check(len(r["ledger"]) == 1 and r["ledger"][0, 1] == 2., "丸め前だけの到達では未約定")
            expected_price = rounded if d == 1 else 2000. - rounded
            close(r["ledger"][0, 7], expected_price, "指値を実商品刻みの有利側へ丸める")
            close(r["ledger"][0, 7] / tick, round(r["ledger"][0, 7] / tick), "実商品刻みの整数倍")
            close(r["summary"]["net"], 3. * multiplier - 2. * int(3. * fee), "刻み追加後も費用後会計一致")
    CASES.append("TOPIXmini0.25・NKmicro5の指値刻み、買floor・売ceil、丸め前到達では未約定")

    f = fixture([999., 999.5, 1001., 1002.], [1000., 1000., 1002., 1003.], [0], [1], close_time=2.)
    r = run(engine, f)
    check(r["summary"]["unclosed"] == 0 and r["ledger"][0, 2] == 3., "場締切後の次正常気配で返済")
    check(r["ledger"][0, 13] == 7., "場締切理由")
    short = list(f)
    short[1] = {key: value[:3].copy() for key, value in f[1].items()}
    r = run(engine, tuple(short))
    check(r["summary"]["unclosed"] == 3 and len(r["ledger"]) == 0, "締切後の次値なしは未清算")
    CASES.append("固定場末締切・次気配なしの未清算を隠さない")

    r = run(engine, fixture([], [], [0], [1]))
    check(r["summary"]["fills"] == 0 and r["summary"]["net"] == 0., "正常気配ゼロ")

    # ----------------------------------------
    # 将来の価格を替えても、同じ原prefix時点の足公開資産と約定は変わらない。
    rng = np.random.default_rng(119)
    for case in range(36):
        mid = 1000. + np.cumsum(rng.normal(0., 2., 90))
        spread = rng.choice([.5, 1., 2.], size=90)
        b, a = mid - spread / 2., mid + spread / 2.
        pubs = list(range(0, 89, 3))
        entries = [1 if j % 5 == 0 else 0 for j in range(len(pubs))]
        exits = [j % 5 == 3 for j in range(len(pubs))]
        width = float(rng.choice([3., 6., 15.]))
        mode, entrymode, guard = case % 3, (case // 3) % 2, (case // 6) % 2
        f = fixture(b, a, pubs, entries, widths=[width] * len(pubs), exits=exits,
                    exit_mode=mode, entry_mode=entrymode, guard=guard, quantity=1 + case % 10)
        full = run(engine, f)
        mirrored = fixture(2000. - a, 2000. - b, pubs, entries, widths=[width] * len(pubs), exits=exits,
                           direction=-1, exit_mode=mode, entry_mode=entrymode, guard=guard, quantity=1 + case % 10)
        other = run(engine, mirrored)
        for key in ("net", "realized", "profit", "loss", "fees", "unclosed", "canceled", "fills", "halted"):
            close(full["summary"][key], other["summary"][key], "乱数人工系列の売買鏡像")
        for cutoff in (5, 17, 38, 66):
            pubmask = np.asarray(pubs) <= cutoff
            pf = (
                {key: value[pubmask].copy() for key, value in f[0].items()},
                {key: value[:cutoff + 1].copy() for key, value in f[1].items()},
                {key: value[pubmask].copy() for key, value in f[2].items()}, dict(f[3]),
            )
            prefix = run(engine, pf)
            np.testing.assert_allclose(prefix["equity"], full["equity"][pubmask], equal_nan=True, atol=1e-7)
            check(True, "prefix公開資産不変")
            np.testing.assert_array_equal(prefix["position"], full["position"][pubmask])
            check(True, "prefix公開建玉不変")
            actual_ledger = full["ledger"][full["ledger"][:, 2] <= cutoff]
            np.testing.assert_allclose(prefix["ledger"], actual_ledger, equal_nan=True, atol=1e-7)
            check(True, "prefix約定明細不変")
    CASES.append("乱数36条件×売買鏡像と4prefixの因果性・全出口/新規/場予算モード")

    after = {p.relative_to(ROOT).as_posix(): digest(p) for p in names}
    check(before == after, "監査中の源不変")
    proof = dict(全合格=True, 検査数=CHECKS, 合成乱数seed=119, 人工乱数条件=36,
                 市場入力読取=0, prepared読取=0, 既金融結果読取=0, 新金融=0, API=0,
                 source_SHA256=after, 検査群=CASES,
                 限界="源の因果執行・費用会計の純人工監査。手法の収益性、市場データの完全性、実商品の約定可能性の証明ではない。")
    proof["差分"] = "旧成功2030項目を新経済源へ再接続し、実商品指値刻みの独立期待値を追加。旧源/成功証跡はrevision1に保全。"
    destination = HERE / "因果約定と親会計及び実商品指値刻みの独立純人工検査_v2.json"
    assert not destination.exists()
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
