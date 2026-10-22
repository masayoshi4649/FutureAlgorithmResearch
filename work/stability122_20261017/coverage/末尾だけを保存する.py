"""指定原板の末尾だけを一度保存し、時刻と気配の実schemaを確認する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    """
    機能: 原板の末尾最大二MiBだけを一読し自所有へ保存する。
    引数: なし。
    返り値: None。原板は書き換えずAPI・金融を使用しない。
    """
    source = ROOT / 'book/TOPIX/2026-09-24_Day.jsonl'
    destination = HERE / 'owned_raw_tail'
    assert not destination.exists(), '原板末尾の同一読取を重ねません'
    destination.mkdir(parents=True)
    size = source.stat().st_size
    length = min(size, 2 * 1024 * 1024)
    with source.open('rb') as stream:
        stream.seek(size - length)
        payload = stream.read(length)
    start = size - length
    if start:
        skip = payload.index(b'\n') + 1
        payload = payload[skip:]
        start += skip
    saved = destination / '2026-09-24_Day_tail.jsonl'
    saved.write_bytes(payload)
    values = [json.loads(line) for line in payload.splitlines() if line.strip()]
    metadata = dict(source=source.relative_to(ROOT).as_posix(), source_size=size,
                    range_start=start, range_end=size, original_read_bytes=length,
                    complete_lines=len(values), saved_path=saved.relative_to(ROOT).as_posix(),
                    saved_sha256=hashlib.sha256(payload).hexdigest(),
                    原板読取回数=1, 原板変更=0, API=0, 金融再生=0)
    (destination/'取得範囲.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(metadata=metadata, first_keys=list(values[0]),
                          first=values[0], last=values[-1]), ensure_ascii=False))


if __name__ == '__main__':
    main()
