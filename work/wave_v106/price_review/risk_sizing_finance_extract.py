"""事前固定した5新3旧台帳と4packetを一読し、保存会計の数量・時価・停止を監査する。"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import gzip
import hashlib
import json
import pickle

import numpy as np

import range_finance_audit as A
from e01_trade_finance_audit import inspect_orders
from risk_sizing_oracle import fee, sized_quantity, LOSS
from risk_sizing_finance_small import near


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_risk_sizing'
DATA_CACHE=globals().get('DATA_CACHE',{})
READS=globals().get('READS',{})


def read(path: Path) -> dict:
    """
    機能: 保存小JSONをUTF-8で取得する。
    引数: path(Path)は小資料の位置。
    返り値: dictは保存値。金融再生を呼ばない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: source又は小JSONのSHA256を取得する。
    引数: path(Path)は小資料の位置。
    返り値: strは指紋。大型bytesはload内一読のものだけで指紋化する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(item: dict) -> dict:
    """
    機能: 固定された一ファイルを同bytes一読し、以後は同じメモリを参照する。
    引数: item(dict)は固定path/SHA256。
    返り値: dictは保存台帳又はpacket。デバッグ時も原ファイルの二読を禁止する。
    """
    name=item['path']; sha=item['SHA256']
    if name in DATA_CACHE:
        assert READS[name]==sha; return DATA_CACHE[name]
    path=ROOT/name; assert path.resolve().is_relative_to(ROOT/'work')
    content=path.read_bytes(); assert hashlib.sha256(content).hexdigest()==sha
    READS[name]=sha; value=pickle.loads(gzip.decompress(content)); DATA_CACHE[name]=value
    return value


def expand(value: object, n: int) -> np.ndarray:
    """
    機能: 保存された前方保持の曲線を補間なしで展開する。
    引数: value(object)、n(int)は保存曲線と正常行数。
    返り値: ndarrayは当時行の同値曲線。未来値は使わない。
    """
    return A.expand(value,n) if isinstance(value,dict) else value


def accepted(base: dict, mode: str) -> tuple[bool,int]:
    """
    機能: 当時W60の母採否と拒否理由を独立計算する。
    引数: base(dict)、mode(str)は当時票とVETO/CONFIRM。
    返り値: tuple[bool,int]は元公開採否。実busyとは区別する。
    """
    if not base['known']:
        return (True,0) if mode=='VETO' else (False,100+base['reason'])
    if base['direction_votes']<2:
        return (True,0) if mode=='VETO' else (False,200)
    allow=base['balance']>=.25 if mode=='CONFIRM' else base['balance']>-.25
    return allow,0 if allow else 201 if mode=='CONFIRM' else 202


def clock(account: dict, row: int) -> str:
    """
    機能: 保存価格時計を日本時間の表示に変換する。
    引数: account(dict)、row(int)は保存口座と正常行。
    返り値: strは日本時間。受信時刻ではなく価格時計の代理である。
    """
    return datetime.fromtimestamp(float(account['record']['time_s'][row]),ZoneInfo('Asia/Tokyo')).isoformat(timespec='seconds')


