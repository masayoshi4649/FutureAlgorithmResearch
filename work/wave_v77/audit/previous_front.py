"""過去に全明細監査済みの前16場だけを、金額8:2の分母で再集計する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from independent_account import near, save


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "work/wave_v76"
SYMBOLS = ("TOPIX", "NK225")


def summarize(rows: list[dict], symbol: str) -> dict:
    """機能: 保存場別明細会計を商品別に合算し、金額比率と一場依存を算出する。

    引数: rows(list[dict])、symbol(str)。返り値: 商品会計(dict)。
    利益・損失は手数料後の建値別明細。追加組を別勝利に数える新評価とは分離する。
    """
    own = [r for r in rows if r["symbol"] == symbol]
    profit = sum(r["profit"] for r in own)
    loss = sum(r["loss"] for r in own)
    net = sum(r["net"] for r in own)
    near(profit - loss, net, "商品利益損失の差")
    fees = sum(r["fees"] for r in own)
    near(sum(r["gross"] for r in own) - fees, net, "商品料金")
    trades = sum(r["trades"] for r in own)
    best = max(own, key=lambda r: r["net"])
    p2, l2 = profit - best["profit"], loss - best["loss"]
    near(p2 - l2, net - best["net"], "最大黒字場除外")
    return dict(profit=profit, loss=loss, net=net, fees=fees, trades=trades,
        active_sessions=sum(r["trades"] > 0 for r in own),
        winning_lots=sum(r["winning_lots"] for r in own),
        losing_lots=sum(r["losing_lots"] for r in own),
        money_profit_share=profit / (profit + loss) if profit + loss else None,
        profit_loss_ratio=profit / loss if loss else None,
        zero_loss_positive=loss == 0 and profit > 0,
        win_rate=sum(r["wins"] for r in own) / trades if trades else None,
        best_session=best["session"], without_best_session=net - best["net"],
        without_best_profit=p2, without_best_loss=l2,
        without_best_money_profit_share=p2 / (p2 + l2) if p2 + l2 else None,
        without_best_profit_loss_ratio=p2 / l2 if l2 else None)


def main() -> None:
    """機能: 既往996条件の前16場を再集計し、8:2到達と最低件数を別に記録する。

    引数: なし。返り値: なし(None)。後13場の成績は評価・出力に使わない。
    """
    fixed_path = OLD / "事前固定.json"
    fixed = json.loads(fixed_path.read_text(encoding="utf-8"))
    front = set(fixed["前16"])
    records = []
    digests = {}
    for config in fixed["条件"]:
        path = OLD / "results" / f"{config['id']}.json"
        packet = json.loads(path.read_text(encoding="utf-8"))
        rows = [r for r in packet["rows"] if r["session"] in front]
        assert len(rows) == 32
        products = {s: summarize(rows, s) for s in SYMBOLS}
        for symbol, m in products.items():
            saved = packet["periods"]["前16"][symbol]
            for field in ("profit", "loss", "net", "fees", "trades", "active_sessions", "winning_lots", "losing_lots", "win_rate", "without_best_session"):
                assert m[field] == saved[field], (config["id"], symbol, field)
            if m["money_profit_share"] is not None:
                near(1 - m["money_profit_share"], saved["money_loss_share"], "金額損失割合")
            if m["profit_loss_ratio"] is not None:
                near(m["profit_loss_ratio"], saved["profit_loss_ratio"], "PF")
        records.append(dict(id=config["id"], products=products,
            eligible=all(products[s]["trades"] >= 20 and products[s]["active_sessions"] >= 8 for s in SYMBOLS),
            both_target=all(products[s]["money_profit_share"] is not None and products[s]["money_profit_share"] >= .8 for s in SYMBOLS)))
        digests[config["id"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    # ----------------------------------------
    # 前半だけで商品ごとの参考首位と共通首位を比較し、後半を再選択に使わない。
    eligible = [r for r in records if r["eligible"]]
    both_key = lambda r: (-min(r["products"][s]["money_profit_share"] for s in SYMBOLS), r["id"])
    best = sorted(eligible, key=both_key)[:5]
    single = {}
    for symbol in SYMBOLS:
        pool = [r for r in records if r["products"][symbol]["trades"] >= 20 and r["products"][symbol]["active_sessions"] >= 8]
        single[symbol] = sorted(pool, key=lambda r: (-r["products"][symbol]["money_profit_share"], r["id"]))[:3]
    selected = json.loads((OLD / "前半選定.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in selected["代表"]}
    save(HERE / "既往前16金額比率基準の再集計.json", dict(合格=True,
        条件数=len(records), 前半場数=16, 場別商品会計数=len(records) * 32,
        共通最低件数充足数=len(eligible), 共通8対2参考到達数=sum(r["both_target"] for r in records),
        共通8対2最低件数充足到達数=sum(r["both_target"] for r in eligible),
        共通前半上位=best, 商品別前半参考上位=single,
        既往六代表=[r for r in records if r["id"] in ids],
        元固定SHA256=hashlib.sha256(fixed_path.read_bytes()).hexdigest(), 元結果SHA256=digests,
        主指標="手数料後の全決済明細利益/(利益+損失)",
        参照範囲="既往全明細監査済み996結果の前16場のみ。今回は元台帳を再計算せず、保存場別会計を独立再合算。後13の会計を選択・出力に使わない。",
        新候補選定ではない=True, 原本取得=0, API取得=0, 実注文=0))
    print(json.dumps(dict(合格=True, 条件数=len(records), 最低件数充足=len(eligible),
        共通8対2参考到達=sum(r["both_target"] for r in records), 共通首位=best[0]), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
