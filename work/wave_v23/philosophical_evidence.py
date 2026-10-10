"""市場原理の代理信号を、注文損益とは別に5分・15分先の価格で説明的に点検する。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np

import learned_flow
import signals


OUT = Path(__file__).resolve().parent
HORIZONS = (5, 15)
SYMBOLS = ("TOPIX", "NK225")


def divide(numerator: float, denominator: float) -> float | None:
    """機能: 標本ゼロを欠損として比率を返す。

    引数: numerator/denominator (float) は分子と分母。
    返り値: 比率または欠損 (float|None)。
    """
    return float(numerator / denominator) if denominator else None


def digest(path: Path) -> str:
    """機能: 説明用の入力ファイルの内容ハッシュを記録する。

    引数: path (Path) は読み取り対象。
    返り値: SHA256の16進文字列 (str)。
    """
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1048576):
            result.update(block)
    return result.hexdigest()


def samples(ready: dict, horizon: int) -> dict:
    """機能: 毎分の最初の原本行と同一セッション内の将来価格を対応させる。

    引数: ready (dict) は原本時刻・行番号・価格・ATR等、horizon (int) は分数。
    返り値: 観測位置・将来位置・ATR正規化価格差等の辞書 (dict)。
    注意: 将来ラベルは説明的評価だけに使用し、方向生成や注文条件へ渡さない。
    """
    times = np.asarray(ready["time_s"], dtype=float)
    boundaries = np.arange(ready["start"] + 1200, min(ready["limit"], times[-1]) + 1e-8, 60.0)
    positions = np.searchsorted(times, boundaries, side="left")
    valid = positions < len(times)
    positions, boundaries = positions[valid], boundaries[valid]
    valid = times[positions] - boundaries <= 60.0
    positions = np.unique(positions[valid])
    targets = times[positions] + horizon * 60.0
    future = np.searchsorted(times, targets, side="left")
    valid = future < len(times)
    positions, targets, future = positions[valid], targets[valid], future[valid]
    atr = np.asarray(ready["atr"], float)[positions]
    valid = (times[future] <= ready["limit"]) & (times[future] - targets <= 60.0)
    valid &= np.isfinite(atr) & (atr > 0)
    positions, future, atr, targets = positions[valid], future[valid], atr[valid], targets[valid]
    difference = np.asarray(ready["last"], float)[future] - np.asarray(ready["last"], float)[positions]
    assert np.all(np.asarray(ready["seq"])[future] > np.asarray(ready["seq"])[positions])
    assert np.all(times[future] >= times[positions] + horizon * 60.0)
    assert np.all(times[future] <= ready["limit"])
    return dict(indices=positions, future_indices=future, difference=difference, normalized=difference / atr,
                available=len(positions), maximum_future_delay=float(np.max(times[future] - targets, initial=0)))


def measure(data: dict, directions: np.ndarray, side: str) -> dict:
    """機能: 買い・売り・合計を区別して、方向一致と価格差を測る。

    引数: data (dict) は説明用標本、directions (ndarray[int8]) は原本各行の固定信号、side (str)。
    返り値: 加算可能な件数・価格差合計と比率を持つ辞書 (dict)。
    """
    current = np.asarray(directions)[data["indices"]]
    active = current != 0 if side == "合計" else current == (1 if side == "買い" else -1)
    signed = current[active] * data["normalized"][active]
    points = current[active] * data["difference"][active]
    total, count = len(current), int(active.sum())
    positive, negative = int((signed > 0).sum()), int((signed < 0).sum())
    raw_up = int((data["difference"] > 0).sum())
    raw_down = int((data["difference"] < 0).sum())
    longs, shorts = int((current[active] == 1).sum()), int((current[active] == -1).sum())
    output = dict(標本数=total, 予測件数=count, 予測なし件数=int((current == 0).sum()), 買い予測件数=longs, 売り予測件数=shorts,
                  正方向件数=positive, 逆方向件数=negative, 同値件数=count - positive - negative,
                  方向付きATR差合計=float(signed.sum()), 方向付き価格差合計=float(points.sum()),
                  全時刻上昇件数=raw_up, 全時刻下落件数=raw_down, 全時刻同値件数=total - raw_up - raw_down,
                  全時刻ATR差合計=float(data["normalized"].sum()),
                  売買比率だけの期待正方向件数=float((longs * raw_up + shorts * raw_down) / total) if total else 0.0)
    return finalize(output)


def finalize(record: dict) -> dict:
    """機能: 加算済み件数から説明用の比率と平均を作る。

    引数: record (dict) は件数・合計値。
    返り値: 平均・比率を付与した新しい辞書 (dict)。
    """
    result = dict(record)
    n = record["予測件数"]
    result.update(方向一致率=divide(record["正方向件数"], n),
                  同値を除く方向一致率=divide(record["正方向件数"], record["正方向件数"] + record["逆方向件数"]),
                  平均方向付きATR差=divide(record["方向付きATR差合計"], n),
                  平均方向付き価格差=divide(record["方向付き価格差合計"], n),
                  予測率=divide(n, record["標本数"]),
                  常時買い一致率=divide(record["全時刻上昇件数"], record["標本数"]),
                  常時売り一致率=divide(record["全時刻下落件数"], record["標本数"]),
                  売買比率だけの期待一致率=divide(record["売買比率だけの期待正方向件数"], n))
    return result


def combine(records: list[dict]) -> dict:
    """機能: 同じ銘柄・予測時間・売買方向のセッション別計数を合算する。

    引数: records (list[dict]) は measure の出力を含む行。
    返り値: 再計算した期間指標 (dict)。
    """
    names = ["標本数", "予測件数", "予測なし件数", "買い予測件数", "売り予測件数", "正方向件数", "逆方向件数", "同値件数",
             "方向付きATR差合計", "方向付き価格差合計", "全時刻上昇件数", "全時刻下落件数", "全時刻同値件数", "全時刻ATR差合計",
             "売買比率だけの期待正方向件数"]
    output = finalize({name: sum(row[name] for row in records) for name in names})
    output.update(セッション数=len(records), 予測したセッション数=sum(row["予測件数"] > 0 for row in records),
                  平均差が正のセッション数=sum((row["平均方向付きATR差"] or 0) > 0 for row in records))
    active = [row["平均方向付きATR差"] for row in records if row["予測件数"] > 0]
    output["予測ありセッションの単純平均ATR差"] = float(np.mean(active)) if active else None
    return output


def percentage(value: float | None) -> str:
    """機能: 欠損を区別して比率を日本語報告用に整形する。

    引数: value (float|None) は比率。
    返り値: 百分率または未計測表記 (str)。
    """
    return "予測なし" if value is None else f"{value * 100:.1f}%"


def metric(row: dict) -> str:
    """機能: 件数・方向一致・ATR平均を一つの短いセルへまとめる。

    引数: row (dict) は集計指標。
    返り値: 日本語表のセル文字列 (str)。
    """
    value = row["平均方向付きATR差"]
    average = "―" if value is None else f"{value:+.3f}"
    return f"{row['予測件数']:,}件／{percentage(row['方向一致率'])}／{average}ATR"


def notes(specs: list[dict], summary: list[dict], per_session: list[dict]) -> str:
    """機能: 市場仮説と将来価格の観察結果を短い日本語で対応させる。

    引数: specs (list[dict]) は信号説明、summary/per_session (list[dict]) は集計。
    返り値: Markdown説明文 (str)。
    """
    lookup = {(row["手法ID"], row["銘柄"], row["予測分数"], row["売買"]): row for row in summary}
    names = {row["id"]: row["name"] for row in specs}
    chosen = ["F29", "F38", "F39", "F40", "F44", "F52", "F53"]
    lines = ["# 市場仮説と5分・15分先の観察", "",
             "以下は注文・ストップを使わず、毎分の信号方向にその後価格が動いたかを見る説明的な検証。利益額や売買勝率とは別である。数値は『予測件数／方向一致率／平均方向付きATR差』。同値は一致に数えず、0信号は予測なしとした。", "",
             "| 仮説・手法 | TOPIX・5分 | NK225・5分 | TOPIX・15分 | NK225・15分 |", "|---|---:|---:|---:|---:|"]
    for identifier in chosen:
        cells = [metric(lookup[(identifier, symbol, horizon, "合計")]) for horizon in HORIZONS for symbol in SYMBOLS]
        lines.append(f"| {identifier} {names[identifier]} | " + " | ".join(cells) + " |")
    lines += ["", "## 売りだけを分けた観察", "",
              "| 手法 | TOPIX・5分 | NK225・5分 | TOPIX・15分 | NK225・15分 |", "|---|---:|---:|---:|---:|"]
    for identifier in ["F29", "F38", "F52", "F53"]:
        cells = [metric(lookup[(identifier, symbol, horizon, "売り")]) for horizon in HORIZONS for symbol in SYMBOLS]
        lines.append(f"| {identifier} {names[identifier]} | " + " | ".join(cells) + " |")
    lines += ["", "## 売買成績で残った5候補の方向応答", "",
              "候補は注文損益側で既に固定したもの。ここで方向応答を見て候補を入れ替えていない。", "",
              "| 手法 | TOPIX・5分 | NK225・5分 | TOPIX・15分 | NK225・15分 |", "|---|---:|---:|---:|---:|"]
    for identifier in ["F32", "F08", "F47", "F35", "F17"]:
        cells = [metric(lookup[(identifier, symbol, horizon, "合計")]) for horizon in HORIZONS for symbol in SYMBOLS]
        lines.append(f"| {identifier} {names[identifier]} | " + " | ".join(cells) + " |")
    lines += ["", "F32の仮説は、2分平均で買い板が相対的に厚く売り板が薄く、価格も上へ進んでいれば、上側へ進みやすいというもの。売りは対称。最良数量で重み付けした気配の偏差がスプレッドの0.06を超え、2分の気配価格変化も同方向のときに候補とする。参加者の買い意欲そのものを測ったとは言わない。", "",
              "反証は、厚い板が取消される、反対板が補充される、既に動いた分が戻る、といった場合。F32はTOPIXの平均方向差が5分・15分とも小幅な正、NKは5分が小幅な負で15分は正だった。どの時間でも一方向に進む強い予測器とは言えない。一致率が半分未満でも平均差が正なら、当たる回数より当たった値幅が寄与している。", "",
              "したがってF32と損失制限を組み合わせた売買の黒字は、そのまま高い方向正答率の証明にはならない。逆指値でさらに進行を確認する入口、伸びる玉を保持する出口、連敗停止の効果を分け、同じ注文管理と乱数方向の対照も合わせて評価する。"]
    lines += ["", "## このデータで支持された範囲", ""]
    for identifier in chosen:
        rows = [lookup[(identifier, symbol, horizon, "合計")] for horizon in HORIZONS for symbol in SYMBOLS]
        positive = sum((row["平均方向付きATR差"] or 0) > 0 for row in rows)
        counts = "/".join(str(row["予測件数"]) for row in rows)
        conclusion = "両銘柄・両時間で平均方向差は正" if positive == 4 else f"平均方向差が正なのは4区分中{positive}区分"
        lines.append(f"- {identifier}：{conclusion}。{('予測が少なく個別事例の影響が大きい。' if min(row['予測件数'] for row in rows) < 50 else '')}")
    lines += ["", "- 例えば『売り圧力が続くなら、その後も下がる』は売り行の平均方向差が正か、複数セッションへ広がっているかで反証できる。OFIの定義が正しいことと、将来価格への予測力があることは別である。",
              "- 吸収・補充や両市場一致は標本を絞るため、単独OFIより平均が良くても同じ場面での直接比較ではない。市場の条件付けとしての候補であり改善効果の因果証明ではない。",
              "- 5分・15分先の窓は重なり、同じ波が複数回入る。全13セッションは既読で、54固定条件と4過去学習条件を比較した同じデータである。p値、独立試行数、未知データの正答率とは呼ばない。",
              "- 各セッション・買い/売り別・常時買い/常時売りの基準値は philosophical_evidence.json に全件保存した。未来側の価格は評価ラベル専用で、信号・注文生成へ戻していない。", ""]
    return "\n".join(lines)


def main() -> None:
    """機能: 固定済み58信号の説明的な将来価格評価を保存する。

    引数: なし。
    返り値: なし (None)。既存コード、原本、売買結果は変更しない。
    """
    input_path, direction_path = OUT / "inputs.pkl", OUT / "directions.pkl"
    if not direction_path.exists():
        raise FileNotFoundError("親の固定方向生成が未完了です。directions.pkl の完成後に再実行してください")
    inputs = pickle.loads(input_path.read_bytes())
    directions = pickle.loads(direction_path.read_bytes())
    specs = signals.catalog() + learned_flow.catalog()
    assert set(directions) == {item["id"] for item in specs}
    prepared = {(key, horizon): samples(ready, horizon) for key, ready in inputs.items() for horizon in HORIZONS}
    rows, groups = [], defaultdict(list)
    for spec in specs:
        for key, ready in inputs.items():
            assert len(directions[spec["id"]][key]) == len(ready["seq"])
            for horizon in HORIZONS:
                for side in ("合計", "買い", "売り"):
                    row = dict(手法ID=spec["id"], 手法名=spec["name"], 銘柄=key[1], セッション=key[0], 予測分数=horizon, 売買=side,
                               **measure(prepared[(key, horizon)], directions[spec["id"]][key], side))
                    rows.append(row)
                    groups[(spec["id"], spec["name"], key[1], horizon, side)].append(row)
    summary = [dict(手法ID=identifier, 手法名=name, 銘柄=symbol, 予測分数=horizon, 売買=side, **combine(items))
               for (identifier, name, symbol, horizon, side), items in groups.items()]
    metadata = dict(作成時刻=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), 信号数=len(specs), セッション数=len({key[0] for key in inputs}),
                    標本規則="開始20分後から毎分境界以降の最初の有効原本行。ATRは標本時点だけ。予測先は標本時刻+5分/15分以降の最初の価格。",
                    範囲="標本・予測先とも当該セッションの返済期限以内。境界・予測先から60秒超の欠測を除外。",
                    予測なし="信号0は予測件数に含めず、予測なし件数へ分離。方向一致はsignedreturn>0、同値は別計数。",
                    評価限界="全データ既読、条件探索と同一データ、重複する将来窓。説明統計のみで有意性p値や未知精度ではない。注文損益ではない。",
                    時間漏洩対策="固定済み方向を原本行位置で参照し、将来価格はこの評価だけに使用。別セッションの価格を参照しない。",
                    入力SHA256={path.name: digest(path) for path in (input_path, direction_path)},
                    個別集計数=len(rows), 期間集計数=len(summary),
                    最大未来観測遅延秒=max(data["maximum_future_delay"] for data in prepared.values()))
    payload = dict(説明=metadata, 期間集計=summary, セッション集計=rows)
    (OUT / "philosophical_evidence.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (OUT / "日本語短評.md").write_text(notes(specs, summary, rows), encoding="utf-8")
    print(f"説明用検証を保存しました: {len(specs)}信号、{len(rows)}個別集計、{len(summary)}期間集計")


if __name__ == "__main__":
    main()