def gate_and_size(a: dict, out: dict, config: dict, gu_path: dict) -> dict:
    """
    機能: 不変影、当行票、当行整数q、実料清算余力、次正常気配を独立照合する。
    引数: a/out/config/gu_path(dict)は一読口座・台帳・条件・独立GU実注文曲線。
    返り値: dictは公開数量とGU部分返済の小観測。GU停止後は診断として明示する。
    """
    q=a['quotes']; r=a['record']; feed=a['feed']; n=len(r['price']); symbol=a['symbol']
    mask=np.ones(n,bool); reasons=np.zeros(n,np.int32); virtual_delta=np.zeros(n,np.int64); current=np.full(n,-1,np.int64)
    entries={}; previous=0; cid=-1
    for order in feed:
        row,parent,side,quantity,new=map(int,(order[0],order[2],order[3],order[4],order[7]))
        virtual_delta[row]+=side*quantity
        if new:
            current[previous:row]=cid; cid=parent; previous=row; entries[parent]=order
            base=a['trade_features']['60'][row]; mask[row],reasons[row]=accepted(base,config['mode'])
            if base['reason']!=2:
                assert base['candidate_raw_row']==a['mapping'][row] and base['candidate_raw_seq']==r['seq'][row]
                near(base['candidate_price_time_s'],r['time_s'][row])
    current[previous:]=cid
    np.testing.assert_array_equal(expand(out['gate_accepted'],n),mask)
    np.testing.assert_array_equal(expand(out['gate_reasons'],n),reasons)
    states=expand(out['execution_states'],n)
    np.testing.assert_array_equal(states[:,0],current); np.testing.assert_array_equal(states[:,1],np.cumsum(virtual_delta))
    assert out['shadow_feed_SHA256']==a['paper_SHA256']
    gu=out['shadow_GU_orders']; paid=np.zeros(n,np.int64)
    for order in gu: paid[int(order[0])]+=fee(int(order[4]),symbol)
    paid=np.cumsum(paid); reserve=gu_path['equity']-gu_path['liquidation']
    expected=np.column_stack((paid,reserve,gu_path['equity'],gu_path['liquidation'],np.maximum(0.,LOSS[symbol]+gu_path['liquidation'])))
    np.testing.assert_allclose(expand(out['sizing_fee_curve'],n),expected,rtol=0,atol=1e-7)
    diagnostics=out['sizing_events']; assert len(diagnostics)==len(entries)
    observed=[]; by_row={int(e[0]):e for e in diagnostics}
    control=out['control']; stop=control.get('判断行',n)
    for parent,pub in entries.items():
        row=int(pub[0]); event=by_row[row]; assert int(event[1])==parent and int(event[2])==pub[3] and int(event[3])==pub[4]
        near(event[5],pub[9]); near(event[8],gu_path['liquidation'][row]); near(event[9],max(0.,LOSS[symbol]+gu_path['liquidation'][row]))
        assert event[11]==paid[row]; near(event[12],reserve[row]); assert bool(event[14])==mask[row]
        oracle=sized_quantity(float(pub[9]),float(q['bid'][row]),float(q['ask'][row]),float(event[9]),symbol)
        if not gu_path['valid'][row]:
            assert event[4]==0 and event[13]==96
        elif not oracle['known']:
            assert event[4]==0 and event[13]==96
        else:
            assert int(event[4])==oracle['quantity']
            if oracle['quantity']==0: assert event[13]==97
            else: near(event[10],oracle['amounts'][oracle['quantity']-1]); assert event[13]==0
        observed.append(dict(親=parent,公開行=row,原行=int(a['mapping'][row]),原seq=int(r['seq'][row]),価格時計=clock(a,row),
            影初回=int(pub[4]),公開実予定q=int(event[4]),実余力=float(event[9]),予定額=float(event[10]),
            数量理由=int(event[13]),母許可=bool(event[14]),公開時実待機=bool(event[15]),実政策停止後GU診断=row>stop))
    for order in gu[gu[:,7]==1]:
        row,source,parent,quantity=map(int,(order[0],order[1],order[2],order[4])); event=by_row[source]
        assert mask[source] and event[15] and quantity==event[4] and row==source+1+int(np.flatnonzero(gu_path['valid'][source+1:])[0])
        assert int(q['seq'][row])>int(q['seq'][source]) and not (a['quiet'][row] or a['quiet_force'][row] or r['time_s'][row]>=r['limit'])
    # 累積元返済比率を独立再計算する。予約されない0枚を注文へ補完しない。
    partial=[]
    for order in gu[gu[:,7]==1]:
        parent=int(order[2]); real=int(order[4]); virtual=int(entries[parent][4]); closes=gu[(gu[:,2]==parent)&(gu[:,7]==0)]
        completed=0
        for source in dict.fromkeys(int(o[1]) for o in closes):
            group=closes[closes[:,1]==source]; quantity=int(group[:,4].sum())
            normal=group[group[:,6]==91]
            if len(normal):
                shadow_closed=int(feed[(feed[:,2]==parent)&(feed[:,7]==0)&(feed[:,0]<=source),4].sum())
                expected_closed=real*shadow_closed//virtual
                assert completed+quantity==expected_closed
            completed+=quantity
        assert completed==real
        if real==3 and len(closes)>1:
            partial.append(dict(親=parent,GU実初回=real,GU返済=[int(o[4]) for o in closes],
                範囲='保存GU診断の部分返済であり、停止後の実政策注文とは区別する。'))
    return dict(公開=observed,GU_Q3部分=partial)


