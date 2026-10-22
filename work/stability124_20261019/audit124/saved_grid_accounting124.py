"""新会計と保存引用・同値共有を独立算術で照合する。金融再生はしない。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from io import BytesIO
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
sys.path.insert(0,str(ROOT/'work/stability120_20261017/audit'))
import saved_accounting120 as A
from qualifications120e import valid_quotes_e,qualifications
READS=Counter()


def load_module(name: str,path: Path):
    """
    機能: 売買エンジンを呼ばず、純粋な商品契約・設定関数だけを読む。
    引数: name(str)は固有名、path(Path)は源。
    返り値: moduleは読んだ源。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def read_json(path: Path,expected: str | None=None) -> dict:
    """
    機能: 小さいJSONを一読して根指定の指紋へ拘束する。
    引数: path(Path)は資料、expected(str|None)は指紋。
    返り値: dictは保存内容。
    """
    raw=path.read_bytes()
    READS['小JSON']+=1
    if expected is not None:A.check(A.sha(raw)==expected,'124JSONの正式SHA')
    return json.loads(raw)


def account(q: dict,o: np.ndarray,l: np.ndarray,c: np.ndarray,p: np.ndarray,row: dict,config: dict) -> dict:
    """
    機能: 保存注文から全原行の現金・全在庫・資産・最終代理会計を独立照合する。
    引数: q(dict)は所有気配、o/l/c/p(ndarray)は保存四台帳、row/config(dict)は集計と商品契約。
    返り値: dictは確認した枚数・純益・代理参照・固定在庫診断。
    """
    accepted,rejected=valid_quotes_e(q,config)
    A.near(row['clock_rejected'],rejected,'124入力の時計価格資格棄却')
    A.near(row['step'],row['params']['unit'],'124基準unitはIVで動かさない')
    A.check(o.ndim==l.ndim==c.ndim==p.ndim==2 and o.shape[1]==18 and l.shape[1]==19 and c.shape[1]==8 and p.shape[1]==17,'124四台帳の列数')
    A.check(len(l)==row['regular_closed']==0 and np.all(o[:,1]==1),'124途中返済なし通常台帳は新規だけ')
    fee=math.floor(config['fee']+1e-9)
    normalized=dict(row)
    normalized.update(net=float(c[-1,2]),cash=-fee*len(o),profit=0.,loss=0.,fees=fee*len(o),closed_lots=0,
        wins=0,losses=0,unclosed=len(o),held_entry_fees=fee*len(o),last_equity=float(c[-1,2]),realized_net=0.,
        forced_loss=0.,forced_profit=0.,trail_net=0.,long_net=0.,short_net=0.,clock_rejected=0)
    first_mid=(accepted['bid'][0]+accepted['ask'][0])/2
    core_result=A.audit_account(accepted,o,l,c,normalized,config,dict(mode=14,fraction=row['params']['unit']/first_mid))
    qualifications(accepted,o,row,config,dict(mode=2,trail=float('inf')))

    # ----------------------------------------
    # 発火線を引いた待機極値が、その判断までに実在したLastであることを検査する。
    initial,spacing,unit=(row['params'][k] for k in ('initial','spacing','unit'))
    A.check(len(set((int(v[2]),int(v[10])) for v in o))==len(o),'124方向rankの重複なし')
    if len(o):
        values,first=np.unique(accepted['last'],return_index=True)
        decoded=o[:,17]-o[:,2]*(initial+o[:,10]*spacing)*unit
        indices=np.searchsorted(values,decoded)
        A.check(np.all(indices<len(values)),'124待機極値は観測範囲内')
        A.near(values[indices],decoded,'124初回と段間隔を引くと実在Last')
        decisions=A.positions(accepted['row'],o[:,3],'124待機極値の判断')
        A.check(np.all(first[indices]<=decisions),'124未来のLastを待機極値に使わない')

    # ----------------------------------------
    # 最後の正常気配へ全UIDを一度だけ代理清算する。通常返済注文を作らない。
    target=config['session_end'];end=float(accepted['time'][-1]);reference=int(accepted['row'][-1])
    A.check(target-360<=end<=target,'124終端代理は六分以内')
    certificates=[]
    for en in o:
        side=en[2];exit_price=accepted['bid'][-1] if side==1 else accepted['ask'][-1]
        gross=side*(exit_price-en[7])*config['multiplier']
        certificates.append([en[0],side,en[10],en[3],en[4],en[6],en[7],reference,end,exit_price,gross,2*fee,gross-2*fee,target,
            accepted['last'][-1],accepted['bid'][-1],accepted['ask'][-1]])
    expected=np.asarray(certificates,float).reshape(-1,17)
    A.near(p,expected,'124全UID代理十七列と買bid売ask及び往復料金')
    A.check(len(set(p[:,0]))==len(p)==len(o)==row['proxy_count'] and set(p[:,0])==set(o[:,0]),'124全新規UIDを一回だけ代理清算')
    net=float(expected[:,12].sum())
    expected_summary=dict(net=net,cash=net,profit=float(np.maximum(expected[:,12],0).sum()),loss=float(np.maximum(-expected[:,12],0).sum()),
        fees=2*fee*len(o),closed_lots=len(o),wins=int(np.count_nonzero(expected[:,12]>0)),losses=int(np.count_nonzero(expected[:,12]<0)),
        unclosed=0,held_entry_fees=0,last_equity=net,long_net=float(expected[expected[:,1]==1,12].sum()),
        short_net=float(expected[expected[:,1]==-1,12].sum()),entries=len(o),last_time=end)
    for key,value in expected_summary.items():A.near(row[key],value,'124代理後summaryの'+key)
    A.near(c[-1,2],net,'124最終清算時価と代理純益一致')
    A.near(c[-1,3],-fee*len(o),'124通常cashへ将来返済を混ぜない')
    A.near(c[-1,5]+c[-1,6],len(o),'124通常曲線は代理前在庫を保持')
    context=row['context']
    A.check(context['measured'] and context['kind']=='CLOSE_PROXY' and context['base_unclosed']==len(o),'124代理前在庫の区別')
    for key,value in dict(scheduled_time=target,reference_row=reference,reference_time=end,age_seconds=target-end,
            reference_last=accepted['last'][-1],reference_bid=accepted['bid'][-1],reference_ask=accepted['ask'][-1]).items():
        A.near(context[key],value,'124代理contextの'+key)
    A.check(context['approximation']==(end<target),'124近似と予定時計の区別')
    terminal=context['terminal_event']
    A.check(terminal['scheduled_time']==target and terminal['long']==terminal['short']==0 and '代理' in terminal['source'],'124別終端事象の記述')
    A.near(terminal['equity'],net,'124別終端の資産')
    A.near(terminal['cash'],net,'124別終端の現金')
    last_net=float(sum(en[2]*(accepted['last'][-1]-en[7])*config['multiplier']-2*fee for en in o))
    A.near(context['last_price_reference_net'],last_net,'124Last参考とBBO主会計の区別')
    long=o[o[:,2]==1];short=o[o[:,2]==-1]
    lock=dict(balanced=len(long)==len(short)>0,both_caps=len(long)==len(short)==config['cap'])
    if lock['balanced']:
        basis=float(short[:,7].sum()-long[:,7].sum())*config['multiplier']
        spread_cost=len(long)*(accepted['ask'][-1]-accepted['bid'][-1])*config['multiplier']
        A.near(basis-spread_cost-len(o)*2*fee,net,'124同枚数の固定建値差と気配差及び全費用')
        lock.update(locked_basis_gross=basis,closing_spread_cost=float(spread_cost))
    return dict(entries=len(o),net=net,fees=2*fee*len(o),normal=core_result,lock=lock,reference_row=reference,reference_time=end)


