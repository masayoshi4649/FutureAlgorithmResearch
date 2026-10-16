"""指値の成立親の入口改善と、未成立親の損益喪失を全元親で恒等分解する。"""
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import importlib.util
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROUND=HERE.parent
ROOT=ROUND.parents[2]
EPS=1e-7


def module(name,path):
    """
    機能: 保存素材の読取準備を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj;spec.loader.exec_module(obj)
    return obj


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    """
    機能: 読取ファイルの指紋を計算する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scalar(value):
    """
    機能: NumPyの単一値をJSON互換にする。
    引数: value(object)。
    返り値: int/float/bool。
    """
    if isinstance(value,np.generic):return value.item()
    raise TypeError(type(value).__name__)


def stamp(ready,row):
    """
    機能: 原本の代理時計を日本時間文字列で表す。
    引数: ready(dict)、row(int)。
    返り値: str又はNone。
    """
    return datetime.fromtimestamp(float(ready['time_s'][row]),ZoneInfo('Asia/Tokyo')).isoformat() if row>=0 else None


def groups(ledger):
    """
    機能: 決済全脚の料金前後を元GUの親IDへ合算する。
    引数: ledger(dict)。
    返り値: dict[int,dict]。
    """
    out={}
    for t in ledger['net_trades']:
        cid=int(t['組']);g=out.setdefault(cid,dict(gross=0.,fees=0.,net=0.))
        g['gross']+=float(t['利益損失前']);g['fees']+=float(t['手数料']);g['net']+=float(t['収支'])
    return out


def entries(ledger):
    """
    機能: 親ごとに一回だけの初回新規を取り出す。
    引数: ledger(dict)。
    返り値: dict[int,ndarray]。
    """
    out={}
    for o in ledger['orders']:
        if o[7]:
            cid=int(o[2]);assert cid not in out;out[cid]=o
    return out


def summarize(rows,sessions):
    """
    機能: 成立親の有利化と未成立親の旧利益損失を全親で集計する。
    引数: rows(list[dict])、sessions(list[str])。
    返り値: dict。無取引は勝ちに数えない。
    """
    filled=[r for r in rows if r['成立']];missed=[r for r in rows if not r['成立']]
    better=sum(r['入口有利化による粗利益'] for r in filled)
    saved=sum(-r['対照収支'] for r in missed if r['対照収支']<0)
    lost=sum(r['対照収支'] for r in missed if r['対照収支']>0)
    delta=sum(r['収支差'] for r in rows)
    assert abs(delta-(better+saved-lost))<1e-5
    net=np.array([r['実収支'] for r in rows]);profit=float(net[net>0].sum());loss=float(-net[net<0].sum())
    active={s:any(r['成立'] for r in rows if r['session']==s) for s in sessions}
    bysession={s:sum(r['実収支'] for r in rows if r['session']==s) for s in sessions}
    return dict(全元親数=len(rows),成立親数=len(filled),未成立親数=len(missed),
        成立親の入口改善益=better,未成立の旧損失回避=saved,未成立の旧利益喪失=lost,収支差=delta,
        料金前差=sum(r['料金前差'] for r in rows),料金差=sum(r['料金差'] for r in rows),
        成立親料金差=sum(r['料金差'] for r in filled),対照収支=sum(r['対照収支'] for r in rows),
        利益=profit,損失=loss,収支=float(net.sum()),金額利益割合=profit/(profit+loss) if profit+loss else None,
        活動場=sum(active.values()),黒字場=sum(active[s] and bysession[s]>EPS for s in sessions),
        赤字場=sum(active[s] and bysession[s]<-EPS for s in sessions),無取引場=sum(not x for x in active.values()),
        旧負けが成立後黒字=sum(r['対照収支']<0 and r['実収支']>0 for r in filled),
        旧勝ちが成立後負け=sum(r['対照収支']>0 and r['実収支']<0 for r in filled),
        成立親の旧黒字=sum(r['対照収支']>0 for r in filled),成立親の旧赤字=sum(r['対照収支']<0 for r in filled),
        二十親未満=len(filled)<20)


def cancel_records(identifier,book,ready):
    """
    機能: 指値の永久取消を、初回紙上部分・全返済・予定に分ける。
    引数: identifier(str)、book/ready(dict)。
    返り値: list[dict]。
    """
    out=[]
    for e in book.get('limit_events',[]):
        if e[1] not in (3,4):continue
        label=('紙上の最初の部分返済' if e[11]>0 else '紙上の最初の全返済') if e[1]==3 else ('既知場末' if e[17]==93 else '米国見送り')
        row=int(e[0]);source=int(e[3])
        out.append(dict(ID=identifier,session=ready['session'],symbol=ready['symbol'],組=int(e[2]),
            分類=label,行=row,代理時計=stamp(ready,row),元新規行=source,元新規代理時計=stamp(ready,source),
            指値=float(e[8]),紙上残枚数=int(e[11]),理由=int(e[17])))
    return out


