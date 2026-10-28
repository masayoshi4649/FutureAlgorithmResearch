"""確定済み1分足だけから価格の速度と速度変化を計算する。売買は行わない。"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
WINDOWS = (3, 5, 10, 20)
SELECTED = ("17:15", "17:20", "19:05", "19:10", "20:25", "20:30", "18:26", "20:15", "20:53")
WAVES = (("17:10", "18:26", "上昇"), ("19:00", "20:15", "下落"), ("20:20", "20:53", "上昇"))


def clock(text: str) -> datetime:
    """
    機能: 今回の対象日の日本時間を作る。
    引数: text(str)は時:分。
    返り値: datetimeは時差付きの日本時間。
    """
    return datetime.fromisoformat(f"2026-10-26T{text}:00+09:00")


def direction(value: float | None) -> int | None:
    """
    機能: 傾き等の符号を丸め誤差と区別する。
    引数: value(float|None)は測定値。
    返り値: int|Noneは負=-1、零=0、正=1又は欠測。
    """
    if value is None:
        return None
    return 0 if abs(value) < 1e-9 else (1 if value > 0 else -1)


def regression(values: list[float]) -> float:
    """
    機能: 等間隔1分の終値列を最小二乗直線で近似する。
    引数: values(list[float])は過去から現在へ並ぶ終値。
    返り値: floatは価格ポイント/分の傾き。
    """
    center = (len(values) - 1) / 2
    mean = sum(values) / len(values)
    numerator = sum((i - center) * (value - mean) for i, value in enumerate(values))
    denominator = sum((i - center) ** 2 for i in range(len(values)))
    return numerator / denominator


def at_time(bars: dict[datetime, dict], at: datetime) -> dict:
    """
    機能: その時点で名目公開済みの足だけから複数期間の傾きを作る。
    引数: bars(dict[datetime,dict])は足始刻をキーにした確定足、at(datetime)は判断時計。
    返り値: dictは価格・最終参照足・各回帰傾き。欠損分足は補間しない。
    """
    latest = at - timedelta(seconds=120)
    row = {"判断時刻": at.isoformat(), "最新参照足の始刻": latest.isoformat(),
           "最新参照足の終値": bars.get(latest, {}).get("close")}
    for n in WINDOWS:
        times = [latest - timedelta(minutes=k) for k in range(n - 1, -1, -1)]
        values = [float(bars[t]["close"]) for t in times if t in bars]
        row[f"傾き{n}分_pt毎分"] = regression(values) if len(values) == n else None
    return row


def state(speed: float | None, delta: float | None) -> str:
    """
    機能: 速度の方向と変化の方向を混同せず表す。
    引数: speed(float|None)は5分傾き、delta(float|None)は1分前からの差。
    返り値: strは方向・加減速、又は未準備。
    """
    d, a = direction(speed), direction(delta)
    if d is None or a is None:
        return "準備不足"
    if d == 0:
        return "5分傾きがゼロ"
    if a == 0:
        return "上昇速度維持" if d > 0 else "下落速度維持"
    if d > 0:
        return "上昇加速" if a > 0 else "上昇減速"
    return "下落減速" if a > 0 else "下落加速"


def calculate(bars: dict[datetime, dict], end: datetime) -> list[dict]:
    """
    機能: セッション開始から終端まで毎分の因果的な特徴を計算する。
    引数: bars(dict[datetime,dict])は確定足、end(datetime)は観測打切。
    返り値: list[dict]は全時点の傾き・差分・転換。
    """
    rows = []
    indexed = {}
    at = clock("17:00")
    while at <= end:
        row = at_time(bars, at)
        current = row["傾き5分_pt毎分"]
        for lag in (1, 5):
            previous = indexed.get(at - timedelta(minutes=lag), {}).get("傾き5分_pt毎分")
            delta = current - previous if current is not None and previous is not None else None
            row[f"5分傾きの{lag}分前からの差_pt毎分"] = delta
            row[f"5分傾きの{lag}分間平均加速度_pt毎分毎分"] = delta / lag if delta is not None else None
        earlier = indexed.get(at - timedelta(minutes=1), {}).get("傾き5分_pt毎分")
        old, new = direction(earlier), direction(current)
        row["5分傾きの符号転換"] = None if old is None or new is None or old == new else f"{old}→{new}"
        short = row["傾き3分_pt毎分"]
        row["3分傾きと5分傾きの差_pt毎分"] = short - current if short is not None and current is not None else None
        row["速度と変化の状態"] = state(current, row["5分傾きの1分前からの差_pt毎分"])
        indexed[at] = row
        rows.append(row)
        at += timedelta(minutes=1)
    return rows


def number(value: float | None) -> str:
    """
    機能: 報告表へ欠測又は小数値を整形する。
    引数: value(float|None)は計算値。
    返り値: strは表示文字列。
    """
    return "未準備" if value is None else f"{value:+.2f}"


def main() -> None:
    """
    機能: 取得済みデータを全区間計算後、事後診断用の指定時刻を抽出して保存する。
    引数: なし。入力は親/data、打切は親/入力目録.json。
    返り値: なし。JSONとMarkdownのみ書き、注文・ネット通信は行わない。
    """
    cutoff = datetime.fromisoformat(json.loads((BASE / "入力目録.json").read_text(encoding="utf-8"))["cutoff"])
    outputs = {}
    checks = []
    # ----------------------------------------
    # 金融経路ではなく、単調列と未来足改変で数式・参照境界を検査する。
    for n in WINDOWS:
        assert abs(regression([100 + 2 * i for i in range(n)]) - 2) < 1e-9
    for symbol in ("NK225", "TOPIX"):
        source = BASE / "data" / f"{symbol}_candles_1min.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        bars = {datetime.fromisoformat(b["time"]): b for b in data["data"]
                if b["closed"] and datetime.fromisoformat(b["time"]) + timedelta(seconds=120) <= cutoff}
        all_rows = calculate(bars, cutoff)
        indexed = {datetime.fromisoformat(r["判断時刻"]): r for r in all_rows}
        selected = [indexed[clock(text)] for text in SELECTED]
        for point in (clock(text) for text in SELECTED):
            mutated = {t: (dict(b, close=b["close"] * 100 + 123) if t + timedelta(seconds=120) > point else b)
                       for t, b in bars.items()}
            assert at_time(bars, point) == at_time(mutated, point)
            prefix = {t: b for t, b in bars.items() if t + timedelta(seconds=120) <= point}
            assert at_time(bars, point) == at_time(prefix, point)
        flips = [r for r in all_rows if r["5分傾きの符号転換"]]
        missing = []
        minute = clock("17:00")
        while minute + timedelta(seconds=120) <= cutoff:
            if minute not in bars:
                missing.append(minute.isoformat())
            minute += timedelta(minutes=1)
        waves = []
        for begin, finish, intended in WAVES:
            samples = [r for r in all_rows if clock(begin) <= datetime.fromisoformat(r["判断時刻"]) <= clock(finish)]
            valid = [r for r in samples if r["傾き5分_pt毎分"] is not None]
            waves.append({"区間": f"{begin}〜{finish}", "ユーザー指定方向": intended,
                          "評価点数": len(valid), "正傾き点数": sum(r["傾き5分_pt毎分"] > 1e-9 for r in valid),
                          "負傾き点数": sum(r["傾き5分_pt毎分"] < -1e-9 for r in valid),
                          "符号転換回数": sum(bool(r["5分傾きの符号転換"]) for r in valid),
                          "開始点": samples[0], "終了点": samples[-1]})
        result = {"商品": symbol, "入力sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "切断": cutoff.isoformat(), "毎分結果": all_rows, "固定抽出": selected,
                  "全区間の5分傾き符号転換": flips, "三波区間の集計": waves,
                  "補間しなかった欠損分足の始刻": missing}
        outputs[symbol] = result
        (HERE / f"{symbol}_傾き.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        checks.append({"商品": symbol, "完成足本数": len(bars), "全評価時刻数": len(all_rows),
                       "未来価格改変不変": True, "接頭辞再計算一致": True, "固定抽出点数": len(selected)})
    # ----------------------------------------
    # 指定した時刻は売買トリガーではなく、ユーザーが示した波の事後診断である。
    text = ["# 価格の傾きと勢いの変化の数値監査", "",
            "確定済み1分足の終値を使い、3・5・10・20本の直線回帰傾きを毎分計算しました。売買や条件最適化はしていません。足始刻から2分後（足末＋60秒）に利用可能とする名目公開時計です。欠損足は補間しません。",
            "", "以下の時刻はユーザーが挙げた波に合わせた**事後の診断点**であり、その場で自動的に選ばれたエントリー時刻ではありません。", "",
            "| 判断時刻 | 参照済み最新足 | 日経3分傾き | 日経5分傾き | 日経10分傾き | 日経20分傾き | 5分傾きの1分前比 | TOPIX5分傾き |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for i, row in enumerate(outputs["NK225"]["固定抽出"]):
        peer = outputs["TOPIX"]["固定抽出"][i]
        text.append(f"| {row['判断時刻'][11:16]} | {row['最新参照足の始刻'][11:16]}足 | " +
                    " | ".join(number(row[f"傾き{n}分_pt毎分"]) for n in WINDOWS) +
                    f" | {number(row['5分傾きの1分前からの差_pt毎分'])} | {number(peer['傾き5分_pt毎分'])} |")
    text += ["", "傾きと差の単位はpt/分。1分前比を1分で割った値は加速度pt/分²と数値上同じです。5分前比は別途JSONへ保存し、加速度は差を5分で割ります。",
             "", "- 速度が正・差が正：上昇加速。速度が正・差が負：上昇減速であって下落への転換ではありません。",
             "- 速度が負・差が負：下落加速。速度が負・差が正：下落減速であって上昇への転換ではありません。",
             "- 3分傾き−5分傾きは短い窓と長い窓の差であり、時間微分そのものではありません。負の速度で短期がさらに負なら下落加速の候補、短期がゼロへ近づくなら下落減速の候補です。",
             "- 傾きの符号が反転した時点と、同じ方向のまま強弱が変わる時点を分けます。短窓の符号は往復し得るため、そのまま売買すれば利益になるとの評価はしていません。", "",
             "全時刻の計算後に指定点を抽出し、指定点より後の価格を大幅改変しても当該値が変わらないことを検査しました。これは未来参照防止の検査であり、方向予測の確度の測定ではありません。", ""]
    text += ["## 波の途中でも短期の符号は往復する", "",
             "| 日経の指定区間 | 5分傾きを計算できた毎分点数 | 正 | 負 | ゼロを含む符号転換数 |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for wave in outputs["NK225"]["三波区間の集計"]:
        text.append(f"| {wave['区間']} | {wave['評価点数']} | {wave['正傾き点数']} | {wave['負傾き点数']} | {wave['符号転換回数']} |")
    text += ["", "各波は事後指定で、評価点は重複する窓です。転換数はゼロとの行き来も含み、独立した取引機会数ではありません。例えば19:05は5分傾き−13でも3分傾き+10で、下降中の短い反発を数値として区別できます。",
             "", "日経には公開対象の分足が14分欠けています。実約定がない区間などの可能性があるため、勝手に終値を補って連続足としません。欠損時刻はJSONに列挙しました。TOPIXの欠損は1分です。", ""]
    (HERE / "結果.md").write_text("\n".join(text), encoding="utf-8")
    (HERE / "検査.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"抽出": outputs["NK225"]["固定抽出"], "検査": checks}, ensure_ascii=True))


if __name__ == "__main__":
    main()
