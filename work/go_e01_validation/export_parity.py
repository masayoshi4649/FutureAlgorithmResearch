"""既存 Python E01 を変更せず、Go 移植の検査用入力と正解注文を出力する。"""

from pathlib import Path
import argparse
import gzip
import importlib.util
import json
import math
import pickle
import sys

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "アルゴリズム調査/00045_E01リアルタイム仮想トレード/papertrade"
sys.path.insert(0, str(PYTHON))
from strategy import E01Engine
from features import FeatureEngine


def export_features() -> None:
    """機能: 公開待機・中値封印・欠測を含む特徴量の元実装正解を保存する。

    引数: なし。返り値: なし(None)。
    """
    engine = FeatureEngine("検査_Day", 0)
    actions = []
    for symbol, scale in (("TOPIX", 1), ("NK225", 20)):
        for interval, count in ((300, 18), (60, 90)):
            candles = []
            for i in range(count):
                close = (1000 + i * interval / 60) * scale
                candles.append(dict(time=i * interval, open=close, high=close + 2 * scale, low=close - 2 * scale, close=close, closed=True))
            engine.ingest_candles(symbol, interval, candles, 5700)
            actions.append(dict(kind="candles", symbol=symbol, interval=interval, received=5700, candles=candles))
    for i in range(900):
        at = 5760 + i * 2 + (70 if i >= 600 else 0)
        quoted = at - (2 if i % 15 == 1 else 0)
        for symbol, scale in (("TOPIX", 1), ("NK225", 20)):
            mid = scale * (1100 + 12 * math.sin(i / 70) + i * .015)
            book = dict(QuoteTime=quoted, Price=mid + (4 if i % 3 == 0 else 0), Bid=mid - .5 * scale, Ask=mid + .5 * scale, BidQty=2, AskQty=3)
            if i % 177 == 0:
                book["BidQty"] = 0
            raw = dict(CurrentPriceTime=book["QuoteTime"], CurrentPrice=book["Price"], Buy1=dict(Price=book["Bid"], Qty=book["BidQty"]), Sell1=dict(Price=book["Ask"], Qty=book["AskQty"]))
            output = engine.on_book(symbol, raw, at)
            fields = ("atr", "main_direction", "peer_direction", "allowed_direction", "ema_fast", "ema_slow", "direction", "adverse", "adverse_source", "input_index")
            actions.append(dict(kind="book", symbol=symbol, received=at, book=book, expected=[output[k] or 0 for k in fields]))
    target = ROOT / "App/E01/internal/strategy/testdata/python_features.json.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(json.dumps(actions, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"), mtime=0))


def evaluate(symbol: str, session: dict, rows: list, mode: str) -> dict:
    """機能: 元実装へ順番に入力して検査台帳を作る。

    引数: symbol(str)、session(dict)、rows(list)、mode(str)。
    返り値: 検査入力と正解(dict)。
    """
    engine = E01Engine(symbol, session["id"], session["start"], session["force_close"], session["close"], fill_mode=mode)
    orders = []
    for i, row in enumerate(rows):
        t, price, atr, direction, adverse, source = row
        for e in engine.on_tick(t, price, atr, int(direction), int(adverse), int(source), input_index=i):
            orders.append([e["row"], e["source_row"], e["campaign"], e["direction"] if e["event"] == "新規" else -e["direction"], e["quantity"], e["price"], e["reason_code"], int(e["event"] == "新規")])
    result = dict(symbol=symbol, session=session, mode=mode, ticks=rows, orders=orders, realized=engine.status()["realized_yen"])
    print(json.dumps({k: v for k, v in result.items() if k not in ("ticks", "orders")}, ensure_ascii=False), "注文数", len(orders), flush=True)
    return result


def main() -> None:
    """機能: 合成検査系列又は保存実データから圧縮検査ファイルを出力する。

    引数: なし。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical", action="store_true")
    args = parser.parse_args()
    cases = []
    if args.historical:
        spec = importlib.util.spec_from_file_location("移植照合旧信号", ROOT / "work/wave_v48/update_20261001/replay_added_session.py")
        old = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = old
        spec.loader.exec_module(old)
        folder = ROOT / "work/wave_v50/update_20261002_two"
        inputs = pickle.loads((folder / "new_inputs.pkl").read_bytes())
        features = pickle.loads((folder / "new_features_depth.pkl").read_bytes())
        signals = old.signals(inputs, features, ROOT)
        ledger = {(r["session"], r["symbol"]): r for r in json.loads(gzip.decompress((folder / "ledgers/E01.json.gz").read_bytes()))}
        for key, ready in sorted(inputs.items()):
            direction, bad = signals["entry"][key], signals["B00"][key]
            rows = [[float(t), float(p), float(a) if math.isfinite(a) else 0.0, int(d), int(b), int(s)] for t, p, a, d, b, s in zip(ready["time_s"], ready["last"], ready["atr"], direction, bad["direction"], bad["source_row"])]
            session = dict(id=key[0], start=float(ready["start"]), force_close=float(ready["limit"]), close=float(ready.get("session_close", ready["limit"] + 600)))
            case = evaluate(key[1], session, rows, "specified")
            assert case["orders"] == ledger[key]["orders"], "既存研究台帳との不一致"
            cases.append(case)
        target = ROOT / "work/go_e01_validation/historical_orders.json.gz"
    else:
        export_features()
        for symbol, scale in (("TOPIX", 1), ("NK225", 20)):
            rows = []
            for i in range(7400):
                price = scale * (1000 + 30 * math.sin(i / 60) + 12 * math.sin(i / 11))
                price = round(price / (.5 * scale)) * .5 * scale
                direction = 1 if math.cos(i / 60) > 0 else -1
                if i % 251 < 9:
                    direction = 0
                adverse = -direction if i % 91 < 7 else 0
                rows.append([800 + i * 4, price, scale * (10 + 3 * math.sin(i / 400)), direction, adverse, i])
            for mode in ("specified", "observed"):
                cases.append(evaluate(symbol, dict(id="合成_Day", start=0, force_close=30000, close=30600), rows, mode))
        target = ROOT / "App/E01/internal/strategy/testdata/python_orders.json.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(json.dumps(cases, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"), mtime=0))
    print(target, flush=True)


if __name__ == "__main__":
    main()
