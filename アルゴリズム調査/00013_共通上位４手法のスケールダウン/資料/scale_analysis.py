"""共通上位４手法の保存済み約定を、整数枚数と小口商品の倍率へ換算する。"""

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


WORK = Path(__file__).resolve().parent
SOURCE = WORK.parent / "wave_v17"
IDS = ["M3_逆_A03", "M3_逆_A00", "M2_逆_A00", "M2_逆_A01"]
SESSIONS = [f"2026-09-{day:02d}_{kind}" for day in range(21, 26) for kind in ["Day", "Night"]]
PRODUCTS = {
    "TOPIX": {"name": "TOPIXミニ", "multiplier": 1000, "original_multiplier": 10000,
              "tick": 0.25, "cap": 10,
              "source_url": "https://www.jpx.co.jp/derivatives/products/domestic/mini-topix-futures/index.html"},
    "NK225": {"name": "NK225マイクロ", "multiplier": 10, "original_multiplier": 1000,
              "tick": 5, "cap": 20,
              "source_url": "https://www.jpx.co.jp/derivatives/products/domestic/225micro-futures/01.html"},
}
NAMES = {"M3_逆_A03": "両銘柄の逆方向を狙い、順行後に追加", "M3_逆_A00": "両銘柄の逆方向を固定枚数で保持",
         "M2_逆_A00": "板の偏りの逆方向を固定枚数で保持", "M2_逆_A01": "板の逆方向を広い追跡幅で保持"}
QUANTITY_FIELDS = {"profit_units", "loss_units", "zero_units", "unit_balance", "closed_units",
                   "max_long", "max_short", "max_gross", "max_net"}
CHECKS = {"整数枚数の返済行数": 0, "区間集計数": 0, "週集計数": 0, "現在セッション取得": 0}


def read(name):
    """元作業の日本語JSONを読む。

    引数: name (str) はファイル名。返り値: JSON内容 (dict | list)。
    """
    return json.loads((SOURCE / name).read_text(encoding="utf-8-sig"))


def integer_scale(value, factor):
    """端数枚数を許さず数量を換算する。

    引数: value (int | float) は元枚数、factor (Fraction) は倍率。返り値: 整数枚数 (int)。
    """
    result = Fraction(int(value)) * factor
    assert int(value) == value and result.denominator == 1, (value, factor)
    return result.numerator


def scale_row(original, factor, symbol):
    """金額・枚数・１枚平均をそれぞれ正しい倍率で換算する。

    引数: original (dict) は元集計、factor (Fraction) は数量倍率、symbol (str) は銘柄。
    返り値: 換算した集計 (dict)。比率・件数・時刻条件は変えない。
    """
    product = PRODUCTS[symbol]
    contract = product["multiplier"] / product["original_multiplier"]
    money = float(factor) * contract
    row = dict(original)
    for key, value in original.items():
        if key in QUANTITY_FIELDS:
            row[key] = integer_scale(value, factor)
        elif key.endswith("_yen"):
            row[key] = round(value * money, 8)
        elif key in ("avg_profit_per_unit", "avg_loss_per_unit") and value is not None:
            row[key] = value * contract
        elif key == "cash_error":
            row[key] = value * float(factor)
    assert row["max_long"] <= product["cap"] and row["max_short"] <= product["cap"]
    assert row["max_gross"] <= product["cap"]
    return row


