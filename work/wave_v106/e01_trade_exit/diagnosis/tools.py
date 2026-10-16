"""保存金融の金額・原行・親を、再生せず診断する小部品。"""

from datetime import datetime,timezone,timedelta
from decimal import Decimal,ROUND_FLOOR
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SOURCE=HERE.parent
VALUE={'TOPIX':1000.,'NK225':10.}
FEE={'TOPIX':41.8,'NK225':11.}


def read(path: Path) -> tuple[object,str]:
    """
    機能: 保存結果を一回bytes読取し、同bytesの指紋と内容を返す。
    引数: path(Path)はwork内の保存資料。
    返り値: tuple[object,str]はJSON又はpickleとSHA256。実行・APIへ接続しない。
    """
    assert path.resolve().is_relative_to(ROOT/'work')
    saved=path.read_bytes();sha=hashlib.sha256(saved).hexdigest()
    return (json.loads(saved.decode('utf-8-sig')) if path.suffix=='.json'
            else pickle.loads(gzip.decompress(saved) if path.suffix=='.gz' else saved)),sha


def write(name: str, value: dict) -> str:
    """
    機能: 未保存の診断証跡を所有領域へ保存する。
    引数: name(str)、value(dict)は新資料名と内容。
    返り値: strは保存SHA256。元金融結果・登録sourceは変更しない。
    """
    path=HERE/name;assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 残UID返済料を当時注文単位で求める。
    引数: quantity(int)、symbol(str)は残玉数と商品。
    返り値: intは片道floor料金。別UIDを合算しない。
    """
    return int((Decimal(int(quantity))*Decimal(str(FEE[symbol]))).to_integral_value(rounding=ROUND_FLOOR))


def clock(account: dict, row: int) -> dict:
    """
    機能: 保存normal行の価格時計を日本時刻と原seqへ結ぶ。
    引数: account(dict)、row(int)は保存気配口座とnormal行。
    返り値: dictは原行系譜。価格時計を実受信時計とは呼ばない。
    """
    q=account['quotes'];t=float(q['time_s'][row])
    return dict(normal_row=int(row),raw_seq=int(q['seq'][row]),price_time_s=t,
                JST=datetime.fromtimestamp(t,timezone(timedelta(hours=9))).isoformat())


def parents(ledger: dict) -> dict:
    """
    機能: 不変紙上親cidをキーに保存された完結実親を整理する。
    引数: ledger(dict)は保存台帳。
    返り値: dict[int,dict]は実親。影の未約定親を勝敗へ数えない。
    """
    result={int(p['親']):p for p in ledger['parent']};assert len(result)==len(ledger['parent'])
    assert np.isclose(sum(p['収支'] for p in result.values()),ledger['summary']['収支'],atol=1e-5,rtol=0.)
    return result


def contribution(before: dict, after: dict) -> dict:
    """
    機能: 紙上親cidで実入口の変化と共通親の出口差を独立に足し直す。
    引数: before/after(dict)は同枚数同出口の保存台帳。
    返り値: dictは5寄与と各親id集合。未約定親を損失回避へ数えない。
    """
    a,b=parents(before),parents(after);removed=a.keys()-b.keys();added=b.keys()-a.keys();common=a.keys()&b.keys()
    values=dict(収支変化=after['summary']['収支']-before['summary']['収支'],
        避けた基準損失=sum(-a[k]['収支'] for k in removed if a[k]['収支']<0),
        失った基準利益=sum(a[k]['収支'] for k in removed if a[k]['収支']>0),
        共通入口の出口変化=sum(b[k]['収支']-a[k]['収支'] for k in common),
        新たな入口の収支=sum(b[k]['収支'] for k in added))
    assert np.isclose(values['収支変化'],values['避けた基準損失']-values['失った基準利益']+
                      values['共通入口の出口変化']+values['新たな入口の収支'],atol=1e-5,rtol=0.)
    return dict(**values,消えた親=sorted(removed),新しい親=sorted(added),共通親=sorted(common))


def parent_path(ledger: dict, account: dict, cid: int) -> dict:
    """
    機能: 実注文・部分返済・残UID料から親の料金後清算時価を事後に測る。
    引数: ledger/account(dict)、cid(int)は保存実親。
    返り値: dictはMFE/MAE・利益返しと原行。別の出口の金融は計算しない。
    """
    q=account['quotes'];symbol=account['symbol'];orders=ledger['orders'];ids=ledger['order_uids']
    chosen=np.flatnonzero(orders[:,2]==cid);assert len(chosen)
    first,last=int(orders[chosen[0],0]),int(orders[chosen[-1],0]);n=last-first+1
    cash_delta=np.zeros(n);charge=np.zeros(n);quantity_delta=np.zeros(n);reserve=np.zeros(n)
    targets=ledger.get('exit_target_uids',np.full(len(orders),-1,np.int64));state={};cursor=0;previous=0
    for oi in chosen:
        o=orders[oi];row,side,quantity,new=map(int,(o[0],o[3],o[4],o[7]));i=row-first
        reserve[previous:i]=sum(fee(v['remaining'],symbol) for v in state.values() if v['remaining'])
        cash_delta[i]-=side*quantity*o[5];charge[i]+=fee(quantity,symbol);quantity_delta[i]+=side*quantity
        if new:state[int(ids[oi])]=dict(remaining=quantity,side=side)
        else:
            left=quantity;target=int(targets[oi])
            for uid,v in state.items():
                if not v['remaining'] or v['side']!=-side or (target>=0 and uid!=target):continue
                take=min(left,v['remaining']);left-=take;v['remaining']-=take
                if not left:break
            assert left==0
        previous=i
    reserve[previous:]=sum(fee(v['remaining'],symbol) for v in state.values() if v['remaining'])
    held=np.cumsum(quantity_delta);valid=q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['ask']>q['bid'])
    prior=np.maximum.accumulate(np.where(valid,np.arange(len(valid)),-1));assert np.all(prior[first:last+1]>=0)
    b=q['bid'][prior[first:last+1]];a=q['ask'][prior[first:last+1]]
    path=(np.cumsum(cash_delta)+np.maximum(held,0)*b+np.minimum(held,0)*a)*VALUE[symbol]-np.cumsum(charge)-reserve
    assert np.isclose(path[-1],parents(ledger)[cid]['収支'],atol=1e-5,rtol=0.) and held[-1]==0
    best,worst=int(np.argmax(path)),int(np.argmin(path))
    return dict(事後の最大清算利益=float(path[best]),事後の最大清算損失=float(path[worst]),
                最大利益時刻=clock(account,first+best),最大損失時刻=clock(account,first+worst),
                最大利益から返した金額=float(path[best]-path[-1]),実現可能な別出口利益ではない=True)
