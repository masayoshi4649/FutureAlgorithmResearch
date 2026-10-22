"""ユーザーのコピー完了後、終了済み二板が先に取得した専用コピーと一致するか確認する。"""

import hashlib
from pathlib import Path

from run_update126 import HERE, ROOT, read, save


def main() -> None:
    """
    機能: 原本を変更せず追加二場の日経生板を一読し、取得済み指紋と同一と確認する。
    引数: なし。
    返り値: None。ファイル不足又は内容差異がある間は金融実行前に停止する。
    """
    acquisition = read(HERE / "終了済み追加二場の取得.json")
    expected = [item for item in acquisition["files"] if "stage/book/NK225/" in item["path"]]
    assert len(expected) == 2
    locations = [(ROOT / "book/NK225" / Path(item["path"]).name, item) for item in expected]
    assert all(path.exists() and path.stat().st_size == item["bytes"] for path, item in locations), "追加二場のコピー完了待ち"
    records = []
    for path, item in locations:
        before = path.stat()
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = path.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        assert digest == item["sha256"], path.name
        records.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=digest,
                            bytes=after.st_size, original_reads=1, owned_copy_unchanged=True))
    save(HERE / "ユーザーのコピー完了と取得済み二板の同一確認.json", dict(passed=True,
        files=records, financial_replays=0, original_market_writes=0, API=0))
    print("ユーザーのコピー完了を確認、取得済み二板と完全一致", flush=True)


if __name__ == "__main__":
    main()
