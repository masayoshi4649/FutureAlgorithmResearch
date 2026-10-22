"""公表板の原行順から、固定30秒の価格応答と出来高方向代理を作る。"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
from numba import njit

from common130 import HERE, ROOT, BASE, read, reference

DEST = HERE / "prepared"
RAW = HERE / "activity_raw"
COLUMNS = ["気配中値の30秒差", "30秒の公表出来高正増分", "買い代理量から売り代理量を引いた値", "既知フラグ"]


@njit(cache=False)
def calculate(times, last, volume, bid, ask, sequences, quote_valid):
    """
    機能: 未来の同時計原行も参照せず、固定30秒の公表活動を計算する。
    引数: times/last/volume/bid/ask(ndarray[float])、sequences(ndarray[int])、quote_valid(ndarray[bool])。
    返り値: tuple[ndarray,ndarray,ndarray]は特徴4列、始端原行、窓の内訳5列。
    例外: ValueErrorは価格時計が非有限又は逆行する入力。有限・単調非減少が前提。
    """
    n = len(times)
    for i in range(n):
        if not np.isfinite(times[i]) or (i > 0 and times[i] < times[i-1]):
            raise ValueError("価格時計は有限かつ単調非減少でなければなりません")
    output = np.full((n, 4), np.nan)
    output[:, 3] = 0.
    anchors = np.full(n, -1, np.int64)
    details = np.full((n, 5), np.nan)
    known = np.zeros(n, np.bool_)
    buys, sells, others, pos = [np.zeros(n) for _ in range(4)]
    invalid = np.zeros(n, np.int64)
    mids = np.full(n, np.nan)
    for i in range(n):
        known[i] = quote_valid[i] and np.isfinite(times[i]) and np.isfinite(last[i])
        known[i] = known[i] and np.isfinite(volume[i]) and volume[i] >= 0.
        known[i] = known[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0. < bid[i] < ask[i]
        if known[i]:
            mids[i] = (bid[i] + ask[i]) / 2.
        if i == 0:
            continue
        buys[i], sells[i], others[i], pos[i], invalid[i] = buys[i-1], sells[i-1], others[i-1], pos[i-1], invalid[i-1]
        valid_edge = known[i] and known[i-1] and sequences[i] == sequences[i-1] + 1
        valid_edge = valid_edge and times[i] >= times[i-1] and volume[i] >= volume[i-1]
        if not valid_edge:
            invalid[i] += 1
            continue
        dv = volume[i] - volume[i-1]
        pos[i] += dv
        if dv > 0.:
            if last[i] >= ask[i-1]:
                buys[i] += dv
            elif last[i] <= bid[i-1]:
                sells[i] += dv
            else:
                others[i] += dv
    # ----------------------------------------
    # 各判断時点までの累計差だけを使う。同時計の後続行は累計に入れない。
    for i in range(n):
        a = np.searchsorted(times, times[i] - 30., side="left") - 1
        anchors[i] = a
        if a < 0:
            continue
        bad = invalid[i] - invalid[a]
        details[i] = np.array([buys[i]-buys[a], sells[i]-sells[a], others[i]-others[a], float(bad), times[i]-30.-times[a]])
        if not known[i] or not known[a] or bad > 0 or times[i]-30.-times[a] > 30.:
            continue
        output[i, 0] = mids[i] - mids[a]
        output[i, 1] = pos[i] - pos[a]
        output[i, 2] = (buys[i] - buys[a]) - (sells[i] - sells[a])
        output[i, 3] = 1.
    return output, anchors, details


def val(value: object) -> float:
    """
    機能: 欠測を補完せず原資料の数値を読む。
    引数: value(object)は公表値。
    返り値: floatは値又はNaN。
    """
    return float(value) if isinstance(value, (int, float)) else np.nan


def dump(path: Path, value: dict) -> None:
    """
    機能: 新作業の非金融特徴に付属する出典を保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")


