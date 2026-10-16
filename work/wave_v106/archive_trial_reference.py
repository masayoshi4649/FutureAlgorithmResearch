"""開始失敗した試行の実装証跡を、保存した同指紋の旧源へ結び直す。"""

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data'


def main() -> None:
    """
    機能: 金融0の開始失敗を記録し、旧源を同SHAの保存版へ参照する。
    引数: --trial(str)は登録ID、--source/--archive(Path)は元位置と不変旧源。
    返り値: None。仕様の算法を変えず、元台帳を履歴へ保持する。
    """
    parser = argparse.ArgumentParser(description='同指紋の旧実装証跡を参照する。新しい算法は別登録する。')
    parser.add_argument('--trial',required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    assert archive.is_relative_to(ROOT) and archive.is_file()
    path = DATA/'trials.json'
    original = path.read_bytes()
    table = json.loads(original.decode('utf-8-sig'))
    row = next(r for r in table['trials'] if r['id']==args.trial)
    implementations = row['spec']['implementation']
    matches = [key for key in implementations if Path(key.replace('\\','/'))==args.source]
    assert len(matches)==1
    key = matches[0]
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest==implementations[key], '元登録と旧源の指紋が不一致です'
    archive_relative = archive.relative_to(ROOT).as_posix()
    del implementations[key]
    implementations[archive_relative] = digest
    row['status'] = '開始失敗・新金融0。参照IDを修正した別登録で再開'
    row['result'] = '旧基準IDのlookupで停止。金融play前なので新金融0。算法・入力・費用は変更しない。'
    row['archived_implementation'] = dict(元位置=args.source.as_posix(),証跡位置=archive_relative,sha256=digest,
        意味='原計画で固定した内容の保存証跡。算法の再開は別試行に登録する。')
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    backup = DATA/'history'/('trials_'+hashlib.sha256(original).hexdigest()+'.json')
    if not backup.exists():
        backup.write_bytes(original)
    temporary = DATA/'trials_archive_reference.tmp'
    temporary.write_text(json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    temporary.replace(path)
    print('旧源の同指紋を確認し開始失敗記録へ接続。新金融0。')


if __name__=='__main__':
    main()
