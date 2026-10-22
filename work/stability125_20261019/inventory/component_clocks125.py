"""所有済み標本だけで、受信時計と市場コンポーネント時計の有無を区別する。"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
OLD = ROOT / "work/stability124_20261019"


def save(name: str, value: Any) -> None:
    """
    機能: 新しい時刻診断を所有領域へ保存する。
    引数: name (str) 保存名、value (Any) JSON 化可能な内容。
    返り値: None。
    """
    path = HERE / name
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clock_fields(value: Any, prefix: str = "") -> dict[str, Any]:
    """
    機能: ネストを含む時刻・受信・連番らしい項目を列挙する。
    引数: value (Any) JSON 値、prefix (str) 現在の階層。
    返り値: dict[str, Any] 完全パスと値。
    """
    found = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else key
            lowered = key.lower()
            if any(token in lowered for token in ("time", "timestamp", "received", "sequence")) or lowered in {"seq", "datetime", "date"}:
                found[name] = item
            found.update(clock_fields(item, name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.update(clock_fields(item, f"{prefix}[{index}]"))
    return found


def boundary_lines(path: pathlib.Path) -> list[dict[str, Any]]:
    """
    機能: 所有先物コピーの先頭三行と末尾三行だけを保存する。
    引数: path (Path) 124 の既所有原本コピー。
    返り値: list[dict] 行位置・同一性・生 JSON・時刻項目。
    """
    result = []
    before = path.stat()
    with path.open("rb") as handle:
        for _ in range(3):
            offset = handle.tell()
            line = handle.readline()
            if not line:
                break
            row = json.loads(line)
            result.append({"offset": offset, "sha256": hashlib.sha256(line).hexdigest(), "row": row, "time_fields": clock_fields(row)})
        handle.seek(max(0, before.st_size - 32768))
        if handle.tell() > 0:
            handle.readline()
        start = handle.tell()
        raw = handle.read(before.st_size - start)
        lines = raw.splitlines(keepends=True)
        offsets = []
        for line in lines:
            offsets.append(start)
            start += len(line)
        for offset, line in list(zip(offsets, lines))[-3:]:
            if offset in {item["offset"] for item in result}:
                continue
            row = json.loads(line)
            result.append({"offset": offset, "sha256": hashlib.sha256(line).hexdigest(), "row": row, "time_fields": clock_fields(row)})
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return result


def main() -> None:
    """
    機能: オプション標本と新デイ先物の所有境界だけを検査し、時計の推定可能範囲を記録する。
    引数: なし。
    返り値: None。元 book・CSV・金融 cache・API を読まない。
    """
    full_path = OLD / "inventory/オプション生JSONの少数標本.json"
    schema_path = OLD / "inventory/オプション保存項目と時刻の標本確認.json"
    bounds_path = OLD / "inventory/オプション保存608ファイルの境界目録.json"
    full = json.loads(full_path.read_bytes())
    schema = json.loads(schema_path.read_bytes())
    boundaries = json.loads(bounds_path.read_bytes())
    option_fields = sorted({key for item in full for key in clock_fields(item["row"])})
    schema_fields = sorted(key for key in schema["トップレベル項目と標本型"] if "time" in key.lower() or "received" in key.lower() or "sequence" in key.lower())
    option_samples = [{"path": item["path"], "offset": item["offset"], "time_fields": clock_fields(item["row"])} for item in full]
    counter = collections.Counter()
    examples = []
    for file in boundaries:
        samples = sorted(file["samples"], key=lambda item: item["offset"])
        for left, right in zip(samples, samples[1:]):
            a, b = left["fields"], right["fields"]
            if (a["CurrentPriceTime"], a["TradingVolumeTime"]) != (b["CurrentPriceTime"], b["TradingVolumeTime"]):
                continue
            counter["両約定関連時計が同じ隣接標本対"] += 1
            bbo_changed = tuple((a[side] or {}).get(key) for side in ("Buy1", "Sell1") for key in ("Price", "Qty")) != tuple((b[side] or {}).get(key) for side in ("Buy1", "Sell1") for key in ("Price", "Qty"))
            greek_changed = any(a[key] != b[key] for key in ("IV", "Delta", "Gamma", "Theta", "Vega"))
            counter["同じ両時計で最良気配価格または数量が変化"] += bbo_changed
            counter["同じ両時計でIVまたはGreeksが変化"] += greek_changed
            if (bbo_changed or greek_changed) and len(examples) < 8:
                examples.append({"path": file["path"], "left": left, "right": right, "bbo_changed": bbo_changed, "greeks_changed": greek_changed})
    # ----------------------------------------
    manifest_path = OLD / "追加原本入力目録.json"
    manifest = json.loads(manifest_path.read_bytes())
    futures = []
    for item in manifest["inputs"]:
        if item["kind"] != "book":
            continue
        path = ROOT / item["staged_path"]
        assert path.resolve().is_relative_to(OLD / "inputs/book") and path.stat().st_size == item["bytes"]
        rows = boundary_lines(path)
        futures.append({"symbol": item["symbol"], "session": item["session"], "path": item["staged_path"], "inherited_full_sha256": item["sha256"], "今回の全体hash再計算": False, "sampled_rows": len(rows), "all_top_level_fields": sorted({key for row in rows for key in row["row"]}), "time_field_paths": sorted({key for row in rows for key in row["time_fields"]}), "samples": rows})
    save("既所有標本の全Time項目と先物新デイ境界.json", {"オプション少数生JSON": option_samples, "少数生JSONのネストを含む時計項目": option_fields, "オプション2866標本のトップレベル時計項目": schema_fields, "先物": futures, "option同時計の反例数": dict(counter), "option代表反例": examples, "読取": {"原本追加": 0, "原option全行": 0, "金融cache": 0, "124所有先物コピー": "2本の先頭末尾各3行のみ", "API": 0, "金融再生": 0}})
    conclusion = {"passed": True, "判断対象": "新しい金融効果ではなく保存項目と時計の意味だけ", "保存された時計項目": schema_fields, "オプション受信時計": "標本に独立項目なし。collectorのメモリreceivedAtがpayloadへ保存されないことは124でsource確認済み。", "オプションBBO市場イベント時計": "2866標本の全トップレベル項目および8生JSONのネストにBidTime/AskTime/Buy1.Time/Sell1.Time等を確認できない。全608ファイル全行の不存在を証明した調査ではない。", "オプションIVとGreeks時計": "同標本にIVTime/DeltaTime/計算時刻等は見つからない。", "新Day先物": {row["symbol"]: {"time_field_paths": row["time_field_paths"], "sampled_rows": row["sampled_rows"]} for row in futures}, "同じ約定関連時計での反例": dict(counter), "最大コンポーネント時計案": "CurrentPriceTimeとTradingVolumeTimeの最大値は、価格・累積出来高の市場時刻についての下限的情報にはなるが、時刻を持たないBBO/IVの当時利用可能時刻の上限にはならない。BBO/IVが更新されても両時計が同じ実標本がある。", "仮にBBO時計が保存されていた場合": "BBO成分とLast・出来高成分の各イベント時刻の最大値以降でのみ使用する条件は、古い価格時刻へ新しい気配を戻す誤結合を減らせる。ただし市場eventTimeは受信時刻でなく、通信遅延・二市場共通受信順は未確定。各成分の時計が本当に同payloadの値へ対応すること、逆行・欠測・同時刻末尾をどう扱うかの検査が別途必要。", "既知調査との関係": [{"source": "00093_押し回復と両市場再確認の待機入口", "重複": "価格gapによる候補取消と原seqの連続性を既に確認。sourceはwork/wave_v97。"}, {"source": "00094_価格時計と観測源を分ける待機改修", "重複": "4時計政策を既に金融比較。価格時計gapと真の受信断裂を区別。同clockの板変更、共通受信順不明、先物気配時刻非対応を記録。sourceはwork/wave_v98。"}, {"source": "00095_現在方向の価格源を分ける待機検証", "重複": "取引価格源とBBO源を分離。相手は厳密過去・同時計先頭で接頭不変を確認。sourceはwork/wave_v99。"}, {"source": "00096_元候補からの入口価格上限と安定性", "重複": "時計の独立受信情報を新規に獲得した調査ではなく、既候補からの価格上限変更。"}, {"source": "00097_初回小枚数と利益で支える増玉の安定性 / 00098_増玉の停止余裕と線保全の再検証", "重複": "枚数・停止線の比較。時刻不明を解消する新データではない。"}], "今回の差分": "新しいoptionファイルの時計項目を分類し、10月19日Dayの先物所有コピーの少数境界にも同じ制約が残るかを確認。旧全場や旧金融は再実行しない。", "次の有用な改善": "今後の収集で各payloadにローカル受信UTC・単調時計・共通global_seq・接続epochを別sidecarまたは封筒として残す。市場eventTimeと別保存し、過去ファイルに推定追加しない。現在の検証は価格時刻代理上の仮定と明記する。", "金融再生": 0, "原本追加読取": 0}
    save("受信時計とBBOイベント時計を区別した小結.json", conclusion)
    print(json.dumps({"オプション全トップレベルTime": schema_fields, "先物": conclusion["新Day先物"], "反例数": dict(counter), "金融再生": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
