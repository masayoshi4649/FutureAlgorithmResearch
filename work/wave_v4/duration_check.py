"""保存データの同じ信号を複数の評価期間で比較する独立診断。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research import load_data, save_json
from signals import FAMILIES, get_signals


OUT = Path(__file__).resolve().parent
HORIZONS = (10, 20, 40, 60, 120)


def event_returns(data: dict, family: int, param: float, warmup: int = 14) -> list[dict]:
    """機能: 因果的に間引いた共通イベントの各評価期間の方向損益を作る。

    引数: data (dict) は保存セッションの再生入力、family (int) は信号系統、
        param (float) は信号感度、warmup (int) は新規参照を許す開始後の分数。
    返り値: 全評価期間の価格が同セッションで観測できたイベント損益 (list[dict])。
    """
    records = []
    for key, item in data.items():
        session, symbol = key
        peer = data[(session, "TOPIX" if symbol == "NK225" else "NK225")]["z"]
        z, one = item["z"], item["one"]
        signals = get_signals(z, peer, family, param)
        times = one.index
        last_entry = None
        for stamp, direction in signals.items():
            if direction == 0:
                continue
            intended_entry = stamp + pd.Timedelta(minutes=2)
            if (intended_entry - z.index[0]).total_seconds() / 60 < warmup:
                continue
            entry_position = times.searchsorted(intended_entry)
            if entry_position >= len(times):
                continue
            entry_time = times[entry_position]
            if last_entry is not None and entry_time < last_entry + pd.Timedelta(minutes=30):
                continue
            if entry_time + pd.Timedelta(minutes=max(HORIZONS)) > item["limit"]:
                continue
            targets = [entry_time + pd.Timedelta(minutes=period) for period in HORIZONS]
            exits = [times.searchsorted(target) for target in targets]
            if any(position >= len(times) or times[position] > item["limit"] for position in exits):
                continue
            atr = float(z.loc[stamp, "atr"])
            if not np.isfinite(atr) or atr <= 0:
                continue
            last_entry = entry_time
            entry_price = float(one.open.iloc[entry_position])
            event_id = f"{family}_{param:g}_{warmup}_{session}_{symbol}_{entry_time.isoformat()}"
            for period, target, position in zip(HORIZONS, targets, exits):
                exit_price = float(one.open.iloc[position])
                gross = int(direction) * (exit_price - entry_price)
                net = gross - 2 * item["tick"]
                records.append(dict(
                    event_id=event_id, family=family, param=param, warmup=warmup,
                    name=FAMILIES[family], symbol=symbol, session=session,
                    signal_time=stamp + pd.Timedelta(minutes=1), entry_time=entry_time,
                    entry_price=entry_price, side=int(direction), atr=atr, horizon_min=period,
                    exit_time=times[position], exit_price=exit_price,
                    actual_duration_min=(times[position] - entry_time).total_seconds() / 60,
                    extra_exit_wait_min=(times[position] - target).total_seconds() / 60,
                    extra_entry_wait_min=(entry_time - intended_entry).total_seconds() / 60,
                    gross_points=gross, net_points=net, net_atr=net / atr, gross_correct=gross > 0, correct=net > 0,
                ))
    return records


def aggregate(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """機能: 期間比較を同じイベント集合の利益率と ATR 単位で要約する。

    引数: frame (DataFrame) はイベント損益、keys (list[str]) は期間以外の集計区分。
    返り値: 件数・費用後利益率・損益分布の表 (DataFrame)。
    """
    return frame.groupby(keys + ["horizon_min"], dropna=False, sort=True).agg(
        count=("event_id", "count"), wins=("correct", "sum"), win_rate=("correct", "mean"),
        gross_win_rate=("gross_correct", "mean"),
        median_net_atr=("net_atr", "median"), mean_net_atr=("net_atr", "mean"),
        mean_net_points=("net_points", "mean"), median_net_points=("net_points", "median"),
        max_extra_exit_wait_min=("extra_exit_wait_min", "max"),
    ).reset_index()


def run() -> None:
    """機能: 24系統の共通イベントで評価期間を比較し、採用信号を別掲する。

    引数: なし。
    返り値: なし (None)。独立診断の表と日本語レポートを作り、選定条件は変更しない。
    """
    fixed = json.loads((OUT / "固定設定.json").read_text(encoding="utf-8"))
    for name, expected in fixed["code_sha256"].items():
        if hashlib.sha256((OUT / name).read_bytes()).hexdigest() != expected:
            raise AssertionError("凍結コードが一致しません。" + name)
    data = load_data()
    rows = []
    for family in FAMILIES:
        rows.extend(event_returns(data, family, 1.0))
    frame = pd.DataFrame(rows)
    selected = pd.DataFrame(event_returns(data, 1, 0.75, 60))
    for values in (frame, selected):
        if not values.groupby("event_id").horizon_min.agg(tuple).map(lambda value: value == HORIZONS).all():
            raise AssertionError("評価期間のイベント集合が一致しません。")
        if values.groupby(["family", "symbol", "session", "entry_time"]).size().max() != len(HORIZONS):
            raise AssertionError("同じ参照新規の重複があります。")
    family_summary = aggregate(frame, ["family", "name", "param", "warmup", "symbol"])
    pooled = aggregate(frame, ["symbol"])
    cell_summary = aggregate(frame, ["family", "symbol", "session"])
    selected_summary = aggregate(selected, ["family", "param", "warmup", "symbol"])
    summaries = pd.concat([family_summary.assign(scope="系統別"), pooled.assign(scope="24系統の延べ集計"), selected_summary.assign(scope="採用信号の別掲")], ignore_index=True)
    summaries.to_csv(OUT / "継続時間比較.csv", index=False, encoding="utf-8-sig")
    cell_summary.to_csv(OUT / "継続時間比較_セッション別.csv", index=False, encoding="utf-8-sig")
    pd.concat([frame.assign(scope="標準24系統"), selected.assign(scope="採用信号")]).to_csv(OUT / "継続時間比較_イベント.csv", index=False, encoding="utf-8-sig")

    # ----------------------------------------
    patterns = []
    for symbol in ("NK225", "TOPIX"):
        wide = family_summary[family_summary.symbol.eq(symbol)].pivot(index="family", columns="horizon_min", values="win_rate")
        patterns.append(dict(
            symbol=symbol, family_count=len(wide),
            monotonically_nondecreasing=int(wide.diff(axis=1).iloc[:, 1:].ge(0).all(axis=1).sum()),
            higher_120_than_10=int((wide[120] > wide[10]).sum()),
            lower_120_than_10=int((wide[120] < wide[10]).sum()),
            tied_120_and_10=int((wide[120] == wide[10]).sum()),
            best_horizon_counts={str(int(period)): int(count) for period, count in wide.idxmax(axis=1).value_counts().items()},
        ))
    save_json(OUT / "継続時間比較.json", dict(
        horizons=HORIZONS, data_sessions=sorted({key[0] for key in data}),
        family_patterns=patterns, pooled=pooled.to_dict("records"), selected=selected_summary.to_dict("records"),
        event_count=len(frame) // len(HORIZONS), selected_event_count=len(selected) // len(HORIZONS),
        maximum_entry_wait_min=float(frame.extra_entry_wait_min.max()),
        maximum_exit_wait_min=float(frame.extra_exit_wait_min.max()),
        core_hashes_match=True,
    ))
    lines = [
        "# 評価期間と方向判定の正答率", "",
        "同じ因果信号を10・20・40・60・120分後に評価した。長く観察するほど正答率が一律に上がるとは限らない。保存４セッションだけを使用し、現在セッションと採用条件の再選定には使っていない。", "",
        "24系統それぞれ感度1.0で、非ゼロ方向の最初の判定を採り、その参照新規時刻から30分以上空けて次の最初の非ゼロ判定を採った。同方向継続中の再観測も含む。分mの情報は確定後に使い、m+2以降の最初の実在１分足の始値を参照新規価格とした。", "",
        "10・20・40・60・120分後それぞれの最初の実在１分足始値を返済参照価格とし、全５期間がセッション内返済期限までに揃うイベントだけを全期間で共通に使った。方向付き値幅が往復２ティックを超えたものを正答とした。これは指値注文の実約定やトレーリング返済の成績とは別の、信号方向の診断である。", "",
        "## 全24系統の延べ集計", "",
        "|銘柄|評価期間|延べイベント数|控除前方向一致率|費用後正答率|費用後損益の中央値／ATR|平均／ATR|",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in pooled.to_dict("records"):
        lines.append(f'|{row["symbol"]}|{row["horizon_min"]}分|{row["count"]}|{row["gross_win_rate"]:.1%}|{row["win_rate"]:.1%}|{row["median_net_atr"]:+.3f}|{row["mean_net_atr"]:+.3f}|')
    lines.extend(["", "同じ相場・時刻を複数の信号系統が繰り返し含む延べ集計であり、この件数を独立標本数とはみなさない。短い評価期間ほど固定の往復コストが値幅に対して重くなる。費用後正答率の改善をそのまま方向の予測力向上とは読まず、控除前方向一致率と併せて判断する。ゼロ値幅はどちらの一致率でも正答に数えない。", ""])
    for item in patterns:
        lines.append(f'{item["symbol"]}では、評価期間を10→20→40→60→120分と延ばしたとき正答率が一度も低下しなかった系統は{item["monotonically_nondecreasing"]}/{item["family_count"]}。120分の正答率が10分より高い系統は{item["higher_120_than_10"]}、低い系統は{item["lower_120_than_10"]}、同率は{item["tied_120_and_10"]}だった。')
    lines.extend(["", "## 採用信号を別に確認", "", "family1、感度0.75、開始60分までは新規参照しない条件。実際の採用注文の押し戻し指値や返済トレーリングはこの診断には使わない。", "", "|銘柄|評価期間|イベント数|費用後正答率|費用後損益の中央値／ATR|", "|---|---:|---:|---:|---:|"])
    for row in selected_summary.to_dict("records"):
        lines.append(f'|{row["symbol"]}|{row["horizon_min"]}分|{row["count"]}|{row["win_rate"]:.1%}|{row["median_net_atr"]:+.3f}|')
    lines.extend(["", "## 解釈の範囲", "", "長い波を後から選んで検知率を測ると、将来の持続時間を使って正解を選ぶ偏りが入る。この診断は将来の波の長さでイベントを選んでおらず、同じ信号の評価期間を変えている。したがって『本当に長く続く波なら事前に見分けやすい』ことを直接証明するものではない。短期の急変と長期の緩やかな変化を速度別に分離した比較でもない。", "", "120分後まで評価できる集合に揃えたため、引け前のイベントは全期間から除いている。価格観測のない分は次の実在足まで待つため、名目の評価期間より長い場合がある。最大の追加待機は参照新規で " + str(float(frame.extra_entry_wait_min.max())) + " 分、返済参照で " + str(float(frame.extra_exit_wait_min.max())) + " 分だった。", "", "４セッションの方向や値動きに強く依存し、同一系統の120分評価も30分おきに重なる。24系統・両銘柄を独立した検証期間と数えたり、この勝率を将来の保証に使ったりはしない。正答率が高い評価期間を新たに採用し直しておらず、採用の返済方法も変更していない。", ""])
    (OUT / "継続時間比較.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(dict(延べイベント=len(frame) // 5, 採用イベント=len(selected) // 5, 傾向=patterns), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    run()
