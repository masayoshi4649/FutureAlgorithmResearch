"""固定十二IV条件と旧十九間隔の追加一場を、同条件の二重再生なしで測る。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import engine123 as E
import codec124
from catalog123 import specifications as gaps
from catalog124 import specifications,parameters
from settings124 import settings

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from common124 import HERE,ROOT,SCENE,read,save,sha


def economic_key(params: dict) -> tuple:
    """
    機能: 表示政策名ではなく実際の経済パラメータで同値会計を識別する。
    引数: params(dict)は初回・間隔・枚数・一単位。
    返り値: tupleは重複再生を避ける四つの固定値。
    """
    return tuple(params[k] for k in ('initial','spacing','cap','unit'))


def execute(fixed_path: Path,registration_path: Path) -> None:
    """
    機能: 登録拘束後に新経済だけ測り、旧TOPIX基準と同値条件を引用する。
    引数: fixed_path/registration_path(Path)は根の正式固定と登録全出力。
    返り値: None。全会計・注文・玉・終端代理と実際の再生数を保存する。
    """
    fixed=read(fixed_path);registered=read(registration_path);assert registered['終了コード']==0
    assert json.loads(registered['stdout'])['spec']['implementation']==fixed['sources']
    for p,h in fixed['sources'].items():assert sha(ROOT/p)==h,p
    for binding in [fixed['input_manifest'],fixed['quote_manifest'],fixed['option_features'],fixed['old_gap_result']]:
        assert sha(ROOT/binding['path'])==binding['sha256']
    proof=fixed['grid_artificial'];assert sha(ROOT/proof['path'])==proof['sha256'] and read(ROOT/proof['path'])['passed']
    manifest=read(ROOT/fixed['input_manifest']['path']);references=read(ROOT/fixed['quote_manifest']['path'])
    old=read(ROOT/fixed['old_gap_result']['path']);features=read(ROOT/fixed['option_features']['path'])
    feature_map={r['session']:r for r in features['features']};sessions=references['sessions']
    assert len(sessions)==41 and sessions==list(feature_map)
    old_rows={(r['session'],r['method']):r for r in old['runs']}
    old_rows.update({(r['session'],'I3_G3'):r for r in old['baseline']['rows']})
    assert len(old_rows)==760
    inputs={(r['session'],r['symbol']):r for r in references['inputs']}
    new_inputs={i['symbol']:i for i in manifest['inputs'] if i['kind']=='book'}
    out=HERE/'grid/measurement';assert not out.exists();out.mkdir()
    runs=[];latest=[];caches=[];reads=[];calculations=0;source_reuse=0;equivalent_reuse=0

    # ----------------------------------------
    # 一商品・一場の入力を必要なときだけ読み、同じ設定は一回の会計に共有する。
    for scene in sessions:
        feature=feature_map[scene]
        if feature['known']:
            from datetime import datetime
            assert datetime.fromisoformat(feature['available_at'])<datetime.fromisoformat(feature['session_starts_at'])
        for symbol in ('TOPIX','NK225'):
            config=settings(symbol,scene);memo={};arrays={};quotes=None;serial=0
            requests=[('option',s,parameters(s,feature,symbol)) for s in specifications()]
            if scene==SCENE and symbol=='TOPIX':
                requests += [('latest',s,dict(initial=s['initial'],spacing=s['spacing'],cap=10,unit=1.,used=False)) for s in gaps()]
            for family,spec,params in requests:
                key=economic_key(params);origin='new';reference=None
                if key in memo:
                    entry=memo[key];equivalent_reuse+=1
                else:
                    old_id={(3.,3.,10,1.):'I3_G3',(3.,10.,10,1.):'I3_G10',(15.,15.,10,1.):'I15_G15'}.get(key)
                    if symbol=='TOPIX' and scene!=SCENE and old_id is not None:
                        source=old_rows[scene,old_id]
                        entry=dict(summary={k:v for k,v in source.items() if k not in ('symbol','session','method')},
                            origin='旧四十場の同条件保存引用',reference=dict(path=fixed['old_gap_result']['path'],method=old_id,session=scene))
                        source_reuse+=1
                    else:
                        if quotes is None:
                            if scene==SCENE:
                                item=new_inputs[symbol];path=ROOT/item['staged_path']
                                info=dict(kind='jsonl',path=item['staged_path'],bytes=item['bytes'],sha256=item['sha256'],symbol=symbol,session=scene)
                                prepared=codec124.load(info,symbol)
                                quotes={k:prepared['quotes'][k] for k in ['row','time','last','bid','ask']}
                                reads.append(dict(prepared['read_metadata'],input_kind='新所有JSONL'))
                            else:
                                item=inputs[scene,symbol];payload=(ROOT/item['path']).read_bytes()
                                assert hashlib.sha256(payload).hexdigest()==item['sha256']
                                with np.load(BytesIO(payload),allow_pickle=False) as saved:
                                    quotes={k:saved['quotes__'+k].copy() for k in ['row','time','last','bid','ask']}
                                reads.append(dict(session=scene,symbol=symbol,kind='既存所有NPZ',path=item['path'],sha256=item['sha256']))
                            assert len(quotes['row'])>0 and np.all(np.diff(quotes['time'])>=0)
                        local=dict(config,cap=params['cap'])
                        o,l,c,s,p,x=E.evaluate(quotes,local,'CLOSE_PROXY',params['initial'],params['spacing'],params['unit'])
                        assert not len(l) and len(o)==len(p)==s['entries'] and np.all(o[:,1]==1)
                        assert x['measured'] and s['unclosed']==0 and s['max_long']<=params['cap'] and s['max_short']<=params['cap']
                        assert s['net']==s['profit']-s['loss']==sum(p[:,12])
                        signed=p[:,1]
                        summary=dict(s,long_net=float(p[signed==1,12].sum()),short_net=float(p[signed==-1,12].sum()),
                            context=x,proxy_count=len(p),regular_closed=0)
                        ledger_id=str(serial);serial+=1;calculations+=1
                        for name,value in [('orders',o),('lots',l),('curves',c),('proxy_lots',p)]:arrays[ledger_id+'__'+name]=value
                        entry=dict(summary=summary,origin='新しい経済設定を一回再生',reference=dict(session=scene,symbol=symbol,ledger_id=ledger_id))
                    memo[key]=entry
                row=dict(symbol=symbol,session=scene,method=spec['id'],name=spec['name'],params=params,
                    **entry['summary'],origin=entry['origin'],reference=entry['reference'])
                if family=='option':
                    row.update(option_known=feature['known'],option_used=params['used'],
                        option_effective_changed=params['used'] and key!=(3.,3.,10 if symbol=='TOPIX' else 20,1. if symbol=='TOPIX' else 20.),
                        option_previous_session=feature['previous_session'])
                    runs.append(row)
                else:latest.append(row)
            if arrays:
                path=out/(symbol+'_'+scene+'.npz')
                np.savez_compressed(path,**arrays,**{'quotes__'+k:v for k,v in quotes.items()})
                caches.append(dict(symbol=symbol,session=scene,path=path.relative_to(ROOT).as_posix(),sha256=sha(path),ledgers=serial))
            print(scene,symbol,'新会計',serial,flush=True)

    # ----------------------------------------
    # 全41場の表示行と、実際に新金融を行った同値でない会計数を区別する。
    assert len(runs)==12*41*2 and len(latest)==19
    for p,h in fixed['sources'].items():assert sha(ROOT/p)==h,p
    save(HERE/'grid/十二IV条件の全四十一場と旧十九条件の追加一場.json',dict(passed=True,sessions=sessions,specs=specifications(),
        rows=runs,latest_rows=latest,cache=caches,input_reads=reads,financial_accounts=calculations,
        old_account_references=source_reuse,equivalent_account_references=equivalent_reuse,option_known=features['known'],
        source=fixed['sources'],order_columns=E.BASE.ORDER_COLUMNS,lot_columns=E.BASE.LOT_COLUMNS,curve_columns=E.BASE.CURVE_COLUMNS,
        proxy_columns=E.PROXY_COLUMNS,old_gap_reference=fixed['old_gap_result'],option_feature_reference=fixed['option_features'],
        original_market_reads=0,API=0,real_orders=0,unclosed=0,
        limitations='旧40とオプション既知10場は開発。追加10月19日デイは固定比較。前場IVは場中変化の予測でなく提供値の粗い尺度。日経IVをTOPIX固有IVと呼ばない。終端は直前6分BBO代理。'))
    print('新会計',calculations,'旧引用',source_reuse,'同値共有',equivalent_reuse,flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--fixed',type=Path,required=True);parser.add_argument('--registration',type=Path,required=True)
    args=parser.parse_args();execute(args.fixed,args.registration)
