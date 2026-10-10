"""保存済みの同一週集計から、銘柄別と両銘柄共通の順位を作成する。"""

import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK))
from report import describe

SYMBOLS = ("NK225", "TOPIX")


def read(path):
    """保存済みの集計を読み込む。

    引数: path (Path) は対象ファイル。返り値: JSON の内容 (dict | list)。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def make_rankings():
    """週収支順位と、両銘柄の弱い側を重視する損小利大順位を作成する。

    引数: なし。返り値: 原集計・規則・順位を含む表示用データ (dict)。
    """
    names = ["週合計.json", "セッション集計.json", "全条件一覧.json"]
    hashes = {name: hashlib.sha256((WORK / name).read_bytes()).hexdigest() for name in names}
    weeks = read(WORK / names[0])
    sessions = read(WORK / names[1])
    configs = {row["id"]: row for row in read(WORK / names[2])}
    by_week = {(row["method_id"], row["symbol"]): row for row in weeks}
    atr = {(row["method_id"], row["symbol"]): row for row in read(HERE / "audit_atr_normalized.json")["週"]}
    assert len(weeks) == 360 and len(sessions) == 3600 and len(configs) == 180

    # ----------------------------------------
    # 銘柄別の円額順位は、同じ銘柄の中だけで比較する。
    individual_all = {}
    individual = {}
    for symbol in SYMBOLS:
        ordered = sorted((row for row in weeks if row["symbol"] == symbol),
                         key=lambda row: (-row["net_yen"], row["method_id"]))
        individual_all[symbol] = [{"rank": i, "id": row["method_id"]} for i, row in enumerate(ordered, 1)]
        individual[symbol] = individual_all[symbol][:5]

    # ----------------------------------------
    # 共通候補は、両銘柄とも損益分岐点を超えることを必須にする。
    common_all = []
    for method_id in configs:
        rows = [by_week[(method_id, symbol)] for symbol in SYMBOLS]
        if not all(row["net_yen"] > 0 and row["money_ratio"] > 1 and row["unit_payoff"] > 1 for row in rows):
            continue
        remaining = []
        for symbol, row in zip(SYMBOLS, rows):
            group = [r for r in sessions if r["method_id"] == method_id and r["symbol"] == symbol]
            remaining.append(row["net_yen"] - max(r["net_yen"] for r in group))
        common_all.append({
            "id": method_id,
            "score": min(min(row["money_ratio"], row["unit_payoff"]) for row in rows),
            "min_positive": min(row["positive_sessions"] for row in rows),
            "min_recovery": min(row["net_yen"] / row["drawdown_yen"] for row in rows),
            "stable": all(row["positive_sessions"] >= 6 for row in rows) and min(remaining) > 0,
        })
    common_all.sort(key=lambda row: (-row["score"], -row["min_positive"], -row["min_recovery"], row["id"]))
    for rank, row in enumerate(common_all, 1):
        row["rank"] = rank
    common = common_all[:5]
    assert len(common_all) == 12

    # ----------------------------------------
    # 上位に出た同じ条件を、両銘柄について省略せず収録する。
    selected = sorted({row["id"] for rows in individual.values() for row in rows} | {row["id"] for row in common})
    methods = {}
    for method_id in selected:
        config = configs[method_id]
        stocks = {}
        for symbol in SYMBOLS:
            week = by_week[(method_id, symbol)]
            group = sorted((row for row in sessions if row["method_id"] == method_id and row["symbol"] == symbol), key=lambda row: row["session"])
            profits = sorted((row["net_yen"] for row in group), reverse=True)
            assert len(group) == 10
            stocks[symbol] = {
                "week": week, "sessions": group,
                "best_session_removed_net": week["net_yen"] - profits[0],
                "best_two_removed_net": week["net_yen"] - sum(profits[:2]),
                "atr": atr[(method_id, symbol)],
            }
        methods[method_id] = {"id": method_id, "name": config["name"],
                              "description": " ".join(describe(config)), "config": config, "stocks": stocks}

    return {
        "metadata": {
            "title": "週収支ランキングと両銘柄共通手法",
            "period": "2026年９月21日日中〜９月25日夜間（26日朝）、全10セッション",
            "conditions": 180, "basic_qualified": len(common_all),
            "stable_qualified": sum(row["stable"] for row in common_all),
            "individual_rule": "同銘柄の週収支の降順。同額の場合はIDの昇順。",
            "common_eligibility": "両銘柄とも週収支が正、利益合計÷損失合計が１超、１枚平均利益÷１枚平均損失が１超。",
            "common_rule": "両銘柄の金額損益比・１枚平均損益比、計４値の最小値が大きい順。同点は少ない側の黒字セッション数、低い側の週収支÷最大下落、IDの昇順。",
            "stable_rule": "順位とは別の補助判定。両銘柄とも６区間以上が黒字、かつ最大利益の１セッションを除いても週収支が正。将来の安定性を保証する判定ではない。",
            "money_ratio": "利益合計÷損失合計（損失は絶対値）。",
            "unit_payoff": "（利益合計÷利益枚数）÷（損失合計÷損失枚数）。枚数の勝率とは別。",
            "unit_balance": "利益で返済した枚数−損失で返済した枚数。残っている建玉数ではなく、週内の返済枚数の差。",
            "normalization": "同一IDの設定を両銘柄に適用。幅は各銘柄の確定足から計算したATRで調整。円額は合算せず、倍率に依存しない損益比で共通順位を決める。",
            "atr_auxiliary": "補助確認として各返済の損益を同じ組の初回ATRで割る。順位には使わず、値動きの大きな区間への依存を示す。",
            "scope": "既読の同一週180条件の比較であり、未使用データによる検証ではない。新しいパラメータ探索、現在セッション取得、売買再計算は行っていない。",
            "execution": "費用０・指定価格約定の既存モデル。各セッション内に全玉返済。買い100枚・売り100枚をそれぞれ上限とする。",
            "scale": "初期金額は元のラージ倍率。0.1倍・0.01倍は円額だけの換算で、実mini・microの板・約定検証ではない。",
            "source_hashes": hashes,
        },
        "individual": individual, "individual_all": individual_all,
        "common": common, "common_all": common_all, "methods": methods,
    }


def main():
    """表示データを書き出し、件数を日本語で表示する。

    引数: なし。返り値: なし (None)。
    """
    result = make_rankings()
    (HERE / "ranking_data.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"作成完了：銘柄別各５件、共通５件、比較対象{len(result['methods'])}条件。基本資格{result['metadata']['basic_qualified']}件。")


if __name__ == "__main__":
    main()