def stop_check(a: dict, out: dict, config: dict, gu_path: dict) -> None:
    """
    機能: GU実注文から先着円停止、実接頭と残UIDだけの次正常気配返済を確認する。
    引数: a/out/config/gu_path(dict)は一読素材と独立曲線。
    返り値: None。未来の勝ち親や返済テンプレートを停止選択へ用いない。
    """
    symbol=a['symbol']; gu=out['shadow_GU_orders']; uids=out['shadow_GU_uids']; valid=gu_path['valid']
    hits=np.flatnonzero(valid&((gu_path['liquidation']>=config['profit_goal_yen'][symbol])|(gu_path['liquidation']<=-LOSS[symbol])))
    assert out['control']['発動']==bool(len(hits))
    if not len(hits): np.testing.assert_array_equal(out['orders'],gu); return
    decision=int(hits[0]); keep=gu[:,0]<=decision; count=int(keep.sum()); control=out['control']
    assert control['判断行']==decision; near(control['判断時清算利益'],gu_path['liquidation'][decision])
    assert control['種別']==('利益目標' if gu_path['liquidation'][decision]>=config['profit_goal_yen'][symbol] else '損失予算')
    np.testing.assert_array_equal(out['orders'][:count],gu[keep]); np.testing.assert_array_equal(out['order_uids'][:count],uids[keep])
    held={}
    for order,uid in zip(gu[keep],uids[keep]):
        side,parent,quantity,new=map(int,(order[3],order[2],order[4],order[7]))
        if new: held[int(uid)]=dict(parent=parent,side=side,quantity=quantity)
        else:
            remaining=quantity
            for state in held.values():
                if state['parent']==parent and state['side']==-side:
                    amount=min(remaining,state['quantity']); remaining-=amount; state['quantity']-=amount
            assert remaining==0
    open_uid={uid:v for uid,v in held.items() if v['quantity']}; after=out['orders'][count:]
    assert len(after)==len(open_uid)
    if open_uid:
        fill=decision+1+int(np.flatnonzero(valid[decision+1:])[0]); assert control['返済行']==fill
        for order,uid in zip(after,out['exit_target_uids'][count:]):
            state=open_uid.pop(int(uid)); assert order[0]==fill and order[1]==decision and order[2]==state['parent'] and order[3]==-state['side'] and order[4]==state['quantity'] and order[7]==0
    assert not open_uid and not np.any(out['orders'][(out['orders'][:,0]>decision)&(out['orders'][:,7]==1)])


