"""保存結果の移植用照合資料を抜き出す。注文核は実行しない。"""
import gzip
import hashlib
import json
import pickle
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "work/visual_pdca129_20261020"))
from features129 import build


def finite_json(value):
    """
    機能: 非有限の特徴だけを null に変換する。
    引数: value(list又は数値)。
    返り値: list又は有限数値又はNone。
    """
    if isinstance(value, list):
        return [finite_json(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main():
    """
    機能: 四商品場の保存入力と保存注文を同値確認へ提供する。
    引数: なし。
    返り値: None。新しい注文・金融成績は算出しない。
    """
    results, refs = [], {}
    gates = np.load(ROOT / "work/stability126_20261019/rearm126/追加十一場のＧ入口許可.npz")
    for scene, symbol, method, folder in [
        ("2026-10-16_Day", "TOPIX", "DV07", "day_round2"),
        ("2026-10-19_Day", "NK225", "DV05", "day_round2"),
        ("2026-09-30_Night", "TOPIX", "NV01", "round1"),
        ("2026-09-23_Night", "NK225", "NV25", "round7"),
    ]:
        packet_path = ROOT / f"work/stability126_20261019/input_audit/attempt2/prepared126/{scene}.pkl"
        order_path = ROOT / f"work/visual_pdca129_20261020/{folder}/measurement/{symbol}_{scene}.npz"
        for path in (packet_path, order_path):
            refs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        packet = pickle.loads(packet_path.read_bytes())
        key = scene, symbol
        ready, q = packet["inputs"][key], packet["quotes"][key]
        n = len(ready["last"])
        columns = np.zeros((n, 3))
        if scene.endswith("_Day"):
            market = packet["markets"][key]
            history = np.full((n, 15), np.nan)
            raw = packet["features"][key]["columns"]
            columns[:, 0] = np.where(gates[symbol+"_"+scene], raw[0], 0)
            columns[:, 1] = np.where(packet["features"][key]["valid"], raw[1], 0)
            columns[:, 2] = raw[2]
        else:
            _, markets, histories, _ = build(packet, "last" if symbol == "TOPIX" else "mid", 0.)
            market, history = markets[key], histories[key]
        rows = np.column_stack((ready["time_s"], ready["last"], q["bid"], q["ask"],
                                q["quote_valid"], ready["atr"], columns, market, history))
        orders = np.load(order_path)[method+"__orders"]
        results.append(dict(session=scene, symbol=symbol, method=method,
                            start=ready["start"], end=ready["limit"], tick=ready["tick"],
                            us_open=ready["us_open"] if np.isfinite(ready["us_open"]) else 0., rows=finite_json(rows.tolist()),
                            orders=orders.tolist()))
        print(scene, symbol, len(rows), len(orders), flush=True)
    payload = dict(scope="保存済み原行と注文の移植同値確認。新金融評価ではない。", references=refs, cases=results)
    with gzip.open(HERE / "selected_orders.json.gz", "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(payload, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
