"""全独立台帳監査を集約し、期間集計と凍結指紋を照合する。"""

from __future__ import annotations

from audit_all import read, digest, ROOT, WORK, HERE
from independent_account import near, save


def aggregate(rows: list[dict], sessions: list[str], symbol: str, ready: dict) -> dict:
    """機能: 別会計の場指標だけから期間損益と全行 DD を再集計する。

    引数: rows(list[dict])、sessions(list[str])、symbol(str)、ready(dict)。
    返り値: 同商品期間指標(dict)。
    """
    rows = sorted([r for r in rows if r["session"] in sessions and r["symbol"] == symbol], key=lambda r: r["session"])
    fields = ("profit", "loss", "net", "gross", "fees", "wins", "losses", "trades", "winning_lots",
        "losing_lots", "flat_lots", "campaign_profit", "campaign_loss", "campaigns", "campaign_wins",
        "campaign_losses", "campaign_flats", "core_net", "cover_net")
    a = {field: sum(r[field] for r in rows) for field in fields}
    cap, point = (10, 1000.) if symbol == "TOPIX" else (20, 10.)
    a["net_ticks"] = sum(r["net"] / (cap * point * ready[(r["session"], symbol)]["tick"]) for r in rows)
    a.update(active_sessions=sum(r["campaigns"] > 0 for r in rows),
        positive_sessions=sum(r["net"] > 0 for r in rows),
        campaign_win_rate=a["campaign_wins"] / a["campaigns"] if a["campaigns"] else None,
        campaign_payoff=(a["campaign_profit"] / a["campaign_wins"]) / (a["campaign_loss"] / a["campaign_losses"])
            if a["campaign_wins"] and a["campaign_losses"] else None,
        win_rate=a["wins"] / a["trades"] if a["trades"] else None,
        payoff=(a["profit"] / a["winning_lots"]) / (a["loss"] / a["losing_lots"])
            if a["winning_lots"] and a["losing_lots"] else None,
        mean_net_ticks=a["net_ticks"] / a["campaigns"] if a["campaigns"] else None,
        max_long=max(r["max_long"] for r in rows), max_short=max(r["max_short"] for r in rows),
        max_campaign_loss=max(r["max_campaign_loss"] for r in rows),
        without_best_session=a["net"] - max(r["net"] for r in rows))
    cash = peak = drop = 0.
    for row in rows:
        drop = max(drop, row["drawdown"], peak - cash - row["equity_min"])
        peak = max(peak, cash + row["equity_max"])
        cash += row["net"]
    a["drawdown"] = drop
    return a


def main() -> None:
    """機能: 192条件・10752口座の独立監査を統合し期間集計も照合する。

    引数: なし。返り値: なし(None)。
    """
    fixed = read(WORK / "事前固定.json")
    ready = read(ROOT / "work/wave_v69/prepared/inputs.pkl")
    records = []
    paths = sorted(HERE.glob("台帳独立監査_*of3.json"))
    assert len(paths) == 3
    for path in paths:
        proof = read(path)
        assert proof["合格"] and proof["条件数"] == 64 and proof["口座数"] == 3584
        records.extend(proof["条件"])
    assert len(records) == len({r["ID"] for r in records}) == 192
    assert {r["ID"] for r in records} == {r["id"] for r in fixed["条件"]}
    sums = []
    for record in records:
        packet = read(WORK / "results" / (record["ID"] + ".json"))
        account_map = {(r["session"], r["symbol"]): r for r in record["口座"]}
        for reported in packet["rows"]:
            key = (reported["session"], reported["symbol"])
            cap, point = (10, 1000.) if key[1] == "TOPIX" else (20, 10.)
            near(reported["net_ticks"], account_map[key]["net"] / (cap * point * ready[key]["tick"]), "場正規化呼値損益")
        periods = {}
        for name in ("前16", "後12", "全セッション"):
            label = "全28" if name == "全セッション" else name
            periods[label] = {}
            for symbol in ("TOPIX", "NK225"):
                a = aggregate(record["口座"], fixed[name], symbol, ready)
                for field, value in a.items():
                    reported = packet["periods"][label][symbol][field]
                    if value is None:
                        assert reported is None
                    else:
                        near(float(value), float(reported), label + "/" + symbol + "/" + field)
                periods[label][symbol] = a
        sums.append(dict(ID=record["ID"], 設定=record["設定"], 期間=periods, 合格=True))
    fingerprints = {path: digest(ROOT / path) == expected for path, expected in fixed["SHA256"].items()}
    assert all(fingerprints.values())
    save(HERE / "全条件の独立監査.json", dict(合格=True, 条件数=192, 口座数=10752,
        凍結指紋=fingerprints, 全原本行時価指紋一致口座=10752,
        共通満額初回一致口座=10752, 期間集計一致数=192 * 3 * 2,
        明細と一組評価="元玉・保険を含む全玉の決済、未清算損の隠蔽なし",
        shard資料=[path.name for path in paths], 条件=sums))
    print("全192条件・10752口座・1152期間集計・凍結9指紋: 合格", flush=True)


if __name__ == "__main__":
    main()
