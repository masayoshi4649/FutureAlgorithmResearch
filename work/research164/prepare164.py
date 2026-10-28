"""旧53完了場と追加10月27日ナイトの読取専用入力目録を固定する。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    """ファイル内容を逐次読みSHA256を返す。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    """条件選択前の54場目録を保存し、売買は実行しない。

    引数: なし。返り値: None。
    """
    prior = ROOT/"work/transfer163/inputs163.json"
    before = json.loads(prior.read_text(encoding="utf-8"))
    scenes = before["sessions"]
    assert len(scenes) == 53
    for scene in scenes:
        scene["previously_used"] = True
        scene["confirmation"] = scene["split"] == "test"
    jst = timezone(timedelta(hours=9))
    start = datetime(2026, 10, 27, 17, tzinfo=jst)
    end = datetime(2026, 10, 28, 6, tzinfo=jst)
    extra = dict(session="2026-10-27_Night", kind="Night", start=start.timestamp(),
                 us_open=datetime(2026, 10, 27, 22, 30, tzinfo=jst).timestamp(),
                 force_close=(end-timedelta(minutes=10)).timestamp(), end=end.timestamp(),
                 cutoff=(end+timedelta(minutes=1)).timestamp(), partial=False,
                 books={}, candles={}, fingerprints=[], split="extra", previously_used=False, confirmation=True)
    for product in ("NK225", "TOPIX"):
        folder = ROOT.parent/"JP_OSE_Data/future"/product/extra["session"]
        files = [folder/"book.jsonl", folder/"candle_1min.csv", folder/"candle_5min.csv"]
        extra["books"][product] = files[0].as_posix()
        extra["candles"][product] = {"60":files[1].as_posix(), "300":files[2].as_posix()}
        for path in files:
            original = path.stat()
            digest = sha(path)
            after = path.stat()
            assert (original.st_size, original.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
            extra["fingerprints"].append(dict(path=path.as_posix(), exists=True, bytes=original.st_size,
                mtime_ns=original.st_mtime_ns, sha256=digest, unchanged_during_read=True))
    scenes.append(extra)
    assert len({s["session"] for s in scenes}) == 54
    assert sum(s["kind"] == "Day" for s in scenes) == 27
    payload = dict(created_at=datetime.now().astimezone().isoformat(), sessions=scenes,
        counts={"train":30,"validation":10,"test":13,"extra":1}, fees=0,
        product="NK225micro", max_per_side=100, equivalent_mini_per_side=10, point_value=10,
        known_development=True, new_financial_replays=0,
        selection="旧前40場で日中・夜米国前・夜米国後を独立選択し固定、旧後13場と追加1夜を確認。未見実証とは呼ばない。",
        scope="手法IDは一意で不変。時間割と合算運用は手法IDとは分離する。",
        sources=[dict(path=prior.relative_to(ROOT).as_posix(),sha256=sha(prior))],
        us_open_basis="追加10月27日夜は直前10月26日夜の米国開始JST22:30設定を継承。開始年月日を進め、場中情報から変更しない。")
    previous = next(s for s in scenes if s["session"] == "2026-10-26_Night")
    assert extra["us_open"]-previous["us_open"] == 86400
    out = HERE/"inputs164.json"
    assert not out.exists()
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(sessions=54, new_financial_replays=0, counts=payload["counts"]),ensure_ascii=False))


if __name__ == "__main__":
    main()