def stats(rows: list[dict]) -> dict:
    """
    機能: 全場とIV既知場を固定分母で集計する。
    引数: rows(list[dict])は一商品の一条件の対象小会計。
    返り値: dictはP/L・場数・枚数・大勝ち依存。
    """
    n=len(rows);positive=sorted([r for r in rows if r['net']>0],key=lambda r:(-r['net'],r['session']))
    excluded={r['session'] for r in positive[:3]}
    profit=float(sum(r['profit'] for r in rows));loss=float(sum(r['loss'] for r in rows))
    net=float(sum(r['net'] for r in rows))
    return dict(sessions=n,profit=profit,loss=loss,net=net,profit_fraction=profit/(profit+loss) if profit+loss else None,
        black=len(positive),red=sum(r['net']<0 for r in rows),zero=sum(r['net']==0 for r in rows),
        inactive=sum(r['entries']==0 for r in rows),active_zero=sum(r['entries']>0 and r['net']==0 for r in rows),
        median=float(np.median([r['net'] for r in rows])) if n else None,mean=net/n if n else None,
        worst=float(min([0.]+[r['net'] for r in rows])),entries=int(sum(r['entries'] for r in rows)),fees=float(sum(r['fees'] for r in rows)),
        excluded_top3=[dict(session=r['session'],net=r['net']) for r in positive[:3]],
        net_without_top3=float(sum(r['net'] for r in rows if r['session'] not in excluded)))


