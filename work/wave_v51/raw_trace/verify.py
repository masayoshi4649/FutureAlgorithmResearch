"""生板トレースの原本指紋・全CSV会計・実行実装不変を独立確認する。"""
from pathlib import Path
import csv
import hashlib
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def main() -> None:
    """機能: 全トレースCSVと既存原本固定値を検査する。

    引数: なし。返り値: なし(None)。
    """
    audit=json.loads((HERE/'監査.json').read_text(encoding='utf8'))
    raw_fixed=json.loads((ROOT/'work/wave_v50/update_20261007_added/固定.json').read_text(encoding='utf8'))['原本SHA256']
    assert audit['全合格'] and audit['原本数']==8 and audit['口座数']==24
    for name,digest in audit['実装SHA256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    records=[];count=0
    for source in audit['原本別']:
        name=source['原本'].replace('\\','/')
        assert raw_fixed[name]==source['原本SHA256']
        for method in source['方式']:
            path=HERE/method['ログ'];assert hashlib.sha256(path.read_bytes()).hexdigest()==method['ログSHA256']
            previous=-1;rows=0;fills=0
            with path.open(encoding='utf-8-sig',newline='') as handle:
                for row in csv.DictReader(handle):
                    seq=int(row['原本行番号0起点']);assert seq>previous;previous=seq
                    assert abs(float(row['実現累計円'])+float(row['含み円'])-float(row['合計円']))<1e-7
                    cap=10 if source['symbol']=='TOPIX' else 20
                    assert 0<=int(row['買建枚数'])<=cap and 0<=int(row['売建枚数'])<=cap
                    for order in json.loads(row['当行約定注文JSON']):
                        assert order[3]==seq and order[2]<seq and order[1]>=order[0]
                        fills+=1
                    rows+=1
            assert rows==method['ログ行数'] and fills==method['注文数']
            count+=rows;records.append(dict(ログ=method['ログ'],行数=rows,約定数=fills,全合格=True))
    assert count==audit['CSV行数']
    value=dict(全合格=True,既存原本SHA256一致数=8,実装指紋不変=True,CSV数=len(records),CSV合計行数=count,
               CSV会計原本行順約定順序一致=True,CSV別=records,
               監査SHA256=hashlib.sha256((HERE/'監査.json').read_bytes()).hexdigest(),検証実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'独立確認.json').write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print('8原本固定値・24CSV・'+str(count)+'記録の独立確認完了',flush=True)


if __name__=='__main__':main()
