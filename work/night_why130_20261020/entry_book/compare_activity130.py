"""全親の局所原板集計と全原行特徴を照合し、候補の分母を固定する。"""

import sys
import pickle
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from diagnose_entry130 import HERE, read, save
sys.path.insert(0, str(HERE.parent))
from common130 import reference
import activity130


def main() -> None:
    """
    機能: 145保存親について二つの観測実装を比較し、全親・前後半分類を保存する。
    引数: なし。
    返り値: None。見送り後の注文経路や損益は再生しない。
    """
    data = read(HERE / "全入口の原板活動と固定価格表示数量.json")
    scenes = sorted({r["session"] for r in read(activity130.HERE / "原板活動の非金融準備.json")["inputs"]})
    records, checks = [], 0
    for r in data["records"]:
        book = r["book30"]
        with np.load(activity130.DEST / f'{r["symbol"]}_{r["session"]}.npz') as packet:
            i = r["decision_row"]
            features, detail, anchor = packet["activity"][i], packet["details"][i], int(packet["anchor_row"][i])
        old = book["anchor_fresh"] and book["signed_mid_change"] > 0. and book["signed_volume_balance"] is not None and book["signed_volume_balance"] < 0.
        known = features[3] == 1.
        selected = known and r["side"] * features[0] > 0. and r["side"] * features[2] < 0. and features[1] > 0.
        if known:
            assert np.isclose(r["side"] * features[0], book["signed_mid_change"])
            assert np.isclose(features[1], book["volume_positive"])
            assert np.isclose(detail[0], book["buy_proxy"])
            assert np.isclose(detail[1], book["sell_proxy"])
            assert np.isclose(detail[2], book["ambiguous_volume"])
            assert anchor == book["anchor_row"]
            checks += 6
        records.append(dict(method=r["method"], session=r["session"], symbol=r["symbol"], number=r["number"],
            decision_time=r["decision_time"], decision_row=i, side=r["side"], net=r["net"],
            old_selected=bool(old), selected=bool(selected), known=bool(known), changed=bool(old != selected),
            half="前半10場" if scenes.index(r["session"]) < 10 else "後半11場",
            features=[float(x) if np.isfinite(x) else None for x in features],
            details=[float(x) if np.isfinite(x) else None for x in detail], anchor_row=anchor))
    groups = []
    for method in ("N36", "NV25"):
        for symbol in ("TOPIX", "NK225"):
            for half in ("全場", "前半10場", "後半11場"):
                population = [r for r in records if r["method"] == method and r["symbol"] == symbol and (half == "全場" or r["half"] == half)]
                selected = [r for r in population if r["selected"]]
                groups.append(dict(method=method, symbol=symbol, half=half, denominator=len(population),
                    known=sum(r["known"] for r in population), selected=len(selected),
                    winning=sum(r["net"] > 0. for r in selected), losing=sum(r["net"] < 0. for r in selected),
                    net=sum(r["net"] for r in selected),
                    ids=[f'{r["session"]}/{r["number"]}' for r in selected]))
    source = Path(activity130.__file__)
    result = dict(passed=True, financial_replays=0, checks=checks, records=records, groups=groups,
        changes=[r for r in records if r["changed"]], source=reference(source),
        note="原板局所集計と全原行特徴の二実装照合。未見標本の勝率や見送り後の金融結果ではない。")
    save(HERE / "全原行活動と全親分類の照合.json", result)
    refs = {r["session"]: r for r in read(activity130.BASE / "入力準備.json")["packets"]}
    invalid_examples = []
    for row in result["changes"]:
        packet = pickle.loads((activity130.ROOT / refs[row["session"]]["path"]).read_bytes())
        rd = packet["inputs"][(row["session"], row["symbol"])]
        quote = packet["quotes"][(row["session"], row["symbol"])]
        raw = dict(np.load(activity130.RAW / f'{row["symbol"]}_{row["session"]}.npz'))
        invalid = []
        for i in range(row["anchor_row"] + 1, row["decision_row"] + 1):
            causes = []
            if rd["seq"][i] != rd["seq"][i-1] + 1:
                causes.append("原行飛び")
            if not quote["quote_valid"][i] or not quote["quote_valid"][i-1]:
                causes.append("気配有効フラグが偽")
            if not 0. < raw["bid"][i] < raw["ask"][i] or not 0. < raw["bid"][i-1] < raw["ask"][i-1]:
                causes.append("不正気配")
            if raw["volume"][i] < raw["volume"][i-1]:
                causes.append("公表出来高逆戻り")
            if causes:
                invalid.append(dict(row=i, sequence=int(rd["seq"][i]), previous_sequence=int(rd["seq"][i-1]),
                    time=datetime.fromtimestamp(rd["time_s"][i], timezone(timedelta(hours=9))).isoformat(),
                    causes=causes, bid=float(raw["bid"][i]), ask=float(raw["ask"][i]),
                    volume=float(raw["volume"][i])))
        wanted = {n for v in invalid for n in range(v["previous_sequence"], v["sequence"] + 1)}
        originals = []
        rawpath = activity130.ROOT / "book" / row["symbol"] / (row["session"] + ".jsonl")
        if wanted:
            with rawpath.open("rb") as handle:
                for n, line in enumerate(handle):
                    if n > max(wanted):
                        break
                    if n in wanted:
                        raw = json.loads(line)
                        originals.append(dict(sequence=n, time=raw.get("CurrentPriceTime"),
                            last=raw.get("CurrentPrice"), volume=raw.get("TradingVolume"),
                            buy=raw.get("Buy1"), sell=raw.get("Sell1")))
        invalid_examples.append(dict(parent=row, invalid=invalid, original_lines=originals))
    save(HERE / "分類変更三親の原行不連続.json", dict(financial_replays=0, cases=invalid_examples))
    print(groups)
    print("分類変更", result["changes"])


if __name__ == "__main__":
    main()
