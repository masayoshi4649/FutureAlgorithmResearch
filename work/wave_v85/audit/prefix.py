"""共同信号の厳密過去写像と、実影を再生成した途中切断不変を確認する。"""

import hashlib
import argparse
import json
from pathlib import Path
import numpy as np

from original import module, HERE, WORK, ROOT


def clip(value, count, length):
    """
    機能: 原本行と同じ長さの配列だけを再帰的に切断する。
    引数: value (object)、count/length (int)。
    返り値: object の独立コピー。
    """
    if isinstance(value, dict):
        return {k: clip(v, count, length) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(clip(v, count, length) for v in value)
    if isinstance(value, np.ndarray):
        return value[:count].copy() if value.ndim and len(value) == length else value.copy()
    return value


def compare(a, b, count):
    """
    機能: 過去の注文・制御・影計画を全列一致で点検する。
    引数: a/b (dict)、count (int)。
    返り値: int の比較配列数。
    """
    checks = 0
    event_columns = dict(orders=0, trades=7, cycles=2, prepare_events=1, entry_preparations=1,
        slot_events=0, adjustment_events=0, budget_events=0, branch_events=0, risk_events=0,
        guard_events=0, block_events=0, time_events=0)
    curves = ("curve", "atr_curve", "control_curve", "slot_curve", "branch_curve", "guard_curve", "plans", "execution_plans")
    for left, right in ((a, b), (a["shadow"], b["shadow"])):
        for name, col in event_columns.items():
            if name in left:
                x, y = left[name], right[name]
                np.testing.assert_array_equal(x[x[:, col] < count], y[y[:, col] < count], err_msg=name)
                checks += 1
        for name in curves:
            if name in left:
                np.testing.assert_array_equal(left[name][:count], right[name][:count], err_msg=name)
                checks += 1
    return checks


def signals_boundary(strategy):
    """
    機能: 厳密過去と30秒・180秒の境界を、原本とは独立した小列で試す。
    引数: strategy (module)。
    返り値: list[dict] の検査結果。
    """
    keys = ("試験", "TOPIX"), ("試験", "NK225")
    inputs = {keys[0]: dict(time_s=np.array([100., 100., 101., 130., 131.])),
              keys[1]: dict(time_s=np.array([99., 99., 100., 101., 130.]))}
    features = {
        keys[0]: dict(columns=(None, np.array([-1, -1, 1, 1, 1]), np.array([0, 0, 2, 0, 0])), valid=np.ones(5, bool)),
        keys[1]: dict(columns=(None, np.array([1, -1, 1, 1, 1]), np.array([0, 1, 2, 3, 4])), valid=np.ones(5, bool))}
    joint = strategy.joint_features(keys[0], inputs, features)
    np.testing.assert_array_equal(joint["peer_row"], [1, 1, 2, 3, 4])
    np.testing.assert_array_equal(joint["direction"], [-1, -1, 1, 1, 0])
    assert joint["valid"][3] and not joint["valid"][4]
    records = [dict(検査="相手同時計後続を除外し直前時計の既読末尾を参照、30秒丁度は許可31秒は不可", 合格=True)]
    original = strategy.base.gate.expanded
    targets = np.array([100., 100., 101., 280., 281.])
    fake = dict(gap=np.ones(5), slow=np.ones(5), release=np.full(5, 100.))
    try:
        strategy.base.gate.expanded = lambda key, models, stamps: (fake, fake)
        state, own, peer, valid = strategy.ema_features(keys[0], dict(time_s=targets, last=np.ones(5)), {})
        np.testing.assert_array_equal(valid, [True, True, True, True, False])
        np.testing.assert_array_equal(own, [0, 0, 0, 0, -1])
        assert state.tolist() == [1] * 5
        records.append(dict(検査="EMA公開同時計は自己時計の先頭行へ対応、180秒丁度有効181秒は解除に使わない", 合格=True))
    finally:
        strategy.base.gate.expanded = original
    return records


def main():
    """
    機能: 固定統合版の原本を途中で切り、現在以後を見ない注文再生成を確認する。
    引数: なし。
    返り値: None。損益総額は表示・選抜しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--time-mode", default="")
    args = parser.parse_args()
    prepare = module("wave85_audit_prepare", WORK / "prepare.py")
    strategy = module("wave85_strategy", WORK / "strategy.py")
    import numba
    numba.config.CACHE_DIR = str(HERE / "cache")
    boundaries = signals_boundary(strategy)
    inputs, signals, _ = prepare.load_inputs()
    features = strategy.initialize(inputs, signals)
    keys = [("2026-10-05_Day", "TOPIX"), ("2026-10-09_Night", "NK225")]
    records = []
    checks = 0
    for key in keys:
        ready = inputs[key]
        feature = features[key]
        n = len(ready["last"])
        peer_key = key[0], "NK225" if key[1] == "TOPIX" else "TOPIX"
        for observed in (False, True):
            config = dict(mask=15, time_mode=args.time_mode)
            full, _ = strategy.play(config, ready, feature, observed=observed)
            cuts = {int(n * f) for f in (.23, .57, .89)}
            for name in ("guard_events", "block_events", "risk_events", "adjustment_events", "time_events"):
                for event in full[name][:4]:
                    i = int(event[0])
                    cuts.update((max(2, i), min(n - 1, i + 1), min(n - 1, i + 2)))
            for count in sorted(cuts):
                current = clip(ready, count, n)
                own_f = clip(feature, count, n)
                peer = inputs[peer_key]
                peer_count = int(np.searchsorted(peer["time_s"], current["time_s"][-1], side="right"))
                pair_inputs = {key: current, peer_key: clip(peer, peer_count, len(peer["last"]))}
                pair_features = {key: own_f, peer_key: clip(features[peer_key], peer_count, len(peer["last"]))}
                recomputed = strategy.joint_features(key, pair_inputs, pair_features)
                for name in feature["joint"]:
                    np.testing.assert_array_equal(recomputed[name], feature["joint"][name][:count])
                own_f["joint"] = recomputed
                part, _ = strategy.play(config, current, own_f, observed=observed)
                checks += compare(full, part, count)
            records.append(dict(セッション=key[0], 銘柄=key[1], 観測価格=observed, 切断数=len(cuts),
                切断行=sorted(cuts), Pイベント数=len(full["guard_events"]), Cイベント数=len(full["block_events"]),
                時間イベント数=len(full["time_events"]), 時間帯=args.time_mode,
                実影再生成一致=True, 相手も切断した共同特徴一致=True))
            print(key, "観測" if observed else "指定", len(cuts), "切断一致", flush=True)
    result = dict(全合格=True, 信号境界=boundaries, 検査=records, 切断数=sum(r["切断数"] for r in records),
        配列照合数=checks, 実装SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (WORK / "engine.py", WORK / "strategy.py", WORK / "catalog.py", Path(__file__))},
        制約="公開済み元信号から注文までの監査。基礎信号の原本切断は準備時の別検査。保存時計の因果性であり真の受信時刻は復元しない。",
        新損益による候補選抜=False)
    filename = "時間帯あり統合版の未来切断.json" if args.time_mode else "共同信号境界と統合版の未来切断.json"
    (HERE / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(全合格=True, 切断数=result["切断数"], 配列照合数=checks), ensure_ascii=False))


if __name__ == "__main__":
    main()
