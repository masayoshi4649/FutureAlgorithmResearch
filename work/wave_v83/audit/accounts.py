"""保存された全注文・親組・時価と、期間集計を独立会計する。"""

import argparse
import pickle
from context import *
from independent import account,compare,aggregate

sys.path.insert(0,str(WORK))
import data


def load(path: Path) -> object:
    """機能: 監査対象を読取専用で読み込む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def main() -> None:
    """機能: 指定段階の全会計と、存在する予約イベントを再計算する。

    引数: CLI --stage(str)、--count(int)、--limit(int|None)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--stage',required=True);parser.add_argument('--count',type=int,required=True)
    parser.add_argument('--limit',type=int)
    options=parser.parse_args();base=WORK/options.stage
    fixed=load(WORK/'results/事前固定.json')
    for path,h in fixed['code_SHA256'].items():assert digest(WORK/path)==h,path
    paths=sorted(base.glob('seed*/results/*.json')) if options.stage=='sensitivity' else sorted((base/'results').glob('*.json'))
    assert len(paths)==options.count,(len(paths),options.count)
    if options.limit:paths=paths[:options.limit]
    inputs=data.load_data()
    totals=dict(条件数=0,口座数=0,注文数=0,決済脚数=0,全玉終了組数=0,
        会計照合項目=0,期間会計数=0,予約イベント独立照合口座=0,予約イベント数=0,全行清算時価SHA一致口座=0)
    hashes={};detail={}
    for path in paths:
        packet=load(path);c=packet['config'];run=packet['run']
        ledgerpath=path.parent.parent/'ledgers'/f'{c["id"]}.pkl';ledgers=load(ledgerpath)
        bykey={(r['session'],r['symbol']):r for r in packet['rows']}
        assert set(ledgers)==set(bykey)
        rows=[]
        for key,saved in sorted(ledgers.items()):
            raw=data.as_tuple(inputs[key])
            if options.stage in ['ideal','ideal_fee']:
                raw=list(raw);raw[2]=raw[1];raw[3]=raw[1];raw[7]=raw[6];raw=tuple(raw)
                actual,curve=account(key,raw,saved,run,fee_override=0. if options.stage=='ideal' else None)
            else:actual,curve=account(key,raw,saved,run)
            totals['会計照合項目']+=compare(actual,bykey[key]);rows.append(actual)
            if 'events' in saved:
                args=arguments(raw,c['family'],width=c['width_ticks'],variant=c['variant'],symbol=key[1],
                    delay=run['delay'],seed=run['seed'],slip=run['slip_ticks'])
                reservation_oracle(args,(saved['orders'],saved['trades'],curve,saved['stats'],saved['events']))
                totals['予約イベント独立照合口座']+=1;totals['予約イベント数']+=len(saved['events'])
            totals['口座数']+=1;totals['注文数']+=len(saved['orders']);totals['決済脚数']+=len(saved['trades'])
            totals['全玉終了組数']+=len(saved['cycles']);totals['全行清算時価SHA一致口座']+=1
        for name,sessions in [('前16',fixed['前16']),('後14',fixed['後14']),('対象',run['sessions'])]:
            for symbol in ['TOPIX','NK225']:
                actual=aggregate(rows,symbol,sessions)
                totals['会計照合項目']+=compare(actual,packet['periods'][name][symbol]);totals['期間会計数']+=1
        totals['条件数']+=1;hashes[str(path.relative_to(WORK))]=digest(path);detail[str(path.relative_to(WORK))]=len(ledgers)
        if totals['条件数']%12==0 or totals['条件数']==len(paths):
            print(f'独立会計 {options.stage} {totals["条件数"]}/{len(paths)}、{totals["口座数"]}口座',flush=True)
    result=dict(合格=True,段階=options.stage,**totals,各条件口座数=detail,結果SHA256=hashes,
        事前固定SHA256=digest(WORK/'results/事前固定.json'),エンジンSHA256=digest(WORK/'engine.py'),
        留意='全約定・現金・保有・親組・時価を独立再構成。新規予約とIOC失効の順序はイベント保存のある最終代表で全件検査する。初回/乱数感度で未保存の予約上限・失効数はエンジン統計と人工境界を参照。')
    if options.stage=='persistent':
        persistent_fixed=load(WORK/'persistent/固定条件.json')
        for path,h in persistent_fixed['実装SHA256'].items():assert digest(WORK/path)==h
        result['追加対照固定SHA256']=digest(WORK/'persistent/固定条件.json')
        result['追加対照実装SHA256']=persistent_fixed['実装SHA256']
    name=options.stage.replace('/','_')+('一部' if options.limit else '')+'の独立会計監査.json'
    save(name,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['結果SHA256','各条件口座数']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
