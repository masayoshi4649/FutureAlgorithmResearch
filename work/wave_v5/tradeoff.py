"""主候補の条件を一つずつ変え、入口と微細な波の負担を測る。"""

from __future__ import annotations

from dataclasses import asdict, replace
import json

import numpy as np
import pandas as pd

from search import OUT, ConfigV5, cell_metrics, evaluate, load_data_v5, ranking_metrics, save_json, schedule_for, simulate_exit


def stress_result(data: dict, cfg: ConfigV5, delay: int, penetration: int) -> tuple[list, list]:
    """機能: 同じ条件の参照を遅らせるか、指値通過を要求して再生する。

    引数: data (dict)、cfg (ConfigV5)、delay/penetration (int)。返り値: 取引とセル (tuple[list,list])。
    """
    schedules = schedule_for(data, cfg)
    all_trades, cells = [], []
    for key, item in data.items():
        prepared = dict(item)
        prepared["positions"] = np.searchsorted((item["z"].index + pd.Timedelta(minutes=2 + delay)).asi8,
                                                item["times"].asi8, side="right") - 1
        trades = simulate_exit(prepared, schedules[key], cfg, limit_penetration_ticks=penetration)
        all_trades.extend(trades)
        cells.append(cell_metrics(trades, *key))
    return all_trades, cells


def main() -> None:
    """機能: 最適な変更を選び直さず、事前列挙した感度をすべて掲載する。

    引数: なし。返り値: なし (None)。現在APIは使わない。
    """
    original = json.loads((OUT / "方向主候補.json").read_text(encoding="utf-8"))
    cfg = ConfigV5(**original["config"])
    data = load_data_v5()
    changes = [("基準", cfg)]
    changes.extend((f"新規方式_{entry}", replace(cfg, entry=entry)) for entry in ("signal_limit", "stop", "pullback", "trail"))
    changes.extend((f"入口幅_{value:g}ATR", replace(cfg, offset=value)) for value in (.25, .5, 1.))
    changes.extend((f"方向確認_{value}分", replace(cfg, confirm=value)) for value in (1, 3, 5))
    changes.extend((f"再新規待機_{value}分", replace(cfg, cooldown=value)) for value in (5, 15, 30, 60))
    changes.extend((f"初動待機_{value}分", replace(cfg, warmup=value)) for value in (15, 45, 60))
    changes.extend((f"信号閾値_{factor:.0%}", replace(cfg, param=cfg.param * factor)) for factor in (.8, 1., 1.2))
    if cfg.exit_mode == "fixed_bracket":
        changes.extend((f"損切り_{value:g}ATR", replace(cfg, stop_loss=value)) for value in (.5, 1., 1.5, 2.5))
        changes.extend((f"利確_{value:g}ATR", replace(cfg, take_profit=value)) for value in (2., 3., 4.))
    else:
        initial_stop = min(2.5, cfg.trail) if cfg.exit_mode == "nativebaseline" else cfg.stop_loss
        changes.extend((f"追跡幅_{value:g}ATR", replace(cfg, exit_mode="small_stop_trail", stop_loss=initial_stop, trail=value))
                       for value in (1.5, 2.5, 4., 6.))
    save_json(OUT / "入口比較計画.json", dict(条件=[dict(name=name, config=asdict(c)) for name, c in changes],
        補助=["追加１分遅延", "追加２分遅延", "指値１ティック通過", "指値２ティック通過"],
        用途="主候補の感度と入口の比較。ここから再選択しない。追跡幅の対照は初期損切り幅を基準と同じに固定する。"))
    rows, details = [], []
    cases = [(name, changed, evaluate(data, changed)) for name, changed in changes]
    cases.extend((name, cfg, stress_result(data, cfg, delay, penetration)) for name, delay, penetration in
                 (("追加１分遅延", 1, 0), ("追加２分遅延", 2, 0), ("指値１ティック通過", 0, 1), ("指値２ティック通過", 0, 2)))
    for name, changed, (trades, cells) in cases:
        details.append(dict(name=name, config=asdict(changed), trades=trades, cells=cells))
        for symbol in ("NK225", "TOPIX"):
            ts = [t for t in trades if t["symbol"] == symbol]
            cs = [c for c in cells if c["symbol"] == symbol]
            rows.append(dict(比較=name, 銘柄=symbol, 件数=len(ts),
                利益=sum(c["profit"] for c in cs), 損失=sum(c["loss"] for c in cs),
                収支=sum(c["net"] for c in cs), 厳格収支=sum(c["stress"] for c in cs),
                利益件数=sum(c["wins"] for c in cs),
                保有時間中央値=float(np.median([t["duration_min"] for t in ts])) if ts else None,
                十五分以内=sum(c["micro15_count"] for c in cs),
                十五分以内収支=sum(c["micro15_net"] for c in cs),
                費用=sum(c["cost"] for c in cs), 最悪セッション=min(c["net"] for c in cs)))
    pd.DataFrame(rows).to_csv(OUT / "入口と微細波比較.csv", index=False, encoding="utf-8-sig")
    save_json(OUT / "入口と微細波明細.json", details)
    print(pd.DataFrame(rows).to_json(orient="records", force_ascii=False))


if __name__ == "__main__":
    main()
