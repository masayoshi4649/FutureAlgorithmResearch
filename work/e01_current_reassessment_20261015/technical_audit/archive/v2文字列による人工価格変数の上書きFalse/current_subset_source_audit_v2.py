"""確定足・当時票差・厳密結合の八源subsetだけを独立合成で確認する。"""

import ast
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import traceback

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENGINE = ROOT/'work/e01_current_reassessment_20261015/engine'
NAMES = ('bars.py','flows.py','input_contract.py','order_kernel.py','daily.py','price_features.py','catalog.py','common.py')
OUTPUT = HERE/'確定足と当時票差及び厳密結合八源subsetの独立純人工_v2.json'
COUNTS = Counter()


def check(ok: bool, label: str) -> None:
    """
    機能: subsetの独立合成期待を分類付きで照合する。
    引数: ok(bool)、label(str) は条件と分類。
    返り値: None。不一致は停止する。
    """
    assert bool(ok),label
    COUNTS[label]+=1


def same(left: object,right: object,label: str) -> None:
    """
    機能: NaNの位置を保ち合成配列を比較する。
    引数: left/right(object)、label(str) は値と分類。
    返り値: None。未知を0へ補完しない。
    """
    np.testing.assert_array_equal(left,right,err_msg=label)
    COUNTS[label]+=1


