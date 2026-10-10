"""実保存経路の収束再開を、区間極値と過去気配の別計算で検査する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from causality import study
from independent_account import save


HERE = Path(__file__).resolve().parent


def first_release(times: np.ndarray, bids: np.ndarray, asks: np.ndarray, quality: np.ndarray, reset: np.ndarray,
                  direct: np.ndarray, lag30: np.ndarray, began: int, stop: int, width: float, tick: float, mode: int) -> int | None:
    """機能: 観測品質と方向の連続区間ごとに、最初の収束成立行を独立に求める。

    引数: 各観測列(np.ndarray)、began/stop/mode(int)、width/tick(float)。
    返り値: 最初成立行(int)又は不成立(None)。ゼロ方向・品質切断で区間を分断する。
    """
    indices = np.arange(began, stop)
    d = direct[began:stop]
    good = quality[began:stop] & ~reset[began:stop] & (d != 0)
    if not len(indices):
        return None
    boundaries = np.r_[0, np.flatnonzero((good[1:] != good[:-1]) | ((d[1:] != d[:-1]) & good[1:])) + 1, len(indices)]
    wait = 600. if mode == 4 else 0.
    for left, right in zip(boundaries[:-1], boundaries[1:]):
        if not good[left]:
            continue
        group = indices[left:right]
        side = int(d[left])
        mid = (bids[group] + asks[group]) / 2.
        extreme = np.minimum.accumulate(mid) if side == 1 else np.maximum.accumulate(mid)
        updates = np.r_[True, side * np.diff(extreme) < -tick * 1.e-8]
        update_rows = np.maximum.accumulate(np.where(updates, np.arange(len(group)), 0))
        adverse_time = times[group[update_rows]]
        lag = lag30[group]
        before = np.maximum(lag, 0)
        returned = (lag >= 0) & (side * (bids[group] - bids[before]) >= tick - tick * 1.e-8) & (side * (asks[group] - asks[before]) >= tick - tick * 1.e-8)
        success = (times[group] >= times[began] + wait) & (times[group] - adverse_time >= 30.) & (side * (mid - extreme) >= width - tick * 1.e-8) & returned
        arrived = np.flatnonzero(success)
        if len(arrived):
            return int(group[arrived[0]])
    return None


def main() -> None:
    """機能: 全収束方式の再開／未再開を、最初成立行まで照合して保存する。

    引数: --extension(bool)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--extension", action="store_true")
    cli = parser.parse_args()
    area = HERE.parent / "extension" if cli.extension else HERE.parent
    fixed = study.load(area / ("追記固定.json" if cli.extension else "事前固定.json"))
    ready, features, meta = study.material()
    prepared = study.prepare(ready, features, meta)
    conditions = [c for c in fixed["条件"] if c["pause_mode"] in (3, 4)]
    checked = resumed = ongoing = 0
    for c in conditions:
        ledgers = study.load(area / "ledgers" / (c["id"] + ".pkl"))
        for key, ledger in ledgers.items():
            r, f, p = ready[key], features[key], prepared[key]
            pauses = ledger["pauses"]
            starts = list(pauses[pauses[:, 1] == 0, 0].astype(int))
            ends = list(pauses[pauses[:, 1] == 1, 0].astype(int))
            direct = p["direction"][(c["reference"], c["band"])]
            width = max(1., np.ceil(p["open_price"] * c["entry_fraction"] / r["tick"] - 1.e-10)) * r["tick"]
            for index, began in enumerate(starts):
                ended = ends[index] if index < len(ends) else None
                stop = ended + 1 if ended is not None else len(r["time_s"])
                found = first_release(r["time_s"], f["bid"], f["ask"], p["quality"], f["reset"], direct, p["lag30"], began, stop, width, r["tick"], c["pause_mode"])
                assert found == ended, ("最初の収束再開行", c["id"], key, began, ended, found)
                checked += 1
                resumed += int(ended is not None)
                ongoing += int(ended is None)
    output_name = "追加収束方式の最初再開行独立監査.json" if cli.extension else "全収束方式の最初再開行独立監査.json"
    save(HERE / output_name, dict(合格=True, 条件数=len(conditions), 口座数=len(conditions) * len(ready),
        収束待機数=checked, 再開数=resumed, 終端まで未再開数=ongoing,
        検査="品質と方向の連続区間を分離し、逆行極値の初回更新時計、30秒未更新、始値比反発幅、両気配1呼値進行、10分併用の全条件を別の区間計算で照合。最初成立行が記録再開行と一致。",
        engine_SHA256=study.digest(HERE.parent / "engine.py"), 原本取得=0, API取得=0, 実注文=0))
    print(json.dumps(dict(合格=True, 条件数=len(conditions), 待機数=checked, 再開数=resumed), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
