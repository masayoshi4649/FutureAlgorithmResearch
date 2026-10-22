"""保存済み日中約定の赤字上位場だけを具体的な時刻と清算可能損益へ戻す。"""

from collections import Counter
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "work/stability126_20261019"
SOURCE = OLD / "diagnosis_notes/bbo/trace_bbo_loss126.py"


def read(path: Path) -> dict:
    """
    機能: 保存JSONを診断目的で読み取る。
    引数: path(Path)は既存資料の位置。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    """
    機能: GU_Qの日中赤字上位三場を商品別に抽出し、保存注文を診断する。
    引数: なし。
    返り値: None。既存約定を変えず、新しい金融再生も行わない。
    """
    destination = HERE / "日中赤字上位三場の保存約定診断.json"
    assert not destination.exists()
    module_spec = importlib.util.spec_from_file_location("saved_diagnosis126", SOURCE)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    fees_path = OLD / "fees_20261020/二候補の四十三場の注文別手数料と実保有枚数.json"
    result_path = OLD / "gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json"
    prepared_path = OLD / "input_audit/attempt2/全四十一場の元入力と新市場特徴の非金融準備.json"
    fees, result, prepared = map(read, (fees_path, result_path, prepared_path))
    cache = {(x["session"], x["symbol"]): x for x in result["cache"]}
    packets = {x["session"]: x for x in prepared["packets"]}
    metadata = {(x["session"], x["symbol"]): x for x in result["metadata"]}
    records, sources, loaded_packets = [], [], {}
    for symbol in ("TOPIX", "NK225"):
        ranked = sorted(
            [r for r in fees["rows"] if r["method"] == "GU_Q" and r["symbol"] == symbol
             and r["session"].endswith("_Day")],
            key=lambda row: row["after_fees"],
        )[:3]
        for account in ranked:
            scene = account["session"]
            if scene not in loaded_packets:
                loaded_packets[scene] = pickle.loads(module.payload(packets[scene], sources, "上位赤字場の時刻と既保存気配"))
            packet = loaded_packets[scene]
            reference = cache[scene, symbol]
            with np.load(BytesIO(module.payload(reference, sources, "既存GU_Qの注文と親会計")), allow_pickle=False) as arrays:
                actual = {name: arrays["GU_Q__" + name] for name in ("orders", "cycles", "execution_events")}
                for name in actual:
                    np.testing.assert_array_equal(actual[name], arrays["G_Q__" + name])
            empty = {"orders": np.empty((0, 8)), "cycles": np.empty((0, 10))}
            groups = module.group_details(packet, symbol, actual, empty)
            ready = packet["inputs"][scene, symbol]
            for group in groups:
                selected = actual["orders"][actual["orders"][:, 2] == group["campaign"]]
                unit = 418 if symbol == "TOPIX" else 110
                group["fees"] = int(((selected[:, 4].astype(np.int64) * unit) // 10).sum())
                group["after_fees"] = group["net"] - group["fees"]
                group["maximum_r"] = group["maximum_observed_liquidation_pnl"] / group["initial_risk_yen"]
                group["giveback_yen"] = group["maximum_observed_liquidation_pnl"] - group["net"]
                group["source_board_side"] = int(ready["board_side"][group["source_row"]])
                group["source_trend_side"] = int(ready["trend_side"][group["source_row"]])
                group["holding_minutes"] = (
                    ready["time_s"][int(selected[-1, 0])] - ready["time_s"][group["entry_row"]]
                ) / 60
                group.pop("Last_comparison")
            assert np.isclose(sum(g["net"] for g in groups), account["before_fees"])
            assert sum(g["fees"] for g in groups) == account["fees"]
            loss = [g for g in groups if g["net"] < 0]
            records.append(dict(
                account=account, session_state=metadata[scene, symbol], groups=groups,
                loss_analysis=dict(
                    groups=len(groups), losing_groups=len(loss), winning_groups=sum(g["net"] > 0 for g in groups),
                    never_positive=sum(not g["positive_observed"] for g in loss),
                    reached_quarter_r=sum(g["maximum_r"] >= .25 for g in loss),
                    reached_half_r=sum(g["maximum_r"] >= .5 for g in loss),
                    reached_one_r=sum(g["maximum_r"] >= 1 for g in loss),
                    two_market_opposition_before_exit=sum(g["first_two_market_opposition"] is not None for g in loss),
                    reasons=dict(Counter(g["final_reason"] for g in loss)),
                ),
            ))
    summary = {}
    for symbol in ("TOPIX", "NK225"):
        groups = [g for r in records if r["account"]["symbol"] == symbol for g in r["groups"]]
        loss = [g for g in groups if g["net"] < 0]
        summary[symbol] = dict(
            sessions=3, groups=len(groups), losing=len(loss), winning=sum(g["net"] > 0 for g in groups),
            losses_yen=sum(g["net"] for g in loss),
            never_positive=sum(not g["positive_observed"] for g in loss),
            reached_quarter_r=sum(g["maximum_r"] >= .25 for g in loss),
            reached_half_r=sum(g["maximum_r"] >= .5 for g in loss),
            reached_one_r=sum(g["maximum_r"] >= 1 for g in loss),
            two_market_opposition_before_exit=sum(g["first_two_market_opposition"] is not None for g in loss),
        )
    output = dict(
        passed=True, method="GU_Q", display_alias="日中のG_Qと注文・親会計・実行記録の完全同値を確認",
        summary=summary, records=records, reads=sources,
        references=[dict(path=p.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                    for p in (fees_path, result_path, prepared_path, SOURCE)],
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        limits=[
            "各商品の日中赤字上位三場を事後選別した診断。全取引の発生率や予測精度ではない。",
            "清算可能最高益は既存約定から当行正常BBOだけで評価。最高値を実際に取れた成績ではない。",
            "時刻は保存CurrentPriceTimeの代理であり、二市場の同時受信順は証明できない。",
            "改修条件の新規金融再生はしていない。改善案の収益性は未測定。",
        ],
        financial_replays=0, original_market_reads=0, API=0, real_orders=0,
    )
    destination.write_text(json.dumps(module.primitive(output), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    for record in records:
        print(record["account"]["symbol"], record["account"]["session"], record["account"]["after_fees"])
        for group in sorted(record["groups"], key=lambda item: item["entry_time"]):
            print(group["direction"], group["entry_time"], group["entry_price"], "→", group["final_time"],
                  group["net"], "MFE", group["maximum_observed_liquidation_pnl"], "R", round(group["maximum_r"], 3),
                  "反対", group["first_two_market_opposition"])


if __name__ == "__main__":
    main()