def main():
    """
    機能: 根担当の全十条件完了通知後、指値八幅の全元親と価格改善恒等式を確認する。
    引数: なし。
    返り値: None。新条件の実行・代表変更・配分最適化は行わない。
    """
    fixed=read(ROUND/'事前固定.json');configs={c['id']:c for c in fixed['catalog']}
    paths={k:ROUND/'observed/results'/(k+'.json') for k in configs}
    assert len(paths)==10 and all(p.exists() for p in paths.values()),'全十条件保存完了が必要'
    results={k:read(p) for k,p in paths.items()};ledgers={}
    for k in configs:
        p=ROUND/'observed/ledgers'/(k+'.pkl');assert sha(p)==results[k]['ledger_SHA256']
        ledgers[k]=pickle.loads(p.read_bytes())
    prepare=module('wave85_prepare',ROOT/'work/wave_v85/prepare.py');inputs,_,_=prepare.load_inputs(True)
    base=ledgers['L_GU_NEXT'];limits=[c for c in configs.values() if c['execution_mode']=='LIMIT']
    out=dict(対象='八つの有利指値と二対照。全30場は既知で、元GUの紙上返済は不変。',主仮説='L_D50',
        差額式='全差額=成立親の入口価格改善益+未成立の旧負け回避−未成立の旧勝ち喪失。未成立を無視しない。',
        実装SHA256=fixed['code_SHA256'],結果SHA256={k:sha(p) for k,p in paths.items()},全親=[],条件=[],取消全件=[],包含関係=[])
    for identifier,books in ledgers.items():
        for key,book in books.items():
            for nested in ('core_ledger','virtual_ledger'):
                a=base[key]['core_ledger'];b=book[nested]
                for name in ('orders','trades','cycles','fees'):np.testing.assert_array_equal(a[name],b[name])
                assert a['curve_SHA256']==b['curve_SHA256'] and a['net_trades']==b['net_trades']
    out['全条件の紙上GU完全一致']=True
    # ----------------------------------------
    # 成立した親は返済を固定したまま入口差だけ改善する。その選ばれ方も含め全体を見る。
    for config in limits:
        identifier=config['id'];records=[];checks=[];cancels=[]
        for key,ready in sorted(inputs.items()):
            old=base[key];new=ledgers[identifier][key];universe=entries(old['core_ledger'])
            ae=entries(old);be=entries(new);ag=groups(old);bg=groups(new);value=1000. if key[1]=='TOPIX' else 10.
            assert set(be)<=set(ae)<=set(universe)
            notices={int(e[2]):e for e in new['limit_events'] if e[1]==1}
            for cid,source in universe.items():
                av=ag.get(cid,dict(gross=0.,fees=0.,net=0.));bv=bg.get(cid,dict(gross=0.,fees=0.,net=0.))
                gain=0.;delay=None;newrow=-1;oldrow=int(ae[cid][0]) if cid in ae else -1
                newprice=None;oldprice=float(ae[cid][5]) if cid in ae else None
                if cid in be:
                    a=ae[cid];b=be[cid];newrow=int(b[0]);oldrow=int(a[0]);newprice=float(b[5])
                    assert int(b[3])==int(a[3]) and int(b[4])==int(a[4])
                    assert newrow>=oldrow and newrow>int(source[0])
                    am=(old['orders'][:,2]==cid)&(old['orders'][:,7]==0)
                    bm=(new['orders'][:,2]==cid)&(new['orders'][:,7]==0)
                    cols=[0,3,4,5,6,7]
                    np.testing.assert_array_equal(old['orders'][am][:,cols],new['orders'][bm][:,cols])
                    np.testing.assert_array_equal(old['fees'][am],new['fees'][bm])
                    assert abs(av['fees']-bv['fees'])<1e-7
                    favorable=float(a[3]*(a[5]-b[5]));assert favorable>=-EPS
                    gain=float(a[4]*favorable*value)
                    assert abs((bv['gross']-av['gross'])-gain)<1e-5
                    assert abs((bv['net']-av['net'])-gain)<1e-5
                    delay=float(ready['time_s'][newrow]-ready['time_s'][int(source[0])])
                else:
                    assert not np.any(new['orders'][:,2]==cid) and cid not in bg
                records.append(dict(ID=identifier,session=key[0],symbol=key[1],組=cid,方向=int(source[3]),
                    元新規行=int(source[0]),元新規代理時計=stamp(ready,int(source[0])),
                    指値=float(notices[cid][8]),固定ATR=float(notices[cid][7]),成立=cid in be,
                    対照新規行=oldrow,実新規行=newrow,実新規代理時計=stamp(ready,newrow),
                    対照建値=oldprice,実建値=newprice,予約から代理秒数=delay,
                    対照収支=av['net'],実収支=bv['net'],料金前差=bv['gross']-av['gross'],
                    料金差=bv['fees']-av['fees'],収支差=bv['net']-av['net'],入口有利化による粗利益=gain))
            checks.append(dict(session=key[0],symbol=key[1],全元親数=len(universe),成立親数=len(be),
                成立親の全返済行数量価格料金一致=True,入口同等以上有利=True,全親粗利益差恒等式=True))
            cancels.extend(cancel_records(identifier,new,ready))
        periods={period:{s:summarize([r for r in records if r['session'] in fixed[period] and r['symbol']==s],fixed[period])
            for s in ('TOPIX','NK225')} for period in ('前16','後14','全30')}
        for period in periods:
            for s in ('TOPIX','NK225'):
                saved=results[identifier]['periods'][period][s];current=periods[period][s]
                assert abs(saved['net']-current['収支'])<1e-5
                current.update(最大下落=saved['max_drawdown'],最良1場除外=saved.get('best_session_removed'))
        sides={s:{'買い' if side>0 else '売り':summarize([r for r in records if r['symbol']==s and r['方向']==side],fixed['全30'])
            for side in (1,-1)} for s in ('TOPIX','NK225')}
        cancelcounts={s:dict(Counter(r['分類'] for r in cancels if r['symbol']==s)) for s in ('TOPIX','NK225')}
        out['条件'].append(dict(ID=identifier,幅ATR=config['offset_atr'],期間=periods,買売=sides,
            取消件数=cancelcounts,検算=checks))
        out['全親'].extend(records);out['取消全件'].extend(cancels)
    # ----------------------------------------
    # 深い指値は同じ紙上経路の部分集合。別々の独立戦略と誤認しない。
    ordered=sorted(limits,key=lambda c:c['offset_atr'])
    for shallow,deep in zip(ordered[:-1],ordered[1:]):
        for symbol in ('TOPIX','NK225'):
            a={(r['session'],r['組']) for r in out['全親'] if r['ID']==shallow['id'] and r['symbol']==symbol and r['成立']}
            b={(r['session'],r['組']) for r in out['全親'] if r['ID']==deep['id'] and r['symbol']==symbol and r['成立']}
            assert b<=a
            out['包含関係'].append(dict(浅いID=shallow['id'],深いID=deep['id'],symbol=symbol,
                浅い成立=len(a),深い成立=len(b),深い成立は浅い成立の部分集合=True))
    out['分散の注意']='八幅は同じ方向・元親・出口を共有し、成立集合は入れ子。複数幅を同時運転しても独立した八つの根拠にはならない。配分効果は別途同時保有と全実料金で再生する必要がある。'
    out['例の選び方']='主案の全親から、成立改善・未成立旧勝ち・未成立旧負けの金額上位を事後説明として抽出。売買へは戻さない。'
    out['主案の例']={}
    for s in ('TOPIX','NK225'):
        rows=[r for r in out['全親'] if r['ID']=='L_D50' and r['symbol']==s]
        out['主案の例'][s]=dict(成立による入口改善=sorted([r for r in rows if r['成立']],key=lambda r:-r['入口有利化による粗利益'])[:3],
            未成立で失った旧勝ち=sorted([r for r in rows if not r['成立'] and r['対照収支']>0],key=lambda r:-r['対照収支'])[:3],
            未成立で避けた旧負け=sorted([r for r in rows if not r['成立'] and r['対照収支']<0],key=lambda r:r['対照収支'])[:3])
    out['全対照期間']={k:v['periods'] for k,v in results.items() if configs[k]['execution_mode']!='LIMIT'}
    destination=HERE/'有利指値の入口改善と未成立親の全差分.json'
    destination.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False,default=scalar)+'\n',encoding='utf-8')
    print('八幅の成立価格改善・未成立利益損失・取消・全親恒等式を保存',flush=True)


if __name__=='__main__':main()
