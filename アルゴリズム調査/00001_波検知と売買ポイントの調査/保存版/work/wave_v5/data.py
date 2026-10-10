"""保存済み五セッションを旧研究と同じ因果的特徴・執行入力へ変換する。"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
V4 = OUT.parent / "wave_v4"
if str(V4) not in sys.path:
    sys.path.insert(0, str(V4))

from engine import TICKS, prepare
from research import SESSIONS as OLD_SESSIONS, SYMBOLS, load_data as load_old_data, read_candle
from signals import build_features


NEW_SESSION = "2026-09-23_Day"
SESSIONS = (*OLD_SESSIONS, NEW_SESSION)


def sha256(path: Path) -> str:
    """元ファイルを変更せずに内容のハッシュを求める。

    引数: path（Path）入力ファイル。
    返り値: str。ＳＨＡ－２５６の十六進表現。
    """
    state = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            state.update(block)
    return state.hexdigest()


def ensure_book_features() -> list[dict]:
    """新日中の生板を旧抽出器で一分特徴へ変換し、自領域だけに保存する。

    引数: なし。
    返り値: list[dict]。入力ハッシュと抽出器の品質情報。既存の同一入力は再利用。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "板特徴抽出記録.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    by_symbol = {item["instrument"]: item for item in existing}
    spec = importlib.util.spec_from_file_location("v5保存板抽出", OUT.parent / "wave_v2" / "book_features.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    audits = []
    changed = False
    for symbol in SYMBOLS:
        source = ROOT / "book" / symbol / f"{NEW_SESSION}.jsonl"
        destination = OUT / f"板特徴_{symbol}_{NEW_SESSION}.csv"
        current_hash = sha256(source)
        prior = by_symbol.get(symbol)
        if prior and destination.exists() and prior["source_sha256"] == current_hash and prior["output_sha256"] == sha256(destination):
            audits.append(prior)
            continue
        rows, audit = module.extract(source)
        changed = True
        with destination.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=module.FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        audit.update(instrument=symbol, output_sha256=sha256(destination),
                     extractor_sha256=sha256(Path(module.__file__)))
        audits.append(audit)
    if changed or not manifest_path.exists():
        manifest_path.write_text(json.dumps(audits, ensure_ascii=False, indent=2), encoding="utf-8")
    return audits


def load_data_v5(cutoff: pd.Timestamp | None = None) -> dict:
    """旧四セッションと新日中を読み込み、両銘柄の執行入力を返す。

    引数: cutoff（Timestamp | None）指定時は新日中だけをこの確定締切まで切る。
    返り値: dict。キーは（セッション名、銘柄）、値は旧 engine.prepare と同じ構造。
    旧四セッションは変更しない。新日中は今回の探索用既知データであり未使用評価ではない。
    """
    ensure_book_features()
    result = load_old_data()
    frames = {}
    for symbol in SYMBOLS:
        one = read_candle(ROOT / "candle_1min" / symbol / f"{NEW_SESSION}.csv")
        five = read_candle(ROOT / "candle_5min" / symbol / f"{NEW_SESSION}.csv")
        if cutoff is not None:
            one = one[one.index + pd.Timedelta(minutes=1) <= cutoff]
            five = five[five.index + pd.Timedelta(minutes=5) <= cutoff]
        frames[symbol] = one, five
    end = cutoff.floor("min") - pd.Timedelta(minutes=1) if cutoff is not None else max(one.index[-1] for one, five in frames.values())
    for symbol, (one, five) in frames.items():
        board = OUT / f"板特徴_{symbol}_{NEW_SESSION}.csv"
        features = build_features(one, five, board, TICKS[symbol], end)
        result[(NEW_SESSION, symbol)] = prepare(one, features, symbol, NEW_SESSION)
    return result


def candle_audit() -> list[dict]:
    """五セッションの全保存足について範囲・確定・価格・出来高を監査する。

    引数: なし。
    返り値: list[dict]。ファイル別の品質情報とハッシュ。
    """
    results = []
    for session in SESSIONS:
        for symbol in SYMBOLS:
            retained = {}
            for minutes in (1, 5):
                path = ROOT / f"candle_{minutes}min" / symbol / f"{session}.csv"
                frame = pd.read_csv(path)
                times = pd.to_datetime(frame.time)
                closed = frame.closed.astype(str).str.lower().eq("true")
                volume_complete = frame.volume_complete.astype(str).str.lower().eq("true")
                assert times.is_monotonic_increasing and not times.duplicated().any()
                assert np.isfinite(frame[["open", "high", "low", "close", "volume"]]).all().all()
                assert frame.low.le(frame[["open", "close"]].min(axis=1)).all()
                assert frame.high.ge(frame[["open", "close"]].max(axis=1)).all()
                assert frame.volume.ge(0).all() and (frame[["open", "high", "low", "close"]] > 0).all().all()
                assert np.isclose(frame[["open", "high", "low", "close"]].to_numpy() / TICKS[symbol] % 1, 0).all()
                session_start = pd.Timestamp(session.split("_")[0], tz="Asia/Tokyo")
                lower = session_start + pd.Timedelta(hours=17 if session.endswith("Night") else 8, minutes=0 if session.endswith("Night") else 45)
                upper = session_start + (pd.Timedelta(days=1, hours=6) if session.endswith("Night") else pd.Timedelta(hours=15, minutes=40))
                assert times.ge(lower).all() and times.lt(upper).all()
                retained[minutes] = frame.assign(time=times).set_index("time")
                results.append(dict(session=session, symbol=symbol, minutes=minutes, rows=len(frame),
                                    first=times.iloc[0].isoformat(), last=times.iloc[-1].isoformat(),
                                    unclosed=int((~closed).sum()), incomplete_volume=int((~volume_complete).sum()),
                                    missing_grid_rows=int((times.iloc[-1]-times.iloc[0]).total_seconds()/(minutes*60))+1-len(frame),
                                    invalid_ohlcv=0, duplicate_times=0, time_reversals=0,
                                    source=str(path.relative_to(ROOT)), sha256=sha256(path)))
            aggregate = retained[1].resample("5min").agg({"open":"first", "high":"max", "low":"min", "close":"last", "volume":"sum"}).dropna()
            five = retained[5][["open", "high", "low", "close", "volume"]]
            assert np.array_equal(aggregate.loc[five.index].to_numpy(float), five.to_numpy(float))
    return results


def prefix_and_contract_audit() -> list[dict]:
    """新原本と前回一度取得した確定部分の一致、板の契約情報を確認する。

    引数: なし。
    返り値: list[dict]。足・板特徴の前方一致と原本の契約・時刻品質。
    """
    snapshot = V4 / "一度取得_2026-09-23_Day"
    cutoff = pd.Timestamp(json.loads((snapshot / "取得記録.json").read_text(encoding="utf-8"))["cutoff"])
    start = pd.Timestamp("2026-09-23T08:45:00+09:00")
    end = pd.Timestamp("2026-09-23T15:40:00+09:00")
    audits = []
    for symbol in SYMBOLS:
        candle_results = []
        for minutes in (1, 5):
            path = ROOT / f"candle_{minutes}min" / symbol / f"{NEW_SESSION}.csv"
            archive = pd.read_csv(path).rename(columns={"volume_complete":"volumeComplete"})
            archive["time"] = pd.to_datetime(archive.time)
            old = pd.DataFrame(json.loads((snapshot / f"{symbol}_{minutes}min.json").read_text(encoding="utf-8"))["data"])
            old["time"] = pd.to_datetime(old.time)
            old = old[old.closed & (old.time+pd.Timedelta(minutes=minutes) <= cutoff)].set_index("time")
            prefix = archive[archive.time+pd.Timedelta(minutes=minutes) <= cutoff].set_index("time")
            pd.testing.assert_frame_equal(prefix[old.columns], old, check_dtype=False, check_exact=True)
            candle_results.append(dict(minutes=minutes, prefix_rows=len(prefix), exact_prefix_match=True,
                                       new_confirmed_rows=len(archive)-len(prefix), new_rows=archive.loc[archive.time+pd.Timedelta(minutes=minutes)>cutoff,"time"].astype(str).tolist()))
        old_board = pd.read_csv(snapshot / f"板特徴_{symbol}_{NEW_SESSION}.csv")
        new_board = pd.read_csv(OUT / f"板特徴_{symbol}_{NEW_SESSION}.csv")
        old_board["available_at"] = pd.to_datetime(old_board.available_at)
        new_board["available_at"] = pd.to_datetime(new_board.available_at)
        old_board = old_board[old_board.available_at <= cutoff].reset_index(drop=True)
        prefix_board = new_board[new_board.available_at <= cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(prefix_board, old_board, check_dtype=False, check_exact=True)
        contracts, counts, last, prices_by_minute = Counter(), Counter(), None, {}
        source = ROOT / "book" / symbol / f"{NEW_SESSION}.jsonl"
        with source.open(encoding="utf-8-sig") as stream:
            for line in stream:
                row = json.loads(line)
                counts["raw_rows"] += 1
                contracts[(str(row.get("Symbol")), str(row.get("SymbolName")), str(row.get("SecurityType")), str(row.get("Exchange")))] += 1
                if not row.get("CurrentPriceTime"):
                    counts["missing_time_rows"] += 1
                    continue
                stamp = pd.Timestamp(row["CurrentPriceTime"])
                if not start <= stamp < end:
                    counts["outside_session_rows"] += 1
                    continue
                if last is not None and stamp < last:
                    raise ValueError("生板の約定時刻が逆行しています")
                last = stamp
                price = row.get("CurrentPrice")
                if not isinstance(price, (int,float)) or not np.isfinite(price) or price <= 0:
                    counts["invalid_price_rows"] += 1
                    continue
                minute = stamp.floor("min")
                if minute not in prices_by_minute:
                    prices_by_minute[minute] = dict(open=price, high=price, low=price, close=price)
                else:
                    item = prices_by_minute[minute]
                    item["high"], item["low"], item["close"] = max(item["high"],price), min(item["low"],price), price
        raw_ohlc = pd.DataFrame.from_dict(prices_by_minute, orient="index").sort_index()
        candles = read_candle(ROOT / "candle_1min" / symbol / f"{NEW_SESSION}.csv")
        differences = []
        for stamp in raw_ohlc.index.intersection(candles.index):
            for key in ("open","high","low","close"):
                if raw_ohlc.loc[stamp,key] != candles.loc[stamp,key]:
                    differences.append(dict(time=stamp.isoformat(), field=key, candle=float(candles.loc[stamp,key]), raw=float(raw_ohlc.loc[stamp,key])))
        audits.append(dict(symbol=symbol, cutoff=cutoff.isoformat(), candle_prefix=candle_results,
                           board_prefix_rows=len(old_board), board_exact_prefix_match=True,
                           board_added_rows=len(new_board)-len(old_board), contracts=[dict(symbol_code=key[0], symbol_name=key[1], security_type=key[2], exchange=key[3], rows=count) for key,count in contracts.items()],
                           raw=dict(counts), source_sha256=sha256(source), raw_candle_ohlc_differences=differences,
                           raw_price_minutes=len(raw_ohlc), candle_minutes=len(candles),
                           raw_only_minutes=[stamp.isoformat() for stamp in raw_ohlc.index.difference(candles.index)],
                           candle_only_minutes=[stamp.isoformat() for stamp in candles.index.difference(raw_ohlc.index)]))
    return audits


def write_report(audit: dict) -> None:
    """データの品質、前回との差、契約情報、読込ＡＰＩを資料にする。

    引数: audit（dict）抽出・足・差分の監査結果。
    返り値: None。データ監査ＭａｒｋｄｏｗｎとＪＳＯＮを自領域へ保存する。
    """
    (OUT / "データ監査.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 五セッションのデータ監査", "",
             "今回の対象は保存済み五セッション、二銘柄。現在ＡＰＩは取得していない。book・candle_1min・candle_5min は読み取りだけに使用し、v4を含む旧成果物は変更していない。2026-09-23_Day は既に前回の答え合わせで参照した日であり、今回は探索用の既知データとして扱う。", "",
             "## 読込ＡＰＩ", "", "`from data import load_data_v5`、`data = load_data_v5()` で `(session, symbol)` をキーとする10入力を得る。値は旧 engine.prepare と同じ one・z・times・values・positions・atr・ref・reg・r2・limit 等。旧四セッションはv4のload_dataをそのまま使用し、新日中だけv5の板特徴を用いて追加する。任意のcutoffは新日中だけに作用し、確定足終了時刻がcutoff以下の範囲を返す。", "",
             "## 足の品質", "", "全20足ファイルに時刻重複・逆行・不正ＯＨＬＣ・負の出来高・呼値違反はなく、各五分足のＯＨＬＣＶは対応する一分足の再集計と完全一致した。欠落分は無約定等で実在足がない区間であり、特徴の価格前方補完を仮想約定には使わない。", "",
             "|セッション|銘柄|１分足数|５分足数|最後の１分足|", "|---|---|---:|---:|---|"]
    for session in SESSIONS:
        for symbol in SYMBOLS:
            one = next(row for row in audit["candles"] if row["session"]==session and row["symbol"]==symbol and row["minutes"]==1)
            five = next(row for row in audit["candles"] if row["session"]==session and row["symbol"]==symbol and row["minutes"]==5)
            lines.append(f"|{session}|{symbol}|{one['rows']}|{five['rows']}|{one['last']}|")
    lines.extend(["", "## 新日中と前回の取得との関係", "",
                  "前回の締切15:39までの確定一分足・確定五分足は両銘柄とも完全一致。追加は15:39開始の一分足と15:35開始の五分足の確定である。前回の15:35五分足は未確定であり、その未確定値を今回の確定値との一致判定に混ぜない。利用可能時刻が15:39以下の板特徴も完全一致した。", "",
                  "|銘柄|新原本の板行数|範囲外除外|時刻欠落|旧板特徴の一致分数|追加特徴分数|生板ＯＨＬＣと保存足の相違項目|", "|---|---:|---:|---:|---:|---:|---:|"])
    for item in audit["new_day"]:
        counts = item["raw"]
        lines.append(f"|{item['symbol']}|{counts['raw_rows']}|{counts.get('outside_session_rows',0)}|{counts.get('missing_time_rows',0)}|{item['board_prefix_rows']}|{item['board_added_rows']}|{len(item['raw_candle_ohlc_differences'])}|")
    lines.extend(["", "生板先頭に前夜の状態が含まれるため、保存一分足に対応する08:45以上15:40未満の約定時刻だけを採用する。同じ最終約定時刻が続くブロックは次の約定時刻まで解放せず、さらに一分の確定後に利用する。末尾ブロックは破棄。板に受信時刻がない限界は以前と同じで、厳密な実約定時刻を復元するものではない。", "",
                  "生板と足に小差がある場合、保存足を価格・約定の正本とし、生板は次時刻待ちによる板特徴として扱う。差分の時刻・価格はＪＳＯＮに全件保存した。", "",
                  "## 原本に記録された契約情報", "", "|通称|Symbol|SymbolName|SecurityType|Exchange|", "|---|---|---|---|---|"])
    for item in audit["new_day"]:
        for contract in item["contracts"]:
            lines.append(f"|{item['symbol']}|{contract['symbol_code']}|{contract['symbol_name']}|{contract['security_type']}|{contract['exchange']}|")
    for item in audit["new_day"]:
        if item["raw_only_minutes"] or item["candle_only_minutes"]:
            lines.extend(["", f"{item['symbol']} の生板にだけ時刻が現れる分: {item['raw_only_minutes']}。保存足にだけ存在する分: {item['candle_only_minutes']}。保存足のない分を新規・返済の実行足として補わない。"])
    lines.extend(["", "この表は保存データの表記であり、限月や取引倍率を外部から補完していない。ＮＫ２２５の価格差は円幅、ＴＯＰＩＸの価格差は指数ポイントで比較し、異なる単位の損益を直接合算しない。契約の乗数を使った金額換算は別途明示する。", "",
                  "## 再生成", "", "`python -X utf8 work/wave_v5/data.py`。新日中の生板特徴は入力・出力ハッシュが一致すれば再利用し、変更時はv5内だけを再作成する。入力ハッシュは監査ＪＳＯＮに記録する。", ""])
    (OUT / "データ監査.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """特徴量の準備と品質監査を実行し、十入力を読み込めることを確認する。

    引数: なし。
    返り値: None。
    """
    feature_audits = ensure_book_features()
    data = load_data_v5()
    assert len(data) == 10 and set(key[0] for key in data) == set(SESSIONS)
    print("データ読込準備完了: 5セッション × 2銘柄", flush=True)
    audit = dict(api_requested=False, sessions=list(SESSIONS), prepared_inputs=len(data),
                 book_features=feature_audits, candles=candle_audit(), new_day=prefix_and_contract_audit())
    audit["source_sha256"] = {str(path.relative_to(ROOT)): sha256(path)
                              for directory in ("book", "candle_1min", "candle_5min")
                              for path in sorted((ROOT / directory).glob("*/*"))
                              if path.is_file() and path.stem in SESSIONS}
    write_report(audit)
    print(json.dumps(audit["new_day"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
