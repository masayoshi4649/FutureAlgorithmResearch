"""追加七場の完成会計を一読保全し、旧参照と新測定を分けて表示する。"""

import hashlib
import json
from pathlib import Path


def main() -> None:
    """
    機能: h完了結果を根の所有へ保全して14新測定の収支を確認する。
    引数: なし。固定された完成結果を使用する。
    返り値: None。原市場・金融再生0。
    """
    base = Path(__file__).resolve().parent
    source = base / 'v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json'
    output = base / 'v6_resume/root_owned'
    assert not output.exists()
    payload = source.read_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    data = json.loads(payload)
    assert data['全合格'] and data['source_SHA256'] == data['source_end_SHA256']
    assert len(data['rows']) == 80 and len(data['new_accounts']) == 14
    assert data['raw_reads'] == data['old_financial_rerun'] == 0
    output.mkdir()
    (output / source.name).write_bytes(payload)
    summary = dict(全合格=True, SHA256=sha, result_reads=1, market_reads=0, financial_replay=0,
        metrics=data['metrics'], rows=[row for row in data['rows'] if row['session'] in data['new_sessions']],
        counters=data['counters'])
    (output / '新七場と旧三十三場の保存小会計.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
