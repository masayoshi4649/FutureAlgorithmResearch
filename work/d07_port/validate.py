"""登録済みD07移植を、実行ごとのGo版指紋を残して照合する。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def digest(path):
    """保存資料の指紋を計算する。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    """固定した条件のGo版だけを再生し、実行版・全差分・実行結果を保存する。

    引数: --all(bool)は50場、--addon(bool)は追加担当単独も照合、--note(str)は移植修正内容。
    返り値: None。実注文も研究の期待結果更新も行わない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--all',action='store_true')
    parser.add_argument('--addon',action='store_true')
    parser.add_argument('--note',required=True)
    args=parser.parse_args()
    receipt=json.loads((HERE/'登録受領.json').read_text(encoding='utf8'))
    assert receipt['returncode']==0
    number=1
    while (HERE/f'run{number:02d}').exists():number+=1
    folder=HERE/f'run{number:02d}';folder.mkdir()
    app=ROOT/'App/SessionTrader'
    files=sorted((app/'internal/strategy').glob('*.go'))
    files.extend([HERE/'validate.py'])
    fingerprints={p.relative_to(ROOT).as_posix():digest(p) for p in files}
    archive=folder/'実行時実装.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path in files:z.write(path,path.relative_to(ROOT).as_posix())
    env=dict(os.environ,SESSIONTRADER_D07_REPORT=str(folder/'D07全約定照合.json'))
    env.pop('SESSIONTRADER_D07_ALL',None)
    if args.all:env['SESSIONTRADER_D07_ALL']='1'
    pattern='^TestD07Saved(Integration|Addon)$' if args.addon else '^TestD07SavedIntegration$'
    command=['go','test','./internal/strategy','-run',pattern,'-count=1','-json']
    manifest={'trial_id':receipt['trial_id'],'prototype_archive_sha256':receipt['archive_sha256'],
        'implementation':fingerprints,'archive_sha256':digest(archive),
        'fixtures_sha256':digest(HERE/'fixtures/manifest.json'),
        'note':args.note,'all_sessions':args.all,'command':command,
        'scope':'独立移植照合。差分修正は原仕様との不一致訂正であり、新探索を行わない。'}
    (folder/'実行条件.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(folder.name+'開始',flush=True)
    with (folder/'go結果.jsonl').open('wb') as out,(folder/'go標準エラー.txt').open('wb') as err:
        result=subprocess.run(command,cwd=app,env=env,stdout=out,stderr=err)
    changed=[name for name,value in fingerprints.items() if digest(ROOT/name)!=value]
    summary={'returncode':result.returncode,'実行中変更ファイル':changed,'go結果_sha256':digest(folder/'go結果.jsonl')}
    report=folder/'D07全約定照合.json'
    if report.exists():
        rows=json.loads(report.read_text(encoding='utf8'))
        summary.update(sessions=len(rows),passed=sum(x['Passed'] for x in rows),exact=sum(x['Exact'] for x in rows),
            actual_orders=sum(x['Orders'] for x in rows),expected_orders=sum(x['ExpectedOrders'] for x in rows),
            actual_net=sum(x['Gross'] for x in rows),expected_net=sum(x['ExpectedGross'] for x in rows))
    (folder/'結果要約.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    raise SystemExit(result.returncode or (1 if changed else 0))


if __name__=='__main__':main()
