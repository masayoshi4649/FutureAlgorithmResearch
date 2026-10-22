"""日中の具体損失に対する反例と、固定尺度の時間変化を保存資料から整理する。"""

import hashlib
import json
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    """
    機能: 赤字上位場の入口条件に合う勝ち親も併記し、固定ATRと当時公開ATRを比較する。
    引数: なし。
    返り値: None。条件付き損益は既存親の分類であり、新手法の損益ではない。
    """
    diagnostic_path = HERE / "日中赤字上位三場の保存約定診断.json"
    prepared_path = ROOT / "work/stability126_20261019/input_audit/attempt2/全四十一場の元入力と新市場特徴の非金融準備.json"
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    conditional = []
    for symbol in ("TOPIX", "NK225"):
        groups = [g for account in diagnostic["records"] if account["account"]["symbol"] == symbol
                  for g in account["groups"]]
        for name in ("両市場120秒が0.1ATR超反対", "自己の保存trendが反対"):
            selected = []
            for group in groups:
                direction = 1 if group["direction"] == "買い" else -1
                market = group["source_market"]
                match = (market[11] == 1 and all(market[k] is not None and direction * market[k] < -.1 for k in (5, 7))
                         if name == "両市場120秒が0.1ATR超反対"
                         else group["source_trend_side"] == -direction)
                if match:
                    selected.append(dict(time=group["entry_time"], direction=group["direction"], net=group["net"]))
            conditional.append(dict(symbol=symbol, condition=name, selected=selected,
                                    count=len(selected), wins=sum(g["net"] > 0 for g in selected),
                                    losses=sum(g["net"] < 0 for g in selected),
                                    saved_group_net=sum(g["net"] for g in selected)))
    # ----------------------------------------
    # 具体例の固定尺度と、各時点で公開されていた尺度の推移だけを取り出す。
    reference = next(p for p in prepared["packets"] if p["session"] == "2026-10-16_Day")
    payload = (ROOT / reference["path"]).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == reference["sha256"]
    packet = pickle.loads(payload)
    scales = []
    for account in diagnostic["records"]:
        if account["account"]["session"] != "2026-10-16_Day":
            continue
        symbol = account["account"]["symbol"]
        ready = packet["inputs"]["2026-10-16_Day", symbol]
        for group in sorted(account["groups"], key=lambda value: value["entry_time"]):
            scales.append(dict(
                symbol=symbol, entry_time=group["entry_time"], fixed_atr=group["fixed_atr"],
                public_atr_at_entry=float(ready["atr"][group["entry_row"]]),
                observed_peak_time=group["peak_time"], public_atr_at_peak=float(ready["atr"][group["peak_row"]]),
                final_time=group["final_time"], public_atr_at_exit=float(ready["atr"][group["exits"][-1]["row"]]),
                peak_yen=group["maximum_observed_liquidation_pnl"], net=group["net"],
            ))
    output = dict(
        passed=True, conditional_classifications=conditional, scale_examples=scales,
        sources=[dict(path=p.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in (diagnostic_path, prepared_path, Path(__file__))] + [reference],
        financial_replays=0, original_market_reads=0, API=0,
        caution="赤字上位三場を選んだ後の条件分類。選別された親を除外した数値は、新手法の成績ではない。",
    )
    target = HERE / "入口拒否の反例と日中尺度の縮小.json"
    assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, classifications=len(conditional), scale_examples=len(scales)), ensure_ascii=False))


if __name__ == "__main__":
    main()
