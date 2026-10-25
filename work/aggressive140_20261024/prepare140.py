"""新配置の保存素材を監査し、旧数式のまま追加3場の非金融入力を作る。"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT.parent / "JP_OSE_Data"
PREVIOUS = ROOT / "work/update132_20261021/prepare_inputs132.py"
SCENES = ("2026-10-22_Night", "2026-10-23_Day", "2026-10-23_Night")
sys.dont_write_bytecode = True


def read(path):
    """
    機能: UTF-8の既存目録を読む。
    引数: path(Path)は目録位置。
    返り値: dict又はlistは読取内容。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    """
    機能: 所有域に新規資料だけを保存する。
    引数: path(Path)、value(dict又はlist)は保存先と値。
    返り値: None。原本と既存成果の上書きを拒否する。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def digest(path):
    """
    機能: 内容を変更せずSHA256を計算する。
    引数: path(Path)は入力ファイル。
    返り値: strは内容指紋。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_module(name, path):
    """
    機能: 元実装を変更せず明示位置から読み込む。
    引数: name(str)、path(Path)は登録名と実装位置。
    返り値: moduleは読込済み実装。金融処理は呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def scene_bounds(scene):
    """
    機能: 素材監査の場内窓と既存研究の返済時刻を得る。
    引数: scene(str)はセッション名。
    返り値: tuple[datetime,datetime,datetime]は開始・終了・返済時計。
    """
    day = datetime.fromisoformat(scene[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
    if scene.endswith("_Day"):
        start, end = day.replace(hour=8, minute=45), day.replace(hour=15, minute=45)
    else:
        start, end = day.replace(hour=17), (day + timedelta(days=1)).replace(hour=6)
    return start, end, end - timedelta(minutes=10)


def inventory():
    """
    機能: 全50場の存在と終端を点検し、追加3場のみ全文監査する。
    引数: なし。
    返り値: None。売買判断・会計・API取得は行わない。
    """
    basic = []
    for symbol in ("NK225", "TOPIX"):
        for directory in sorted((DATA / "future" / symbol).iterdir()):
            if not directory.is_dir():
                continue
            raw, compressed = directory / "book.jsonl", directory / "book.jsonl.gz"
            assert raw.exists() and compressed.exists(), directory
            item = dict(symbol=symbol, session=directory.name, book_bytes=raw.stat().st_size)
            with raw.open("rb") as stream:
                first = json.loads(stream.readline())
                stream.seek(max(0, item["book_bytes"] - 65536))
                last = json.loads(stream.read().splitlines()[-1])
            item.update(first_raw_clock=first.get("CurrentPriceTime"), last_raw_clock=last.get("CurrentPriceTime"))
            with compressed.open("rb") as stream:
                stream.seek(-4, 2)
                item["gzip_size_matches_raw"] = struct.unpack("<I", stream.read())[0] == item["book_bytes"] % 2**32
            assert item["gzip_size_matches_raw"]
            for kind in ("candle_1min", "candle_5min"):
                path = directory / (kind + ".csv")
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                assert rows and all(row["closed"] == "true" for row in rows), path
                item[kind] = dict(rows=len(rows), first=rows[0]["time"], last=rows[-1]["time"],
                                  incomplete_volume=sum(row["volume_complete"] != "true" for row in rows))
            basic.append(item)
    assert len(basic) == 100 and all(sum(x["symbol"] == symbol for x in basic) == 50 for symbol in ("NK225", "TOPIX"))

    # ----------------------------------------
    # 追加分は元監査関数のファイル位置と対象時計だけを新しい値へ接続する。
    audit = load_module("audit134_material140", ROOT / "work/update134_20261022/audit134.py")
    audit.ROOT = ROOT.parent
    materials = []
    for scene in SCENES:
        start, end, close = scene_bounds(scene)
        audit.START, audit.END = start.isoformat(), end.isoformat()
        for symbol in ("NK225", "TOPIX"):
            for kind, filename, minutes in (("book", "book.jsonl", 0), ("candle_1min", "candle_1min.csv", 1), ("candle_5min", "candle_5min.csv", 5)):
                source = DATA / "future" / symbol / scene / filename
                item = audit.audit_book(source) if kind == "book" else audit.audit_candle(source, minutes)
                item.update(path=source.as_posix(), session=scene, symbol=symbol, kind=kind,
                            consumer_path=f"{kind}/{symbol}/{scene}{'.jsonl' if kind == 'book' else '.csv'}")
                assert item["unchanged_during_read"]
                if kind == "book":
                    item["reaches_force_close"] = bool(item["last_session_price_clock"] and item["last_session_price_clock"] >= close.isoformat())
                    item["reaches_last_six_minutes"] = bool(item["last_session_price_clock"] and item["last_session_price_clock"] >= (end - timedelta(minutes=6)).isoformat())
                    assert item["reaches_force_close"] and item["invalid_json"] == 0
                else:
                    assert item["unclosed_rows"] == 0
                materials.append(item)
                print(scene, symbol, kind, "素材監査完了", flush=True)
    save(HERE / "inventory140.json", dict(passed=True, input_root=DATA.as_posix(), all_sessions=sorted({x["session"] for x in basic}),
         new_complete_file_sets=list(SCENES), materials=materials, basic=basic, financial_replays=0, API=0, real_orders=0,
         notes=["gzipは非圧縮長だけを照合。金融入力にはrawを使用。", "旧47場は保存packetの指紋で保持。旧原本全内容と移動原本の一致は別途照合。", "CurrentPriceTimeは最終価格の時計であり板受信時刻ではない。", "最終の同値気配は正常BBOとして約定に使わない。", "夜間足の欠けた分は価格更新の不在を含み、通信欠落と断定しない。", "研究返済は昼15:35/夜05:50。引けの清算結果を仮定しない。" ]))


def known_manifest():
    """
    機能: 旧47場の保存packetを再計算せず内容指紋で確認する。
    引数: なし。
    返り値: None。新しい相場再生は行わない。
    """
    records, sources = [], []
    for name in ("manifest139.json", "manifest139_extra.json"):
        source = ROOT / "work/tranche139_20261022" / name
        old = read(source)
        sources.append(dict(path=source.relative_to(ROOT).as_posix(), sha256=digest(source)))
        for item in old["packets"]:
            path = Path(item["path"])
            if not path.is_absolute():
                path = ROOT / path
            assert digest(path) == item["sha256"], path
            records.append(dict(session=item["session"], path=path.relative_to(ROOT).as_posix(),
                                sha256=item["sha256"], bytes=path.stat().st_size))
    assert len(records) == len({x["session"] for x in records}) == 47
    save(HERE / "known_manifest140.json", dict(passed=True, sessions=[x["session"] for x in records], packets=records,
         sources=sources, financial_replays=0, raw_rebuilt=False,
         scope="00139までの47場保存packetを同一指紋で再利用。元原本の移動を理由に数式や時計を作り直さない。"))
    print("旧47場packetの内容指紋が一致", flush=True)


def select_materials(inventory_value, sessions):
    """
    機能: 新原本配置から、資格を確認した追加素材を選択する。
    引数: inventory_value(dict)、sessions(tuple[str,...])は目録と対象場。
    返り値: list[dict]は絶対原本パスと旧consumer位置を持つ18素材。
    """
    assert set(sessions) <= set(inventory_value["new_complete_file_sets"])
    selected = [dict(item) for item in inventory_value["materials"] if item["session"] in sessions]
    assert len(selected) == len(sessions) * 6
    for item in selected:
        stat = Path(item["path"]).stat()
        assert (stat.st_size, stat.st_mtime_ns) == (item["bytes"], item["mtime_ns"])
        assert item["unchanged_during_read"]
        if item["kind"] == "book":
            assert item["reaches_force_close"]
    return selected


def input_views(output, materials):
    """
    機能: 新配置から旧clock/CSV数式で、原seqを保ったconsumer表示だけを所有域へ作る。
    引数: output(Path)、materials(list[dict])は保存先と資格済み原本一覧。
    返り値: list[dict]は原本と表示の指紋・採否。数式、順序、価格を変更しない。
    """
    previous = sys.modules["prepare132_for140"]
    consumer = output / "engine/legacy_root"
    clock = previous.module("clock_adapter", previous.ADAPTER / "clock_adapter.py")
    csv_view = previous.module("csv_view124", previous.ADAPTER / "csv_view124.py")
    bounds = previous.original_function(previous.ADAPTER / "adapter_v6.py", "bounds",
               dict(datetime=datetime, timedelta=timedelta, timezone=timezone))
    logs = []
    for item in materials:
        source = Path(item["path"])
        before = source.stat()
        start, end = bounds(item["session"])
        destination = consumer / item["consumer_path"]
        if item["kind"] == "book":
            proof = clock.write_view(source, destination, item["sha256"], start, end)
        else:
            proof = csv_view.write(source.read_bytes(), destination, item["sha256"], start, end)
            proof["clock_check"] = clock.validate_csv(destination, start, end)
        after = source.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) == (item["bytes"], item["mtime_ns"])
        logs.append(dict(path=destination.relative_to(ROOT).as_posix(), session=item["session"], symbol=item["symbol"],
                         kind=item["kind"], qualification=proof, source_path=item["path"], source_sha256=item["sha256"],
                         source_bytes=item["bytes"], source_mtime_ns=item["mtime_ns"], original_reads=1))
        print(item["session"], item["symbol"], item["kind"], "旧数式の原時計資格確認", flush=True)
    save(output / "consumer_manifest.json", dict(passed=True, read_log=logs, financial_replays=0))
    return logs


def prepare():
    """
    機能: 元132の非金融処理へ新しい素材位置だけを接続する。
    引数: なし。
    返り値: None。通常影・注文核・金融会計を呼ばない。
    """
    previous = load_module("prepare132_for140", PREVIOUS)
    previous.HERE = HERE
    previous.select_materials, previous.input_views = select_materials, input_views
    previous.prepare(HERE / "inputs", SCENES, HERE / "inventory140.json")
    save(HERE / "adapter_manifest140.json", dict(passed=True,
         sources={str(path.relative_to(ROOT).as_posix()): digest(path) for path in (Path(__file__), PREVIOUS)},
         replaced_functions=["select_materials", "input_views"],
         numerical_change=False, financial_replays=0, API=0, real_orders=0,
         notes="新配置からconsumerへのパス接続だけを差替え。旧時計資格・確定足・ATR・特徴・BBO・G許可は同じ数式。"))


def main():
    """
    機能: 棚卸し、旧packet照合、追加入力準備を独立に実行する。
    引数: 起動引数strは inventory、known、prepare のいずれか。
    返り値: None。全段階で金融会計を実行しない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("inventory", "known", "prepare"))
    args = parser.parse_args()
    {"inventory": inventory, "known": known_manifest, "prepare": prepare}[args.stage]()


if __name__ == "__main__":
    main()
