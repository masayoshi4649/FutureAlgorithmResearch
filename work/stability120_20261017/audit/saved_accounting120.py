"""保存注文の算術だけを再構成し、戦略・原市場を再生しない独立会計。"""

from collections import Counter
import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
CHECKS=Counter()
READS=Counter()
ORDER_COLUMNS=('uid','kind','side','decision_row','fill_row','decision_time','fill_time','price','fee','reason','rung','quantity','decision_mid','fill_last','fill_bid','fill_ask','net','trigger_price')
LOT_COLUMNS=('uid','side','rung','entry_decision_row','entry_row','entry_time','entry_price','exit_decision_row','exit_row','exit_time','exit_price','gross','fees','net','reason','mfe','mae','entry_last','exit_last')
CURVE_COLUMNS=('row','time','equity','cash','realized_net','long','short','drawdown')


def check(value: bool,label: str) -> None:
    """
    機能: 保存会計と独立算術の意味別一致を判定する。
    引数: value(bool)、label(str)は条件と根拠。
    返り値: None。誤差を実利益へ読み替えず不一致は停止する。
    """
    assert bool(value),label
    CHECKS[label]+=1


def near(actual: object,expected: object,label: str) -> None:
    """
    機能: 全在庫算術を浮動小数の丸め範囲だけ許容して比較する。
    引数: actual/expected(object)、label(str)は保存値と独立値。
    返り値: None。商品額の大きさに依存する緩い既定相対誤差は使わない。
    """
    check(np.allclose(actual,expected,rtol=1e-11,atol=1e-5,equal_nan=True),label)


