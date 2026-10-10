"""出口を見た後の二次感度として、再新規の待機と方向再確認を比較する。"""

from __future__ import annotations

from dataclasses import asdict, replace

from shared import OUT, SESSIONS, SYMBOLS, MULTIPLIERS, load_inputs, save_json
from search_exits import evaluate
from exit_engine import ExitRule


def summarize(cells: list[dict], trades: list[dict], symbol: str) -> dict:
    """機能: 銘柄別合計と、各セルの初回・再新規の収支を分けて計算する。

    引数: cells/trades (list[dict])、symbol (str)。返り値: 銘柄集計 (dict)。
    初回と再新規はセッション内の発生順で区分し、将来価格を条件にしない。
    """
    fields = ("count", "profit_yen", "loss_yen", "net_yen", "stress_yen", "giveback_yen")
    result = {field: sum(cell[field] for cell in cells if cell["symbol"] == symbol) for field in fields}
    first, again = [], []
    for session in SESSIONS:
        subset = sorted((trade for trade in trades if trade["session"] == session and trade["symbol"] == symbol),
                        key=lambda trade: trade["entry_time"])
        first.extend(subset[:1])
        again.extend(subset[1:])
    multiplier = MULTIPLIERS[symbol]
    for name, subset in (("first", first), ("reentry", again)):
        result[f"{name}_count"] = len(subset)
        result[f"{name}_net_yen"] = sum(t["net_points"] for t in subset) * multiplier
        result[f"{name}_profit_yen"] = sum(max(0, t["net_points"]) for t in subset) * multiplier
        result[f"{name}_loss_yen"] = sum(max(0, -t["net_points"]) for t in subset) * multiplier
    assert abs(result["profit_yen"] - result["loss_yen"] - result["net_yen"]) < 1e-8
    assert abs(result["first_net_yen"] + result["reentry_net_yen"] - result["net_yen"]) < 1e-8
    return result


