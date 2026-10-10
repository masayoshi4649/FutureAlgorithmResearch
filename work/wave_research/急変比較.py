"""既に評価済みの保存データで急変型と３０分継続型を事後比較する。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import research


OUT = Path(__file__).resolve().parent
HORIZONS = (5, 30, 60)
KINDS = ("急変型", "継続型")
SYMBOLS = ("NK225", "TOPIX")
SESSIONS = ("2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day")


def classify(z: pd.DataFrame) -> dict[str, pd.Series]:
    """機能: 過去の確定５分足だけから排他的な２分類を判定する。

    引数: z (DataFrame) はＡＴＲ１２を含む確定５分足特徴量。
    返り値: dict[str, Series] は分類別の方向。１はロング、−１はショート、０は中立。
    """
    change5 = z.close.diff()
    change30 = z.close - z.close.shift(6)
    direction = np.sign(change30)
    absolute_sum = change5.abs().rolling(6).sum()
    efficiency = change30.abs() / absolute_sum.replace(0, np.nan)
    largest_share = change5.abs().rolling(6).max() / absolute_sum.replace(0, np.nan)
    differences = pd.concat([change5.shift(offset) for offset in range(6)], axis=1)
    agreement = differences.mul(direction, axis=0).gt(0).sum(axis=1)
    ready = (z.age >= 17) & z.atr.notna() & (z.atr > 0)
    impulse = np.sign(change5).where(ready & (change5.abs() >= z.atr), 0).fillna(0).astype(int)
    steady = direction.where(ready & (change5.abs() < z.atr) & (change30.abs() >= 1.5 * z.atr)
                             & (efficiency >= 0.35) & (agreement >= 4) & (largest_share <= 0.5), 0).fillna(0).astype(int)
    if ((impulse != 0) & (steady != 0)).any():
        raise ValueError("急変型と継続型が重複しています。")
    return {"急変型": impulse, "継続型": steady}


def detect(one: pd.DataFrame, z: pd.DataFrame, directions: pd.Series, kind: str, session: str, symbol: str) -> list[dict]:
    """機能: １分の待機と６０分間隔を適用して実在足の検知イベントを作る。

    引数: one/z (DataFrame)、directions (Series)、kind/session/symbol (str)。
    返り値: list[dict] は未来採点を含む検知イベント。未来採点は検知後にのみ行う。
    """
    events = []
    next_allowed = one.index[0]
    deadline = research.session_end(one.index) - pd.Timedelta(minutes=30)
    for stamp, side in directions.items():
        if side == 0:
            continue
        eligible = stamp + pd.Timedelta(minutes=6)
        position = one.index.searchsorted(eligible)
        if position >= len(one):
            continue
        entry = one.index[position]
        if entry - eligible > pd.Timedelta(minutes=2) or entry < next_allowed or entry >= deadline:
            continue
        record = {
            "分類": kind, "セッション": session, "銘柄": symbol,
            "方向": int(side), "検知時刻": stamp + pd.Timedelta(minutes=5), "開始時刻": entry,
            "開始価格": float(one.iloc[position].open), "ＡＴＲ": float(z.loc[stamp, "atr"]),
        }
        events.append(record)
        next_allowed = entry + pd.Timedelta(minutes=60)
    for record in events:
        record.update(research.label_wave(one, record["開始時刻"], record["開始価格"], record["方向"], record["ＡＴＲ"]))
    return events


def valid(record: dict, horizon: int, cohort: str) -> bool:
    """機能: 指定未来時間を採点可能なイベントか判定する。

    引数: record (dict)、horizon (int)、cohort (str)。
    返り値: bool は指定時間または３時間全てが採点可能かどうか。
    """
    horizons = HORIZONS if cohort == "３時間の共通標本" else (horizon,)
    return all(record.get(f"wave{value}") is not None for value in horizons)


def aggregate(events: list[dict]) -> pd.DataFrame:
    """機能: 各分類を同じ将来ラベルで採点し、ゼロ検知も含めて集計する。

    引数: events (list[dict]) は全検知イベント。
    返り値: DataFrame は分類、データ区分、銘柄、標本区分、評価時間別の結果。
    """
    rows = []
    groups = {
        "既評価の保存３セッション合計": SESSIONS,
        "開発に使用した９月２１日日中・夜間": SESSIONS[:2],
        "既評価の９月２２日日中": SESSIONS[2:],
        **{session: (session,) for session in SESSIONS},
    }
    for group, sessions in groups.items():
        for symbol in (*SYMBOLS, "両銘柄合計"):
            for kind in KINDS:
                members = [event for event in events if event["分類"] == kind and event["セッション"] in sessions
                           and (symbol == "両銘柄合計" or event["銘柄"] == symbol)]
                cells = [(session, item) for session in sessions for item in SYMBOLS if symbol == "両銘柄合計" or item == symbol]
                empty = sum(not any(event["セッション"] == session and event["銘柄"] == item for event in members) for session, item in cells)
                for cohort in ("各時間の有効標本", "３時間の共通標本"):
                    for horizon in HORIZONS:
                        scored = [event for event in members if valid(event, horizon, cohort)]
                        count = len(scored)
                        waves = sum(bool(event[f"wave{horizon}"]) for event in scored)
                        directions = sum(event[f"forward{horizon}_atr"] > 0 for event in scored)
                        rows.append({
                            "比較の性格": "評価結果を見た後の補足探索", "データ区分": group, "銘柄": symbol,
                            "分類": kind, "標本区分": cohort, "評価時間分": horizon,
                            "検知総数": len(members), "対象セル数": len(cells), "無検知セル数": empty,
                            "採点可能数": count, "採点不能数": len(members) - count,
                            "ロング数": sum(event["方向"] == 1 for event in scored),
                            "ショート数": sum(event["方向"] == -1 for event in scored),
                            "波の正答数": waves, "波の正答率": waves / count if count else None,
                            "方向の正答数": directions, "方向の正答率": directions / count if count else None,
                        })
    return pd.DataFrame(rows)


def percent(value: float | None) -> str:
    """機能: 欠測を区別して正答率の表示を作る。

    引数: value (float | None) は比率。
    返り値: str は百分率または採点不能という表示。
    """
    return "採点不能" if value is None or pd.isna(value) else f"{value * 100:.1f}％"


def write_report(table: pd.DataFrame, events: list[dict]) -> None:
    """機能: 固定仮説、実測結果、事後比較の制約を文書化する。

    引数: table (DataFrame) は集計、events (list[dict]) は検知イベント。
    返り値: None。
    """
    lines = [
        "# 急変型と継続型の事後補足比較", "",
        "これは開発と評価の結果を既に見た後に追加した補足探索。９月２１日日中・夜間と９月２２日日中の保存データを使用し、未使用データでの検証とは呼ばない。現在セッションデータは使っていない。採用設定の変更や閾値の再調整は行っていない。", "",
        "## 変更しない仮説", "",
        "- 両分類とも保存済みの確定５分足、連続区間１８本以上、１２期間のＡＴＲを使用。時間の欠落がある箇所は特徴量をリセットする。",
        "- 急変型: 直近５分の終値変化の絶対値が１ＡＴＲ以上。変化の符号を検知方向とする。",
        "- 継続型: 直近５分変化が１ＡＴＲ未満、３０分変化が１．５ＡＴＲ以上、６本の方向効率が０．３５以上、直近６差分のうち進行方向と一致するものが４本以上、最大絶対５分変化÷絶対変化合計が０．５以下。３０分変化の符号を検知方向とする。",
        "- 同じ検知時刻で急変型と継続型は排他的。同じ相場の波が後の時刻に別分類で検知されることはある。分類別・銘柄別・セッション別に前回検知から６０分以上空ける。同方向の追加再準備条件は設けない。",
        "- 検知足が確定した後に１分待ち、その予定時刻から２分以内の最初の実在１分足の始値を開始価格とする。補完足へ新規開始しない。既存検証と同じく日中１５時０５分・夜間５時２０分以降は新規検知しない。",
        "- 同じ label_wave で５・３０・６０分後を評価。波の正答は最終終値が０．５ＡＴＲ以上順行、評価区間の分末終値の６０％以上が順行、最大逆行１ＡＴＲ以内。方向正答は最終終値が方向どおりであること。横ばいは正答ではない。",
        "- ２分までの無観測を直前終値で補完し、それを超える欠測や末尾不足は採点不能。各時間の有効標本と、３つの評価時間を全て採点できる共通標本を別集計する。検知後の採点にのみ未来を使用する。", "",
        "## 保存３セッションの両銘柄合計", "",
        "| 標本 | 分類 | 未来分数 | 波正答数／分母 | 波正答率 | 方向正答数／分母 | 方向正答率 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    selected = table[(table["データ区分"] == "既評価の保存３セッション合計") & (table["銘柄"] == "両銘柄合計")]
    for _, row in selected.iterrows():
        lines.append(f"| {row['標本区分']} | {row['分類']} | {row['評価時間分']} | {row['波の正答数']}/{row['採点可能数']} | {percent(row['波の正答率'])} | {row['方向の正答数']}/{row['採点可能数']} | {percent(row['方向の正答率'])} |")
    lines.extend(["", "## 既に評価済みの９月２２日日中だけの比較", "", "| 分類 | 未来分数 | 波正答数／分母 | 波正答率 | 方向正答率 |", "| --- | ---: | ---: | ---: | ---: |"])
    previous_day = table[(table["データ区分"] == "既評価の９月２２日日中") & (table["銘柄"] == "両銘柄合計") & (table["標本区分"] == "各時間の有効標本")]
    for _, row in previous_day.iterrows():
        lines.append(f"| {row['分類']} | {row['評価時間分']} | {row['波の正答数']}/{row['採点可能数']} | {percent(row['波の正答率'])} | {percent(row['方向の正答率'])} |")
    lines.extend(["", "全体の３０分波正答率では継続型が高いが、９月２２日日中に限定すると差が消える。セッションをまたいで一貫した優位性は確認できていない。"])
    lines.extend(["", "## セッション別の検知件数", "", "| セッション | 銘柄 | 急変型 | 継続型 |", "| --- | --- | ---: | ---: |"])
    for session in SESSIONS:
        for symbol in SYMBOLS:
            counts = [sum(event["セッション"] == session and event["銘柄"] == symbol and event["分類"] == kind for event in events) for kind in KINDS]
            lines.append(f"| {session} | {symbol} | {counts[0]} | {counts[1]} |")
    lines.extend([
        "", "## 読み取りの制約", "",
        "- 標本は保存３セッションしかなく、両銘柄や近い時刻のイベントも独立ではない。分類間では検知時刻、ロング／ショート比率、相場環境が違うため、正答率差だけで持続期間が精度を上げたとは断定できない。",
        "- ５分変化・３０分変化を用いた過去形状の比較と、検知後５・３０・６０分の将来評価を区別する。継続型の検知時点まで３０分続いていても、その後さらに３０分続くとは限らない。",
        "- 各時間で分母が変わる結果は、採点不能になったイベント構成の影響を含む。共通標本も確認し、分母が小さい率や検知ゼロは結論を出す根拠にしない。",
        "- 本補足は波の形状と継続を比較する診断であり、取引コスト控除後の収益性を検証したものではない。", "",
        "詳細は `急変比較.csv`。再現は `python work/wave_research/急変比較.py`。", "",
    ])
    (OUT / "急変比較.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """機能: 指定した固定仮説を既評価の３保存セッションで１回比較する。

    引数: なし。
    返り値: None。外部通信や採用条件変更は行わない。
    """
    data = research.load_sessions(SESSIONS, 5)
    events = []
    for (session, symbol), (one, z) in data.items():
        directions = classify(z)
        for kind in KINDS:
            events.extend(detect(one, z, directions[kind], kind, session, symbol))
    table = aggregate(events)
    table.to_csv(OUT / "急変比較.csv", index=False, encoding="utf-8-sig")
    write_report(table, events)
    print("急変型・継続型の事後補足比較が完了しました。", flush=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