def main(result: Path,expected_sha: str,output: Path,fixed_path: Path,registration_path: Path) -> None:
    """
    機能: 完成通知後だけ新保存台帳を一読し、金融再生なしで全会計と引用を照合する。
    引数: result/fixed_path/registration_path/output(Path)は根指定資料・未使用自所有先、expected_sha(str)は完成SHA。
    返り値: None。
    """
    A.check(not output.exists(),'124監査出力未使用')
    owned=output/'owned';owned.mkdir(parents=True)
    raw=result.read_bytes();READS['完成結果']+=1
    A.check(A.sha(raw)==expected_sha,'124完成結果の根指定SHA')
    (owned/'完成結果.json').write_bytes(raw)
    data=json.loads(raw);fixed=read_json(fixed_path);registration=read_json(registration_path)
    A.check(data['passed'] and registration['終了コード']==0,'124完成と登録成功')
    registered=json.loads(registration['stdout'])
    sources={path:A.sha((ROOT/path).read_bytes()) for path in data['source']}
    A.check(sources==data['source']==fixed['sources']==registered['spec']['implementation'],'124正式源の開始拘束')
    binding=fixed['grid_artificial'];proof=read_json(ROOT/binding['path'],binding['sha256'])
    A.check(proof['passed'] and proof['financial_accounts']==0,'124金融前独立人工の正式固定')
    A.check(proof['engine_sha256']==sources['work/stability124_20261019/grid/engine123.py'] and
        proof['core_sha256']==sources['work/stability124_20261019/grid/core123.py'] and
        proof['catalog_sha256']==sources['work/stability124_20261019/grid/catalog124.py'],'124人工と金融の同一版')
    feature_binding=fixed['option_features'];features=read_json(ROOT/feature_binding['path'],feature_binding['sha256'])
    feature_map={r['session']:r for r in features['features']}
    A.check(data['sessions']==list(feature_map) and len(data['sessions'])==41,'124全四十一場と前場特徴')
    A.check(features['known']==11 and features['unknown']==30,'124IV既知未知の分母')
    old_binding=fixed['old_gap_result'];old=read_json(ROOT/old_binding['path'],old_binding['sha256'])
    old_map={(r['session'],r['method']):r for r in old['runs']}
    old_map.update({(r['session'],'I3_G3'):r for r in old['baseline']['rows']})
    A.check(len(old_map)==760,'124旧十九間隔の四十場引用元')
    catalog=load_module('audit124_catalog',WORK/'grid/catalog124.py')
    contracts=load_module('audit124_settings',WORK/'grid/settings124.py')
    A.check(catalog.specifications()==data['specs'] and len(data['specs'])==12,'124固定十二条件')
    rows=data['rows'];latest=data['latest_rows'];all_rows=rows+latest
    A.check(len(rows)==984 and len(latest)==19,'124十二条件二商品四十一場と十九追加一場')
    A.check(len({(r['symbol'],r['session'],r['method']) for r in rows})==984,'124商品場条件は一意')
    ledger_rows={};old_count=0
    latest_session=data['sessions'][-1]
    for row in all_rows:
        feature=feature_map[row['session']]
        if row in rows:
            spec=next(s for s in data['specs'] if s['id']==row['method'])
            params=catalog.parameters(spec,feature,row['symbol'])
            A.check(params==row['params'],'124結果の前場IV固定パラメータ')
            A.check(row['option_known']==feature['known'] and row['option_used']==params['used'],'124IV利用の区分')
            if feature['known']:
                A.check(datetime.fromisoformat(feature['available_at'])<datetime.fromisoformat(feature['session_starts_at']),'124前場情報の利用上限')
        ref=row['reference']
        if row['origin']=='旧四十場の同条件保存引用':
            A.check(row['symbol']=='TOPIX' and row['session']!=latest_session and ref['path']==old_binding['path'],'124旧引用の対象')
            source=old_map[(ref['session'],ref['method'])]
            summary={k:v for k,v in source.items() if k not in ('symbol','session','method')}
            A.check(all(row[k]==v for k,v in summary.items()),'124旧引用の全summary不変')
            old_count+=1
        else:
            A.check(row['origin']=='新しい経済設定を一回再生','124新会計又は同値共有')
            key=(ref['symbol'],ref['session'],ref['ledger_id'])
            ledger_rows.setdefault(key,[]).append(row)
    references={(r['symbol'],r['session']):r for r in data['cache']}
    A.check(len(references)==len(data['cache']),'124新cache商品場一意')
    reports=[]
    for number,ref in enumerate(data['cache']):
        path=(ROOT/ref['path']).resolve()
        A.check(path.is_relative_to((WORK/'grid/measurement').resolve()),'124新所有measurementだけ一読')
        raw=path.read_bytes();READS['新小cache']+=1
        A.check(A.sha(raw)==ref['sha256'],'124新cacheSHA')
        (owned/path.name).write_bytes(raw)
        with np.load(BytesIO(raw),allow_pickle=False) as saved:arrays={k:saved[k].copy() for k in saved.files}
        expected_keys={f'{i}__{kind}' for i in range(ref['ledgers']) for kind in ('orders','lots','curves','proxy_lots')}
        expected_keys|={'quotes__'+k for k in ('row','time','last','bid','ask')}
        A.check(set(arrays)==expected_keys,'124新経済だけの保存集合')
        q={k:arrays['quotes__'+k] for k in ('row','time','last','bid','ask')}
        base=contracts.settings(ref['symbol'],ref['session'])
        for index in range(ref['ledgers']):
            key=(ref['symbol'],ref['session'],str(index));aliases=ledger_rows.pop(key)
            row=aliases[0]
            params=row['params']
            for alias in aliases:
                A.check(tuple(alias['params'][k] for k in ('initial','spacing','cap','unit'))==tuple(params[k] for k in ('initial','spacing','cap','unit')),'124同値共有の経済パラメータ一致')
                A.check(all(alias[k]==row[k] for k in ('net','profit','loss','fees','entries','context','reference')),'124同値共有の結果一致')
            o,l,c,p=[arrays[f'{index}__'+name] for name in ('orders','lots','curves','proxy_lots')]
            answer=account(q,o,l,c,p,row,dict(base,cap=params['cap']))
            reports.append(dict(symbol=ref['symbol'],session=ref['session'],ledger_id=str(index),methods=[r['method'] for r in aliases],**answer))
        print(f'{number+1}/{len(data["cache"])} 商品場の全新会計一致',flush=True)
    A.check(not ledger_rows,'124全新会計参照は保存台帳へ対応')
    A.check(len(reports)==data['financial_accounts'],'124新金融数とunique台帳数')
    A.check(data['old_account_references']+data['equivalent_account_references']+data['financial_accounts']==len(all_rows),'124新金融と旧引用と同値共有の全件会計')
    A.check(sources=={p:A.sha((ROOT/p).read_bytes()) for p in sources},'124源の終端不変')
    statistics={symbol:{spec['id']:dict(all=stats([r for r in rows if r['symbol']==symbol and r['method']==spec['id']]),
        option_known=stats([r for r in rows if r['symbol']==symbol and r['method']==spec['id'] and r['option_known']]))
        for spec in data['specs']} for symbol in ('TOPIX','NK225')}
    projection=dict(passed=True,statistics=statistics,latest=[r for r in rows if r['session']==latest_session],
        latest_gap=latest,financial_replay=0)
    A.save(output/'十二IV条件の全場と既知場の独立集計.json',projection)
    proof=dict(passed=True,result_sha256=expected_sha,sources=sources,source_sha256=A.sha(Path(__file__).read_bytes()),
        saved_accounts=len(reports),display_rows=len(all_rows),financial_replay=0,original_market_reads=0,old_npz_reads=0,
        registry_changes=0,checks=dict(A.CHECKS),reads=dict(READS),reports=reports,
        留保='通常台帳と全行時価を独立算術で照合。方向予測の新実行ではない。取消待機の全内部状態は期待線人工へ委譲。終端は実引け約定ではなく直前六分の代理。')
    target=output/'十二IV条件と十九追加間隔の保存会計独立監査.json'
    A.save(target,proof)
    print(json.dumps(dict(passed=True,path=target.relative_to(ROOT).as_posix(),sha256=A.sha(target.read_bytes()),
        saved_accounts=len(reports),display_rows=len(all_rows),reads=dict(READS)),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fixed',type=Path,required=True)
    parser.add_argument('--registration',type=Path,required=True)
    args=parser.parse_args()
    main(args.result,args.sha256,args.output,args.fixed,args.registration)
