"""他因子をそろえた２２比較を、セッション単位の対応差として独立に集計する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from audit_statistics import exact_signflip, holm_adjust

OUT = Path(__file__).resolve().parent
FULL_SESSIONS = ["2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day",
                 "2026-09-22_Night", "2026-09-23_Day"]
SYMBOLS = ["NK225", "TOPIX"]
FACTORS = ["信号", "入口", "出口", "時間帯"]


def contrasts() -> list[dict]:
    """機能: 収支を読む前に指定した出口１１・時間帯４・入口７比較を列挙する。

    引数: なし。
    返り値: list[dict]。識別子・変更因子・基準値・変更値・対象セッション。
    """
    rows = []
    for factor, baseline, variants in [
        ("出口", "X00", [f"X{index:02d}" for index in range(1, 12)]),
        ("時間帯", "Z00", [f"Z{index:02d}" for index in range(1, 5)]),
        ("入口", "E02", ["E00", "E01", "E03", "E04", "E05", "E06", "E07"]),
    ]:
        for variant in variants:
            sessions = [value for value in FULL_SESSIONS if value.endswith("Night")] if factor == "時間帯" else FULL_SESSIONS
            rows.append(dict(比較=f"{factor}_{variant}_対_{baseline}", 因子=factor, 基準=baseline,
                             変更=variant, 対象セッション=sessions))
    return rows


def calculate(cells: pd.DataFrame) -> tuple[list[dict], pd.DataFrame]:
    """機能: 同条件の対応差を各銘柄内で中央値化し、同一セッションの両銘柄を束ねる。

    引数: cells (DataFrame) は通常再生の全条件セッション集計。
    返り値: tuple[list[dict], DataFrame]。全２２診断とセッション銘柄別の要約。
    """
    data = cells[cells["セッション"].isin(FULL_SESSIONS)].copy()
    if "約定遅延" in data.columns:
        data = data[data["約定遅延"].eq("次行")].copy()
    parsed = data["方式"].str.rsplit("_", n=3, expand=True)
    if parsed.shape[1] != 4:
        raise ValueError("方式は信号・入口・出口・時間帯の４要素である必要があります。")
    for column, factor in enumerate(FACTORS):
        data[factor] = parsed[column]
    keys = ["方式", "セッション", "銘柄"]
    if data.duplicated(keys).any():
        raise ValueError("条件・セッション・銘柄が重複しています。")
    expected = 20 * 8 * 12 * 5 * len(FULL_SESSIONS) * len(SYMBOLS)
    if len(data) != expected:
        raise ValueError(f"主５セッションの全条件が必要です。想定 {expected} 行、実際 {len(data)} 行。")
    if data["費用倍ATR収支"].isna().any():
        raise ValueError("費用倍 ATR 収支に欠測値があります。")
    diagnostics, session_rows = [], []
    for contrast in contrasts():
        factor = contrast["因子"]
        merge_keys = [value for value in FACTORS if value != factor] + ["セッション", "銘柄"]
        selected = data[data["セッション"].isin(contrast["対象セッション"])]
        baseline = selected[selected[factor].eq(contrast["基準"])][merge_keys + ["費用倍ATR収支", "取引数"]]
        variant = selected[selected[factor].eq(contrast["変更"])][merge_keys + ["費用倍ATR収支", "取引数"]]
        paired = variant.merge(baseline, on=merge_keys, how="outer", suffixes=("_変更", "_基準"),
                               indicator=True, validate="one_to_one")
        assert paired["_merge"].eq("both").all(), contrast
        paired["差"] = paired["費用倍ATR収支_変更"] - paired["費用倍ATR収支_基準"]
        paired["片方以上取引あり"] = paired["取引数_変更"].gt(0) | paired["取引数_基準"].gt(0)
        grouped = paired.groupby(["セッション", "銘柄"], sort=False)["差"]
        statistics = grouped.agg(["size", "median", "mean", "min", "max"])
        statistics["改善割合"] = grouped.apply(lambda values: float((values > 0).mean()))
        statistics["悪化割合"] = grouped.apply(lambda values: float((values < 0).mean()))
        statistics["不変割合"] = grouped.apply(lambda values: float((values == 0).mean()))
        by_symbol = {}
        for session in contrast["対象セッション"]:
            for symbol in SYMBOLS:
                item = statistics.loc[(session, symbol)]
                active = paired[paired["セッション"].eq(session) & paired["銘柄"].eq(symbol) & paired["片方以上取引あり"]]
                row = dict(比較=contrast["比較"], 因子=factor, 基準=contrast["基準"], 変更=contrast["変更"],
                           セッション=session, 銘柄=symbol, 対応組合せ数=int(item["size"]),
                           費用倍ATR差中央値=float(item["median"]), 費用倍ATR差平均=float(item["mean"]),
                           最小差=float(item["min"]), 最大差=float(item["max"]),
                           改善割合=float(item["改善割合"]), 悪化割合=float(item["悪化割合"]), 不変割合=float(item["不変割合"]),
                           片方以上取引あり組合せ数=len(active),
                           片方以上取引あり改善割合=float(active["差"].gt(0).mean()) if len(active) else None)
                session_rows.append(row)
                by_symbol[(session, symbol)] = row
        differences = [sum(by_symbol[(session, symbol)]["費用倍ATR差中央値"] for symbol in SYMBOLS) / 2
                       for session in contrast["対象セッション"]]
        result = exact_signflip(differences, "two-sided")
        active = paired[paired["片方以上取引あり"]]
        diagnostics.append(dict(**contrast, **result,
                                対応組合せ総数=len(paired),
                                全対応組合せの改善割合=float((paired["差"] > 0).mean()),
                                全対応組合せの不変割合=float((paired["差"] == 0).mean()),
                                片方以上取引あり組合せ総数=len(active),
                                片方以上取引あり改善割合=float(active["差"].gt(0).mean()) if len(active) else None,
                                集約手順="各セッション・各銘柄で全他因子の差の中央値を取り、同セッションの両銘柄中央値を平均"))

    # ----------------------------------------
    # 良かった比較だけを残さず、事前に定義した全２２比較へ一括補正する。
    adjusted = holm_adjust({row["比較"]: row["未補正比率"] for row in diagnostics})
    for row in diagnostics:
        row["全22比較Holm補正比率"] = adjusted[row["比較"]]
    return diagnostics, pd.DataFrame(session_rows)


def main() -> None:
    """機能: 保存集計から対応差と少数標本の統計診断を作り、解釈の限界を添える。

    引数: なし。
    返り値: None。対応差分の JSON・CSV を同じフォルダに保存する。
    """
    path = OUT / "全条件セッション集計.csv"
    diagnostics, sessions = calculate(pd.read_csv(path))
    output = {
        "入力SHA256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "比較数": len(diagnostics),
        "費用設定": "実際の売買気配差に加え往復４呼値を控除",
        "解釈": "全て既知の探索データ。出口は複数設定を含むパッケージ差であり、単独の短縮条件だけの因果効果ではない。",
        "少数標本の限界": "最大５セッション・完全夜間２本。同日の日中と夜間の独立性も保証されず、候補設計に過去探索が反映されている。確認的な市場法則の証明ではない。",
        "診断": diagnostics,
    }
    (OUT / "対応差分診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    sessions.to_csv(OUT / "対応差分_セッション.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(diagnostics).to_csv(OUT / "対応差分_検定.csv", index=False, encoding="utf-8-sig")
    print(f"事前定義した {len(diagnostics)} 比較・{len(sessions)} セッション銘柄差を集計しました。", flush=True)


if __name__ == "__main__":
    main()
