"""人工会計と保存済み全台帳を、主会計から独立して照合する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

from engine_synthetic import arguments,run,HERE,WORK
from independent import account,compare,aggregate

sys.path.insert(0,str(WORK))
import accounting
import study
import pdca


def ledger(out: tuple) -> dict:
    """機能: 再生配列を独立監査用の入力辞書へまとめる。

    引数: out(tuple)。返り値: 注文・決済・時価・統計・イベント(dict)。
    """
    return dict(orders=out[0],trades=out[1],curve=out[2],stats=out[3],events=out[4])


def artificial() -> dict:
    """機能: 両商品の整数料金・指値・遅延・無効気配を独立計算する。

    引数: なし。返り値: 人工会計検査結果(dict)。
    """
    checks=fields=0
    for symbol in ['TOPIX','NK225']:
        qty,value,fee=(10,1000.,41.8) if symbol=='TOPIX' else (20,10.,11.)
        for mode in range(3):
            for delay in [0.,1.,5.]:
                for trail in [0,1]:
                    times=np.arange(60.,251.);bids=np.full(len(times),100.)
                    bids[(times>=66)&(times<90)]=98.
                    bids[(times>=90)&(times<110)]=104.
                    bids[(times>=110)&(times<150)]=99.
                    args=arguments(times,bids,entry_mode=mode,latency=delay,trail_mode=trail,
                        quantity=qty,value=value,fee_unit=fee)
                    out=run(args);actual,curve=account(('人工',symbol),args,ledger(out))
                    expected=accounting.account(('人工',symbol),args,out)
                    fields+=compare(actual,expected);checks+=1
        args=arguments([60,65,124,125,130],[100,100,np.nan,np.nan,99],
            quantity=qty,value=value,fee_unit=fee)
        out=run(args);actual,_=account(('無効気配タイマー',symbol),args,ledger(out))
        fields+=compare(actual,accounting.account(('無効気配タイマー',symbol),args,out));checks+=1
        assert actual['decision_quote_last_valid']==1 and actual['decision_quote_missing']==0
        assert np.isfinite(actual['decision_to_fill_cost'])
    return dict(合格=True,人工口座数=checks,独立会計照合項目=fields,
        主会計SHA256=hashlib.sha256((WORK/'accounting.py').read_bytes()).hexdigest())


def real(stage: str, expected: int | None) -> dict:
    """機能: 指定段階の全結果を注文原本から再会計する。

    引数: stage(str)、expected(int|None)。返り値: 全口座監査結果(dict)。
    """
    fixed=study.load(WORK/'初回事前固定.json');base=WORK/stage
    paths=sorted((base/'results').glob('*.json'))
    if expected is not None:assert len(paths)==expected,(len(paths),expected)
    materials=study.material();accounts=orders=trades=fields=periods=0
    if stage=='quality_strict3':
        ready,books,previous,maps=materials
        strict=study.load(WORK/'strict3/prepared/signals.pkl')
        for key in strict:
            np.testing.assert_array_equal(strict[key]['grid'],previous[key]['grid'])
        remapped={key:(np.searchsorted(strict[key]['grid'],r['time_s'],side='right')-1).astype(np.int32) for key,r in ready.items()}
        materials=ready,books,strict,remapped
    hashes={};counts={}
    for index,path in enumerate(paths):
        packet=study.load(path);config=packet['config'];delay=config['latency']
        saved=study.load(base/'ledgers'/f'{config["id"]}.pkl')
        assert study.digest(base/'ledgers'/f'{config["id"]}.pkl')==packet['ledger_SHA256']
        rows=[];bykey={(r['session'],r['symbol']):r for r in packet['rows']}
        assert set(saved)==set(bykey)
        for key in sorted(saved):
            make=pdca.arguments if 'state_mode' in config or config.get('invert',False) else study.arguments
            args=make(config,key,materials,delay)
            actual,curve=account(key,args,saved[key]);fields+=compare(actual,bykey[key]);rows.append(actual)
            accounts+=1;orders+=len(saved[key]['orders']);trades+=len(saved[key]['trades'])
        target=[s for s in fixed['全30'] if any(r['session']==s for r in rows)]
        for name,sessions in [('対象',target),('前16',fixed['前16']),('後14',fixed['後14'])]:
            for symbol in ['TOPIX','NK225']:
                actual=aggregate(rows,symbol,sessions)
                fields+=compare(actual,packet['periods'][name][symbol]);periods+=1
        hashes[path.name]=study.digest(path)
        counts[config['id']]=len(saved)
        if (index+1)%24==0 or index+1==len(paths):
            print(f'独立会計 {stage} {index+1}/{len(paths)} 条件、{accounts} 口座',flush=True)
    return dict(合格=True,段階=stage,条件数=len(paths),口座数=accounts,注文数=orders,決済数=trades,
        照合項目数=fields,期間口座数=periods,全行清算時価SHA一致口座数=accounts,
        各条件口座数=counts,結果SHA256=hashes,
        初回事前固定SHA256=study.digest(WORK/'初回事前固定.json'),エンジンSHA256=study.digest(WORK/'engine.py'),
        主会計SHA256=study.digest(WORK/'accounting.py'))


def main() -> None:
    """機能: 人工又は全保存台帳の会計監査を実行し、監査範囲へだけ保存する。

    引数: CLI --stage(str)、--count(int)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--stage');parser.add_argument('--count',type=int)
    options=parser.parse_args()
    if options.stage:
        result=real(options.stage,options.count)
        name=options.stage.replace('/','_').replace('\\','_')+'の全口座独立会計監査.json'
    else:
        result=artificial();name='料金と欠測タイマーの人工独立会計監査.json'
    (HERE/name).write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['結果SHA256','各条件口座数']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
