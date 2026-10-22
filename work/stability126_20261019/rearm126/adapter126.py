"""凍結済み原Ｅ０１へ既知のＧ入口とＵ予定回避だけを費用零で再接続する。"""

import ast
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ENGINE = WORK/"engine"
_PLAY = {}


def catalog():
    """
    機能: 過去に固定されたＧとＧＵの二対照だけを返す。
    引数: なし。
    返り値: list[dict]は今回の新しい閾値探索を含まない二条件。
    """
    return [dict(id="E01_G", mask=1, time_mode="", name="両市場の開始条件を入口で再確認"),
            dict(id="E01_G_U", mask=1, time_mode="U", name="開始条件の再確認と米国寄付き前後静観")]


def zero_fee_play(runtime):
    """
    機能: 同ｂｙｔｅｓ旧ｐｌａｙへ費用列を零にする一文だけを追加する。
    引数: runtime(dict)は所有コピーの旧数値接続。
    返り値: callableは旧原版と同じ引数・全返却配列を持つ関数。
    """
    old = runtime["old"]
    if id(old) in _PLAY:
        return _PLAY[id(old)]
    path = ENGINE/"legacy_root/work/wave_v85/strategy.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    function = next(v for v in tree.body if isinstance(v, ast.FunctionDef) and v.name == "play")
    positions = [i for i, node in enumerate(function.body) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "losspar" for target in node.targets)]
    assert len(positions) == 1
    function.body.insert(positions[0]+1, ast.parse("losspar[12] = 0.").body[0])
    namespace = dict(vars(old))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(path), "exec"), namespace)
    _PLAY[id(old)] = namespace["play"]
    return _PLAY[id(old)]


def make_gate(runtime, packet, consumer_root):
    """
    機能: 旧の確定足指標・公開対応・開始条件をそのまま用いてＧだけを再構成する。
    引数: runtime/packet(dict)、consumer_root(Path)は所有一分足を含む参照根。
    返り値: dict[tuple,dict]は元の十列を維持しｇａｔｅを追加した特徴。
    """
    import policy126
    policy126.bind_runtime(runtime, packet["inputs"], packet["signals"])
    gate = runtime["old"].base.gate
    consumer_root = Path(consumer_root).resolve()
    gate.replay.entry.set_root(consumer_root)
    assert gate.replay.entry.HIERARCHY.LEGACY.ROOT == consumer_root
    models = {key:gate.model(ready) for key, ready in packet["inputs"].items()}
    features = {}
    for key, ready in packet["inputs"].items():
        feature = dict(packet["features"][key])
        own, peer = gate.expanded(key, models, ready["time_s"])
        feature["gate"] = gate.gate_mask(dict(kind="rearm"), feature["columns"][0], own, peer)
        assert feature["gate"].shape == ready["last"].shape
        features[key] = feature
    return features


def play(runtime, config, ready, feature):
    """
    機能: 既知Ｇ又はＧＵを元の通常影・出口影・枠会計で費用零運転する。
    引数: runtime/config/ready/feature(dict)は凍結数値源と一商品の当時入力。
    返り値: tuple[dict,dict]は旧原版と同じ経済配列及び固定設定。
    """
    assert config["id"] in ("E01_G", "E01_G_U") and config["mask"] == 1
    assert config["time_mode"] == ("U" if config["id"].endswith("_U") else "")
    return zero_fee_play(runtime)(config, ready, feature, observed=True)
