"""今回の12仮説を記述集計し、固定選定を変更せずに確認結果を記載します。"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path


HERE = Path(__file__).resolve().parent
STUDY = HERE.parent.parent / "アルゴリズム調査" / "00170_複数時間足のテクニカルと指標出口"
SYMBOLS = ("NK225", "TOPIX")
KINDS = ("Day", "Night")
LABELS = {"NK225": "日経", "TOPIX": "TOPIX", "Day": "日中", "Night": "夜間"}
FAMILIES = {
    1: "平均付近の押し目回復", 2: "中期平均の先行転換", 3: "レンジのRSI回復",
    4: "トレンド中のRSI再加速", 5: "MACD差分の再加速", 6: "MACDゼロ回復",
    7: "BB収縮からの拡張", 8: "BB上側の継続回復", 9: "BB突破失敗の帯内回帰",
    10: "DMI方向発生", 11: "DMI優位継続中の押し目", 12: "更新とRSI不一致後の反転確認",
}


def cash(value: float) -> str:
    """
    機能: 金額を円の桁区切りで表します。
    引数: value は float 型の金額です。
    返り値: str 型の表示用金額です。
    """
    return f"{value:,.0f}" if abs(value - round(value)) < 0.00001 else f"{value:,.2f}"


def percentage(numerator: int, denominator: int) -> str:
    """
    機能: 対象件数がない比率を未定として表します。
    引数: numerator と denominator は int 型の分子と分母です。
    返り値: str 型の比率、または対象なしの表示です。
    """
    return "対象なし" if denominator == 0 else f"{numerator / denominator:.1%}"


def checked_number(row: dict, field: str) -> float:
    """
    機能: 欠測をゼロへ置き換えずに分析用数値を確認します。
    引数: row は dict 型の結果、field は str 型の項目名です。
    返り値: float 型の有限値です。
    """
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"欠測または不正な数値です。{row.get('method_id')}/{row.get('session')}/{field}")
    return float(value)


def load_groups() -> tuple[dict, dict, dict, dict]:
    """
    機能: 今回の実結果と固定済み選定だけを読み、区分別の会計を準備します。
    引数: なし。
    返り値: tuple 型の元入力、選定、区分別結果、分割情報です。
    """
    source = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
    selection = json.loads((HERE / "rootselection.json").read_text(encoding="utf-8"))
    configs = {item["id"]: item for item in source["configs"]}
    splits = {(item["symbol"], item["session"]): item for item in selection["splits"]}
    audits = {(item["symbol"], item["session"]): item for item in source["audits"]}
    if len(configs) != 72 or len(splits) != len(selection["splits"]) or set(audits) != set(splits):
        raise ValueError("72定義、入力監査、検討・確認の分割が一致しません。")
    groups = {}
    seen = set()
    for row in source["results"]:
        candidate = row["config_id"]
        session_key = row["symbol"], row["session"]
        unique = candidate, *session_key
        if candidate not in configs or session_key not in splits or unique in seen:
            raise ValueError(f"結果の候補・場・重複が不正です。{unique}")
        seen.add(unique)
        if row["method_id"] != f"{row['symbol']}_T170_{candidate}":
            raise ValueError(f"銘柄と実手法IDが一致しません。{unique}")
        split = splits[session_key]
        if not isinstance(row["complete"], bool) or row["complete"] != split["complete"] or row["complete"] != audits[session_key]["complete"]:
            raise ValueError(f"場完了の状態が一致しません。{unique}")
        for field in ("realized_yen", "gross_profit_yen", "gross_loss_yen", "entry_count"):
            checked_number(row, field)
        if abs(row["gross_profit_yen"] - row["gross_loss_yen"] - row["realized_yen"]) > 0.00001:
            raise ValueError(f"利益−損失と収支が一致しません。{unique}")
        if row["session"].endswith("_Day"):
            kind = "Day"
        elif row["session"].endswith("_Night"):
            kind = "Night"
        else:
            raise ValueError(f"昼夜を判定できません。{unique}")
        group_key = candidate, row["symbol"], kind, split["phase"]
        if row["complete"]:
            groups.setdefault(group_key, []).append(row)
    if len(seen) != len(configs) * len(audits):
        raise ValueError("全候補と全場の直積が揃っていません。")
    return source, selection, groups, splits


def metrics(groups: dict, candidate: str, symbol: str, kind: str, phase: str) -> dict:
    """
    機能: 一つの固定候補・銘柄・昼夜・区間の完全場を集計します。
    引数: groups は dict 型、残る4引数は str 型の対象区分です。
    返り値: dict 型の場数、収支、新規回数、無取引場数です。
    """
    rows = groups.get((candidate, symbol, kind, phase), [])
    return {"sessions": len(rows), "net": sum(row["realized_yen"] for row in rows), "entries": sum(row["entry_count"] for row in rows), "no_trade": sum(row["entry_count"] == 0 for row in rows)}


def comparisons(groups: dict, family: int, mode: str, phase: str) -> list[float]:
    """
    機能: 同じ時間足・銘柄・昼夜における出口違いの収支差を作ります。
    引数: groups は dict 型、family は int 型、mode と phase は str 型です。
    返り値: list[float] 型の8区分の比較差です。
    """
    result = []
    left, right = ("F", "I") if mode == "F-I" else (mode, "T")
    for variant in ("A", "B"):
        for symbol in SYMBOLS:
            for kind in KINDS:
                first = metrics(groups, f"F{family:02d}{variant}_{left}", symbol, kind, phase)
                second = metrics(groups, f"F{family:02d}{variant}_{right}", symbol, kind, phase)
                if first["sessions"] != second["sessions"]:
                    raise ValueError("出口比較の場数が一致しません。")
                result.append(first["net"] - second["net"])
    return result


def vote(values: list[float]) -> str:
    """
    機能: 収支差の正・同値・負を数えます。
    引数: values は list[float] 型の収支差です。
    返り値: str 型の正/同/負の件数です。
    """
    return f"{sum(value > 0 for value in values)}/{sum(value == 0 for value in values)}/{sum(value < 0 for value in values)}"


def family_metrics(groups: dict, family: int) -> dict:
    """
    機能: 全I/F候補を選別せず12仮説の再現性と無取引を記述します。
    引数: groups は dict 型、family は int 型の仮説番号です。
    返り値: dict 型の16区分の検討・確認指標です。
    """
    pairs = []
    for variant in ("A", "B"):
        for mode in ("I", "F"):
            candidate = f"F{family:02d}{variant}_{mode}"
            for symbol in SYMBOLS:
                for kind in KINDS:
                    pairs.append(tuple(metrics(groups, candidate, symbol, kind, phase) for phase in ("検討", "確認")))
    train_positive = sum(first["net"] > 0 for first, _ in pairs)
    confirmation_positive = sum(second["net"] > 0 for _, second in pairs)
    retained = sum(first["net"] > 0 and second["net"] > 0 for first, second in pairs)
    no_trade = [sum(pair[index]["no_trade"] for pair in pairs) for index in (0, 1)]
    observations = [sum(pair[index]["sessions"] for pair in pairs) for index in (0, 1)]
    entries = [sum(pair[index]["entries"] for pair in pairs) for index in (0, 1)]
    return {"family": family, "train_positive": train_positive, "confirmation_positive": confirmation_positive, "retained": retained, "no_trade": no_trade, "observations": observations, "entries": entries, "i_train": comparisons(groups, family, "I", "検討"), "i_confirm": comparisons(groups, family, "I", "確認"), "f_train": comparisons(groups, family, "F", "検討"), "f_confirm": comparisons(groups, family, "F", "確認"), "floor_confirm": comparisons(groups, family, "F-I", "確認")}


def report(source: dict, selection: dict, groups: dict, splits: dict) -> str:
    """
    機能: 固定4選定と別枠の事後集計を一つの簡潔な資料にします。
    引数: 4引数はいずれも dict 型の今回の実測入力です。
    返り値: str 型のMarkdownです。
    """
    summary = [family_metrics(groups, family) for family in FAMILIES]
    denominator = sum(item["train_positive"] for item in summary)
    retained = sum(item["retained"] for item in summary)
    no_trade = [sum(item["no_trade"][index] for item in summary) for index in (0, 1)]
    observations = [sum(item["observations"][index] for item in summary) for index in (0, 1)]
    lines = ["# 指標仮説の確認結果", "", f"12仮説のI/F候補について、検討で黒字だった{denominator}区分のうち、確認でも黒字を維持したのは{retained}区分（{percentage(retained, denominator)}）。無取引の場は検討{percentage(no_trade[0], observations[0])}、確認{percentage(no_trade[1], observations[1])}だった。これは仮説・時間足・出口・銘柄・昼夜の重なる区分を数えた記述であり、独立した試行の成功確率ではない。", "", "検討時に固定した4選定を以下に残す。相対順位は低頻度の候補も選ぶため、選定済みというだけで勝者・有望候補とは扱わない。確認成績による候補差し替え、後半で活発だった候補の再選択は行わない。", "", "| 銘柄・昼夜 | 固定候補 | 検討収支 | 新規・無取引/場 | 確認収支 | 新規・無取引/場 | Tの確認収支 | 確認差 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for choice in selection["selected"]:
        candidate, symbol, kind = choice["method_id"], choice["symbol"], choice["kind"]
        training = metrics(groups, candidate, symbol, kind, "検討")
        confirmation = metrics(groups, candidate, symbol, kind, "確認")
        control = metrics(groups, choice["control_id"], symbol, kind, "確認")
        link = f"[{candidate}](損益/{LABELS[symbol]}_{candidate}.md)"
        lines.append(f"| {LABELS[symbol]}・{LABELS[kind]} | {link} | {cash(training['net'])} | {int(training['entries'])}・{training['no_trade']}/{training['sessions']} | {cash(confirmation['net'])} | {int(confirmation['entries'])}・{confirmation['no_trade']}/{confirmation['sessions']} | {cash(control['net'])} | {cash(confirmation['net'] - control['net'])} |")

    selected_confirmation = [metrics(groups, item["method_id"], item["symbol"], item["kind"], "確認") for item in selection["selected"]]
    negative_selected = sum(item["net"] < 0 for item in selected_confirmation)
    positive_selected = [item for item in selected_confirmation if item["net"] > 0]
    lines.extend(["", f"固定{len(selected_confirmation)}枠中{negative_selected}枠が確認赤字。黒字の{len(positive_selected)}枠も新規合計{int(sum(item['entries'] for item in positive_selected))}回にとどまる。低頻度そのものを欠陥とはしないが、少数の成立例や無取引のゼロ収支から反復性を強く主張できない。"])

    # ----------------------------------------
    # 全仮説を同じ尺度で列挙し、順位や後半の勝者を作りません。
    lines.extend(["", "以下は固定4選定とは別の事後探索一覧である。各仮説の16区分はA/B×I/F×2銘柄×昼夜。黒字は完全場の合計収支が正、維持は同じ区分が検討・確認の両方で黒字だった件数。無取引率は各候補を評価した完全場のうち新規0回の割合で、同じ場を複数候補で数える。0円は黒字に含めない。", "", "I−T、F−Tはそれぞれ8区分の正/同/負の件数。中央値は8区分の収支差の中央値（円）。差の金額は各商品10枚の会計であり、同一元本比の比較ではない。無取引同士の同値は指標出口の有効性を示さない。出口で保有経路が変わるため、差には後続の再参加も含まれ、単独の出口約定だけの因果効果ではない。", "", "| 仮説 | 黒字区分 検討→確認（/16） | 黒字の維持 | 無取引率 検討→確認 | I−T 検討→確認（正/同/負） | F−T 検討→確認（正/同/負） | I−T 確認中央値 | F−T 確認中央値 |", "|---|---:|---:|---:|---|---|---:|---:|"])
    for item in summary:
        family = item["family"]
        silence = "→".join(percentage(item["no_trade"][index], item["observations"][index]) for index in (0, 1))
        maintenance = "対象なし" if item["train_positive"] == 0 else f"{item['retained']}/{item['train_positive']}"
        lines.append(f"| H{family:02d} {FAMILIES[family]} | {item['train_positive']}→{item['confirmation_positive']} | {maintenance} | {silence} | {vote(item['i_train'])}→{vote(item['i_confirm'])} | {vote(item['f_train'])}→{vote(item['f_confirm'])} | {cash(statistics.median(item['i_confirm']))} | {cash(statistics.median(item['f_confirm']))} |")
    lines.append("")
    for item in summary:
        family = item["family"]
        if item["train_positive"] == 0:
            verdict = "検討に黒字区分がなく、再現性の出発点が成立していない。"
        elif item["retained"] == 0:
            verdict = f"検討黒字{item['train_positive']}区分はいずれも確認で非黒字となり、黒字の再現は確認できない。"
        else:
            verdict = f"黒字維持は{item['retained']}/{item['train_positive']}区分に限られ、仮説全体の安定性を支持する結果ではない。"
        inactive = item["no_trade"][1] / item["observations"][1]
        if inactive >= 0.8:
            verdict += " 確認の無取引が8割以上で、成立例の不足を負けにくさと混同できない。"
        elif inactive >= 0.5:
            verdict += " 確認の半数以上は無取引だった。"
        lines.append(f"- H{family:02d}：{verdict} F−Iの確認差は正/同/負={vote(item['floor_confirm'])}。")

    incomplete = sum(not item["complete"] for item in splits.values())
    completion_note = "今回は全114場が完全場だった。" if incomplete == 0 else f"未完{incomplete}場を採否・上表の収支と頻度の集計から除外した。"
    lines.extend(["", f"集計対象は今回の{len(source['configs'])}固定候補×{len(source['audits'])}場＝{len(source['results']):,}結果。{completion_note}各候補の全場会計は[全候補と損益](全候補と損益.md)から参照できる。主比較は各商品mini片方向10枚・手数料0円であり、気配差と次原行の執行を含む。", "", "無取引には場内だけの指標準備待ちと条件不成立の両方が含まれる。この集計だけで両者の内訳は推定しない。検討と確認では場数も相場環境も異なるため、単純な総額の大小だけで優劣を決めない。元データは今回の `summary.json` と `rootselection.json` のみ。過去研究の成績は使っていない。", ""])
    return "\n".join(lines)


def main() -> None:
    """
    機能: 今回の実結果から仮説確認資料を1個だけ作成します。
    引数: なし。
    返り値: None。既存の戦略・選定・会計資料は変更しません。
    """
    source, selection, groups, splits = load_groups()
    body = report(source, selection, groups, splits)
    destination = STUDY / "指標仮説の確認結果.md"
    destination.write_text(body, encoding="utf-8", newline="\n")
    if destination.read_text(encoding="utf-8") != body:
        raise ValueError("保存後の本文が一致しません。")
    print(json.dumps({"出力": str(destination), "バイト数": destination.stat().st_size, "全仮説数": len(FAMILIES), "固定選定数": len(selection["selected"]), "選定変更": "なし"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
