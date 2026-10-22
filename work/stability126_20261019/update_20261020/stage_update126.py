"""追加二場の終了済み原板と足を、原本を変更せず検証専用領域へ取得する。"""

import hashlib
import json
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCENES = ("2026-10-19_Night", "2026-10-20_Day")


def material(source: Path, target: Path, max_bps: float | None) -> dict:
    """
    機能: 一度の原本読取で専用コピーと指紋を作り、取得前後の原本状態を照合する。
    引数: source(Path)は終了済み原本、target(Path)は新規保存先、max_bps(float|None)は上限速度。
    返り値: dictは位置、ＳＨＡ２５６、サイズ、更新時刻および読取回数。
    """
    assert target.resolve().is_relative_to(HERE) and not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".取得中")
    assert not partial.exists()
    before = source.stat()
    digest, copied, started = hashlib.sha256(), 0, time.monotonic()
    with source.open("rb") as origin, partial.open("xb") as destination:
        while chunk := origin.read(1024 * 1024):
            destination.write(chunk)
            digest.update(chunk)
            copied += len(chunk)
            if max_bps is not None:
                delay = copied / max_bps - (time.monotonic() - started)
                if delay > 0:
                    time.sleep(min(delay, 2.0))
    after = source.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    assert copied == before.st_size == partial.stat().st_size
    partial.rename(target)
    return dict(source=str(source), path=target.relative_to(ROOT).as_posix(),
                sha256=digest.hexdigest(), bytes=copied, source_mtime_ns=before.st_mtime_ns,
                source_reads=1, network_max_bps=max_bps)


def main() -> None:
    """
    機能: ローカルの追加足とＴＯＰＩＸ板、保存元共有の不足日経板だけを取得する。
    引数: なし。
    返り値: None。会計再生と現在セッションＡＰＩ接続は行わない。
    """
    manifest = HERE / "終了済み追加二場の取得.json"
    assert not manifest.exists()
    records = []
    for scene in SCENES:
        for symbol in ("TOPIX", "NK225"):
            for category, suffix in (("candle_1min", ".csv"), ("candle_5min", ".csv"), ("book", ".jsonl")):
                relative = Path(category) / symbol / (scene + suffix)
                source = ROOT / relative
                remote = not source.exists()
                if remote:
                    assert category == "book" and symbol == "NK225"
                    source = Path(r"\\10.10.100.1\log") / relative
                records.append(material(source, HERE / "stage" / relative, 1_250_000. if remote else None))
                print(scene + " " + category + "/" + symbol + " の専用コピーを保存", flush=True)
    assert len(records) == 12
    manifest.write_text(json.dumps(dict(passed=True, sessions=SCENES, files=records,
        financial_replays=0, API=0, real_orders=0,
        note="共有保存元の終了済み二場を取得。研究原本フォルダーには書き込まない。"),
        ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("追加二場の原本一読取得が完了", flush=True)


if __name__ == "__main__":
    main()