def main() -> None:
    """
    機能: rootへ送付済み抽出計画だけを実行し、5新3旧台帳と4packetの独立監査を保存する。
    引数: なし。元ファイルは各一読で、人工又は金融エンジンを再実行しない。
    返り値: Noneは自所有の小証跡。全264大台帳の検証とは呼ばない。
    """
    plan_path=HERE/'risk_sizing_金融抽出5新3旧4packetの事前固定.json'; plan=read(plan_path)
    assert digest(plan_path)=='9f82b9fbb9426af9427be72674e21a056a0032257a4744eb0e1fbeab94278983'
    result=read(ROOT/plan['financial_result_path']); assert digest(ROOT/plan['financial_result_path'])==plan['financial_result_SHA256']
    configs={c['id']:c for c in result['configs']}; target=HERE/'risk_sizing_抽出5新3旧と4packetの実数量料金停止の独立監査.json'; assert not target.exists()
    packets={s:load(v) for s,v in plan['一読packet'].items()}
    new={}; reviewed=[]; parents={}; comparisons=[]
    for item in plan['新台帳']:
        a=packets[item['session']]['accounts'][item['symbol']]; out=load(item); cid=item['id']; key=cid,item['session'],item['symbol']; n=len(a['record']['price'])
        p,legs,path=inspect_orders(out,a['quotes'],item['symbol'])
        _,_,gu_path=inspect_orders(dict(orders=out['shadow_GU_orders'],order_uids=out['shadow_GU_uids']),a['quotes'],item['symbol'],False)
        diag=gate_and_size(a,out,configs[cid],gu_path); stop_check(a,out,configs[cid],gu_path)
        new[key]=out; parents[key]=p
        if item['purpose'].startswith('q0'):
            zero=[v for v in diag['公開'] if v['公開実予定q']==0 and v['母許可'] and not v['実政策停止後GU診断']]
            actual=[o for o in out['orders'] if o[7]]
            assert zero and actual and min(z['公開行'] for z in zero)<min(int(o[1]) for o in actual)
        if item['purpose'].startswith('実Q2'):
            assert out['summary']['新規枚数']==2 and len(out['orders'])==3 and out['summary']['費用']==165
            assert [int(o[4]) for o in out['orders']]==[2,1,1]
        leg_gain=sum(max(0.,v['net']) for v in legs); leg_loss=sum(max(0.,-v['net']) for v in legs)
        near(out['actual_leg_totals']['profit'],leg_gain); near(out['actual_leg_totals']['loss'],leg_loss)
        reviewed.append(dict(id=cid,session=item['session'],symbol=item['symbol'],目的=item['purpose'],親数=len(p),
            収支=out['summary']['収支'],料金=out['summary']['費用'],実政策注文=[dict(行=int(o[0]),判断行=int(o[1]),親=int(o[2]),
            方向=int(o[3]),数量=int(o[4]),価格=float(o[5]),理由=int(o[6]),新規=bool(o[7]),価格時計=clock(a,int(o[0]))) for o in out['orders']],
            停止=out['control'],**diag))
    for item in plan['旧台帳']:
        a=packets[item['session']]['accounts'][item['symbol']]; old=load(item); p,_,_=inspect_orders(old,a['quotes'],item['symbol'])
        key=item['new_id'],item['session'],item['symbol']; fresh=parents[key]; removed=set(p)-set(fresh); joined=set(p)&set(fresh); added=set(fresh)-set(p)
        values=dict(収支変化=sum(x['net'] for x in fresh.values())-sum(x['net'] for x in p.values()),
            避けた基準損失=sum(-p[k]['net'] for k in removed if p[k]['net']<0),失った基準利益=sum(p[k]['net'] for k in removed if p[k]['net']>0),
            共通入口の数量出口差=sum(fresh[k]['net']-p[k]['net'] for k in joined),新たな入口の収支=sum(fresh[k]['net'] for k in added))
        saved=[d for d in result['各場寄与'][item['new_id']] if d['session']==item['session'] and d['symbol']==item['symbol']]; assert len(saved)==1; d=saved[0]['比較別'][item['comparison']]
        for f,v in values.items(): near(d['共通入口の数量/出口差' if f=='共通入口の数量出口差' else f],v)
        turned=[dict(parent=int(k),old_net=p[k]['net'],new_net=fresh[k]['net']) for k in joined if p[k]['net']>0 and fresh[k]['net']<0]
        assert sorted(turned,key=lambda v:v['parent'])==sorted(d['元勝ち親が赤字化'],key=lambda v:v['parent'])
        comparisons.append(dict(id=item['new_id'],session=item['session'],symbol=item['symbol'],比較=item['comparison'],旧ID=item['id'],**values,
            元勝ち赤字化=turned,消え親=sorted(removed),追加親=sorted(added)))
    assert len(READS)==12 and len(plan['一読packet'])==4 and len(reviewed)==5 and len(comparisons)==3
    proof=dict(全合格=True,範囲='全264小会計とは別に固定5新3旧台帳と4packetのみを実注文から検査。新金融又は全264大台帳の再検証ではない。',
        計画SHA256=digest(plan_path),結果SHA256=plan['financial_result_SHA256'],独立source_SHA256=digest(Path(__file__)),
        直接読取=dict(READS),読取新台帳=5,読取旧台帳=3,読取packet=4,分類別検査=dict(A.COUNT),
        抽出=reviewed,抽出実親5寄与=comparisons,
        留保=['数量イベントと実料曲線は共有GU全行の診断。停止後のGU部分を実政策利益へ足さない。',
              '実Q3部分返済は小表にない。Q3の影部分が見つかった場合もGU診断に限定。',
              '正BBOの理想即時約定の因果監査で、実小型板・待ち順位・通信遅延の証明ではない。',
              '損失枠内に収まった抽出例でも、枠や平均黒字補填の将来保証とは言わない。'],
        新金融=0,新engine=0,全33input再読=0,原板=0,NPZ=0,API=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,新=5,旧=3,packet=4,SHA256=digest(target)),ensure_ascii=False))


if __name__=='__main__': main()
