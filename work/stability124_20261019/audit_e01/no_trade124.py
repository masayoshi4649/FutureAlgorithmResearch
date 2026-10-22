"""独立保存監査で保全したコピーだけから、E01c無取引の直接理由を確かめる。"""

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = dt.timezone(dt.timedelta(hours=9))
RESULT_SHA = "35273f0285d1f28dd98bbbc5451899c7ca0b19dd001db0efdb4c6e91069204e9"


def main() -> None:
    """
    機能: 紙上候補が存在したことと、全件が既知票の釣合い不足で拒否されたことを照合する。
    引数: なし。
    返り値: None。保全済み私有コピー以外の金融入力・原市場を読まず、売買規則を再実行しない。
    """
    result_raw = (HERE / "owned/完成結果.json").read_bytes()
    assert hashlib.sha256(result_raw).hexdigest() == RESULT_SHA
    result = json.loads(result_raw)
    rows = []
    counts = {}
    for detail in result["accounts"]:
        scene, symbol = detail["session"], detail["symbol"]
        account = pickle.loads(gzip.decompress((HERE / "owned/input" / symbol / (scene + ".pkl.gz")).read_bytes()))
        ledger = pickle.loads(gzip.decompress((HERE / "owned/ledger" / symbol / (scene + ".pkl.gz")).read_bytes()))
        entries = account["feed"][account["feed"][:, 7] == 1]
        expected = 2 if symbol == "TOPIX" else 1
        threshold = .5 if symbol == "TOPIX" else .25
        assert len(entries) == expected == detail["diagnosis"]["paper_publications"] == len(detail["gate_diagnostics"])
        assert len(ledger["orders"]) == len(detail["orders"]) == 0
        for order in entries:
            index = int(order[0])
            original = account["trade_features"]["60"][index]
            reported = detail["gate_diagnostics"][str(index)]
            assert reported["vote"] == original
            assert original["known"] is True and original["direction_votes"] >= 2
            direction_votes = original["up_votes"] + original["down_votes"]
            assert direction_votes == original["direction_votes"]
            recomputed = (original["up_votes"] - original["down_votes"]) / direction_votes
            assert np.isclose(original["balance"], recomputed, atol=1e-12, rtol=0)
            assert original["balance"] < threshold == reported["threshold"]
            assert original["accepted"] is False and reported["accepted"] is False and reported["reason"] == 201
            assert not ledger["gate_accepted"][index] and int(ledger["gate_reasons"][index]) == 201
            clock = float(account["record"]["time_s"][index])
            rows.append({"session": scene, "symbol": symbol, "紙上新規公開行": index, "紙上候補方向": "買い" if order[3] > 0 else "売り", "価格時計": dt.datetime.fromtimestamp(clock, JST).isoformat(), "price_time_s": clock, "買い側代理票": original["up_votes"], "売り側代理票": original["down_votes"], "既知方向票": direction_votes, "釣合い": original["balance"], "必要釣合い": threshold, "accepted": False, "reason": 201, "直接拒否理由": "方向票は既知で必要数以上だが、候補方向を支持する釣合いが固定閾値に足りない"})
        counts[symbol] = {"紙上全注文数": len(account["feed"]), "紙上新規候補数": len(entries), "釣合い閾値未達201": len(entries), "実新規数": 0, "実料金": ledger["summary"]["費用"], "収支": ledger["summary"]["収支"]}
        assert ledger["summary"]["費用"] == ledger["summary"]["収支"] == 0
    # ----------------------------------------
    proof = {"passed": True, "result_sha256": RESULT_SHA, "counts": counts, "candidates": rows, "直接原因": "紙上E01はTOPIX2件・NK2251件の買い候補を出したが、すべて後段の方向票gateで拒否。方向データ欠測、票数不足、実約定後の手数料、未返済、途中実行失敗による0ではない。", "留保": "この3件でgateが将来損失を回避したかは測っていない。無取引を黒字・勝ち・安定性達成へ数えない。代理票は真の成行攻撃注文や主体の方向とは異なる。", "参照": "実装のreason201はe01c/engine/entry_policy.pyのvote。算術期待値は保存したup/down票の差から独立再計算した。", "読取": {"今回の保全済み小結果": 1, "今回の保全済み私有入力コピー": 2, "今回の保全済み私有台帳コピー": 2, "原金融cacheの追加読取": 0, "旧cache": 0, "原市場": 0, "金融再実行": 0}, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    target = HERE / "追加場の無取引は方向票閾値未達であることの保存補助確認.json"
    assert not target.exists()
    raw = (json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    target.write_bytes(raw)
    print(json.dumps({"path": target.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "counts": counts, "candidates": rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
