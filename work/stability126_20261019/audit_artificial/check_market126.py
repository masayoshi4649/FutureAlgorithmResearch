"""人工の二市場時計だけで、同時計・未来・古い窓端の混入を検査する。"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys

import numpy as np

from check126 import HERE, ENGINE, OPENED, read_boundary, legacy126


def ready(times, prices, atr):
    """
    機能: 金融・原本と無関係な人工の時計と価格だけを束ねる。
    引数: times/prices(list[float])、atr(float)。
    返り値: dict[str, ndarray]は特徴生成に必要な三列。
    """
    return dict(time_s=np.asarray(times, float), last=np.asarray(prices, float),
                atr=np.full(len(times), atr, dtype=float))


def main():
    """
    機能: 実装に先行する手計算値で二市場の時刻資格を確認する。
    引数: なし。
    返り値: None。所有域へ検証証拠を保存する。
    """
    sys.addaudithook(read_boundary)
    with legacy126.isolated():
        module = importlib.import_module("policy126")
        own_key, peer_key = ("人工", "TOPIX"), ("人工", "NK225")
        own = ready([100, 131, 161, 191, 221, 251, 281], [100, 102, 104, 103, 105, 106, 107], 2.0)
        peer = ready([100, 130, 160, 161, 190, 220, 250, 280], [200, 204, 208, 999, 206, 210, 212, 214], 4.0)
        source = {own_key: own, peer_key: peer}
        value = module.make_market(source)[own_key]
        assert value[0, 11] == 0 and np.isnan(value[0, 1])
        assert value[2, 1] == 208 and value[2, 8] == 160, "同時計一六一の毒値を参照した"
        np.testing.assert_allclose(value[2, [4, 6]], [1, 1], atol=0, rtol=0)
        np.testing.assert_allclose(value[4, [5, 7]], [2.5, 2.5], atol=0, rtol=0)
        assert np.all(value[value[:, 11] == 1, 8] < own["time_s"][value[:, 11] == 1])
        checks = 6
        changed = copy.deepcopy(source)
        changed[peer_key]["last"][3:] = 1000000.0
        other = module.make_market(changed)[own_key]
        np.testing.assert_array_equal(value[:3], other[:3])
        checks += 1
        cut = {own_key:{k:v[:3].copy() for k,v in own.items()}, peer_key:{k:v[:3].copy() for k,v in peer.items()}}
        np.testing.assert_array_equal(value[:3], module.make_market(cut)[own_key])
        checks += 1
        missing = copy.deepcopy(source)
        missing[peer_key]["time_s"] = np.asarray([100, 130, 160, 170, 180, 200, 250, 280], float)
        result = module.make_market(missing)[own_key]
        assert result[4, 11] == 0 and np.isnan(result[4, 1]) and np.isnan(result[4, 6])
        checks += 1
        unknown = copy.deepcopy(source)
        unknown[own_key]["atr"][2] = np.nan
        result = module.make_market(unknown)[own_key]
        assert result[2, 11] == 0 and np.isnan(result[2, 4])
        checks += 1
        boundary = ready([100, 160, 161], [10, 20, 30], 2.0)
        delta, stamps = module.trailing(boundary, 30.0)
        assert delta[1] == 5.0 and stamps[1] == 100.0
        assert np.isnan(delta[2]) and np.isnan(stamps[2])
        checks += 2
        unknown = ready([100, 130, 160], [10, 20, np.nan], 2.0)
        delta, stamps = module.trailing(unknown, 30.0)
        assert np.isnan(delta[2]) and np.isnan(stamps[2])
        checks += 1
        proof = dict(全合格=True, 確認数=checks, 同時計の毒値999を拒否=True,
                     固定期待値={"自己三十秒":1.0,"相手三十秒":1.0,"自己百二十秒":2.5,"相手百二十秒":2.5},
                     将来変更と接頭切断で既知特徴不変=True, 旧窓端の三十秒境界=True,
                     欠測を零へ補完しない=True, 新金融=0, 市場原本読取=0, 実市場配列読取=0,
                     許可小設定読取=OPENED,
                     source_sha256=hashlib.sha256((ENGINE/"policy126.py").read_bytes()).hexdigest())
    path = HERE / "相手厳密過去と窓端の独立純人工監査.json"
    assert not path.exists()
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