def prepare_one(ref: dict, symbol: str) -> dict:
    """
    機能: 一場一商品の原板を保存原行へ対応させ、非金融特徴を作る。
    引数: ref(dict)は既存入力の指紋、symbol(str)は商品。
    返り値: dictは原データ・入力・出力の指紋と品質件数。
    """
    scene = ref["session"]
    packet = pickle.loads((ROOT / ref["path"]).read_bytes())
    rd, quote = packet["inputs"][(scene, symbol)], packet["quotes"][(scene, symbol)]
    source = ROOT / "book" / symbol / f"{scene}.jsonl"
    cached = RAW / f"{symbol}_{scene}.npz"
    if cached.exists():
        data = dict(np.load(cached))
        source_info = read(cached.with_suffix(".json"))
        assert source_info["bytes"] == source.stat().st_size
        assert source_info["mtime_ns"] == source.stat().st_mtime_ns
    else:
        original = source.stat()
        last, volume, bid, ask = [np.full(len(rd["seq"]), np.nan) for _ in range(4)]
        digest = hashlib.sha256()
        pointer = 0
        with source.open("rb") as handle:
            for seq, line in enumerate(handle):
                digest.update(line)
                if pointer >= len(rd["seq"]) or seq != rd["seq"][pointer]:
                    continue
                obj = json.loads(line)
                last[pointer] = val(obj.get("CurrentPrice"))
                volume[pointer] = val(obj.get("TradingVolume"))
                bid[pointer] = val(obj.get("Buy1", {}).get("Price"))
                ask[pointer] = val(obj.get("Sell1", {}).get("Price"))
                pointer += 1
        assert pointer == len(rd["seq"])
        assert source.stat().st_size == original.st_size and source.stat().st_mtime_ns == original.st_mtime_ns
        assert np.array_equal(last, rd["last"], equal_nan=True)
        assert np.array_equal(bid, quote["bid"], equal_nan=True)
        assert np.array_equal(ask, quote["ask"], equal_nan=True)
        data = dict(last=last, volume=volume, bid=bid, ask=ask)
        RAW.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cached, **data)
        source_info = dict(path=source.relative_to(ROOT).as_posix(), sha256=digest.hexdigest(),
            bytes=original.st_size, mtime_ns=original.st_mtime_ns, mapped_rows=pointer)
        dump(cached.with_suffix(".json"), source_info)
    activity, anchor, details = calculate(rd["time_s"], data["last"], data["volume"], data["bid"], data["ask"],
        rd["seq"], quote["quote_valid"])
    DEST.mkdir(parents=True, exist_ok=True)
    target = DEST / f"{symbol}_{scene}.npz"
    np.savez_compressed(target, activity=activity, anchor_row=anchor, details=details,
        time_s=rd["time_s"], seq=rd["seq"])
    result = dict(session=scene, symbol=symbol, source=source_info, packet=ref,
        output=reference(target), rows=len(activity), known=int((activity[:, 3] == 1.).sum()),
        sequence_gaps=int((np.diff(rd["seq"]) != 1).sum()))
    print(scene, symbol, "非金融原板特徴", result["known"], "/", len(activity), flush=True)
    return result


def main() -> None:
    """
    機能: 全21夜間の2商品を固定式で非金融特徴へ変換する。
    引数: コマンド引数--workers(int)は独立ファイル処理の並列数。
    返り値: None。注文核や金融会計を実行しない。
    """
    parser = argparse.ArgumentParser(description="夜間原板の固定30秒活動を非金融で準備")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    refs = [r for r in read(BASE / "入力準備.json")["packets"] if r["session"].endswith("_Night")]
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(prepare_one, ref, symbol) for ref in refs for symbol in ("TOPIX", "NK225")]
        for future in as_completed(futures):
            results.append(future.result())
    dump(HERE / "原板活動の非金融準備.json", dict(passed=True, financial_replays=0,
        columns=COLUMNS, details_columns=["買い代理量", "売り代理量", "曖昧量", "未知接続件数", "始端の古さ秒"],
        source=reference(Path(__file__)), inputs=sorted(results, key=lambda r: (r["session"], r["symbol"])),
        rule="t−30秒より厳密前の最終原行から判断行までの公表増分。始端古さ30秒以内。",
        unknown="必要欠測・不正気配・原行飛び・出来高逆戻りを一つでも含む窓は未知。未知を0にしない。",
        same_clock="同時計は原行順で加算し、当行の後の同時計原行は不使用。",
        proxy="正増分を当行Last>=前行askなら買い、Last<=前行bidなら売り、間内は曖昧。真の成行方向ではない。"))


if __name__ == "__main__":
    main()