def load(name: str,path: Path) -> object:
    """
    機能: 私有複製の純sourceだけを読み込む。
    引数: name(str)、path(Path) は名前と位置。
    返り値: module は部品。金融・reader・JITは実行しない。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def bar_oracle(account: dict,normal: np.ndarray) -> dict:
    """
    機能: 各当行接頭から直前bucketだけを直接抽出し確定高安を独立に計算する。
    引数: account(dict)、normal(ndarray[bool]) は合成価格時計と正常資格。
    返り値: dict は高安・bucket・認定row。未来足や前々足を繰り越さない。
    """
    r=account['record'];n=len(r['price'])
    answer=dict(high=np.full(n,np.nan),low=np.full(n,np.nan),bucket_id=np.full(n,-1,np.int64),confirmed_row=np.full(n,-1,np.int64))
    for row,t in enumerate(r['time_s']):
        if not math.isfinite(t) or not r['start']<=t<r['limit']:
            continue
        current=math.floor((t-r['start'])/300.)
        same_bucket=[];prior=[]
        for j in range(row+1):
            clock=float(r['time_s'][j])
            if not math.isfinite(clock) or not r['start']<=clock<r['limit']:
                continue
            bucket=math.floor((clock-r['start'])/300.)
            if bucket==current:
                same_bucket.append(j)
            if bucket==current-1 and normal[j] and math.isfinite(float(r['price'][j])) and r['price'][j]>0:
                prior.append(float(r['price'][j]))
        answer['bucket_id'][row]=current-1
        answer['confirmed_row'][row]=same_bucket[0]
        if prior:
            answer['high'][row]=max(prior);answer['low'][row]=min(prior)
    return answer


def verify_bars(bars: object) -> None:
    """
    機能: session基準・同clock・空bucket・境界認定行・未来suffixを反例で確認する。
    引数: bars(module) は完成subsetの私有部品。
    返り値: None。実分足・原板を読まない。
    """
    clocks=np.asarray([-1,0,100,299.999,300,300,301,599,600,601,899,1200,1201,1500,1800,1900],float)
    values=np.asarray([5000,100,105,102,1000,106,99,np.nan,107,108,0,110,109,112,115,114],float)
    for start in (0.,28761.25):
        account=dict(record=dict(time_s=clocks+start,price=values.copy(),start=start,limit=start+1800))
        for normal in (np.ones(len(clocks),bool),np.zeros(len(clocks),bool),np.arange(len(clocks))%3!=1):
            expected=bar_oracle(account,normal);full=bars.closed(account,normal)
            for key in expected:
                same(full[key],expected[key],'直前確定bucketの独立直接抽出')
            check(np.isnan(full['high'][11]) and np.isnan(full['low'][12]),'欠落した直前bucketのLを旧足で繰越しない')
            check(full['confirmed_row'][4]==4,'新bucket認定行を過去へ巻戻さない')
            for length in (1,4,5,6,9,12,14,16):
                small=dict(record={k:v[:length].copy() if isinstance(v,np.ndarray) else v for k,v in account['record'].items()})
                prefix=bars.closed(small,normal[:length])
                for key,values in full.items():
                    if isinstance(values,np.ndarray):
                        same(prefix[key],values[:length],'確定高安の独立接頭不変')
            changed=deepcopy(account);changed['record']['price'][5:]+=90000
            altered=bars.closed(changed,normal)
            same(full['high'][:5],altered['high'][:5],'同clock後半と未来高値を確定済みLへ混ぜない')
            same(full['low'][:5],altered['low'][:5],'同clock後半と未来安値を確定済みLへ混ぜない')
    normal=np.ones(len(clocks),bool)
    account=dict(record=dict(time_s=clocks,price=values.copy(),start=0.,limit=1800.))
    base=bars.closed(account,normal);mirror=deepcopy(account)
    mirror['record']['price']=6000-account['record']['price']
    normal &= np.isfinite(values)&(values>0)
    base=bars.closed(account,normal);reverse=bars.closed(mirror,normal)
    same(reverse['high'],6000-base['low'],'Last高安の買売鏡像')
    same(reverse['low'],6000-base['high'],'Last高安の買売鏡像')


def verify_flows(flows: object) -> None:
    """
    機能: 方向別の範囲和差・未知・釣合いだけの改善・強支持を独立に照合する。
    引数: flows(module) は完成subsetの私有部品。
    返り値: None。反対更新proxyを実補充や数量へ変換しない。
    """
    n=18;r=3*np.arange(n,dtype=np.int64)+2
    first=np.maximum(0,r-35);known=np.ones(n,bool);known[7]=False
    up_tape=np.asarray([(j%5 in (1,2)) for j in range(3*n)],np.int64)
    down_tape=np.asarray([(j%7 in (3,4)) and not up_tape[j] for j in range(3*n)],np.int64)
    up=np.asarray([up_tape[s:e+1].sum() for s,e in zip(first,r)],np.int32)
    down=np.asarray([down_tape[s:e+1].sum() for s,e in zip(first,r)],np.int32)
    total=up.astype(np.int64)+down
    balance=np.where(known,(up-down)/total,np.nan)
    v=dict(known=known,up_votes=up,down_votes=down,balance=balance,first_vote_raw_row=first,candidate_raw_row=r,
        candidate_raw_seq=r+1000,candidate_price_time_s=np.arange(n,dtype=float)*5)
    p=dict(own=dict(known=np.ones(n,bool),count=np.asarray([1,2,4]*6),balance=np.asarray([1.,.25,.75]*6)),
        peer_known=np.arange(n)%4!=0,peer_count=np.asarray([2,4,1]*6),peer_balance=np.asarray([1.,.75,-1.]*6))
    for symbol in ('TOPIX','NK225'):
        result=flows.measure(v,p,symbol)
        for i in range(n):
            interval=i>0 and known[i] and known[i-1] and r[i]>r[i-1] and v['candidate_raw_seq'][i]>v['candidate_raw_seq'][i-1] and v['candidate_price_time_s'][i]>=v['candidate_price_time_s'][i-1] and first[i]>=first[i-1]
            check(bool(result['interval_known'][i])==interval,'隣接normalの既知連続原行clock窓始資格')
            for key,tape,newkey in (('up_votes',up_tape,'new_up_lower'),('down_votes',down_tape,'new_down_lower')):
                difference=int(v[key][i]-v[key][i-1]) if interval else 0
                check(result[newkey][i]==max(0,difference),'全normal方向別新更新下限')
                if interval:
                    new_retained=sum(tape[j] for j in set(range(first[i],r[i]+1))-set(range(first[i-1],r[i-1]+1)))
                    expired=sum(tape[j] for j in set(range(first[i-1],r[i-1]+1))-set(range(first[i],r[i]+1)))
                    check(difference==new_retained-expired,'独立集合差による失効と新票の分離')
            for col,side in enumerate((1,-1)):
                vol=bool(known[i] and total[i]>=2 and math.isfinite(balance[i]) and side*balance[i]>=(.5 if symbol=='TOPIX' else .25))
                price=bool(p['own']['known'][i] and p['peer_known'][i] and p['own']['count'][i]>=2 and p['peer_count'][i]>=2 and side*p['own']['balance'][i]>=.25 and side*p['peer_balance'][i]>=.25)
                strong=bool(price and side*p['own']['balance'][i]>=.75 and side*p['peer_balance'][i]>=.75)
                check(result['volume_gate'][i,col]==vol,'unsigned出来高を買売へ一回だけ向ける')
                check(result['price_gate'][i,col]==price and result['strong'][i,col]==strong,'価格min2入口と強支持の独立真偽')
        for length in (1,7,8,9,14,18):
            a={k:x[:length].copy() for k,x in v.items()}
            b={k:{name:x[:length].copy() for name,x in val.items()} if isinstance(val,dict) else val[:length].copy() for k,val in p.items()}
            prefix=flows.measure(a,b,symbol)
            for key,values in prefix.items():
                if isinstance(values,np.ndarray):
                    same(values,result[key][:length],'新票と価格資格の独立接頭')
    bad=deepcopy(v);bad['up_votes'][3]=bad['up_votes'][2]-1
    try:flows.measure(bad,p,'TOPIX')
    except AssertionError:COUNTS['同firstでcountが減る不整合拒否']+=1
    else:raise AssertionError('同first負差を許可')
    empty=deepcopy(v);empty['up_votes'][:]=0;empty['down_votes'][:]=0;empty['balance'][:]=np.nan;empty['first_vote_raw_row'][:]=-1
    value=flows.measure(empty,p,'TOPIX')
    check(not value['volume_gate'].any() and not value['new_up_lower'].any() and not value['new_down_lower'].any(),'既知空範囲sentinelは正票に補完しない')


def main() -> None:
    """
    機能: 完成八源だけを署名し三純部品を確認する。
    引数: なし。
    返り値: None。未完成signal/native/正式specを合格に含めない。
    """
    assert not OUTPUT.exists()
    snapshot=HERE/'八源subsetの私有複製_v2';snapshot.mkdir(exist_ok=False)
    signatures={}
    for name in NAMES:
        saved=(ENGINE/name).read_bytes();signatures[name]=hashlib.sha256(saved).hexdigest()
        ast.parse(saved.decode('utf-8-sig'));(snapshot/name).write_bytes(saved)
    bars=load('independent_current_bars',snapshot/'bars.py')
    flows=load('independent_current_flows',snapshot/'flows.py')
    contract=load('independent_current_join',snapshot/'input_contract.py')
    old_path=ROOT/'work/e01_opportunity_trace_20261015/technical_audit/opportunity_source_audit.py'
    fixture_source=load('independent_current_fixture',old_path)
    old_tree=ast.parse((ROOT/'work/e01_opportunity_trace_20261015/prepare_v2/analysis.py').read_text(encoding='utf-8'))
    new_tree=ast.parse((snapshot/'input_contract.py').read_text(encoding='utf-8'))
    for name in ('equal','validate_public','strict_join'):
        left=next(x for x in old_tree.body if isinstance(x,ast.FunctionDef) and x.name==name)
        right=next(x for x in new_tree.body if isinstance(x,ast.FunctionDef) and x.name==name)
        check(ast.dump(left,include_attributes=False)==ast.dump(right,include_attributes=False),'既監査結合三機能はAST同値')
    for zero in (False,True):
        gate,packet,_=fixture_source.fixture(zero)
        check(contract.strict_join(gate,packet)['公開窓scalar全normal一致']==24,'非恒等map三窓のSELL未知零票厳密join')
        for group,key in (('record','seq'),('record','time_s'),('quotes','bid')):
            broken=deepcopy(packet);broken['accounts']['TOPIX'][group][key][45]+=1
            try:contract.strict_join(gate,broken)
            except AssertionError:COUNTS['原seqclock両BBOの誤joinを拒否']+=1
            else:raise AssertionError('誤joinを許可')
    verify_bars(bars);verify_flows(flows)
    check(signatures['price_features.py']==hashlib.sha256((ROOT/'work/e01_fak_evidence_20261014/engine/price_votes.py').read_bytes()).hexdigest(),'peerstrict過去の旧同bytes部品')
    for name,digest in signatures.items():
        check(hashlib.sha256((ENGINE/name).read_bytes()).hexdigest()==digest,'完成八源subset開始終端不変')
    value=dict(全合格=True,状態='完成八源subsetだけのSOURCE_ONLY。signal/native/登録/金融は未完成。',
        source_SHA256={('work/e01_current_reassessment_20261015/engine/'+k):v for k,v in signatures.items()},
        監査source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),検査数=sum(COUNTS.values()),分類=dict(COUNTS),
        確認=['厳密joinの既監査AST同値と非恒等map/符号/未知','当場基準の直前確定5分足、空足非繰越、認定行、接頭',
            '方向別新票差、失効、unknown跨ぎ、samefirstexact、現在二価格票強支持'],
        未測=['新入口signal状態とL消費再武装','受理FAKと未知の先後','支持線の確定更新','独立実親会計','最終source集合/8spec/登録','新金融の有効性'],
        原cache=0,NPZ=0,金融本文=0,新金融=0,実台帳=0,原board=0,API=0,共有編集=0,初版False保全='archive/確定足definitionを配列と誤読した初版False',
        初版訂正理由='barsのdefinition説明文字列まで接頭配列として切ったchecker誤り。ndarrayだけへ訂正し、owner部品は変えない。')
    OUTPUT.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('八源subset独立純人工 '+str(value['検査数'])+'合格。SHA '+hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        path=HERE/'八源subset独立純人工_v2False.json';assert not path.exists()
        path.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),分類=dict(COUNTS),原cache=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
