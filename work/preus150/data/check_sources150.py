"""登録済み149の原資料を変更せず、現在の同一性を確認する。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent


def digest(path: Path) -> str:
    """ファイルのSHA256を全読で計算する。

    引数: path (Path): 読取対象。
    返り値: str: SHA256。
    """
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):
            result.update(chunk)
    return result.hexdigest()


def main() -> None:
    """156原資料のサイズ・更新時刻を確認し、変化時だけ全読する。

    引数: なし。
    返り値: None。監査根拠を新しい150の領域へ保存する。
    """
    source=ROOT/'work/preus149/data/原資料一覧149.json'
    before=digest(source)
    registered=json.loads((ROOT/'work/preus149/登録受領149.json').read_text('utf-8-sig'))
    assert before==registered['inputs']['sha256']
    manifest=json.loads(source.read_text('utf-8'))
    rows=[]
    for scene in manifest['sessions']:
        for original in scene['fingerprints']:
            path=Path(original['path']);stat=path.stat()
            changed=(stat.st_size!=original['bytes'] or stat.st_mtime_ns!=original['mtime_ns'])
            actual=digest(path) if changed else None
            final=path.stat()
            assert (stat.st_size,stat.st_mtime_ns)==(final.st_size,final.st_mtime_ns)
            rows.append(dict(session=scene['session'],path=str(path),
                prior_bytes=original['bytes'],current_bytes=stat.st_size,
                prior_mtime_ns=original['mtime_ns'],current_mtime_ns=stat.st_mtime_ns,
                metadata_unchanged=not changed,prior_sha256=original['sha256'],
                sha256_read_this_time=actual,bytes_changed=(actual!=original['sha256']) if changed else None,
                verification='今回SHA再読' if changed else '149全読SHAと現在size/mtime一致'))
    assert len(rows)==156
    assert digest(source)==before
    mismatches=[r['path'] for r in rows if r['bytes_changed'] is True]
    output=dict(created_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        source_manifest=dict(path=str(source),sha256=before,unchanged=True),
        files=156,metadata_changed=sum(not r['metadata_unchanged'] for r in rows),
        sha256_reread=sum(r['sha256_read_this_time'] is not None for r in rows),
        content_mismatches=mismatches,all_eligible_for_reuse=not mismatches,
        limitation='size/mtimeが不変のファイルは149での全読SHAを継承。メタデータを意図的に戻す無痕跡変更までは今回再検出しない。',
        financial_replays=0,records=rows)
    (OUT/'149原資料の再利用前照合150.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:output[k] for k in ['files','metadata_changed','sha256_reread','content_mismatches','all_eligible_for_reuse']},ensure_ascii=True))


if __name__=='__main__':
    main()
