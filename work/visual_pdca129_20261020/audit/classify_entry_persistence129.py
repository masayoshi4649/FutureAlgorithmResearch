"""入口準備時の効率条件が発注時にも残るか保存親を分類する。"""

from collections import defaultdict
import json
from pathlib import Path
import pickle
import sys
import hashlib

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import features129


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は位置。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def summarize(rows):
    """
    機能: 分類済み保存親を集計する。
    引数: rows(list[dict])は親。
    返り値: dictは件数、勝敗、収支。
    """
    return dict(親数=len(rows), 黒字=sum(x["net"] > 0 for x in rows),
                赤字=sum(x["net"] < 0 for x in rows), 収支=sum(x["net"] for x in rows))


def main():
    """
    機能: 既存閾値0.35を用いた入口準備条件の失効を保存分類する。
    引数: なし。
    返り値: None。注文を変更せず、数値戦略は再生しない。
    """
    saved = read(HERE/"価格源変更と一時間欠測の保存親独立診断.json")["cases"]
    manifest = read(ROOT/"work/daynight128_20261020/入力準備.json")
    rows = []
    for ref in manifest["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Night"):
            continue
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        for method, kind in (("NV01", "last"), ("NV02", "mid")):
            ready = features129.prices_for(packet, kind)
            history = features129.features128.build(dict(inputs=ready))
            for parent in saved:
                if parent["session"] != scene or parent["method"] != method:
                    continue
                key = scene, parent["symbol"]
                h = history[key][parent["decision_row"]]
                rows.append(dict(parent, efficiency_at_decision=float(h[5]),
                                 efficiency_below_original_arm_threshold=bool(h[5] < .35)))
    groups = []
    for method in ("NV01", "NV02"):
        for symbol in ("TOPIX", "NK225"):
            chosen = [x for x in rows if x["method"] == method and x["symbol"] == symbol]
            stale = [x for x in chosen if x["efficiency_below_original_arm_threshold"]]
            groups.append(dict(method=method, symbol=symbol, total=summarize(chosen),
                               below_original_threshold=summarize(stale),
                               retained_original_threshold=summarize([x for x in chosen if x not in stale])))
    path = HERE/"準備時効率条件が発注時に失効した固定親分類.json"
    assert not path.exists()
    path.write_text(json.dumps(dict(financial_replays=0, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                   groups=groups, rows=rows,
                                   caution="固定親分類。再入場経路と勝ち反例があるため、これをそのまま新戦略成績と扱わない。"),
                               ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(groups, ensure_ascii=False))


if __name__ == "__main__":
    main()
