"""第四巡の注文会計と、確定版全762商品場の表示集計を独立照合する。"""

import argparse
import json
from pathlib import Path
import pickle
import time

import numpy as np
from audit_saved_round1_130 import inspect, read, reference, sha, statistics

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PRIOR = ROOT/"work/visual_pdca129_20261020"
ROUND_NAMES = ("round1_final","round2","round3","round4")
OLD_METHODS = ("D17","DV05","DV07","N36","NV01","NV25")


def save_new(prefix, value):
    """
    機能: この監査領域へ完成証拠を重複せず保存する。
    引数: prefix(str)、value(dict)は名前と検査結果。
    返り値: Pathは新しい証拠位置。
    """
    target = HERE/f"{prefix}_{time.time_ns()}.json"
    assert not target.exists()
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    return target


def audit_accounts():
    """
    機能: 第四巡84商品場を保存注文と原packetから独立再計算する。
    引数: なし。
    返り値: Pathは監査証拠。売買判断や価格予算の状態再生は行わない。
    """
    folder = WORK/"round4"
    measurement_path = folder/"全条件の会計.json"
    measurement = read(measurement_path)
    fixed = read(folder/"固定計画.json")
    assert measurement["sources"] == fixed["sources"]
    for path,digest in fixed["sources"].items():
        assert sha(ROOT/path) == digest
    for ref in fixed["artificial"]+fixed["input_references"]:
        assert sha(ROOT/ref["path"]) == ref["sha256"]
    manifest_ref = measurement["input_manifest"]
    assert sha(ROOT/manifest_ref["path"]) == manifest_ref["sha256"]
    manifest = read(ROOT/manifest_ref["path"])
    packets = {r["session"]:r for r in manifest["packets"] if r["session"].endswith("_Night")}
    caches = {(r["session"],r["symbol"]):r for r in measurement["cache"]}
    rows = {(r["method"],r["session"],r["symbol"]):r for r in measurement["rows"]}
    configs = {c["id"]:c for c in measurement["configs"]}
    assert set(configs) == {"W11","W12"}
    assert len(rows) == 84 and len(caches) == 42 and len(packets) == 21
    audited = []
    for scene,packet_ref in packets.items():
        assert sha(ROOT/packet_ref["path"]) == packet_ref["sha256"]
        packet = pickle.loads((ROOT/packet_ref["path"]).read_bytes())
        for symbol in ("TOPIX","NK225"):
            ref = caches[scene,symbol]
            assert sha(ROOT/ref["path"]) == ref["sha256"]
            with np.load(ROOT/ref["path"],allow_pickle=False) as saved:
                for method,config in configs.items():
                    assert config["exit_style"] == 0
                    result = inspect(packet["inputs"][scene,symbol],packet["quotes"][scene,symbol],
                        saved[method+"__orders"],saved[method+"__trades"],saved[method+"__curve"],
                        rows[method,scene,symbol],config)
                    assert result["partial_exits"] == 0
                    audited.append(result)
        print(scene,len(audited),"商品場会計監査済み",flush=True)
    for path,digest in fixed["sources"].items():
        assert sha(ROOT/path) == digest
    output = dict(passed=True,financial_replays=0,API=0,accounts=len(audited),
        parents=sum(r["entries"] for r in audited),orders=sum(r["orders"] for r in audited),
        exit_parts=sum(r["exit_parts"] for r in audited),rows=sum(r["source_rows"] for r in audited),
        checks=sum(r["checks"] for r in audited),max_curve_difference=max(r["max_curve_difference"] for r in audited),
        source=reference(Path(__file__)),accounting_source=reference(HERE/"audit_saved_round1_130.py"),
        fixed=reference(folder/"固定計画.json"),measurement=reference(measurement_path),
        manifest=manifest_ref,numeric_sources=fixed["sources"],measurement_files=measurement["cache"],
        scope="次正常BBO原行・注文数量・売買代金と保有原価からの全行時価・親手数料・場末flat。入口価格予算は別担当の監査。",
        rows_audit=audited)
    target = save_new("第四巡84商品場の独立保存会計",output)
    print(target,"合格",output["checks"],"親",output["parents"],flush=True)
    return target


