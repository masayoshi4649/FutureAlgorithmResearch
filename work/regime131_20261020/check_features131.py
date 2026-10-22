"""保存原板の未来切断と売買反転で、特徴の因果性・対称性を照合する。"""

import pickle
import numpy as np
from common131 import HERE, ROOT, BASE, read, reference, save
import features131


def restrict(packet, cutoff):
    """
    機能: 両商品の未来原行を取り除いた入力を作る。
    引数: packet(dict)、cutoff(float)は保存入力と切断時刻。
    返り値: dictは切断後の入力。元配列は変更しない。
    """
    out = dict(packet, inputs={}, quotes={})
    for key, value in packet["inputs"].items():
        mask = value["time_s"] <= cutoff
        out["inputs"][key] = {k: v[mask].copy() if isinstance(v, np.ndarray) and len(v) == len(mask)
                             else v for k, v in value.items()}
        out["quotes"][key] = {k: v[mask].copy() for k, v in packet["quotes"][key].items()}
    return out


def mirrored(packet):
    """
    機能: 両商品の価格をそれぞれの中心の上下へ鏡映する。
    引数: packet(dict)は原板入力。
    返り値: dictは気配幅・時刻・ATRを維持した売買反転入力。
    """
    out = dict(packet, inputs={}, quotes={})
    for key, value in packet["inputs"].items():
        center = value["last"][0]
        out["inputs"][key] = dict(value, last=2*center-value["last"])
        q = packet["quotes"][key]
        out["quotes"][key] = dict(q, bid=2*center-q["ask"], ask=2*center-q["bid"])
    return out


def main():
    """
    機能: 代表日中・夜間の未来切断と鏡映を非金融で照合する。
    引数: なし。
    返り値: None。合格指紋と検査件数を保存する。
    """
    cases = []
    for ref in read(BASE / "入力準備.json")["packets"][:2]:
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        original = features131.build(packet)
        cutoff = min(v["start"]+7200. for v in packet["inputs"].values())
        shortened = restrict(packet, cutoff)
        prefix = features131.build(shortened)
        mirror = features131.build(mirrored(packet))
        for key, ready in original[0].items():
            n = len(prefix[0][key]["time_s"])
            for pos in (1, 2, 3):
                assert np.allclose(original[pos][key][:n], prefix[pos][key], equal_nan=True)
            own, reverse = original[2][key], mirror[2][key]
            for col in (6, 7, 10, 11, 13):
                assert np.allclose(own[:,col], -reverse[:,col], equal_nan=True)
            for col in (2, 5, 9, 12, 14):
                assert np.allclose(own[:,col], reverse[:,col], equal_nan=True)
            assert np.array_equal(original[3][key], mirror[3][key])
            cases.append(dict(session=key[0],symbol=key[1],prefix_rows=n,full_rows=len(own)))
    save(HERE / "特徴の未来切断と売買対称.json", dict(passed=True, cases=cases,
         financial_replays=0, sources=[reference(HERE / "features131.py")],
         note="日中と夜間各2商品。未来を切って同時点の特徴を照合。原受信時計の証明ではない。"))
    print("特徴の未来切断・売買対称は合格",flush=True)


if __name__ == "__main__":
    main()
