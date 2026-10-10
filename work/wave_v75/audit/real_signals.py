"""保存29場の共同特徴・全状態・発火・発注候補を別式で全数確認する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from independent_account import save
from model_synthetic import model, oracle_features, oracle_conditions, oracle_pulse, oracle_map, check_features


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load_material() -> tuple[dict, dict, dict, dict]:
    """機能: 固定された保存入力・共通予定時計・参照価格を読み取る。

    引数: なし。返り値: ready/book/sync/meta(tuple[dict,...])。
    """
    meta = json.loads((ROOT / "work/wave_v74/inputs/refmetadata.json").read_text(encoding="utf-8"))
    output = []
    for kind in ("ready", "features"):
        current = {}
        for name in meta["input_paths"][kind]:
            payload = (ROOT / name).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == meta["input_SHA256"][name]
            new = pickle.loads(payload)
            assert not set(current) & set(new)
            current.update(new)
        output.append(current)
    sync = pickle.loads((HERE.parent / "inputs/sync_fresh30.pkl").read_bytes())
    return output[0], output[1], sync, meta


def main() -> None:
    """機能: 全56入口×58口座を独立の窓集計・状態・pulseで照合する。

    引数: --delay(int)。返り値: なし(None)。実売買会計・損益は読み込まない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=int, default=5)
    cli = parser.parse_args()
    delay = cli.delay
    assert delay in (1, 5, 15, 60)
    ready, book, sync, meta = load_material()
    entry_path = HERE.parent / f"prepared/signals_delay{delay}.pkl"
    payload = entry_path.read_bytes()
    entry = pickle.loads(payload)
    counters = json.loads((HERE.parent / f"prepared/入口件数_delay{delay}.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(payload).hexdigest() == counters["signal_SHA256"]
    assert hashlib.sha256((HERE.parent / "signals.py").read_bytes()).hexdigest() == counters["signals_code_SHA256"]
    feature_count = state_count = pulse_count = candidate_count = input_rows = 0
    observed = {}
    for session in sorted(sync):
        grid = sync[session]["grid"]
        for window in (60, 300):
            stats = {}
            for symbol in ("TOPIX", "NK225"):
                key = session, symbol
                assert not np.isinf(book[key]["best_ofi"]).any()
                oracle_input = dict(book[key], tick=ready[key]["tick"])
                expected = oracle_features(grid, delay, window, oracle_input, 30)
                actual = model.features(grid, delay, window, 30, ready[key], book[key])
                check_features(actual, expected)
                stats[symbol] = expected
                feature_count += 1
            for symbol in ("TOPIX", "NK225"):
                peer = "NK225" if symbol == "TOPIX" else "TOPIX"
                key = session, symbol
                oracle_input = dict(book[key], tick=ready[key]["tick"], limit=ready[key]["limit"])
                for level in (0, 1):
                    for paired in (True, False):
                        states, valid = oracle_conditions(stats[symbol], stats[peer], window, level, paired)
                        for family in range(7):
                            ident = f'{"J" if paired else "S"}{family + 1}_W{window}_L{level}'
                            saved = entry[ident][key]
                            np.testing.assert_array_equal(saved["states"], states[family])
                            np.testing.assert_array_equal(saved["valid"], valid)
                            np.testing.assert_array_equal(saved["own_source"], stats[symbol]["now"])
                            np.testing.assert_array_equal(saved["peer_source"], stats[peer]["now"])
                            pulse = oracle_pulse(grid, states[family], valid)
                            np.testing.assert_array_equal(saved["pulse"], pulse)
                            candidates = oracle_map(grid, pulse, stats[symbol], stats[peer], oracle_input)
                            np.testing.assert_array_equal(saved["candidates"], candidates)
                            if len(candidates):
                                g, decision, own_source, peer_source = (candidates[:, column].astype(int) for column in (0, 1, 3, 4))
                                assert np.all(ready[key]["time_s"][own_source] < grid[g] - delay)
                                assert np.all(ready[(session, peer)]["time_s"][peer_source] < grid[g] - delay)
                                assert np.all(ready[key]["time_s"][decision] >= grid[g]) and np.all(ready[key]["time_s"][decision] - grid[g] <= 10.)
                                assert np.all(np.diff(decision) > 0)
                            total = observed.setdefault((ident, symbol), dict(入口=ident, 銘柄=symbol, 候補数=0, 発火数=0, 活動場数=0, 有効状態点数=0))
                            total["候補数"] += len(candidates)
                            total["発火数"] += int(np.count_nonzero(pulse))
                            total["活動場数"] += int(len(candidates) > 0)
                            total["有効状態点数"] += int(valid.sum())
                            state_count += len(grid)
                            pulse_count += int(np.count_nonzero(pulse))
                            candidate_count += len(candidates)
                            input_rows += 1
        print(f"保存共同状態の独立照合完了: {session}", flush=True)
    assert len(entry) == 56 and input_rows == 56 * 58
    for actual in counters["候補会計"]:
        assert actual == observed[(actual["入口"], actual["銘柄"])]
    save(HERE / f"全共同状態と新規pulseの独立監査_delay{delay}.json", dict(合格=True,
        入力候補SHA256=counters["signal_SHA256"], signals_SHA256=counters["signals_code_SHA256"],
        遅延秒=delay, 鮮度上限秒=30, 保存場数=29, 口座数=58, 特徴窓独立照合数=feature_count,
        入口口座比較数=input_rows, 共同状態点比較数=state_count, 発火比較数=pulse_count, 発注候補比較数=candidate_count,
        候補会計=list(observed.values()),
        検査=["同時計先頭の過去参照", "独立の窓切出しOFI比", "resetと不明OFI切断", "百分率価格変化", "両気配の15秒確認", "過去のみ相対平均分散", "七状態", "初回準備済み", "中立60秒再準備", "600秒間隔", "原本行への因果写像", "全入口件数"],
        原本取得=0, API取得=0, 実注文=0, 実損益閲覧=0))
    print(json.dumps(dict(合格=True, 入口口座比較数=input_rows, 共同状態点比較数=state_count, 発注候補比較数=candidate_count), ensure_ascii=False))


if __name__ == "__main__":
    main()
