"""00139の入力所在を固定し、追加夜間の非金融準備と登録後の元通知接続を分離する。"""

import argparse
import ast
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT / "work/update132_20261021"
NEW_SCENES = ("2026-10-21_Night", "2026-10-22_Day")
AUTHORIZATION = None
sys.dont_write_bytecode = True


def read(path):
    """
    機能: 保存目録を読む。
    引数: path(Path又はstr)は対象位置。
    返り値: dict又はlistはJSONの内容。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    """
    機能: 今回所有域へ新規JSONを保存する。
    引数: path(Path)、value(dict又はlist)は保存位置と値。
    返り値: None。既存成果と原本を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def digest(path):
    """
    機能: ファイルの実内容指紋を計算する。
    引数: path(Path)は読み取り対象。
    返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reference(path):
    """
    機能: 絶対位置と相対位置を同じ内容指紋へ結び付ける。
    引数: path(Path)は実在ファイル。
    返り値: dictはpath、relative_path、sha256。
    """
    path = path.resolve()
    return dict(path=path.as_posix(), relative_path=path.relative_to(ROOT).as_posix(), sha256=digest(path))


def module(name, path):
    """
    機能: 元実装を変更せず明示位置から読み込む。
    引数: name(str)、path(Path)はモジュール名と位置。
    返り値: moduleは読み込んだ既存処理。読み込みだけで金融再生しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def manifest_known():
    """
    機能: 既知45場の両銘柄入力・元注文を内容照合して一覧化する。
    引数: なし。
    返り値: None。保存済み結果の所在を確認し、金融関数は実行しない。
    """
    old = read(ROOT / "work/daynight128_20261020/入力準備.json")["packets"]
    new = read(PREVIOUS / "inputs_v1/input_manifest.json")["packets"]
    ledgers = {folder: read(ROOT / f"work/regime131_20261020/{folder}/全条件の会計.json") for folder in ("round3", "round4")}
    newer = read(PREVIOUS / "results/追加セッションの会計.json")
    references, packets = [], []
    for p in old + new:
        scene = p["session"]
        item_input = reference(ROOT / p["path"])
        assert item_input["sha256"] == p["sha256"], p["path"]
        packets.append(dict(session=scene, **item_input))
        for symbol in ("NK225", "TOPIX"):
            method = "T06" if scene.endswith("_Day") else ("U06" if symbol == "NK225" else "T04")
            folder = "round4" if method == "U06" else "round3"
            additional = scene in ("2026-10-20_Night", "2026-10-21_Day")
            ledger = newer if additional else ledgers[folder]
            saved = next(row for row in ledger["cache"] if row["session"] == scene and row["symbol"] == symbol)
            item_orders = reference(ROOT / saved["path"])
            assert item_orders["sha256"] == saved["sha256"], saved["path"]
            prefix = "" if additional else method + "__"
            with np.load(item_orders["path"], allow_pickle=False) as arrays:
                shapes = {name: list(arrays[prefix + name].shape) for name in ("core_orders", "extra_orders")}
            references.append(dict(session=scene, symbol=symbol, method=method, input=item_input,
                                   orders=item_orders, prefix=prefix or "なし", shapes=shapes))
    assert len(packets) == 45 and len(references) == 90
    save(HERE / "manifest139.json", dict(passed=True, sessions=[p["session"] for p in packets], packets=packets,
         references=references, financial_replays=0, API=0, real_orders=0,
         scope="00137・00138と同じ既知45場。全指紋を今回読み直して照合。金融結果を再実行していない。"))
    print("既知45場・90商品場の内容照合完了", flush=True)


