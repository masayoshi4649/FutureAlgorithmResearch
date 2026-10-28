"""trainで尺度を固定した板指標の24入口。第一巡の定数を上書きしない。"""

import json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
STRUCTURES = (
    ("BF", "OFI単独", "表示数量の増減だけから方向を決める"),
    ("BD", "距離板単独", "価格からの距離を重み付けした数量偏りだけから方向を決める"),
    ("BR", "優勢補充単独", "同じ最良価格で増えた数量が反対側より多い方向へ入る"),
    ("BA", "OFIと価格受容", "注文増減の方向に価格が逆行していないことを確認する"),
    ("BP", "補充と価格受容", "補充の優位と、価格が崩れず直近が反対へ進まないことを確認する"),
    ("BC", "OFIと距離板", "注文増減と現在の距離加重数量偏りの一致を確認する"),
    ("BS", "逆OFIと反発", "逆方向の増減でも価格が崩れず、直近5秒が反発した時に入る"),
    ("BU", "吸収代理の二経路", "逆OFI又は優勢補充のどちらかがあり、価格保持と反発を確認する"),
)


def candidates():
    """8構造と3分位による24条件を列挙する。

    引数: なし。返り値: list[dict]。
    """
    return [dict(id=f"{key}{level:02d}", family=key, name=name, description=description,
                 kind="manual", quantile=str(q))
            for key, name, description in STRUCTURES for level, q in enumerate((.5, .75, .9), 1)]


def load_thresholds():
    """事前固定済みのtrain分位を読む。

    引数: なし。返り値: dict。結果に応じた更新を行わない。
    """
    thresholds = json.loads((HERE / "thresholds161r2.json").read_text(encoding="utf-8"))["thresholds"]
    for columns in thresholds.values():
        for record in columns.values():
            if any(not np.isfinite(value) or value <= 0 for value in record["quantiles"].values()):
                raise ValueError("分位閾値は有限の正値である必要があります")
    return thresholds


def signal(features, candidate, side, phase, thresholds):
    """板の分解・組合せを当時の特徴だけで判定する。

    引数: features(dict[str,ndarray])、candidate(dict)、side(int)、phase(str)、thresholds(dict)。
    返り値: ndarray[bool]。逆OFIと同側補充を全候補の必須ANDにしない。
    """
    f, q = features, candidate["quantile"]
    cut = thresholds[phase]
    flow_threshold = cut["ofi15"]["quantiles"][q]
    depth_threshold = cut["depth_imb"]["quantiles"][q]
    refill_name = "bid_refill15" if side == 1 else "ask_refill15"
    opposite_name = "ask_refill15" if side == 1 else "bid_refill15"
    refill_threshold = cut[refill_name]["quantiles"][q]
    own_refill, opposite_refill = f[refill_name], f[opposite_name]
    flow = side * f["ofi15"] >= flow_threshold
    depth = side * f["depth_imb"] >= depth_threshold
    refill = (own_refill >= refill_threshold) & (own_refill > opposite_refill)
    adverse = side * f["ofi15"] <= -flow_threshold
    accepted = (side * f["ret15_pt"] >= 0) & (side * f["ret5_pt"] >= 0)
    held = (side * f["ret15_pt"] >= -10) & (side * f["ret5_pt"] >= 0)
    rebound = (side * f["ret15_pt"] >= -10) & (side * f["ret5_pt"] >= 10)
    rules = {"BF": flow, "BD": depth, "BR": refill, "BA": flow & accepted,
             "BP": refill & held, "BC": flow & depth, "BS": adverse & rebound,
             "BU": (adverse | refill) & rebound}
    valid = (f["spread"] > 0) & (f["spread"] <= 20)
    return valid & rules[candidate["family"]]