def main() -> None:
    """機能: 事後に指定した二出口と四つの再新規条件を再生し、資料を保存する。

    引数: なし。返り値: なし (None)。主探索の192条件や選定を変更しない。
    """
    data, schedules, cfg, primary = load_inputs()
    variants = [("元の45分待機", cfg),
                ("45分待機＋反対方向再確認", replace(cfg, rearm="opposite")),
                ("90分待機", replace(cfg, cooldown=90)),
                ("120分待機", replace(cfg, cooldown=120))]
    rules = [("利益2.5ATRから追跡0.5ATR", ExitRule("stepped", trigger=2.5, width=.5)),
             ("利益2.5ATRから最大利益の80％保護", ExitRule("profit_lock", trigger=2.5, retain=.8))]
    payload = dict(位置づけ="192条件の出口比較を見た後の二次感度。事後探索であり、主選定の置換や未使用期間検証ではない。",
                   固定条件="CUSUM方向、1ATR追跡新規、開始45分待機、初期損切り2.5ATR、費用往復2tick・追加感度4tick。",
                   変更条件="各出口について再新規cooldown45/90/120またはcooldown45＋rearm oppositeを一つずつ比較。",
                   再確認仕様="返済した方向を一旦禁止し、返済後に新たに利用可能となった反対方向の信号を観測すると解除。45分待機も維持。",
                   現在API取得=False, 結果=[])
    lines = ["# 再エントリーの二次感度", "", payload["位置づけ"], "",
             "入口のCUSUM・1ATR反発反落待ちは共通。出口比較の参考候補二つだけを固定し、再新規待機だけを45分から90分・120分へ変更した。別の対照として45分待機に反対方向の再確認を追加した。同時に複数の条件を変更していない。", "",
             "反対方向再確認は、返済した方向への新規を禁止し、返済後に新たに利用可能となった反対方向の信号を一度観測すると解除する。45分待機も残す。", "",
             "金額は万円、ラージ1枚、各取引の往復費用2tick控除。利益・損失は費用控除後に分類した合計。費用倍は往復4tick。全取引セッション内返済。", ""]
    for title, rule in rules:
        rows, base_by_symbol = [], None
        for name, current in variants:
            trades, cells = evaluate(data, schedules, current, rule, primary, False)
            total = {symbol: summarize(cells, trades, symbol) for symbol in SYMBOLS}
            if base_by_symbol is None:
                base_by_symbol = total
            for symbol in SYMBOLS:
                total[symbol]["difference_from_45_yen"] = total[symbol]["net_yen"] - base_by_symbol[symbol]["net_yen"]
                total[symbol]["count_difference_from_45"] = total[symbol]["count"] - base_by_symbol[symbol]["count"]
            item = dict(名称=name, 設定=asdict(current), 出口=asdict(rule), 集計=total, セッション別=cells, 取引=trades)
            rows.append(item)
        payload["結果"].append(dict(出口名=title, 比較=rows))
        lines.extend([f"## {title}", "", "|再新規条件|銘柄|件数|利益|損失|収支|元45分との差|費用倍収支|初回収支|再新規収支|再新規件数|",
                      "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
        for item in rows:
            for symbol in SYMBOLS:
                total = item["集計"][symbol]
                vals = [total[field] / 10000 for field in ("profit_yen", "loss_yen", "net_yen", "difference_from_45_yen", "stress_yen", "first_net_yen", "reentry_net_yen")]
                lines.append(f"|{item['名称']}|{symbol}|{total['count']}|" + "|".join(f"{v:g}" for v in vals) + f"|{total['reentry_count']}|")
        for item in rows:
            lines.extend(["", f"### {item['名称']}：各セッション", "",
                          "|セッション|銘柄|件数|利益|損失|収支|元45分との差|", "|---|---|---:|---:|---:|---:|---:|"])
            reference = {(cell["session"], cell["symbol"]): cell for cell in rows[0]["セッション別"]}
            for cell in item["セッション別"]:
                delta = cell["net_yen"] - reference[cell["session"], cell["symbol"]]["net_yen"]
                vals = [cell[field] / 10000 for field in ("profit_yen", "loss_yen", "net_yen")] + [delta / 10000]
                lines.append(f"|{cell['session']}|{cell['symbol']}|{cell['count']}|" + "|".join(f"{v:g}" for v in vals) + "|")
        lines.append("")
    lines.extend(["## この感度から分かること", "",
                  "45分待機では、段階追跡の再新規による利益91万円・損失40万円・収支51万円（NK225）、利益26万円・損失15.5万円・収支10.5万円（TOPIX）だった。確定損失は全て再新規側にあるが、再新規の合計収支はプラスである。", "",
                  "利益80％保護でも、再新規の合計はNK225が40万円、TOPIXが10万円のプラス。単に取引を減らせば改善する、という結果ではない。", "",
                  "段階追跡を90分待機にするとTOPIXは70万円から93万円へ増え、損失合計も15.5万円から0へ減った。一方NK225は159万円から96万円へ減り、損失合計が40万円から50万円へ増えた。同じ待機変更でも銘柄間で逆の結果だった。", "",
                  "45分待機に反対方向再確認を追加しても、今回の両出口の全取引は変わらなかった。新規できる時刻までに、反対方向の確認が済んでいたためである。", "",
                  "以上は二つの出口を選んだ後の二次感度で、銘柄ごとに有利な待機時間を採用する根拠としては扱わない。", "",
                  "## 読み方", "",
                  "同じ出口の待機条件違いを比較している。待機時間を変えると次の新規時刻や新規方向、さらにその後の取引も変わるため、差額全体を単に『削除した損失取引』と解釈しない。初回取引は各条件で一致する。", "",
                  "初回と再新規の区分は各セッションの発生順であり、初回だけを選んで発注する手法を選定したものではない。二次感度で改善した条件があっても主比較の選定条件は変更しない。", ""])
    for group in payload["結果"]:
        first = group["比較"][0]
        opposite = group["比較"][1]
        assert len(first["取引"]) == len(opposite["取引"])
        assert all(all(a[key] == b[key] for key in a if key != "config")
                   for a, b in zip(first["取引"], opposite["取引"]))
        for item in group["比較"][1:]:
            for symbol in SYMBOLS:
                assert item["集計"][symbol]["first_net_yen"] == first["集計"][symbol]["first_net_yen"]
    save_json(OUT / "再エントリー感度.json", payload)
    (OUT / "再エントリー感度.md").write_text("\n".join(lines), encoding="utf-8")
    for group in payload["結果"]:
        for item in group["比較"]:
            print(group["出口名"], item["名称"], {symbol: {field: item["集計"][symbol][field] for field in ("count", "net_yen", "first_net_yen", "reentry_net_yen")} for symbol in SYMBOLS})


if __name__ == "__main__":
    main()
