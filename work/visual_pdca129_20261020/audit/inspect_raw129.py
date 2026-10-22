"""選定した失敗と勝ち対照の原板だけを、原連番を保って限定確認する。"""

from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "work/daynight128_20261020"


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は読取位置。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    """
    機能: 具体例の原板時刻、数量更新、Lastと気配の接続を調査する。
    引数: なし。
    返り値: None。原板は読み取りのみ、注文や損益を新生成しない。
    """
    output = HERE / "具体時刻の原板と勝ち対照の限定照合.json"
    assert not output.exists()
    diagnosis = read(HERE / "価格時計と気配及び呼値尺度の独立診断.json")
    selectors = [
        ("N27", "NK225", "2026-10-08_Night", "2026-10-09T02:05:42+09:00"),
        ("N27", "NK225", "2026-10-16_Night", "2026-10-17T00:10:02+09:00"),
        ("N27", "TOPIX", "2026-10-01_Night", "2026-10-02T01:34:00+09:00"),
        ("N27", "TOPIX", "2026-10-16_Night", "2026-10-17T00:21:35+09:00"),
        ("D17", "TOPIX", "2026-10-19_Day", "2026-10-19T09:51:43+09:00"),
        ("D17", "TOPIX", "2026-10-19_Day", "2026-10-19T10:08:09+09:00"),
        ("D17", "NK225", "2026-10-16_Day", "2026-10-16T09:51:54+09:00"),
    ]
    chosen = [next(r for r in diagnosis["trades"] if (r["method"], r["symbol"], r["session"], r["entry_time"]) == s)
              for s in selectors]
    manifests = {p["session"]:p for p in read(OLD / "入力準備.json")["packets"]}
    grouped = defaultdict(list)
    for item in chosen:
        grouped[item["session"]].append(item)
    records = []
    source_refs = []
    for scene, items in grouped.items():
        packet = pickle.loads((ROOT / manifests[scene]["path"]).read_bytes())
        required = defaultdict(set)
        details = []
        for item in items:
            symbol = item["symbol"]
            key = scene, symbol
            ready = packet["inputs"][key]
            times, seq = ready["time_s"], ready["seq"]
            points = {}
            for name, index in (("新規判断", item["decision_row"]), ("新規約定", item["entry_row"]), ("最終返済", item["exit_row"])):
                left = int(np.searchsorted(times, times[index], side="left"))
                right = int(np.searchsorted(times, times[index], side="right")) - 1
                points[name] = {"row":index, "seq":int(seq[index]), "同価格時計先頭seq":int(seq[left]),
                               "同価格時計末尾seq":int(seq[right]), "同時計行数":right-left+1}
                required[symbol].update(range(max(0,int(seq[index])-4), int(seq[index])+5))
                required[symbol].update((int(seq[left]),int(seq[right])))
            d = item["decision_row"]
            earlier = int(np.searchsorted(times, times[d]-30., side="right")-1)
            required[symbol].add(int(seq[earlier]))
            points["三十秒比較行"] = {"row":earlier, "seq":int(seq[earlier])}
            peer = "NK225" if symbol == "TOPIX" else "TOPIX"
            other = packet["inputs"][scene,peer]
            peer_time = packet["markets"][key][d,8]
            pi = int(np.searchsorted(other["time_s"], peer_time, side="right")-1)
            assert other["time_s"][pi] < times[d]
            required[peer].update((int(other["seq"][pi]),))
            points["参照した相手"] = {"symbol":peer,"row":pi,"seq":int(other["seq"][pi])}
            details.append((item, points))
        raw_records = {}
        for symbol, requested in required.items():
            path = ROOT / "book" / symbol / (scene+".jsonl")
            selected = {}
            with path.open("rb") as stream:
                for seq, line in enumerate(stream):
                    if seq in requested:
                        raw = json.loads(line)
                        clocks = {k:v for k,v in raw.items() if "Time" in k or "time" in k or "Date" in k}
                        selected[seq] = {
                            "seq": seq, "CurrentPrice":raw.get("CurrentPrice"),
                            "Buy1":raw.get("Buy1"), "Sell1":raw.get("Sell1"),
                            "TradingVolume":raw.get("TradingVolume"), "clocks":clocks,
                            "keys":sorted(raw), "raw_line_sha256":hashlib.sha256(line).hexdigest(),
                        }
                    if seq >= max(requested):
                        break
            assert set(selected)==requested
            raw_records[symbol] = selected
            source_refs.append({"path":path.relative_to(ROOT).as_posix(),"size_bytes":path.stat().st_size,
                                "連番まで走査":seq+1,"JSON解析行数":len(selected),
                                "原ファイル全体SHAではなく抽出行SHAを保存":True})
        for item, points in details:
            symbol = item["symbol"]
            key = scene,symbol
            ready, quote = packet["inputs"][key], packet["quotes"][key]
            rendered = {}
            for name,p in points.items():
                s = p.get("symbol",symbol)
                raw = raw_records[s][p["seq"]]
                r = packet["inputs"][scene,s]
                q = packet["quotes"][scene,s]
                at = p["row"]
                assert raw["CurrentPrice"] == r["last"][at]
                assert datetime.fromisoformat(raw["clocks"]["CurrentPriceTime"]).timestamp() == r["time_s"][at]
                assert raw["Buy1"]["Price"] == q["bid"][at]
                assert raw["Sell1"]["Price"] == q["ask"][at]
                rendered[name] = dict(p, raw=raw)
                if "同価格時計先頭seq" in p:
                    rendered[name]["同時計の先頭原板"] = raw_records[s][p["同価格時計先頭seq"]]
                    rendered[name]["同時計の末尾原板"] = raw_records[s][p["同価格時計末尾seq"]]
            records.append({"method":item["method"],"session":scene,"symbol":symbol,"net":item["net"],
                            "具体点":rendered,"近傍":list(raw_records[symbol].values())})
        print(scene,flush=True)
    result = {"passed":True,"金融再生":0,"API":0,"具体親数":len(records),
              "scope":"当時点と同価格時計の末尾は別。末尾は時計品質の事後診断であり入口判断に使わない。",
              "records":records,"sources":source_refs}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"具体親数":len(records),"原板ファイル数":len(source_refs),
                      "解析行数":sum(s["JSON解析行数"] for s in source_refs)},ensure_ascii=False))


if __name__ == "__main__":
    main()
