"""金融前停止の旧E01を保全し、固定されたPythonと小設定だけを新所有域へ複写する。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=HERE.parent/'e01'


def main() -> None:
    """
    機能: 初回純人工のsource一覧だけを同bytesコピーし、市場・生成物を除外する。
    引数: なし。
    返り値: None。初回所有域、原本、金融、試行台帳を変更しない。
    """
    proof=json.loads((OLD/'同bytes源と固定二設定及び新日付の純人工.json').read_text(encoding='utf8'))
    records=[]
    for relative,expected in proof['sources'].items():
        source=ROOT/relative;local=source.relative_to(OLD)
        assert source.suffix=='.py' or local.as_posix() in {
            'legacy_root/work/wave_v38/探索条件の固定.json',
            'legacy_root/work/wave_v44/探索条件の固定.json',
            'legacy_root/work/wave_v27/hierarchy_design_fixed.json'}
        data=source.read_bytes();assert hashlib.sha256(data).hexdigest()==expected
        target=HERE/local;assert not target.exists(),str(target)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        records.append(dict(source=relative,target=target.relative_to(ROOT).as_posix(),sha256=expected))
    output=dict(passed=True,records=records,source_count=len(records),
        original_market_reads=0,generated_input_copies=0,financial_accounts=0,API=0,real_orders=0)
    path=HERE/'初回源だけの同bytes複写.json';assert not path.exists()
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print('初回源だけ'+str(len(records))+'本を新所有域へ複写。金融0。')


if __name__=='__main__':
    main()
