"""固定幅の問題を検証する追加探索。追跡幅の現在ATR更新と新規確認を比較する。"""

from dataclasses import asdict
import itertools
import json
import time

import pandas as pd

from engine import Config
from research import OUT, load_data, evaluate, summary, ranked, schedule_for, save_json


def configs() -> list[Config]:
    """機能: 現在ATRで追跡する追加条件と、新規指値幅の比較条件を列挙する。

    引数: なし。返り値: 追加比較条件 (list[Config])。
    """
    result = []
    for family, param, entry, trail, cooldown, confirm in itertools.product(range(1, 25), (.75, 1.0, 1.25),
            ("signal_limit", "stop", "pullback", "trail"), (2.0, 3.0, 4.0), (10, 30), (1, 3)):
        result.append(Config(family, param, entry, .5, trail, cooldown, confirm=confirm, trail_basis="current"))
    for family, param, entry, offset, trail, cooldown in itertools.product((1, 3, 4, 7, 10, 14, 18, 23), (.75, 1.0, 1.25),
            ("pullback", "trail"), (.25, 1.0), (2.0, 3.0, 4.0), (10, 30)):
        result.append(Config(family, param, entry, offset, trail, cooldown, trail_basis="current"))
    return result


def main() -> None:
    """機能: 追加仮説を同じ厳格な六波基準で比較し、旧条件を含む順位表を作る。

    引数: なし。返り値: なし (None)。現在セッションには接続しない。
    """
    data, cache = load_data(), {}
    candidates = configs()
    save_json(OUT / "追加探索計画.json", dict(開始=pd.Timestamp.now(tz="Asia/Tokyo"), 条件数=len(candidates),
        理由="新規時のATR固定はセッション初期の大値幅を引きずる。現在ATRへ更新しつつstopを緩めない方式を比較。", 条件=[asdict(c) for c in candidates]))
    base = pd.read_csv(OUT / "全条件比較.csv")
    base["trail_basis"] = "entry"
    base["config"] = base.config.astype(str) + "_entry"
    rows = base.to_dict("records")
    started = time.monotonic()
    for i, cfg in enumerate(candidates, 1):
        key = cfg.family, cfg.param
        if key not in cache:
            cache[key] = schedule_for(data, cfg)
        trades, targets, cells = evaluate(data, cfg, cache[key])
        rows.append(summary(cfg, trades, targets, cells))
        if i % 250 == 0:
            pd.DataFrame(rows[len(base):]).to_csv(OUT / "追加探索途中.csv", index=False, encoding="utf-8-sig")
            print(json.dumps(dict(完了=i, 全条件=len(candidates), 秒=round(time.monotonic()-started), 最大合格=max(row["target_pass"] for row in rows)), ensure_ascii=False), flush=True)
    table = ranked(rows)
    table.to_csv(OUT / "統合全条件比較.csv", index=False, encoding="utf-8-sig")
    table.groupby(["family", "reverse"], sort=False).head(1).to_csv(OUT / "統合系統代表比較.csv", index=False, encoding="utf-8-sig")
    for position, row in enumerate(table.head(12).to_dict("records"), 1):
        cfg = Config(**{field: row[field] for field in Config.__dataclass_fields__})
        trades, targets, cells = evaluate(data, cfg)
        save_json(OUT / f"候補{position:02d}.json", dict(config=asdict(cfg), summary=row, trades=trades, targets=targets, cells=cells))
    print(table.head(5).to_json(orient="records", force_ascii=False), flush=True)


if __name__ == "__main__":
    main()
