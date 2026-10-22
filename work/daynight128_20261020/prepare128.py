"""既知四十三場の通知と因果特徴を準備する。新金融再生は行わない。"""

import pickle
import numpy as np
from common128 import HERE, ROOT, OLD, packets, read, save, reference, sha
from features128 import build


def q_feed(paper, ready, quotes):
    """
    機能: 保存Ｇ入口を旧Ｑと同じ判断行気配条件で抽出する。
    引数: paper/ready/quotes(dict)は既存紙上注文、初回尺度、当時気配。
    返り値: ndarrayは旧ＧＱと同一の十列通知。
    """
    atrs = {int(v[0]):v[5] for v in paper["cycles"]}
    feed = np.zeros((len(paper["orders"]),10))
    feed[:,:8] = paper["orders"]
    permit, keep = {}, []
    for i, order in enumerate(feed):
        row, parent = int(order[0]), int(order[2])
        if order[7] == 1.:
            a = atrs[parent]
            order[9] = a
            bid, ask, last = quotes["bid"][row],quotes["ask"][row],ready["last"][row]
            normal = quotes["quote_valid"][row] and np.isfinite([bid,ask,last,a]).all()
            normal = normal and 0 < bid < ask and a > 0 and last > 0
            adverse = ask-last if order[3] > 0 else last-bid
            permit[parent] = normal and ask-bid <= .5*a and adverse <= .5*a
        if permit[parent]:
            keep.append(i)
    return feed[keep]


def main():
    """
    機能: 入力指紋を確認し、原行の対応を保った追加特徴と旧入口を新保存する。
    引数: なし。
    返り値: None。注文生成・価格再生・成績選択は行わない。
    """
    fixed = read(OLD/"gated_bbo126/固定計画.json")
    old_cache = ROOT/fixed["gated_cache"]["path"]
    assert sha(old_cache) == fixed["gated_cache"]["sha256"]
    archive = np.load(old_cache,allow_pickle=False)
    rows = []
    for ref in packets():
        path = ROOT/ref["path"]
        assert sha(path) == ref["sha256"]
        packet = pickle.loads(path.read_bytes())
        histories = build(packet)
        scene = ref["session"]
        values = {}
        for symbol in ("TOPIX","NK225"):
            key = scene,symbol
            ready, quote = packet["inputs"][key],packet["quotes"][key]
            np.testing.assert_array_equal(ready["seq"],quote["seq"])
            np.testing.assert_array_equal(ready["time_s"],quote["time_s"])
            assert (np.diff(ready["seq"]) > 0).all()
            assert (np.diff(ready["time_s"]) >= 0).all()
            assert ready["time_s"][-1] > ready["limit"]
            values[symbol+"__history"] = histories[key]
            if scene.endswith("_Day"):
                if scene == "2026-10-20_Day":
                    new_path = OLD/"update_20261020/measurement"/("Last_"+symbol+"_"+scene+".npz")
                    with np.load(new_path,allow_pickle=False) as data:
                        paper = {f:data["E01_G__"+f] for f in ("orders","cycles")}
                else:
                    prefix = "G_"+symbol+"_"+scene+"__"
                    paper = {f:archive[prefix+f] for f in ("orders","cycles")}
                values[symbol+"__feed"] = q_feed(paper,ready,quote)
        target = HERE/"prepared"/(scene+".npz")
        target.parent.mkdir(exist_ok=True)
        assert not target.exists()
        np.savez_compressed(target,**values)
        rows.append(dict(**ref,features=reference(target)))
        print(scene,flush=True)
    save(HERE/"入力準備.json",dict(passed=True,packets=rows,sources=[reference(Path(__file__)),
        reference(HERE/"features128.py")],paper_source=reference(old_cache),financial_replays=0,
        scope="同じ既知43場。旧原行・旧公開ATR・原気配を変更せず、当場だけの遅延公開履歴を追加。"))


if __name__ == "__main__":
    from pathlib import Path
    main()