def check_trades(block, row, factor, symbol):
    """建値・返済値から小口契約の損益を再計算し、表示集計と照合する。

    引数: block (dict) は元返済台帳、row (dict) は換算区間、factor (Fraction)、symbol (str)。
    返り値: 初期損失予算の配列 (ndarray)。
    """
    trades, cycles = block["trades"], block["cycles"]
    product = PRODUCTS[symbol]
    quantities = np.array([integer_scale(q, factor) for q in trades[:, 3]], dtype=np.int64)
    values = quantities * trades[:, 2] * (trades[:, 5] - trades[:, 4]) * product["multiplier"]
    win, loss = values > 0, values < 0
    actual = {"gross_profit_yen": values[win].sum(), "gross_loss_yen": -values[loss].sum(),
              "net_yen": values.sum(), "profit_units": quantities[win].sum(),
              "loss_units": quantities[loss].sum(), "zero_units": quantities[values == 0].sum()}
    for key, value in actual.items():
        assert abs(row[key] - value) < 0.00001, (row["method_id"], row["session"], symbol, key)
    np.testing.assert_allclose(trades[:, 4:6] / product["tick"], np.rint(trades[:, 4:6] / product["tick"]), atol=1e-8)
    assert np.all(trades[:, 8] == 0), "対象方式にカバーが含まれている"
    CHECKS["整数枚数の返済行数"] += len(trades)
    CHECKS["区間集計数"] += 1
    return cycles[:, 4] * float(factor) * product["multiplier"]


def variant(method_id, symbol, original_config, weeks, rows, blocks, uniform=False):
    """最大保有枚数または共通初期枚数をそろえた小口版を作成する。

    引数: method_id/symbol (str)、original_config/weeks/rows/blocks (dict)、uniform (bool)。
    返り値: 規則・週・各区間・初期損失予算 (dict)。
    """
    product = PRODUCTS[symbol]
    adding = original_config["manager"] == "A03"
    source_cap = 100 if adding or uniform else 10
    factor = Fraction(product["cap"], source_cap)
    initial = integer_scale(original_config["initial_qty"], factor)
    addition = initial if adding else 0
    config = {"initial_qty": initial, "add_qty": addition, "position_cap": product["cap"],
              "quantity_factor": float(factor),
              "money_factor": float(factor) * product["multiplier"] / product["original_multiplier"],
              "trail_atr": original_config["main_trail"], "risk_atr": 1,
              "entry_atr": 0.25, "add_step_atr": 0.5 if adding else None}
    week = scale_row(weeks[(method_id, symbol)], factor, symbol)
    sessions, risks = [], []
    for session in SESSIONS:
        row = scale_row(rows[(method_id, symbol, session)], factor, symbol)
        risks.extend(check_trades(blocks[(method_id, session, symbol)], row, factor, symbol).tolist())
        sessions.append(row)
    for field in ["gross_profit_yen", "gross_loss_yen", "net_yen", "profit_units", "loss_units", "zero_units", "unit_balance", "closed_units"]:
        assert abs(sum(r[field] for r in sessions) - week[field]) < 0.00001
    for field in ["max_long", "max_short", "max_gross", "max_net"]:
        assert max(r[field] for r in sessions) == week[field]
    quantity_rule = (f"{initial}枚で開始。方向判定が続き、有利に0.5ATR進むごとに{addition}枚追加し、最大{product['cap']}枚。" if adding
                     else f"{initial}枚で開始して固定。追加しない。")
    CHECKS["週集計数"] += 1
    return {"config": config, "quantity_rule": quantity_rule, "week": week, "sessions": sessions,
            "risk": {"min_yen": min(risks), "median_yen": float(np.median(risks)), "max_yen": max(risks)}}


