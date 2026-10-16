"""実両建て・差引・元玉終了抑止の差を、同じ親組と全原本行で分解する。"""
from pathlib import Path
import importlib.util
import hashlib
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROUND=HERE.parent


def module(name,path):
    """
    機能: 読取専用の入力準備を読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def read(path):
    """
    機能: 保存済み日本語JSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 読取対象の内容指紋を計算する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scalar(value):
    """
    機能: NumPyの集計スカラーをJSON互換の単一値へ変換する。
    引数: value(object)。
    返り値: int/float/bool。対応外の型ではTypeErrorを発生する。
    """
    if isinstance(value,np.generic):return value.item()
    raise TypeError(type(value).__name__)


def groups(ledger):
    """
    機能: 実玉が一時ゼロでも仮想ID単位の全新規・全返済・全料金を合算する。
    引数: ledger(dict)。
    返り値: dict[int,dict]。ゼロ取引の仮想組は後の対応時にゼロとして扱う。
    """
    result={}
    for trade in ledger['net_trades']:
        cid=int(trade['組'])
        value=result.setdefault(cid,dict(gross=0.,fees=0.,net=0.,trades=0,lots=0))
        value['gross']+=trade['利益損失前'];value['fees']+=trade['手数料'];value['net']+=trade['収支']
        value['trades']+=1;value['lots']+=trade['枚数']
    return result


def path(ledger,prices):
    """
    機能: 実注文だけから全行の現金・差引枚数・親ID・時価を復元する。
    引数: ledger(dict)、prices(ndarray)。
    返り値: tuple[ndarray,ndarray,ndarray,ndarray]。価格欠測は過去値だけで評価を保留する。
    """
    n=len(prices);orders=ledger['orders'];cash=np.zeros(n);quantity=np.zeros(n)
    np.add.at(cash,orders[:,0].astype(int),-orders[:,3]*orders[:,4]*orders[:,5])
    np.add.at(quantity,orders[:,0].astype(int),orders[:,3]*orders[:,4])
    cash=np.cumsum(cash);quantity=np.cumsum(quantity)
    index=np.maximum.accumulate(np.where(np.isfinite(prices)&(prices>0),np.arange(n),0))
    marked=prices[index].copy();marked[~np.isfinite(marked)]=0.
    cid=np.full(n,-1,np.int64)
    if len(orders):
        last=np.searchsorted(orders[:,0],np.arange(n),side='right')-1
        valid=last>=0;cid[valid]=orders[last[valid],2].astype(np.int64)
    return cash,quantity,cid,cash+quantity*marked


def exposure(ledger,prices,pointvalue):
    """
    機能: 各観測間に実際に持った枚数×価格変化を親組ごとに積算する。
    引数: ledger(dict)、prices(ndarray)、pointvalue(float)。
    返り値: dict[int,float]。当行内売買の現金移動ではなく保有中の価格寄与。
    """
    _,quantity,cid,_=path(ledger,prices)
    index=np.maximum.accumulate(np.where(np.isfinite(prices)&(prices>0),np.arange(len(prices)),0))
    marked=prices[index].copy();marked[~np.isfinite(marked)]=0.
    value=quantity[:-1]*np.diff(marked)*pointvalue
    active=cid[:-1]>=0
    if not np.any(active):return {}
    totals=np.bincount(cid[:-1][active],weights=value[active])
    return {i:float(v) for i,v in enumerate(totals) if v!=0}


def total(records):
    """
    機能: 同じ商品だけの親組差額を全件集計する。
    引数: records(list[dict])。
    返り値: dict。
    """
    return dict(比較親組数=len(records),改善組=sum(r['収支差']>1e-7 for r in records),
        悪化組=sum(r['収支差']<-1e-7 for r in records),同額組=sum(abs(r['収支差'])<=1e-7 for r in records),
        料金前差=sum(r['料金前差'] for r in records),料金差=sum(r['料金差'] for r in records),
        収支差=sum(r['収支差'] for r in records),
        元黒字が赤字=sum(r['元収支']>0 and r['変更収支']<0 for r in records),
        元赤字が黒字=sum(r['元収支']<0 and r['変更収支']>0 for r in records),
        元黒字組の収支差=sum(r['収支差'] for r in records if r['元収支']>0),
        元赤字組の収支差=sum(r['収支差'] for r in records if r['元収支']<0))


