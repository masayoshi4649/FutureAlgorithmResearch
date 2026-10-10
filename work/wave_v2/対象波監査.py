"""保存済み１分足から利用者指定の波を評価用に記述する。通信と売買は行わない。"""

from pathlib import Path
import json
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TARGETS = (
    ("2026-09-21_Day", "10:45", "15:40", 1),
    ("2026-09-22_Day", "09:20", "11:45", -1),
)


def stamp(session: str, clock: str) -> pd.Timestamp:
    """機能: セッション日と時分から日本時間の時刻を作る。

    引数: session (str) は保存セッション名、clock (str) は時分。
    返り値: 日本時間の時刻 (Timestamp)。
    """
    return pd.Timestamp(f"{session[:10]}T{clock}:00+09:00")


def audit(symbol: str, session: str, start: str, end: str, side: int) -> dict:
    """機能: 指定された参照波の方向、振幅、押し戻しと検知猶予を記述する。

    引数: symbol/session/start/end (str) は銘柄、セッション、開始時分、終了時分。
    引数: side (int) はロング１またはショート−１。
    返り値: 評価専用の参照波統計 (dict)。未来価格を使うため検知器から呼ばない。
    """
    frame = pd.read_csv(ROOT / "candle_1min" / symbol / f"{session}.csv")
    frame["time"] = pd.to_datetime(frame.time)
    frame = frame[frame.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index()
    begin, finish = stamp(session, start), stamp(session, end)
    part = frame[(frame.index >= begin) & (frame.index < finish)]
    initial, final = float(part.open.iloc[0]), float(part.close.iloc[-1])
    favorable = part.high if side == 1 else part.low
    adverse = part.low if side == 1 else part.high
    moved = side * (part.close.to_numpy() - initial)
    favorable_moves = side * (favorable.to_numpy() - initial)
    adverse_moves = side * (adverse.to_numpy() - initial)
    close_path = np.r_[initial, part.close.to_numpy()]
    max_retrace = float(np.max(np.maximum.accumulate(np.r_[0.0, moved]) - np.r_[0.0, moved]))
    extreme_index = int(np.argmax(favorable_moves))
    result = {
        "銘柄": symbol,
        "セッション": session,
        "指定方向": "ロング" if side == 1 else "ショート",
        "参照開始": begin.isoformat(),
        "参照終了": finish.isoformat(),
        "参照時間_分": (finish - begin).total_seconds() / 60,
        "参照内の最初の足開始": part.index[0].isoformat(),
        "参照内の最後の足開始": part.index[-1].isoformat(),
        "存在足数": len(part),
        "時計時間に対する存在足割合": round(len(part) / ((finish - begin).total_seconds() / 60), 5),
        "参照開始価格": initial,
        "参照終了価格": final,
        "方向付き終点変位": round(side * (final - initial), 5),
        "方向付き最大順行幅": round(float(np.max(favorable_moves)), 5),
        "開始から最大逆行幅": round(float(max(0.0, -np.min(adverse_moves))), 5),
        "終値経路の最大押し戻し": round(max_retrace, 5),
        "最大順行時刻_足開始": part.index[extreme_index].isoformat(),
        "最大順行から終点までの返上幅": round(float(np.max(favorable_moves) - side * (final - initial)), 5),
        "参照開始価格より順方向の終値割合": round(float(np.mean(moved > 0)), 5),
        "終点変位対終値経路長": round(float(side * (final - initial) / np.sum(np.abs(np.diff(close_path)))), 5),
    }
    # ----------------------------------------
    # 遅れて検知した場合に残る波幅を記述する。遅延価格も取引約定ではない。
    for delay in (30, 60):
        at = begin + pd.Timedelta(minutes=delay)
        price = float(frame.loc[frame.index < at].close.iloc[-1])
        result[f"開始{delay}分後の参照価格"] = price
        result[f"開始{delay}分後から終点までの方向付き変位"] = round(side * (final - price), 5)
    # ----------------------------------------
    # 指定時刻の返済根拠として、その時刻に既に存在する直近確定足も記載する。
    cutoff = stamp(session, "15:35")
    known = frame.loc[frame.index + pd.Timedelta(minutes=1) <= cutoff]
    result["返済期限"] = cutoff.isoformat()
    result["期限までの最終確定足開始"] = known.index[-1].isoformat()
    result["期限までの最終確定足終値"] = float(known.close.iloc[-1])
    result["参照開始から返済期限までの方向付き変位"] = round(side * (float(known.close.iloc[-1]) - initial), 5)
    return result


def main() -> None:
    """機能: ４つの銘柄別参照波を監査し、日本語の表を保存する。

    引数: なし。返り値: なし (None)。
    """
    rows = [audit(symbol, *target) for target in TARGETS for symbol in ("NK225", "TOPIX")]
    pd.DataFrame(rows).to_csv(OUT / "対象波監査.csv", index=False, encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