def main():
    """入力を固定し、４手法の小口版集計と検算記録を保存する。

    引数: なし。返り値: なし (None)。売買シミュレーターや取得APIは実行しない。
    """
    configs = {r["id"]: r for r in read("全条件一覧.json")}
    weeks = {(r["method_id"], r["symbol"]): r for r in read("週合計.json")}
    rows = {(r["method_id"], r["symbol"], r["session"]): r for r in read("セッション集計.json")}
    with (SOURCE / "全返済と組.pkl").open("rb") as stream:
        blocks = pickle.load(stream)
    methods = []
    for rank, method_id in enumerate(IDS, 1):
        original = configs[method_id]
        assert original["hedge_ratio"] == original["reverse_mode"] == original["split_target"] == 0
        entry = ("NK225とTOPIXの持続方向の一致を２回確認し、その逆方向を狙う。取引方向に0.25ATR進む逆指値で開始。" if original["signal"] == "M3"
                 else "板の過去５分の注文フローと値動きが同じ方向に偏った状態を２回確認し、その逆方向に0.25ATR進む逆指値で開始。")
        trail = original["main_trail"]
        exit_text = f"初期枚数×１ATRを組全体の損失予算にする。１ATR順行後は高値・安値から{trail:g}ATR戻れば全返済。180分または場内返済時刻でも全返済。"
        variants = {}
        for symbol in PRODUCTS:
            item = variant(method_id, symbol, original, weeks, rows, blocks)
            item["uniform"] = variant(method_id, symbol, original, weeks, rows, blocks, uniform=True)
            variants[symbol] = item
        methods.append({"id": method_id, "rank": rank, "name": NAMES[method_id], "signal": original["signal"],
                        "entry": entry, "exit": exit_text, "variants": variants})

    # ----------------------------------------
    # 新しい約定検証と誤認しないよう、固定した前提と原集計のハッシュを保存する。
    files = ["全条件一覧.json", "週合計.json", "セッション集計.json", "全返済と組.pkl", "engine.py", "signals.py", "主方向状態.pkl"]
    hashes = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in files}
    data = {
        "metadata": {
            "period": "2026年９月21日日中〜９月25日夜間（26日朝）、10セッション",
            "date": "2026-09-27", "method_count": 4,
            "primary_policy": "各手法で実際に使う最大枚数をTOPIXミニ10枚・NK225マイクロ20枚へ合わせる。増玉型は10段、固定型は初回から上限枚数。",
            "uniform_policy": "補足は元の共通上限100枚を一律10枚・20枚へ縮小。固定型はTOPIXミニ１枚・NK225マイクロ２枚となり、主案の金額・枚数の10分の１。増玉型は主案と同じ。",
            "risk_difference": "主案の固定型は増玉型の10倍の初期枚数・初期損失予算。週収支だけで方式の優劣を決めない。枚数上限は同じでも初期リスクは同じではない。",
            "calculation": "元の建値・返済値・時刻・信号・ATR・価格丸めを維持し、全返済の整数枚数と契約倍率を換算。対象４手法では数量比例により価格条件を維持できる。",
            "data_scope": "元ラージ商品の保存済み板・値動きによる既知１週間の換算。実ミニ・マイクロ板での検証や未使用期間の追加検証ではない。",
            "observation": "信号とATRの観測元は従来のラージ板・足のまま。M3は売買対象が一方だけでもNK225・TOPIX両方を観測する。小口商品も元の同価格で約定すると仮定。",
            "cost": "費用０・指定価格約定の前提を維持。セッション末は全返済。４手法は別々に運用した場合を示し、４つ同時の合計上限ではない。",
            "session_exit": "日中15:35・夜間翌5:50以降の観測で返済を指示し、次の有効な原本行で全返済。新規受付は開始20分後から15:05/翌5:20まで。",
            "atr": "確定５分足のTRを係数1/12で平滑化。最低３本・元商品の２呼値以上。初回注文時のATRを組内で固定。",
            "tick": "元の価格刻みは維持。元の約定価格が小口商品の呼値に一致することは検算し、細かい呼値へ再最適化していない。",
            "units": "利益枚数・損失枚数は１週間・各セッションの返済累計。枚数差は両者の差で、保有上限や場末の建玉残ではない。",
            "budget": "初期損失予算は損切り水準を決める基準であり、実現損失の絶対上限や必要証拠金ではない。",
            "hashes": hashes,
        }, "products": PRODUCTS, "methods": methods,
    }
    (WORK / "scale_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (WORK / "集計検算.json").write_text(json.dumps({"合格": True, **CHECKS}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for method in methods:
        print(method["id"], {symbol: item["week"]["net_yen"] for symbol, item in method["variants"].items()})


if __name__ == "__main__":
    main()
