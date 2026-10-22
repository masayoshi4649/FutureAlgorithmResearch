"""第一巡・第二巡の固定指紋と具体原行の支持資料を保存する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import features129


def read(path):
    """
    機能: UTF-8の保存内容を読む。
    引数: path(Path)は資料位置。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 内容指紋を返す。
    引数: path(Path)は資料位置。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value):
    """
    機能: 価格時計を日本時刻にする。
    引数: value(float)はUnix秒。
    返り値: strは時刻。
    """
    return datetime.fromtimestamp(float(value), timezone(timedelta(hours=9))).isoformat()


def main():
    """
    機能: 固定仕様の現在源・証拠・測定指紋を検査し、特定の注文時特徴を抜き出す。
    引数: なし。
    返り値: None。数値売買は再生せず、自分の監査資料だけを書き込む。
    """
    references = []
    for name in ("round1", "round2"):
        fixed = read(WORK/name/"固定計画.json")
        results = read(WORK/name/"全条件の会計.json")
        started = read(WORK/name/"金融実行開始.json")
        registered = read(WORK/name/"登録.json")
        assert registered["returncode"] == 0
        assert fixed["sources"] == results["sources"] == started["sources"]
        assert fixed["configs"] == results["configs"]
        refs = [dict(path=p, sha256=h) for p, h in fixed["sources"].items()]
        refs += fixed["artificial"] + fixed["input_references"] + results["cache"]
        for ref in refs:
            assert sha(ROOT/ref["path"]) == ref["sha256"], ref["path"]
        references.append(dict(round=name, references_checked=len(refs),
                               fixed_sha256=sha(WORK/name/"固定計画.json"),
                               result_sha256=sha(WORK/name/"全条件の会計.json")))
    inputs = read(ROOT/"work/daynight128_20261020/入力準備.json")
    cases = []
    plans = {
        "2026-10-16_Night": [("TOPIX", "NV02", 1), ("TOPIX", "NV01", 1), ("TOPIX", "NV02", 2)],
        "2026-10-02_Night": [("TOPIX", "NV01", 1), ("TOPIX", "NV02", 1), ("TOPIX", "NV02", 2)],
        "2026-10-01_Night": [("NK225", "NV02", 0), ("NK225", "NV02", 3)],
    }
    for scene, items in plans.items():
        ref = next(x for x in inputs["packets"] if x["session"] == scene)
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        built = {kind: features129.build(packet, kind, 0.) for kind in ("last", "mid")}
        for symbol, method, parent in items:
            archive = np.load(WORK/"round1/measurement"/f"{symbol}_{scene}.npz")
            order = archive[method+"__orders"][parent*2]
            trade = archive[method+"__trades"][parent]
            i = int(order[1])
            key = scene, symbol
            ready = packet["inputs"][key]
            quote = packet["quotes"][key]
            detail = dict(session=scene, symbol=symbol, method=method, parent=parent,
                          row=i, time=stamp(ready["time_s"][i]), entry=trade[4], net=trade[8],
                          bid=quote["bid"][i], ask=quote["ask"][i], features={})
            for kind, (prices, markets, history, context) in built.items():
                detail["features"][kind] = dict(
                    price=float(prices[key]["last"][i]), atr=float(ready["atr"][i]),
                    history={name: float(v) if np.isfinite(v) else None
                             for name, v in zip(features129.features128.NAMES, history[key][i])},
                    short={name: float(markets[key][i, col]) if np.isfinite(markets[key][i, col]) else None
                           for name, col in (("自己30秒", 4), ("自己120秒", 5), ("相手30秒", 6), ("相手120秒", 7))},
                    context=[float(x) if np.isfinite(x) else None for x in context[key][i]])
            cases.append(detail)
    target = HERE/"第一二巡固定源と具体判断行の独立確認.json"
    assert not target.exists()
    target.write_text(json.dumps(dict(passed=True, source_sha256=sha(Path(__file__)),
                                      financial_replays=0, references=references, cases=cases),
                                 ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(dict(passed=True, references=references, cases=len(cases)), ensure_ascii=False))


if __name__ == "__main__":
    main()
