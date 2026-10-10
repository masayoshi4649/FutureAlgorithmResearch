"""最終候補の費用・遅延・指値接触・近傍条件・含み損を点検する。"""

from dataclasses import replace
import json

import numpy as np
import pandas as pd

from engine import Config, simulate
from research import OUT, SYMBOLS, TICKS, load_data, evaluate_by_symbol, schedule_for, save_json
from targets import target_metrics


def stress_evaluate(data: dict, cfgs: dict, delay: int = 0, penetration: int = 0) -> tuple[list, list]:
    """機能: 入力遅延・指値の通過確認を追加した約定感度を再生する。

    引数: data/cfgs (dict)、delay/penetration (int)。返り値: 取引と指定波評価 (tuple[list,list])。
    """
    trades, targets = [], []
    for symbol, value in cfgs.items():
        cfg = Config(**value)
        schedules = schedule_for(data, cfg)
        for key, source in data.items():
            if key[1] != symbol:
                continue
            item = dict(source)
            if delay:
                item["positions"] = np.searchsorted((item["z"].index + pd.Timedelta(minutes=2+delay)).asi8, item["times"].asi8, side="right") - 1
            result = simulate(item, schedules[key], cfg, limit_penetration_ticks=penetration)
            trades.extend(result)
            targets.extend(target_metrics(item["one"], result, symbol, key[0]))
    return trades, targets


def summarize(trades: list, targets: list, name: str) -> list[dict]:
    """機能: 感度条件を銘柄別の指定波・費用後損益へまとめる。

    引数: trades/targets (list)、name (str)。返り値: 銘柄別結果 (list[dict])。
    """
    rows = []
    for symbol in SYMBOLS:
        subset = [t for t in trades if t["symbol"] == symbol and t["closed"]]
        labels = [t for t in targets if t["symbol"] == symbol]
        rows.append(dict(検算=name, 銘柄=symbol, 件数=len(subset), 指定波合格=sum(t["passed"] for t in labels),
            純損益=sum(t["net_points"] for t in subset), 厳格損益=sum(t["stress_points"] for t in subset),
            利益件数=int(sum(t["net_points"] > 0 for t in subset)),
            最大逆方向保有=max(t["opposite_coverage"] for t in labels)))
    return rows


def trade_risk(data: dict, trades: list) -> list[dict]:
    """機能: 全区間を実際に保有した一分足で順行・逆行幅を確認する。

    引数: data (dict)、trades (list)。返り値: 取引ごとの部分観測リスク (list[dict])。
    新規・返済分の高安は順序不明なので除外し、新規分終値と返済価格だけを加える。
    """
    rows = []
    for trade in trades:
        if not trade["closed"]:
            continue
        one = data[(trade["session"], trade["symbol"])]["one"]
        inside = one[(one.index > trade["entry_time"]) & (one.index < trade["exit_time"])]
        prices = np.r_[trade["entry_price"], inside.low, inside.high, trade["exit_price"]]
        if trade["exit_time"] > trade["entry_time"]:
            prices = np.r_[prices, one.loc[trade["entry_time"], "close"]]
        moves = trade["side"] * (prices - trade["entry_price"])
        rows.append(dict(**trade, observed_mae=float(max(0, -moves.min())), observed_mfe=float(max(0, moves.max())),
                         observed_mae_atr=float(max(0, -moves.min())/trade["atr"])))
    return rows


def main() -> None:
    """機能: 保存済みの採用条件を変更せず近傍と約定の診断を保存する。

    引数: なし。返り値: なし (None)。現在APIを呼ばず、診断結果で選び直さない。
    """
    fixed = json.loads((OUT / "固定設定.json").read_text(encoding="utf-8"))
    cfgs, data = fixed["symbol_configs"], load_data()
    trades, targets, cells = evaluate_by_symbol(data, cfgs)
    save_json(OUT / "採用_開発結果.json", dict(symbol_configs=cfgs, trades=trades, targets=targets, cells=cells))
    risk = trade_risk(data, trades)
    save_json(OUT / "採用_取引リスク.json", risk)
    pd.DataFrame(risk).to_csv(OUT / "採用_取引リスク.csv", index=False, encoding="utf-8-sig")
    rows = summarize(trades, targets, "基準")
    for delay, penetration, name in ((1,0,"追加１分遅延"),(2,0,"追加２分遅延"),(0,1,"指値１ティック通過"),(0,2,"指値２ティック通過")):
        ts, labels = stress_evaluate(data, cfgs, delay, penetration)
        rows.extend(summarize(ts,labels,name))
    for field, factor, name in (("param",.9,"信号閾値90%"),("param",1.1,"信号閾値110%"),("offset",.8,"新規幅80%"),
                                ("offset",1.2,"新規幅120%"),("trail",.8,"追跡幅80%"),("trail",1.2,"追跡幅120%")):
        modified = {symbol:{**values,field:values[field]*factor} for symbol,values in cfgs.items()}
        ts, labels, unused = evaluate_by_symbol(data,modified)
        rows.extend(summarize(ts,labels,name))
    save_json(OUT/"採用_感度.json",rows)
    pd.DataFrame(rows).to_csv(OUT/"採用_感度.csv",index=False,encoding="utf-8-sig")
    print(json.dumps(dict(取引数=len(trades), 指定波合格=sum(t["passed"] for t in targets), 感度=rows),ensure_ascii=False))


if __name__ == "__main__":
    main()
