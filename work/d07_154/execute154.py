"""登録と全入力指紋を確認し、00154の金融再生を一度だけ起動する。"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def stamp():
    """現在の監査時計を取得する。

    引数: なし。返り値: strは日本時間のISO時計。
    """
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def inspect(ref):
    """根拠ファイルを全読し登録指紋と照合する。

    引数: ref(dict)はpath/sha256/bytes。返り値: dictは照合結果。
    """
    path = Path(ref['path'])
    if not path.is_absolute():
        path = ROOT / path
    before = path.stat()
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    valid = actual == ref['sha256'] and after.st_size == ref['bytes'] and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    if not valid:
        raise RuntimeError(f"固定指紋不一致: {path}")
    return {'path': str(path), 'bytes': after.st_size, 'sha256': actual, '一致': valid}


def write(path, value):
    """監査結果をUTF-8のJSONとして保存する。

    引数: path(Path)、value(dict)。返り値: なし。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    """正常登録と再照合の成功後だけ、一度の全場再生を行う。

    引数: なし。返り値: なし。既存実行記録・結果がある時は停止する。
    """
    execution = HERE / '金融実行154.json'
    if execution.exists() or (HERE/'results_go').exists():
        raise RuntimeError('実行記録又は結果が既に存在します。再実行しません。')
    receipt = json.loads((HERE/'登録受領154.json').read_text('utf-8'))
    if receipt.get('registered') is not True or receipt.get('returncode') != 0:
        raise RuntimeError('正常登録受領がありません。')
    began = stamp()
    sources = [inspect(r) for r in receipt['sources']]
    inputs = [inspect(r) for r in receipt['inputs']]
    roots = [inspect(receipt[k]) for k in ('plan', 'implementation')]
    manifest = json.loads((HERE/'inputs154.json').read_text('utf-8'))
    originals = [inspect(r) for scene in manifest['sessions'] for r in scene['fingerprints']]
    verification = {'開始': began, '終了': stamp(), '登録成功': True, '実装': sources, '目録': inputs,
                    '計画と実装保存': roots, '原資料': originals, '実装数': len(sources), '原資料数': len(originals),
                    '原資料全読バイト': sum(r['bytes'] for r in originals), '全一致': True}
    write(HERE/'金融前の最終指紋照合154.json', verification)
    command = ['go', 'run', '.', '-manifest', '../inputs154.json', '-configs', '../configs154.json',
               '-registration', '../登録受領154.json', '-out', '../results_go', '-workers', '4']
    record = {'開始': stamp(), '終了': None, '終了コード': None, 'command': command,
              'cwd': str(HERE/'engine_go'), '金融実行回数': 1, '全場数': len(manifest['sessions'])}
    with execution.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(f"全指紋一致：実装 {len(sources)}、原資料 {len(originals)}。固定15条件の金融再生を開始します。", flush=True)
    timer = time.monotonic()
    with (HERE/'金融実行154.log').open('x', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=HERE/'engine_go', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace')
        record['pid'] = process.pid
        write(execution, record)
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line.rstrip(), flush=True)
        code = process.wait()
    record.update({'終了': stamp(), '終了コード': code, '所要秒': time.monotonic()-timer,
                   '結果ファイル数': len(list((HERE/'results_go').glob('*.json')))})
    write(execution, record)
    if code != 0:
        raise SystemExit(code)
    if record['結果ファイル数'] != len(manifest['sessions']):
        raise RuntimeError('正常終了しましたが結果ファイル数が不足しています。再実行しません。')
    print(f"金融再生完了：{record['結果ファイル数']}ファイル、終了コード0。", flush=True)


if __name__ == '__main__':
    main()
