"""第二巡の保存会計と活動判断を全注文・全行から独立照合する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PRIOR = ROOT/"work/visual_pdca129_20261020"


def read(path):
    """
    機能: 保存JSONを読み込む。
    引数: path(Path)は読取先。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 資料の内容指紋を計算する。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 凍結資料の指紋、全FIFO・原行BBO・費用・活動判断を照合する。
    引数: argv[1](str)は保存巡、省略時round2。
    返り値: None。保存注文の会計のみを再計算し、売買判断は再生しない。
    """
    name = sys.argv[1] if len(sys.argv) > 1 else "round2"
    folder = WORK/name
    fixed = read(folder/"固定計画.json")
    data = read(folder/"全条件の会計.json")
    started = read(folder/"金融実行開始.json")
    assert read(folder/"登録.json")["returncode"] == 0
    assert fixed["sources"] == data["sources"] == started["sources"]
    assert fixed["configs"] == data["configs"]
    configs = {c["id"]: c for c in fixed["configs"]}
    assert set(configs) == {"W07", "W08"}
    assert all(c["exit_style"] == 0 and c["activity_mode"] == 1 for c in configs.values())
    references = [dict(path=p, sha256=h) for p, h in fixed["sources"].items()]
    references += fixed["artificial"] + fixed["input_references"] + data["cache"]
    for ref in references:
        assert sha(ROOT/ref["path"]) == ref["sha256"], ref["path"]
    for ref in fixed["artificial"]:
        assert read(ROOT/ref["path"])["passed"]

    # ----------------------------------------
    # 旧独立会計器は保存配列だけを使う。第二巡は全量返済なので同じ会計式が適用できる。
    audit_path = PRIOR/"audit/check_accounting129.py"
    spec = importlib.util.spec_from_file_location("会計129保存照合", audit_path)
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    manifest = read(ROOT/"work/daynight128_20261020/入力準備.json")
    packets = {r["session"]: r for r in manifest["packets"]}
    activity_manifest = read(WORK/"原板活動の非金融準備.json")
    activities = {(r["session"], r["symbol"]): r for r in activity_manifest["inputs"]}
    groups = {}
    for row in data["rows"]:
        groups.setdefault((row["session"], row["symbol"]), []).append(row)
    assert len(groups) == 42 and len(data["rows"]) == 84 and len(data["cache"]) == 42
    assert all({r["method"] for r in rows} == set(configs) for rows in groups.values())
    records, decisions = [], []
    prior_scene = None
    for cache in data["cache"]:
        scene, symbol = cache["session"], cache["symbol"]
        key = scene, symbol
        if scene != prior_scene:
            ref = packets[scene]
            assert sha(ROOT/ref["path"]) == ref["sha256"]
            packet = pickle.loads((ROOT/ref["path"]).read_bytes())
            prior_scene = scene
        ready = packet["inputs"][key]
        quote = packet["quotes"][key]
        source = activities[key]
        assert source["packet"] == packets[scene]
        assert sha(ROOT/source["output"]["path"]) == source["output"]["sha256"]
        with np.load(ROOT/source["output"]["path"], allow_pickle=False) as saved:
            activity = saved["activity"]
            anchor = saved["anchor_row"]
            for field in ("seq", "time_s"):
                np.testing.assert_array_equal(saved[field], ready[field])
                np.testing.assert_array_equal(saved[field], quote[field])
        with np.load(ROOT/cache["path"], allow_pickle=False) as archive:
            assert set(archive.files) == {m+"__"+part for m in configs for part in ("orders", "trades", "curve")}
            for row in groups[key]:
                prefix = row["method"]+"__"
                orders, trades, curve = (archive[prefix+p] for p in ("orders", "trades", "curve"))
                assert trades.shape[1] == 15
                record = previous.inspect(row, orders, trades, curve, ready, quote)
                opened = orders[orders[:, 7] == 1]
                closed = orders[orders[:, 7] == 0]
                assert len(opened) == len(closed) == len(trades)
                np.testing.assert_array_equal(closed[:, 2], trades[:, 14])
                np.testing.assert_array_equal(opened[:, 2], np.arange(len(opened)))
                assert not (orders[:, 6] == 76).any() and row["partial_exits"] == 0
                assert row["parent_wins"] == int((trades[:, 8] > 0).sum())
                assert row["parent_losses"] == int((trades[:, 8] < 0).sum())
                config = configs[row["method"]]
                for order in opened:
                    fill, decision, parent, side, quantity = map(int, order[:5])
                    observed = activity[decision]
                    assert observed[3] == 1 and np.isfinite(observed[:3]).all()
                    assert side*observed[0] > 0 and observed[1] > 0 and side*observed[2] < 0
                    assert abs(observed[2]) <= observed[1]
                    a = int(anchor[decision])
                    assert 0 <= a < decision
                    elapsed = ready["time_s"][decision]-ready["time_s"][a]
                    assert 30. < elapsed <= 60.
                    assert ready["start"] <= ready["time_s"][decision] < ready["limit"]
                    assert ready["time_s"][fill] < ready["limit"]
                    quiet_start = ready["us_open"]-config["opening_buffer"]
                    quiet_end = ready["us_open"]+config["opening_buffer"]
                    assert not quiet_start <= ready["time_s"][decision] < quiet_end
                    assert not quiet_start <= ready["time_s"][fill] < quiet_end
                    assert quantity == (5 if symbol == "TOPIX" else 10)
                    decisions.append(dict(method=row["method"], session=scene, symbol=symbol,
                        parent=parent, direction=side, source_row=decision, source_seq=int(ready["seq"][decision]),
                        fill_row=fill, time_s=float(ready["time_s"][decision]), anchor_row=a,
                        observed_seconds=float(elapsed), activity=observed.tolist(),
                        parent_net=float(trades[trades[:, 14] == parent, 8].sum())))
                record["activity_decisions"] = len(opened)
                record["parent_id_consistent"] = True
                records.append(record)
        print(scene, symbol, len(records), "/84 保存照合", flush=True)
    assert len(records) == 84
    assert len(decisions) == sum(r["computed"]["entries"] for r in records)
    for ref in references:
        assert sha(ROOT/ref["path"]) == ref["sha256"], ref["path"]
    totals = []
    for method in configs:
        for symbol in ("TOPIX", "NK225"):
            rows = [r["computed"] for r in records if r["method"] == method and r["symbol"] == symbol]
            net = np.array([r["net"] for r in rows])
            totals.append(dict(method=method, symbol=symbol, sessions=len(rows),
                net=float(net.sum()), profit=sum(r["profit"] for r in rows),
                loss=sum(r["loss"] for r in rows), fees=sum(r["fees"] for r in rows),
                entries=sum(r["entries"] for r in rows), black=int((net > 0).sum()),
                red=int((net < 0).sum()), idle=sum(r["entries"] == 0 for r in rows),
                breakeven=sum(r["entries"] > 0 and r["net"] == 0 for r in rows)))
    output = HERE/f"{name}_活動判断と全注文全行会計の独立照合_{time.time_ns()}.json"
    result = dict(passed=True, round=name, accounts=len(records),
        orders=sum(r["orders"] for r in records), trades=sum(r["trades"] for r in records),
        curve_rows=sum(r["curve_rows"] for r in records), activity_decisions=len(decisions),
        reference_count=len(references), references=references, records=records, decisions=decisions,
        totals=totals, source=dict(path=(folder/"全条件の会計.json").relative_to(ROOT).as_posix(),
                                  sha256=sha(folder/"全条件の会計.json")),
        fixed_sha256=sha(folder/"固定計画.json"),
        auditor_sha256=sha(Path(__file__)), prior_auditor_sha256=sha(audit_path),
        financial_replays=0, API=0,
        scope="保存全注文FIFO・実注文ごとの費用・全原行時価・親ID・新規判断原行の活動と禁止時刻を照合")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("references", "records", "decisions")}, ensure_ascii=False))
    print(output, flush=True)


if __name__ == "__main__":
    main()