def sha(payload: bytes) -> str:
    """
    機能: 一読した保存bytesと実装源の指紋を計算する。
    引数: payload(bytes)は保存内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def save(path: Path,value: dict) -> None:
    """
    機能: 独立証跡を新規に保存する。
    引数: path(Path)、value(dict)は所有先とJSON内容。
    返り値: None。既存の証跡・Falseを上書きしない。
    """
    assert not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def valid_quotes(quotes: dict,setting: dict) -> tuple[dict,int]:
    """
    機能: 保存観測の場内・時計・気配資格だけを逐次確認する。
    引数: quotes(dict[str,ndarray])、setting(dict)は保存五列と固定時刻。
    返り値: tuple[dict,int]は正常観測と棄却数。売買信号は計算しない。
    """
    rows=quotes['row'];check(np.all(np.diff(rows)>0),'保存原row厳密増加')
    check(all(len(v)==len(rows) for v in quotes.values()),'五列の観測数一致')
    times=quotes['time'];bid=quotes['bid'];ask=quotes['ask']
    basic=np.isfinite(times)&(times>=setting['session_start'])&(times<=setting['session_end'])&np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(bid<=ask)
    accepted=np.zeros(len(rows),dtype=bool);indices=np.flatnonzero(basic)
    if len(indices):
        clocks=times[indices];previous=np.r_[-math.inf,np.maximum.accumulate(clocks)[:-1]]
        accepted[indices]=clocks>=previous
    return {k:v[accepted] for k,v in quotes.items()},int(len(rows)-np.count_nonzero(accepted))


def positions(rows: np.ndarray,wanted: np.ndarray,label: str) -> np.ndarray:
    """
    機能: 保存注文の原rowを正常観測へ一意対応させる。
    引数: rows/wanted(ndarray)、label(str)は正常原rowと対象原row。
    返り値: ndarray[int]は索引。存在しない約定を補完しない。
    """
    found=np.searchsorted(rows,wanted)
    check(np.all(found<len(rows)),label+'が観測末尾以内')
    check(np.all(rows[found]==wanted),label+'が正常観測に存在')
    return found


def audit_account(quotes: dict,orders: np.ndarray,lots: np.ndarray,curve: np.ndarray,row: dict,setting: dict,spec: dict) -> dict:
    """
    機能: 保存注文と正常気配から全原行現金・両方向在庫・清算時価を独立算術で照合する。
    引数: quotes(dict)、orders/lots/curve(ndarray)は政策index除去後の保存列、row/setting/spec(dict)は小会計と固定契約。
    返り値: dictは数量・費用・差額の小診断。金融エンジンの呼出しも方向予測の再計算もしない。
    """
    check(orders.shape[1]==18 and lots.shape[1]==19 and curve.shape[1]==8,'注文玉曲線の保存列')
    q,rejected=valid_quotes(quotes,setting);rr=q['row'];tt=q['time'];bb=q['bid'];aa=q['ask'];n=len(rr)
    check(n>0,'正常観測が存在')
    fee=math.floor(setting['fee']+1e-9);mult=setting['multiplier'];cap=setting['cap']
    fill=positions(rr,orders[:,4],'約定原row');decision=positions(rr,orders[:,3],'判断原row')
    check(np.all(fill==decision+1),'必ず判断後最初の正常原rowで約定')
    check(np.all(orders[:,4]>orders[:,3]) and np.all(orders[:,6]>=orders[:,5]),'同row禁止と非逆行時計')
    check(np.all(np.diff(orders[:,4])>=0),'注文は約定原row順')
    check(np.all(orders[:,11]==1) and np.all(orders[:,8]==fee),'全注文一枚別の料金切捨て')
    check(np.all(np.isin(orders[:,1],(1,2))) and np.all(np.isin(orders[:,2],(-1,1))),'注文種別と符号')
    near(orders[:,5],tt[decision],'判断価格時計');near(orders[:,6],tt[fill],'約定価格時計')
    near(orders[:,7],np.where(orders[:,2]>0,aa[fill],bb[fill]),'買ask売bidの実観測値')
    near(orders[:,12],(bb[decision]+aa[decision])*.5,'判断当時中値')
    near(orders[:,13],q['last'][fill],'約定Last');near(orders[:,14],bb[fill],'約定bid');near(orders[:,15],aa[fill],'約定ask')
    entry={};closed=set();certificates=[]
    cash_delta=np.zeros(n);realized_delta=np.zeros(n)
    long_delta=np.zeros(n);short_delta=np.zeros(n);long_basis_delta=np.zeros(n);short_basis_delta=np.zeros(n)
    for number,o in enumerate(orders):
        uid=int(o[0]);kind=int(o[1]);side=int(o[2]);i=int(fill[number]);rung=int(o[10])
        check(uid==o[0] and 0<=rung<cap and rung==o[10],'UID整数と有効枠')
        if kind==1:
            check(uid not in entry,'実新規UID一意')
            check(o[6]<setting['entry_end'],'実新規は締切前')
            entry[uid]=(o.copy(),i);cash_delta[i]-=fee
            count,basis=(long_delta,long_basis_delta) if side==1 else (short_delta,short_basis_delta)
            count[i]+=1;basis[i]+=o[7]
            near(o[16],0.,'新規注文は決済netを持たない')
        else:
            check(uid in entry and uid not in closed,'返済UIDは実在未返済玉へ一意対応')
            en,ei=entry[uid];held_side=int(en[2]);check(side==-held_side and rung==en[10],'返済方向と同一枠')
            gross=held_side*(o[7]-en[7])*mult;net=gross-2*fee
            near(o[16],net,'返済注文netは実両価格と両道料金')
            cash_delta[i]+=gross-fee;realized_delta[i]+=net
            count,basis=(long_delta,long_basis_delta) if held_side==1 else (short_delta,short_basis_delta)
            count[i]-=1;basis[i]-=en[7]
            marks=held_side*((bb[ei:i+1] if held_side==1 else aa[ei:i+1])-en[7])*mult-2*fee
            certificates.append([uid,held_side,rung,en[3],en[4],en[6],en[7],o[3],o[4],o[6],o[7],gross,2*fee,net,o[9],np.max(marks),np.min(marks),en[13],o[13]])
            closed.add(uid)
    expected_lots=np.asarray(certificates,float).reshape(-1,19)
    near(lots,expected_lots,'玉の全十九列と清算料後MFE/MAE')
    lc=np.cumsum(long_delta);sc=np.cumsum(short_delta)
    lb=np.cumsum(long_basis_delta);sb=np.cumsum(short_basis_delta)
    cash=np.cumsum(cash_delta);realized=np.cumsum(realized_delta)
    check(np.all(lc>=0) and np.all(sc>=0) and np.max(lc)<=cap and np.max(sc)<=cap,'全原row両方向の保有上限')
    if spec['mode'] in (1,2):check(np.all(lc*sc==0),'NETとFLIPの実両建て無し')
    equity=cash+(lc*bb-lb+sb-sc*aa)*mult-(lc+sc)*fee
    high=np.maximum.accumulate(np.maximum(equity,0.));dd=high-equity
    ci=positions(rr,curve[:,0],'公開資産原row')
    near(curve[:,1:],np.column_stack((tt[ci],equity[ci],cash[ci],realized[ci],lc[ci],sc[ci],dd[ci])),'公開curveの全残玉清算時価と現金')
    expected_indices=[];i=0
    while i<n:
        expected_indices.append(i);i=int(np.searchsorted(tt,tt[i]+60,side='left'))
    expected_indices.append(n-1)
    check(np.array_equal(ci,np.asarray(expected_indices)),'価格時計六十秒と最終再掲の曲線保存')
    held=set(entry)-closed;check(len(held)==int(lc[-1]+sc[-1]),'全実新規UIDは返済又は残在庫')
    profits=float(np.sum(np.maximum(lots[:,13],0)));losses=float(np.sum(np.maximum(-lots[:,13],0)))
    first_mid=(bb[0]+aa[0])/2;step=max(setting['observed_tick'],math.floor(first_mid*spec['fraction']/setting['observed_tick']+.5)*setting['observed_tick'])
    expected=dict(net=equity[-1],cash=cash[-1],profit=profits,loss=losses,fees=len(orders)*fee,closed_lots=len(lots),wins=np.count_nonzero(lots[:,13]>0),losses=np.count_nonzero(lots[:,13]<0),unclosed=len(held),max_long=np.max(lc),max_short=np.max(sc),max_drawdown=np.max(dd),min_equity=min(0.,float(np.min(equity))),entries=len(entry),clock_rejected=rejected,step=step,held_entry_fees=len(held)*fee,last_equity=equity[-1],last_time=tt[-1],realized_net=profits-losses,forced_loss=float(np.sum(np.maximum(-lots[lots[:,14]==9,13],0))),forced_profit=float(np.sum(np.maximum(lots[lots[:,14]==9,13],0))),trail_net=float(np.sum(lots[lots[:,14]==1,13])),long_net=float(np.sum(lots[lots[:,1]==1,13])),short_net=float(np.sum(lots[lots[:,1]==-1,13])))
    for key,value in expected.items():near(row[key],value,'小会計の'+key)
    near(cash[-1],realized[-1]-len(held)*fee,'現金と確定netと残入口料の恒等式')
    if not held:near(row['net'],row['profit']-row['loss'],'全玉返済後の時価と確定PL')
    return dict(entries=len(entry),closed=len(closed),unclosed=len(held),orders=len(orders),fees=len(orders)*fee,net=float(equity[-1]),realized_net=float(realized[-1]),cash_PL_difference=float(cash[-1]-(profits-losses)))


def main() -> None:
    """
    機能: 根指定SHAの完成結果と八十小cacheを各一読保全し、保存全三千八百四十口座を独立算術で監査する。
    引数: CLI --result(Path)、--sha256(str)、--output(Path)は許可済み完成物と所有先。
    返り値: None。市場・元119入力・戦略金融再生・台帳変更はいずれも零。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--result',type=Path,required=True);parser.add_argument('--sha256',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();check(not args.output.exists(),'所有監査先未使用')
    payload=args.result.read_bytes();READS['完成結果']+=1;check(sha(payload)==args.sha256,'根指定完成SHA')
    own=args.output/'owned';own.mkdir(parents=True);(own/'完成結果.json').write_bytes(payload)
    data=json.loads(payload.decode('utf8'));del payload
    check(tuple(data['order_columns'])==ORDER_COLUMNS and tuple(data['lot_columns'])==LOT_COLUMNS and tuple(data['curve_columns'])==CURVE_COLUMNS,'公開列定数一致')
    check(len(data['specs'])==48 and len(data['cache'])==80 and len(data['runs'])==3840 and len(data['sessions'])==40,'固定四十八政策八十入力三千八百四十口座')
    check(data['original_market_reads']==0 and data['reused_input_reads']==80 and data['financial_accounts']==3840,'読取と金融口座の由来')
    start_sha={path:sha((ROOT/path).read_bytes()) for path in data['source_SHA256']}
    check(start_sha==data['source_SHA256'],'正式源開始SHA')
    # ----------------------------------------
    # catalogの契約定数だけを使用し、engineはimportも呼出しもしない。
    import importlib.util
    catalog_path=HERE.parent/'catalog120.py';spec=importlib.util.spec_from_file_location('audit_saved120_catalog',catalog_path)
    catalog=importlib.util.module_from_spec(spec);spec.loader.exec_module(catalog)
    check(catalog.specifications()==data['specs'],'固定四十八仕様')
    rows={(r['symbol'],r['session'],r['method']):r for r in data['runs']}
    check(len(rows)==3840,'全口座一意')
    reports=[];seen=set()
    for number,ref in enumerate(data['cache']):
        symbol,session=ref['symbol'],ref['session'];check((symbol,session) not in seen,'cache場商品一意');seen.add((symbol,session))
        path=(ROOT/ref['path']).resolve();check(path.is_relative_to(args.result.resolve().parent),'完成measurement内の小cacheだけ読む')
        raw=path.read_bytes();READS['小cache']+=1;check(sha(raw)==ref['sha256'],'保存cache同bytes指紋')
        dest=own/symbol/(session+'.npz');dest.parent.mkdir(parents=True,exist_ok=True);check(not dest.exists(),'cache保全先未使用');dest.write_bytes(raw)
        with np.load(BytesIO(raw),allow_pickle=False) as stored:arrays={k:stored[k].copy() for k in stored.files}
        del raw
        check(set(arrays)=={'orders','lots','curves','quotes__row','quotes__time','quotes__last','quotes__bid','quotes__ask'},'小cache列集合')
        for key,columns in (('orders',19),('lots',20),('curves',9)):
            a=arrays[key];check(a.ndim==2 and a.shape[1]==columns and np.all(a[:,0]==a[:,0].astype(int)) and np.all((a[:,0]>=0)&(a[:,0]<48)),'政策index前置と列数')
        quotes={k:arrays['quotes__'+k] for k in ('row','time','last','bid','ask')}
        setting=catalog.settings(symbol,session)
        for pi,policy in enumerate(data['specs']):
            pieces=[arrays[k][arrays[k][:,0]==pi,1:] for k in ('orders','lots','curves')]
            answer=audit_account(quotes,*pieces,rows[(symbol,session,policy['id'])],setting,policy)
            reports.append(dict(symbol=symbol,session=session,method=policy['id'],**answer))
        print(f'{number+1}/80 全四十八口座の保存会計照合',flush=True)
    end_sha={path:sha((ROOT/path).read_bytes()) for path in data['source_SHA256']}
    check(end_sha==start_sha,'正式源終端SHA不変')
    unclosed=[r for r in reports if r['unclosed']]
    proof=dict(passed=not unclosed,result_sha256=args.sha256,audit_source_sha256=sha(Path(__file__).read_bytes()),source_SHA256=start_sha,checks=dict(CHECKS),total_checks=sum(CHECKS.values()),reads=dict(READS),saved_accounts=len(reports),unclosed_accounts=unclosed,reconstructed=reports,market_reads=0,original119_cache_reads=0,financial_replay=0,registry_changes=0,留保='保存台帳算術の独立照合であり新しい有効性標本ではない。予約取消数は未発注のstateが保存されないため独立再構成せず、源人工へ委譲する。')
    save(args.output/'保存全四十八政策八十入力の注文玉時価の独立会計監査.json',proof)
    print(json.dumps(dict(passed=not unclosed,accounts=len(reports),checks=sum(CHECKS.values()),reads=dict(READS)),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