def main():
    """
    機能: 根担当の全十三条件完了後、実料金と遅延後露出による損益差を検算する。
    引数: なし。
    返り値: None。新しい閾値・代表・追加条件の選定は行わない。
    """
    fixed=read(ROUND/'事前固定.json')
    resultpaths={c['id']:ROUND/'observed/results'/(c['id']+'.json') for c in fixed['catalog']}
    assert len(resultpaths)==13 and all(p.exists() for p in resultpaths.values()),'全十三条件の保存完了が必要'
    results={k:read(v) for k,v in resultpaths.items()}
    ledgers={k:pickle.loads((ROUND/'observed/ledgers'/(k+'.pkl')).read_bytes()) for k in resultpaths}
    prepare=module('wave85_prepare',ROUND.parents[1]/'wave_v85/prepare.py')
    inputs,_,_=prepare.load_inputs(True)
    out=dict(対象='仮想判断固定・観測現在値で次の有効観測に実行する十三条件。全30場既知。',
        区別='G→Nは全玉時価と差引枚数を同一に保つ料金差。N→Fは実行遅延後の観測区間j〜kの価格露出と料金の変更。途中フラットを別勝負に数え直さない。',
        主仮説='C_H05_S25_F',結果SHA256={str(p):sha(p) for p in resultpaths.values()},比較=[],全親組=[])
    for prefix in ('GU','C_H05_S25','C_H05_S50','I_P00_R50_C1'):
        for before,after in (('G','N'),('N','F')):
            parentrows=[];checks=[];sessions=[]
            aid=prefix+'_'+before;bid=prefix+'_'+after
            for key,ready in sorted(inputs.items()):
                a=ledgers[aid][key];b=ledgers[bid][key];scale=1000. if key[1]=='TOPIX' else 10.
                ac,aq,_,ae=path(a,ready['last']);bc,bq,_,be=path(b,ready['last'])
                if before=='G':
                    np.testing.assert_allclose(ac,bc,atol=1e-8,rtol=0)
                    np.testing.assert_array_equal(aq,bq)
                    np.testing.assert_allclose(ae,be,atol=1e-8,rtol=0)
                ap=exposure(a,ready['last'],scale);bp=exposure(b,ready['last'],scale)
                ag=groups(a);bg=groups(b)
                for cid in sorted(set(ag)|set(bg)):
                    zero=dict(gross=0.,fees=0.,net=0.,trades=0,lots=0)
                    av=ag.get(cid,zero);bv=bg.get(cid,zero)
                    delta=bv['net']-av['net'];gross=bv['gross']-av['gross'];fee=bv['fees']-av['fees']
                    assert abs(delta-(gross-fee))<1e-5
                    assert abs((bp.get(cid,0)-ap.get(cid,0))-gross)<1e-5
                    if before=='G':assert abs(gross)<1e-5
                    parentrows.append(dict(元ID=aid,変更ID=bid,session=key[0],symbol=key[1],組=cid,
                        元収支=av['net'],変更収支=bv['net'],料金前差=gross,料金差=fee,収支差=delta,
                        実保有価格寄与差=bp.get(cid,0)-ap.get(cid,0)))
                fees_a=float(np.sum(a['fees']));fees_b=float(np.sum(b['fees']))
                gross_a=float(a['trades'][:,10].sum()*scale);gross_b=float(b['trades'][:,10].sum()*scale)
                sessions.append(dict(session=key[0],symbol=key[1],元料金前=gross_a,変更料金前=gross_b,
                    元料金=fees_a,変更料金=fees_b,料金前差=gross_b-gross_a,料金差=fees_b-fees_a,
                    収支差=gross_b-gross_a-fees_b+fees_a,
                    元実注文=len(a['orders']),変更実注文=len(b['orders']),
                    差引不一致の観測数=int(np.sum(aq!=bq))))
                checks.append(dict(session=key[0],symbol=key[1],全玉時価と差引一致=True if before=='G' else None,
                    同親組の実保有価格寄与と料金差の恒等式=True))
            periods={period:{symbol:total([r for r in parentrows if r['symbol']==symbol and r['session'] in fixed[period]])
                for symbol in ('TOPIX','NK225')} for period in ('前16','後14','全30')}
            out['比較'].append(dict(元ID=aid,変更ID=bid,期間=periods,全場=sessions,検算=checks))
            out['全親組'].extend(parentrows)
    # ----------------------------------------
    # 固定した主案も全条件も同じ期間欄で掲載し、結果を見た選び直しを行わない。
    fields=('net','gross','fees','cycle_profit','cycle_loss','cycle_profit_share','positive_sessions',
        'negative_sessions','no_trade_sessions','max_drawdown','best_session_removed','worst_session','cycles','new_lots')
    out['全条件期間']={identifier:{period:{symbol:{field:result['periods'][period][symbol].get(field) for field in fields}
        for symbol in ('TOPIX','NK225')} for period in ('前16','後14','全30')} for identifier,result in results.items()}
    # ----------------------------------------
    # 注文経路と親組を変えず手数料だけゼロにした感度。新たな売買再生や無料時の再判定ではない。
    out['同じ実経路の手数料ゼロ感度']={}
    for identifier,book in ledgers.items():
        values=[]
        for key,ledger in book.items():
            for cid,group in groups(ledger).items():
                values.append(dict(session=key[0],symbol=key[1],cid=cid,gross=group['gross']))
        periods={}
        for period in ('前16','後14','全30'):
            periods[period]={}
            for symbol in ('TOPIX','NK225'):
                profits=np.array([v['gross'] for v in values if v['symbol']==symbol and v['session'] in fixed[period]])
                gain=float(profits[profits>0].sum());loss=float(-profits[profits<0].sum())
                share=gain/(gain+loss) if gain+loss else None
                periods[period][symbol]=dict(料金ゼロ親組利益=gain,料金ゼロ親組損失=loss,
                    料金ゼロ収支=float(profits.sum()),料金ゼロ金額利益割合=share,
                    金額利益8割以上=bool(share is not None and share>=.8),
                    活動親組数=len(profits),黒字親組=int(np.sum(profits>0)),赤字親組=int(np.sum(profits<0)),ゼロ親組=int(np.sum(profits==0)))
        out['同じ実経路の手数料ゼロ感度'][identifier]=periods
    out['無料感度の範囲']='同じ実注文時刻・価格・数量・仮想親組のまま手数料を除くだけ。この固定実経路で料金削減だけを行う場合の金額利益割合の上限。無料条件で仮想方向や次の入口を再判定した成績ではない。'
    for mode in ('N','F'):
        for key in inputs:
            a=ledgers['GU_G'][key];b=ledgers['GU_'+mode][key]
            for name in ('orders','cycles','fees'):np.testing.assert_array_equal(a[name],b[name])
            columns=[i for i in range(11) if i!=8]
            np.testing.assert_array_equal(a['trades'][:,columns],b['trades'][:,columns])
            assert a['curve_SHA256']==b['curve_SHA256']
    out['元GUの三実行完全一致']=True
    out['元GU一致の定義']='注文・脚の全経済列・新規UID・親組・料金・料金後全行時価は同一。脚の役割列だけG=0コア、N/F=2差引というメタ情報の差として除外。'
    original=pickle.loads((ROUND.parents[1]/'wave_v85/observed/ledgers/E01_G_U.pkl').read_bytes())
    for key in inputs:
        a=ledgers['GU_IDEAL'][key];b=original[key]
        for name in ('orders','trades','cycles','fees'):np.testing.assert_array_equal(a[name],b[name])
        assert a['curve_SHA256']==b['curve_SHA256'] and a['net_trades']==b['net_trades']
    out['追加観測待ちなしGUの旧全会計完全一致']=True
    destination=HERE/'実両建て差引終了抑止の料金と価格露出の全分解.json'
    destination.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False,default=scalar)+'\n',encoding='utf-8')
    print('八つの対応比較・全親組・全原本行の会計恒等式を保存',flush=True)


if __name__=='__main__':main()
