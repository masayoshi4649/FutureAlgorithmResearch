"""取得済みの一回限りの現在スナップショットを凍結条件で評価する。"""

import hashlib
import json
from pathlib import Path

import pandas as pd

from research import Config, OUT, ROOT, SYMBOLS, evaluate, features, make_bars, signal, write_json


def read_snapshot(path: Path, period: int, cutoff: pd.Timestamp) -> pd.DataFrame:
    """機能: 保存済みJSONから共通締切までの確定足を取り出す。

    引数: path (Path)、period (int) は足分数、cutoff (Timestamp) は締切。
    返り値: 時刻索引付き足 (DataFrame)。通信は行わない。
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(payload["data"])
    df["time"] = pd.to_datetime(df["time"])
    df = df[df.closed & (df.time+pd.Timedelta(minutes=period)<=cutoff)]
    if df.time.duplicated().any():
        raise ValueError("現在スナップショットに時刻重複があります")
    return df.rename(columns={"volumeComplete": "volume_complete"}).set_index("time").sort_index()


def load_current(timeframe: int = 5) -> tuple[dict, list[dict]]:
    """機能: 一度取得した両指数の足を検証データへ変換する。

    引数: timeframe (int) は検知時間軸。返り値: 足の対応表と品質情報 (tuple)。
    """
    directory = OUT/"現在セッション固定"
    metadata = json.loads((directory/"取得記録.json").read_text(encoding="utf-8"))
    cutoff = pd.Timestamp(metadata["cutoff"])
    status = json.loads((directory/"status.json").read_text(encoding="utf-8"))
    ids = {r["code"]: r["sessionId"] for r in status["current"]}
    data, quality = {}, []
    for symbol in SYMBOLS:
        one = read_snapshot(directory/f"{symbol}_1min.json", 1, cutoff)
        five = read_snapshot(directory/f"{symbol}_5min.json", 5, cutoff)
        if (ROOT/"candle_1min"/symbol/f"{ids[symbol]}.csv").exists():
            raise ValueError("現在セッションが保存済みの学習・評価セッションと重複しています")
        bars = make_bars(one, five, timeframe)
        z = features(bars, timeframe)
        reference = features(five).atr.copy()
        reference.index += pd.Timedelta(minutes=5)
        z["risk_atr"] = reference.reindex(z.index+pd.Timedelta(minutes=timeframe), method="ffill",
                                          tolerance=pd.Timedelta(minutes=5)).to_numpy()
        data[(ids[symbol], symbol)] = (one, z)
        quality.append(dict(symbol=symbol, session=ids[symbol], cutoff=cutoff.isoformat(),
                            first=one.index[0].isoformat(), last=one.index[-1].isoformat(),
                            one_minute_bars=len(one), five_minute_bars=len(five),
                            incomplete_excluded=True, overlaps_saved=False))
    if len(set(ids.values()))!=1:
        raise ValueError("両指数のセッションが一致していません")
    return data, quality


def main() -> None:
    """機能: 凍結コードを確認し現在データの評価と直近判定を保存する。

    引数: なし。返り値: なし (None)。検知条件は変更しない。
    """
    frozen = json.loads((OUT/"凍結設定.json").read_text(encoding="utf-8"))
    if hashlib.sha256((OUT/"research.py").read_bytes()).hexdigest()!=frozen["code_sha256"]:
        raise RuntimeError("凍結時と研究コードが一致しません")
    cfg = Config(**frozen["config"])
    data, quality = load_current(cfg.timeframe)
    records, rows = evaluate(data, cfg)
    write_json(OUT/"現在_イベント.json", records)
    write_json(OUT/"現在_集計.json", rows)
    write_json(OUT/"現在_品質.json", quality)
    latest = []
    for (session, symbol), (_, z) in data.items():
        peer = "TOPIX" if symbol=="NK225" else "NK225"
        s = signal(z, data[(session, peer)][1], cfg)
        active = [r for r in records if r["symbol"]==symbol and not r["closed"]]
        latest.append(dict(symbol=symbol, last_bar=z.index[-1].isoformat(),
                           latest_condition=int(s.iloc[-1]), active_events=active,
                           note="直近条件の点灯と、重複抑制・待機を通過した新規検知は別です。"))
    write_json(OUT/"現在_直近状態.json", latest)
    print(json.dumps(dict(集計=rows, 品質=quality, 直近=latest), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