def audit_final():
    """
    機能: 確定比較の762商品場と全36集計を、旧引用・新四巡の一次会計に照合する。
    引数: なし。
    返り値: Pathは監査証拠。途中版の最終全場比較.jsonは参照しない。
    """
    final_path = WORK/"最終全場比較_確定.json"
    final = read(final_path)
    prior_path = PRIOR/"最終全場比較_確定.json"
    prior = read(prior_path)
    reference_rows = [r for r in prior["rows"] if r["method"] in OLD_METHODS]
    inputs = [reference(prior_path)]
    replay_count = 0
    for round_name in ROUND_NAMES:
        path = WORK/round_name/"全条件の会計.json"
        data = read(path)
        assert data["passed"]
        inputs.append(reference(path))
        reference_rows += data["rows"]
        replay_count += data["financial_replays"]
    index = {(r["method"],r["session"],r["symbol"]):r for r in reference_rows}
    displayed = {(r["method"],r["session"],r["symbol"]):r for r in final["rows"]}
    assert len(reference_rows) == len(index) == len(displayed) == len(final["rows"]) == 762
    assert set(displayed) == set(index)
    methods = set(r["method"] for r in final["rows"])
    expected_methods = set(OLD_METHODS)|{f"W{i:02}" for i in range(1,13)}
    assert methods == expected_methods and len(methods) == 18
    assert replay_count == 504
    metadata = {(r["session"],r["symbol"]):r for r in prior["rows"]}
    numeric = ("profit","loss","net","gross","fees","entries","quantity","parent_wins","parent_losses",
               "max_quantity","partial_exits")
    checks = 0
    for key,original in index.items():
        shown = displayed[key]
        for field in numeric:
            if field in original:
                assert original[field] == shown[field], (key,field)
                checks += 1
        info = metadata[original["session"],original["symbol"]]
        for field in ("kind","regime","half_within_kind","week_start","kind_session_index"):
            assert shown[field] == info[field], (key,field)
            checks += 1
    summaries = {(s["method"],s["symbol"]):s for s in final["summary"]}
    assert len(final["summary"]) == len(summaries) == 36
    checks_summary = 0
    for method in sorted(methods):
        for symbol in ("TOPIX","NK225"):
            shown = summaries[method,symbol]
            selected = [r for r in final["rows"] if r["method"] == method and r["symbol"] == symbol]
            assert len(selected) == (22 if method in ("D17","DV05","DV07") else 21)
            targets = [(selected,shown,"全場")]
            assert set(shown["regimes"]) == {r["regime"] for r in selected}
            assert set(shown["halves"]) == {"前半","後半"}
            targets += [([r for r in selected if r["regime"] == label],stat,label)
                        for label,stat in shown["regimes"].items()]
            targets += [([r for r in selected if r["half_within_kind"] == label],stat,label)
                        for label,stat in shown["halves"].items()]
            for rows,actual,label in targets:
                for field,value in statistics(rows).items():
                    assert np.isclose(actual[field],value,rtol=0.,atol=1e-9),(method,symbol,label,field)
                    checks_summary += 1
    assert sum(r["kind"] == "Day" for r in final["rows"]) == 132
    assert sum(r["kind"] == "Night" for r in final["rows"]) == 630
    output = dict(passed=True,financial_replays=0,API=0,total_rows=762,new_rows=504,
        reused_rows=258,methods=18,day_methods=3,night_methods=15,day_rows=132,night_rows=630,
        summaries=36,row_checks=checks,summary_checks=checks_summary,
        source=reference(Path(__file__)),statistics_source=reference(HERE/"audit_saved_round1_130.py"),
        final=reference(final_path),inputs=inputs,
        scope="全一次会計との数値・方向と前後半タグの対応、全体・方向別・時系列前後半の全指標。旧引用は再金融なし。")
    target = save_new("確定762商品場と全36集計の独立照合",output)
    print(target,"合格",checks+checks_summary,flush=True)
    return target


def main():
    """
    機能: 完成済みの第四巡会計又は最終確定一覧を選んで監査する。
    引数: --phase(str)はaccount又はfinal又はboth。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase",choices=("account","final","both"),required=True)
    args = parser.parse_args()
    if args.phase in ("account","both"):
        audit_accounts()
    if args.phase in ("final","both"):
        audit_final()


if __name__ == "__main__":
    main()
