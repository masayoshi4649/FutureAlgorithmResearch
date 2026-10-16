"""長い往復と直近三点を混同せず、局所位相と方向別未fill取消を人工で独立検査する。"""

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys

import numpy as np

from range_engine_check import load,digest,fixture,economy
from range_joint_check import packet


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/local_phase'
OLD=ROOT/'work/wave_v106/range_price'


def state(value: int | None, n: int, tick: float) -> dict:
    """
    機能: 三点の事実から既知強方向・中立・未知を人工作成する。
    引数: value(int|None)、n(int)、tick(float)は方向・正常行数・商品呼値。
    返り値: dictはphase表示契約。財務結果から値を選ばない。
    """
    base=1000*tick;known=np.full(n,value is not None,bool);direction=np.full(n,value or 0,np.int8)
    points=np.repeat([[base,base+(value or 0)*tick,base+2*(value or 0)*tick]],n,axis=0)
    return dict(known=known,direction=direction,points=points,ER=np.full(n,1. if value else 0.),
        TV_ticks=np.full(n,2. if value else 0.),net_ticks=np.full(n,2*(value or 0),float))


def main() -> None:
    """
    機能: 最終sourceを変更せず、独立Fraction/真偽表/人工経済prefixで仕様を反証する。
    引数: なし。正式33packet・実金融結果・原本・APIを読まない。
    返り値: None。私有完全コピー上のPython人工だけと非金融証跡を保存する。
    """
    target=HERE/'local_三点位相と方向別取消の独立人工.json';assert not target.exists()
    paths=[SOURCE/name for name in ('common.py','features.py','catalog.py','selection.py','selection_snapshot.py','interface.py','engine/core.py','engine/reference_core.py')]
    before={str(p.relative_to(ROOT)):digest(p) for p in paths}
    assert digest(SOURCE/'selection_snapshot.py')==digest(OLD/'selection.py')
    assert digest(SOURCE/'engine/reference_core.py')==digest(OLD/'engine/core.py')
    # ----------------------------------------
    # 元AUTO factoryを先に作り、その後だけ私有processの通常名を局所sourceへ接続する。
    sys.path.insert(0,str(OLD));base={(symbol,side):packet(symbol,side,'MARKET') for symbol in ('TOPIX','NK225') for side in (-1,1)}
    F=load('独立局所特徴',SOURCE/'features.py');C=load('独立局所共通',SOURCE/'common.py');catalog=load('独立局所設定',SOURCE/'catalog.py')
    previous={name:sys.modules.get(name) for name in ('features','common')}
    sys.modules['features']=F;sys.modules['common']=C
    try:S=load('独立局所選択',SOURCE/'selection.py')
    finally:
        for name,value in previous.items():
            if value is None:sys.modules.pop(name,None)
            else:sys.modules[name]=value
    I=load('独立局所接口',SOURCE/'interface.py');oldI=load('独立局所旧接口',OLD/'interface.py')
    snapshot=HERE/'local_engine_snapshot.py';snapshot.write_bytes((SOURCE/'engine/core.py').read_bytes());newcore=load('独立局所経済copy',snapshot)
    oldsnapshot=HERE/'local_reference_engine_snapshot.py';oldsnapshot.write_bytes((OLD/'engine/core.py').read_bytes())
    oldcore=load('local_reference_engine_snapshot',oldsnapshot)
    assert digest(oldsnapshot)==digest(OLD/'engine/core.py')
    I.module=lambda name,path:newcore;oldI.module=lambda name,path:oldcore
    counts={};number=0
    def count(label: str, n: int=1) -> None:
        """
        機能: 独立人工の検査数を意味ごとに残す。
        引数: label(str)、n(int)は名称と件数。
        返り値: None。実市場での成功件数として表示しない。
        """
        counts[label]=counts.get(label,0)+n
    for symbol in ('TOPIX','NK225'):
        tick=.5 if symbol=='TOPIX' else 10.
        triples=[];expected=[]
        for first in (-4,-2,0,2,4):
            for second in (-4,-2,0,2,4):
                for third in (-4,-2,0,2,4):
                    values=[Fraction(x,2) for x in (first,second,third)];net=values[-1]-values[0];tv=abs(values[1]-values[0])+abs(values[2]-values[1])
                    er=abs(net)/tv if tv else Fraction(0)
                    direction=(1 if net>0 else -1) if er>=Fraction(3,5) and abs(net)>=2 else 0
                    triples.append([1000*tick+float(v)*tick for v in values]);expected.append((float(net),float(tv),float(er),direction))
        actual=F.phase(np.array(triples),np.ones(len(triples),bool),tick)
        for i,(net,tv,er,direction) in enumerate(expected):
            assert actual['known'][i] and actual['net_ticks'][i]==net and actual['TV_ticks'][i]==tv and actual['ER'][i]==er and actual['direction'][i]==direction;count('Fraction三点ERと2呼値閾値')
        unknown=F.phase(np.array(triples),np.zeros(len(triples),bool),tick)
        assert not unknown['known'].any() and not unknown['direction'].any() and np.isnan(unknown['ER']).all();count('未知を中立へ救済しない')
        for side in (-1,1):
            p=base[symbol,side];short=F.build(p,symbol);measured=p['measured'][symbol];index=measured['normal_sample_index']
            expected=np.column_stack((measured['sample_tables']['own']['midpoint'][index,-3:-1],(p['prepared'][symbol]['record']['bid']+p['prepared'][symbol]['record']['ask'])/2))
            np.testing.assert_array_equal(short['own']['points'],expected);np.testing.assert_array_equal(short['peer']['points'],measured['sample_tables']['peer']['midpoint'][index,-3:]);count('自己当行midと相手strictpast三点')
            # ----------------------------------------
            # 同clock後半のBBOだけが動いても、自己三点の終点は初公表midへ巻戻さない。
            changed=deepcopy(p);changed['prepared'][symbol]['record']['bid'][8:]+=side*tick;changed['prepared'][symbol]['record']['ask'][8:]+=side*tick
            after=F.build(changed,symbol)
            for name in ('own','peer'):
                for field in ('known','points','ER','TV_ticks','net_ticks','direction'):np.testing.assert_array_equal(short[name][field][:8],after[name][field][:8]);count('将来行変更の位相接頭不変')
            n=len(p['prepared'][symbol]['record']['seq'])
            for own in (-1,0,1,None):
                for peer in (-1,0,1,None):
                    sample=dict(own=state(own,n,tick),peer=state(peer,n,(10. if symbol=='TOPIX' else .5)))
                    for policy in ('OWN_VETO','BOTH_VETO','ALIGNED'):
                        allowed,cancel=F.decisions(sample,side,policy)
                        ownopp=own==-side;bothopp=ownopp and peer==-side
                        a=not ownopp if policy=='OWN_VETO' else not bothopp if policy=='BOTH_VETO' else own==side and peer==side
                        b=ownopp if policy=='OWN_VETO' else bothopp
                        assert np.all(allowed==a) and np.all(cancel==b);count('方向別3政策の独立真偽表')
                        config=next(c for c in catalog.catalog() if c['local_policy']==policy and c['margin_ticks']==1 and c['range_entry']=='MARKET')
                        current=deepcopy(p);current['short']={symbol:sample};result=S.build(current,symbol,config)
                        old=S.legacy.build(p,symbol,config);R=old['entry_families']==2
                        np.testing.assert_array_equal(result['event'],np.where(R&(not a),0,old['event']));count('Rだけ入口拒否')
                        np.testing.assert_array_equal(result['local_cancel_buy'],F.decisions(sample,1,policy)[1]);np.testing.assert_array_equal(result['local_cancel_sell'],F.decisions(sample,-1,policy)[1]);count('取消2列の買売区別')
            # ----------------------------------------
            # 元C自己episodeへRと異なる短期状態を与えても、元のC列を拒否しない。
            cpacket=deepcopy(p);row=7;cpacket['measured'][symbol]['states']['0.4'][row]=2*side
            cpacket['measured'][symbol]['boundary_events']['0.4'][row]=0
            c=cpacket['cases'][symbol]['C_OWN'];support=float(p['prepared'][symbol]['record']['bid' if side>0 else 'ask'][row])
            c['event'][row]=side;c['support_price'][row]=support;c['entry_quality'][row]=True;c['entry_reset'][row]=False
            c['decisions']=[dict(row=row,normal_row=row,raw_row=row,raw_seq=int(p['prepared'][symbol]['record']['seq'][row]),side=side,support_price=support,
                selected_support_roots=[dict(anchor_raw_seq=203,support_price=support)],episode=('C人工',side,207))]
            for policy in ('OWN_VETO','BOTH_VETO','ALIGNED'):
                cfg=next(c for c in catalog.catalog() if c['local_policy']==policy and c['margin_ticks']==1 and c['range_entry']=='MARKET')
                cpacket['short']={symbol:dict(own=state(-side,n,tick),peer=state(-side,n,10. if symbol=='TOPIX' else .5))}
                result=S.build(cpacket,symbol,cfg);old=S.legacy.build(cpacket,symbol,cfg)
                for field in ('event','support_price','entry_quality','entry_reset','entry_families'):np.testing.assert_array_equal(result[field],old[field]);count('C元候補と資格不変更')
                assert result['decisions']==old['decisions'];count('C原支持系譜exact')
    # ----------------------------------------
    # 型を含む新2列以外は旧core。小人工で各方向の待機取消・fill先・保有後を対照する。
    for symbol in ('TOPIX','NK225'):
        qty=5 if symbol=='TOPIX' else 10
        for side in (-1,1):
            for label in ('追加取消off','逆側取消','到達同行取消','未到達前取消','保有後取消','C取消非適用'):
                p,n,cfg=fixture(symbol,side,2,'LIMIT');n['range_pending_trend'][:]=False
                n['local_cancel_buy']=np.zeros(13,bool);n['local_cancel_sell']=np.zeros(13,bool)
                own=n['local_cancel_buy'] if side==1 else n['local_cancel_sell'];other=n['local_cancel_sell'] if side==1 else n['local_cancel_buy']
                if label=='逆側取消':other[2:]=True
                if label=='到達同行取消':own[3:]=True
                if label=='未到達前取消':own[2:]=True
                if label=='保有後取消':own[4:]=True
                if label=='C取消非適用':n['entry_families'][1]=1;own[2:]=True;other[2:]=True
                new=I.play(p,n,cfg,quantity=qty,python=True);old=oldI.play(p,n,cfg,quantity=qty,python=True);number+=1
                count('人工独立cash费用全行',economy(p['record'],new))
                if label=='未到達前取消':assert len(new['orders'])==0 and len(new['trades'])==0 and new['curve'].sum()==0;count('取消後未復活料金なし')
                else:
                    for field in ('orders','trades','growth_cohorts','curve','source_curve','target_trace','events'):np.testing.assert_array_equal(new[field],old[field]);count('局所述語のみで旧経済null')
                if label=='到達同行取消':assert new['orders'][0,0]==3 and new['raw_entry_diagnostics'][0]['fill_local_cancel_condition'];count('live到達fillが同行取消より先')
                cut=4 if label!='未到達前取消' else 3
                prefix=deepcopy(p);prefix['record']={k:v[:cut].copy() if isinstance(v,np.ndarray) else v for k,v in p['record'].items()}
                short={k:v[:cut].copy() if isinstance(v,np.ndarray) else deepcopy(v) for k,v in n.items()};short['decisions']=[d for d in short['decisions'] if d['row']<cut]
                partial=I.play(prefix,short,cfg,quantity=qty,finish=False,python=True)
                np.testing.assert_array_equal(partial['orders'],new['orders'][new['orders'][:,0]<cut]);np.testing.assert_array_equal(partial['curve'],new['curve'][:cut]);count('接頭保有と未約定取消に未来返済なし')
    assert before=={str(p.relative_to(ROOT)):digest(p) for p in paths}
    proof=dict(全合格=True,scope='局所18設計の非金融及び私有Python小人工独立反証。正式33入力/金融結果を読まない。',
        検査件数=counts,合計=sum(counts.values()),経済人工口座=number,source_SHA256=before,
        source開始終端一致=True,私有engine_SHA256=digest(snapshot),レビューsource_SHA256=digest(Path(__file__)),
        正式金融再生=0,正式33packet読取=0,原本API=0,
        制約=['ALIGNEDのbothstrongoppだけは追加局所取消の条件。旧knownTREND/固定stop/J/cutは残る。',
            'ALIGNEDで同方向が消えただけでは追加取消しない。未知もpending取消へ代用しない。',
            '三点は120/60秒sampleと現在又はstrict過去endpoint。全tickの流れでも真の受信時刻でもない。',
            '既知33からの損失原因を受けた新研究であり、人工合格を金融改善や未知の収益保証と呼ばない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('局所18の独立人工合格',sum(counts.values()),'検査',number,'人工口座',flush=True)


if __name__=='__main__':main()
