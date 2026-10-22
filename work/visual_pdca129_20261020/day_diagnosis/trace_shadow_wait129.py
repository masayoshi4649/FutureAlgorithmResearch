"""保存注文と元影終了通知の時間差だけを確認する。金融再生は行わない。"""

from io import BytesIO
import json
from pathlib import Path
import pickle

import numpy as np

import render_day129 as source


def main() -> None:
    """
    機能: D17の実返済後に、元影がどれだけ残ったかを保存資料から抽出する。
    引数: なし。
    返り値: None。元影終了までの時間差と既知資料指紋をJSONへ保存する。
    """
    manifest = source.read_json(source.OLD / "入力準備.json")
    refs = {r["session"]: r for r in manifest["packets"]}
    charts = source.read_json(source.HERE / "描画資料と親会計.json")
    rows = []
    for item in charts["images"]:
        if item["prefix"]:
            continue
        scene, symbol = item["scene"], item["symbol"]
        packet = pickle.loads(source.read_fixed(refs[scene]))
        ready = packet["inputs"][scene, symbol]
        with np.load(BytesIO(source.read_fixed(refs[scene]["features"])), allow_pickle=False) as stored:
            feed = stored[symbol + "__feed"]
        for parent in item["parents"]:
            notifications = feed[feed[:, 2] == parent["cid"]]
            ending = int(notifications[-1, 0])
            actual = parent["exit_row"]
            rows.append(dict(
                session=scene, symbol=symbol, parent=parent["cid"],
                entry=parent["entry_time"], actual_exit=parent["exit_time"],
                shadow_end=source.clock(ready["time_s"][ending]),
                actual_exit_row=actual, shadow_end_row=ending,
                shadow_remaining_seconds=max(0., float(ready["time_s"][ending] - ready["time_s"][actual])),
                fee_net=parent["net"],
            ))
    output = dict(rows=rows, reads=source.READS, financial_replays=0,
                  note="同影に再参加できない旧D17の待機区間。区間中の仮想収益は算出していない。")
    destination = source.HERE / "実返済と元影終了の時刻差.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=True))


if __name__ == "__main__":
    main()
