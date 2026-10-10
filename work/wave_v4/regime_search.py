"""継続方向が崩れた時だけ追跡幅を縮める注文構造を検証する。"""

from dataclasses import asdict
import itertools
import json
import time

import pandas as pd

from engine import Config
from research import OUT, load_data, evaluate, summary, ranked, schedule_for, save_json


def main() -> None:
    """機能: 方向が継続する時は広く、崩れた時は一ATRで追跡する仮説を比較する。

    引数: なし。返り値: なし (None)。参照する回帰とATRは二分前の確定足だけ。
    """
    data, cache = load_data(), {}
    candidates = [Config(family, param, entry, .5, trail, cooldown, trail_basis="regime")
        for family, param, entry, trail, cooldown in itertools.product(range(1,25), (.75, 1.0, 1.25),
            ("signal_limit", "pullback", "trail"), (2.5, 4.0, 6.0), (5, 20, 40))]
    save_json(OUT / "状態別追跡探索計画.json", dict(開始=pd.Timestamp.now(tz="Asia/Tokyo"), 条件数=len(candidates),
        規則="自方向の15分回帰とR2>=.25が継続する時は広く、それ以外は1ATR幅。stopは緩めない。指定日や時刻は不使用。", 条件=[asdict(c) for c in candidates]))
    rows = pd.read_csv(OUT / "統合全条件比較.csv").to_dict("records")
    started = time.monotonic()
    for i, cfg in enumerate(candidates, 1):
        key = cfg.family, cfg.param
        if key not in cache:
            cache[key] = schedule_for(data, cfg)
        trades, targets, cells = evaluate(data, cfg, cache[key])
        rows.append(summary(cfg, trades, targets, cells))
        if i % 250 == 0:
            print(json.dumps(dict(完了=i, 全条件=len(candidates), 秒=round(time.monotonic()-started), 最大合格=max(row["target_pass"] for row in rows)), ensure_ascii=False), flush=True)
    table = ranked(rows)
    table.to_csv(OUT / "最終全条件比較.csv", index=False, encoding="utf-8-sig")
    table.groupby(["family", "reverse"], sort=False).head(1).to_csv(OUT / "最終系統代表比較.csv", index=False, encoding="utf-8-sig")
    for position, row in enumerate(table.head(12).to_dict("records"),1):
        cfg = Config(**{field:row[field] for field in Config.__dataclass_fields__})
        trades, targets, cells = evaluate(data,cfg)
        save_json(OUT/f"候補{position:02d}.json",dict(config=asdict(cfg),summary=row,trades=trades,targets=targets,cells=cells))
    print(table.head(5).to_json(orient="records", force_ascii=False),flush=True)


if __name__ == "__main__":
    main()