def audit_night_book(path):
    """
    機能: 追加夜間原板の指紋・場内時計・研究返済時刻への到達を調べる。
    引数: path(Path)は2026-10-21_Nightの原板。
    返り値: dictは素材監査。価格値から注文や収益を求めない。
    """
    before = path.stat()
    sha = hashlib.sha256()
    begin, end = "2026-10-21T17:00:00+09:00", "2026-10-22T06:00:00+09:00"
    first = last = previous = None
    rows = bad = stale = after_end = backwards = normal = 0
    with path.open("rb") as stream:
        for line in stream:
            rows += 1
            sha.update(line)
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                bad += 1
                continue
            stamp = row.get("CurrentPriceTime")
            if not stamp or stamp < begin:
                stale += 1
                continue
            if stamp > end:
                after_end += 1
                continue
            first = first or stamp
            last = stamp
            backwards += bool(previous and stamp < previous)
            previous = stamp
            bid, ask = (row.get("Buy1") or {}).get("Price"), (row.get("Sell1") or {}).get("Price")
            normal += bool(bid and ask and 0 < bid < ask)
    after = path.stat()
    result = dict(path=path.relative_to(ROOT).as_posix(), bytes=before.st_size, mtime_ns=before.st_mtime_ns,
        sha256=sha.hexdigest(), rows=rows, invalid_json=bad, earlier_or_null_clocks=stale,
        after_end_clocks=after_end, backwards_price_clocks=backwards, normal_bbo_rows=normal,
        first_session_price_clock=first, last_session_price_clock=last,
        unchanged_during_read=(before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
        reaches_force_close=bool(last and last > "2026-10-22T05:50:00+09:00"))
    assert result["unchanged_during_read"] and result["reaches_force_close"] and bad == 0
    return result


def prepare_extra():
    """
    機能: 未作成の追加夜間だけを元132の処理で非金融準備し、翌日既存入力と別目録にする。
    引数: なし。
    返り値: None。通常影・注文核・金融会計は呼ばず、元データを変更しない。
    """
    audit = module("audit134_for139", ROOT / "work/update134_20261022/audit134.py")
    materials = []
    for symbol in ("NK225", "TOPIX"):
        materials.append(audit_night_book(ROOT / "book" / symbol / (NEW_SCENES[0] + ".jsonl")))
        for folder, minutes in (("candle_1min", 1), ("candle_5min", 5)):
            materials.append(audit.audit_candle(ROOT / folder / symbol / (NEW_SCENES[0] + ".csv"), minutes))
    inventory = HERE / "追加夜間の素材監査.json"
    save(inventory, dict(new_complete_file_sets=[NEW_SCENES[0]], materials=materials,
                        financial_replays=0, API=0, real_orders=0))
    preparation = module("prepare132_for139", PREVIOUS / "prepare_inputs132.py")
    preparation.HERE = HERE
    preparation.prepare(HERE / "extra_inputs", (NEW_SCENES[0],), inventory)
    # ----------------------------------------
    # 翌デイは既存preparedを再利用し、追加条件の選択に混ぜない目録として隔離する。
    night = read(HERE / "extra_inputs/input_manifest.json")["packets"][0]
    day = read(ROOT / "work/update134_20261022/inputs/input_manifest.json")["packets"][0]
    packets = []
    for item in (night, day):
        ref = reference(ROOT / item["path"])
        assert ref["sha256"] == item["sha256"]
        packets.append(dict(session=item["session"], **ref))
    existing = ROOT / "work/update134_20261022/results/measurement/TOPIX_2026-10-22_Day.npz"
    save(HERE / "manifest139_extra.json", dict(passed=True, sessions=list(NEW_SCENES), packets=packets,
         existing_orders=[dict(session=NEW_SCENES[1], symbol="TOPIX", method="T06", prefix="なし", **reference(existing))],
         need_source_orders=[dict(session=scene, symbol=symbol) for scene, symbol in
                             ((NEW_SCENES[0], "TOPIX"), (NEW_SCENES[0], "NK225"), (NEW_SCENES[1], "NK225"))],
         financial_replays=0, API=0, real_orders=0,
         scope="追加2場の特徴入力だけ。既知45場で条件を固定した後の追加確認用。既に価格診断・TOPIX当日結果を見ているため完全未知標本ではない。"))
    print("追加2場の非金融目録完了", flush=True)


def source_fingerprints():
    """
    機能: 元通知を生成する全数値源と今回接続を事前登録用に列挙する。
    引数: なし。
    返り値: dict[str,str]は相対位置からSHA256への対応。金融関数は呼ばない。
    """
    driver = module("selected132_fingerprint139", PREVIOUS / "run_selected132_v2.py")
    sources = driver.source_fingerprints()
    sources[Path(__file__).relative_to(ROOT).as_posix()] = digest(Path(__file__))
    return sources


def authorize_sources(plan_path, registered_path):
    """
    機能: 元通知の再生を、今回実装を含む正式登録済み計画へ限定する。
    引数: plan_path/registered_path(Path又はstr)は計画と登録応答。
    返り値: None。不足・指紋相違なら例外で中止する。
    """
    global AUTHORIZATION
    plan, registered = read(plan_path), read(registered_path)
    assert registered["returncode"] == 0, "元通知の金融再生には正式登録が必要です"
    expected = source_fingerprints()
    locked = plan["spec"]["implementation"]
    assert all(locked.get(path) == sha for path, sha in expected.items()), "元通知の全数値源が計画へ固定されていません"
    AUTHORIZATION = dict(sessions=set(plan["spec"]["data"]["sessions"]), sources=expected,
                         plan=reference(Path(plan_path)), registered=reference(Path(registered_path)))


def source_orders(packet, symbol):
    """
    機能: 登録後のみ既存132の同一数値核で指定商品だけの元主担当・補完通知を生成する。
    引数: packet(dict)は固定prepared、symbol(str)はTOPIX又はNK225。
    返り値: dictはcore_orders/extra_ordersの12列配列、source_account、audit。
    """
    assert AUTHORIZATION is not None, "先にauthorize_sourcesで正式登録を確認してください"
    assert packet["session"] in AUTHORIZATION["sessions"] and symbol in ("TOPIX", "NK225")
    assert source_fingerprints() == AUTHORIZATION["sources"], "登録後に元通知の数値源が変化しました"
    driver_path = PREVIOUS / "run_selected132_v2.py"
    driver = module("selected132_source139", driver_path)
    driver.validate_packet(packet, packet["session"])
    # ----------------------------------------
    # 元replayの対象商品ループだけを絞る。元ファイルと全数値式は変更しない。
    tree = ast.parse(driver_path.read_text(encoding="utf-8-sig"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "replay")
    loops = [node for node in ast.walk(function) if isinstance(node, ast.For) and
             isinstance(node.target, ast.Name) and node.target.id == "symbol"]
    assert len(loops) == 1 and ast.literal_eval(loops[0].iter) == ("TOPIX", "NK225")
    loops[0].iter = ast.Tuple(elts=[ast.Name(id="requested_symbol", ctx=ast.Load())], ctx=ast.Load())
    namespace = dict(driver.__dict__, requested_symbol=symbol)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(driver_path), "exec"), namespace)
    with driver.modules(HERE / "jit_source") as loaded:
        result = namespace["replay"](loaded, packet, driver.configurations())
    assert len(result) == 1 and result[0][0]["symbol"] == symbol
    row, arrays = result[0]
    return dict(core_orders=arrays["core_orders"], extra_orders=arrays["extra_orders"], source_account=row,
                audit={key: value for key, value in arrays.items() if key not in ("core_orders", "extra_orders")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("manifest", "prepare"))
    args = parser.parse_args()
    {"manifest": manifest_known, "prepare": prepare_extra}[args.stage]()
