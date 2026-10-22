"""完了した二脚会計を一読保全し、根の比較用小集計だけ作る。"""

import argparse
import hashlib
import json
from pathlib import Path
import statistics


def save(path: Path, value: dict) -> None:
    """
    機能: 小さい根確認を日本語JSONへ保存する。
    引数: path(Path)は新規保存先、value(dict)は内容。
    返り値: None。既存成果を置き換えない。
    """
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main() -> None:
    """
    機能: 保存された場会計の収支・活動・大勝ち依存を再集計する。
    引数: CLI result/output(Path)は完成結果と新規所有先。
    返り値: None。市場・金融再生は0で同一結果の再集計に限る。
    """
    p = argparse.ArgumentParser()
    p.add_argument('result', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    assert not args.output.exists()
    before = args.result.stat()
    payload = args.result.read_bytes()
    after = args.result.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    sha = hashlib.sha256(payload).hexdigest()
    data = json.loads(payload)
    assert len(data['sessions']) == 40 and len(data['runs']) == 320
    assert data['source_SHA256'] == data['source_end_SHA256']
    args.output.mkdir(parents=True)
    (args.output / args.result.name).write_bytes(payload)
    save(args.output / '一読と同bytes参照.json', dict(全合格=True, source=str(args.result), SHA256=sha,
        result_reads=1, market_reads=0, financial_replay=0))
    rows = []
    for method in sorted({row['method'] for row in data['runs']}):
        own = [row for row in data['runs'] if row['method'] == method]
        assert len(own) == 40
        values = [row['net'] for row in own]
        black = sum(value > 0 for value in values)
        red = sum(value < 0 for value in values)
        first = own[0]
        idle = sum(row['fills'] == 0 for row in own)
        unclosed = sum(row['unclosed'] for row in own)
        removed = sum(values) - sum(sorted((value for value in values if value > 0), reverse=True)[:3])
        item = dict(method=method, net=sum(values), black=black, red=red, inactive=idle,
            median=statistics.median(values), mean=statistics.mean(values), worst=min(values),
            top3_removed=removed, unclosed=unclosed,
            qualified=sum(values)>0 and statistics.median(values)>0 and removed>0 and unclosed==0)
        rows.append(item)
    save(args.output / '八条件の保存小会計.json', dict(全合格=True, source_SHA256=sha, rows=rows,
        qualification_count=sum(row['qualified'] for row in rows), repeated_evidence=False,
        raw_reads=0, financial_replay=0))
    print(json.dumps(dict(SHA256=sha, rows=rows, row_keys=list(first)), ensure_ascii=False))


if __name__ == '__main__':
    main()
