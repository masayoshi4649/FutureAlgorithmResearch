"""相手GUによる入口見送りと同入口の途中縮小を、全元親組へ対応して分解する。"""
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
JST=ZoneInfo('Asia/Tokyo')


def module(name,path):
    """
    機能: 過去の読取入力又は会計部品を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj;spec.loader.exec_module(obj)
    return obj


def read(path):
    """
    機能: 保存済みJSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    """
    機能: 保存結果又は実装の内容指紋を計算する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scalar(value):
    """
    機能: NumPy単一値をJSON互換値へ変換する。
    引数: value(object)。
    返り値: int/float/bool。
    """
    if isinstance(value,np.generic):return value.item()
    raise TypeError(type(value).__name__)


def stamp(ready,row):
    """
    機能: 原本の代理時計を日本時刻の文字列へ変換する。
    引数: ready(dict)、row(int)。
    返り値: str又はNone。
    """
    return datetime.fromtimestamp(float(ready['time_s'][row]),JST).isoformat() if row>=0 else None


def groups(ledger):
    """
    機能: 全実脚・実料金を仮想親ID単位で合算する。
    引数: ledger(dict)。
    返り値: dict[int,dict]。途中flatを別の勝負に分割しない。
    """
    out={}
    for t in ledger['net_trades']:
        cid=int(t['組']);g=out.setdefault(cid,dict(gross=0.,fees=0.,net=0.,legs=0,lots=0))
        g['gross']+=float(t['利益損失前']);g['fees']+=float(t['手数料']);g['net']+=float(t['収支'])
        g['legs']+=1;g['lots']+=int(t['枚数'])
    return out


def source_entries(ledger):
    """
    機能: 全元GU親の初回注文だけを取り出す。
    引数: ledger(dict)。
    返り値: dict[int,ndarray]。
    """
    result={}
    for o in ledger['orders']:
        if o[7]:
            cid=int(o[2]);assert cid not in result
            result[cid]=o
    return result


def group_orders(ledger,cid):
    """
    機能: 指定仮想親IDの全実注文を抽出する。
    引数: ledger(dict)、cid(int)。
    返り値: ndarray。
    """
    return ledger['orders'][ledger['orders'][:,2]==cid]


def at_parent(ledger,cid,row,price,value,fee):
    """
    機能: 当行までの実親現金と残玉の料金込み清算評価を復元する。
    引数: ledger(dict)、cid/row(int)、price/value/fee(float)。
    返り値: dict。未来の注文・最終組成績は使わない。
    """
    mask=(ledger['orders'][:,2]==cid)&(ledger['orders'][:,0]<=row)
    orders=ledger['orders'][mask];quantity=float(np.sum(orders[:,3]*orders[:,4]))
    cash=float(np.sum(-orders[:,3]*orders[:,4]*orders[:,5])*value)
    paid=float(np.sum(ledger['fees'][mask]));closing=float(np.floor(abs(quantity)*fee+1e-8))
    return dict(差引枚数=int(quantity),当時現金=cash,既払料=paid,見込返済料=closing,
        当時清算収支=cash+quantity*price*value-paid-closing)


def summarize(rows,sessions=None):
    """
    機能: 元黒字の喪失と元赤字の救済を混ぜず、全親の差額を恒等分解する。
    引数: rows(list[dict])、sessions(list[str]又はNone)。
    返り値: dict。
    """
    oldwin=[r for r in rows if r['元収支']>EPS];oldloss=[r for r in rows if r['元収支']<-EPS]
    zero=[r for r in rows if abs(r['元収支'])<=EPS]
    saved=sum(max(0.,r['収支差']) for r in oldloss);lost=sum(max(0.,-r['収支差']) for r in oldwin)
    winmore=sum(max(0.,r['収支差']) for r in oldwin);lossmore=sum(max(0.,-r['収支差']) for r in oldloss)
    zerodelta=sum(r['収支差'] for r in zero);delta=sum(r['収支差'] for r in rows)
    assert abs(delta-(saved-lost+winmore-lossmore+zerodelta))<1e-5
    out=dict(全元親数=len(rows),元活動親=sum(r['元活動'] for r in rows),変更活動親=sum(r['変更活動'] for r in rows),
        元無取引親=sum(not r['元活動'] for r in rows),変更無取引親=sum(not r['変更活動'] for r in rows),
        改善親=sum(r['収支差']>EPS for r in rows),悪化親=sum(r['収支差']<-EPS for r in rows),
        同額親=sum(abs(r['収支差'])<=EPS for r in rows),
        元赤字親の改善額=saved,元黒字親の取り逃し額=lost,元黒字親の上積み額=winmore,
        元赤字親の悪化額=lossmore,元ゼロ親の差額=zerodelta,
        料金前差=sum(r['料金前差'] for r in rows),料金差=sum(r['料金差'] for r in rows),収支差=delta,
        元黒字が赤字=sum(r['元収支']>EPS and r['変更収支']<-EPS for r in rows),
        元赤字が黒字=sum(r['元収支']<-EPS and r['変更収支']>EPS for r in rows))
    for prefix in ('元','変更'):
        nets=np.array([r[prefix+'収支'] for r in rows]);positive=float(nets[nets>EPS].sum());loss=float(-nets[nets<-EPS].sum())
        out[prefix+'利益']=positive;out[prefix+'損失']=loss;out[prefix+'収支']=float(nets.sum())
        out[prefix+'金額利益割合']=positive/(positive+loss) if positive+loss else None
        sessions=sorted({r['session'] for r in rows}) if sessions is None else sessions
        sessionnets={s:sum(r[prefix+'収支'] for r in rows if r['session']==s) for s in sessions}
        active={s:any(r[prefix+'活動'] for r in rows if r['session']==s) for s in sessions}
        out[prefix+'活動場']=sum(active.values());out[prefix+'無取引場']=sum(not x for x in active.values())
        out[prefix+'黒字場']=sum(active[s] and sessionnets[s]>EPS for s in sessions)
        out[prefix+'赤字場']=sum(active[s] and sessionnets[s]<-EPS for s in sessions)
    return out


def notification_reasons(identifier,config,books,inputs,quietmaker):
    """
    機能: 負け通知の初公開時の不採用条件を独立に分類する。
    引数: identifier(str)、config/books/inputs(dict)、quietmaker(callable)。
    返り値: list[dict]。複数の不適格理由を重複して記録する。
    """
    output=[]
    for key,ledger in books.items():
        if config['execution_mode']=='IDEAL':continue
        ready=inputs[key];other=(key[0],'NK225' if key[1]=='TOPIX' else 'TOPIX')
        peer=books[other]['core_ledger'];peerparents=source_entries(peer)
        quiet=quietmaker(ready,'U');gates={int(x[2]):bool(x[14]) for x in ledger['peer_events'] if x[1]==1}
        triggered=set();orders=ledger['orders'];signed=np.cumsum(orders[:,3]*orders[:,4])
        for e in ledger['peer_events']:
            if e[1]!=2:continue
            row=int(e[0]);cid=int(e[2]);peer_cid=int(e[6]);ownside=int(e[3]);peerside=int(peerparents[peer_cid][3])
            last=int(np.searchsorted(orders[:,0],row,side='right'))-1
            actual=float(signed[last]) if last>=0 else 0.;actual_cid=int(orders[last,2]) if last>=0 else -1
            reasons=[]
            if config['holding_mode']==0:reasons.append('途中変更を使わないH0')
            if cid in triggered:reasons.append('同じ親で既に縮小済み')
            if not gates.get(cid,False):reasons.append('自己親の入口不許可又は新規前')
            if quiet['active'][row] or quiet['force'][row] or ready['time_s'][row]>=ready['limit']:reasons.append('予定見送り又は場末')
            if e[10]==0:reasons.append('自己元GUは既に空玉')
            if ownside!=peerside:reasons.append('相手停止の方向が自己と違う')
            if e[18]>=row:reasons.append('自己仮想新規と同観測又は前')
            if actual_cid!=cid or actual*ownside<=0:reasons.append('同じ自己親の実玉が未保有')
            if e[16]>180.:reasons.append('停止通知自体が180秒より古い')
            expected=not reasons
            assert expected==bool(e[14]),(identifier,key,row,reasons,e.tolist())
            if expected:triggered.add(cid)
            output.append(dict(ID=identifier,session=key[0],symbol=key[1],自己組=cid,自己行=row,
                自己代理時計=stamp(ready,row),相手組=peer_cid,相手停止行=int(e[4]),
                相手代理時計=stamp(inputs[other],int(e[4])),停止の古さ秒=float(e[16]),
                発火=expected,不採用理由=reasons,自己元残枚数=int(e[10]),自己実枚数=int(e[11]),
                相手停止理由=int(e[15]),相手確定収支=float(e[8])))
    return output


def concrete(row,a,b,ready,peer_ready):
    """
    機能: 同入口H比較の反例又は救済例を、公開時刻と後の全結果を区別して説明する。
    引数: row/a/b/ready/peer_ready(dict)。
    返り値: dict又はNone。未来成績は事後診断だけに使う。
    """
    cid=row['組'];events=[x for x in b['peer_events'] if x[1]==3 and int(x[2])==cid]
    if not events:return None
    e=events[0];notice=int(e[0]);ao=group_orders(a,cid);bo=group_orders(b,cid)
    value=1000. if ready['symbol']=='TOPIX' else 10.;fee=41.8 if ready['symbol']=='TOPIX' else 11.
    at=at_parent(a,cid,notice,float(ready['last'][notice]),value,fee)
    future=bo[(bo[:,0]>notice)&(bo[:,7]==0)]
    first=future[0] if len(future) else None
    return dict(**row,通知時の元条件の料金込み評価=at,通知自己行=notice,通知自己代理時計=stamp(ready,notice),
        相手停止行=int(e[4]),相手停止代理時計=stamp(peer_ready,int(e[4])),相手停止時収支=float(e[8]),
        元新規代理時計=stamp(ready,int(ao[0,0])),元最終返済代理時計=stamp(ready,int(ao[-1,0])),
        変更最終返済代理時計=stamp(ready,int(bo[-1,0])),
        次返済行=int(first[0]) if first is not None else None,
        次返済代理時計=stamp(ready,int(first[0])) if first is not None else None,
        次返済枚数=int(first[4]) if first is not None else None,
        次返済価格=float(first[5]) if first is not None else None,
        自己が後に回復=at['当時清算収支']<0 and row['元収支']>0,
        元の損失が通知後さらに増加=row['元収支']<at['当時清算収支']-EPS)


def main():
    """
    機能: 根担当の全13完了通知後、入口と途中の効果を全元親へ対応して保存する。
    引数: なし。
    返り値: None。新しい条件選択・再生・閾値変更は行わない。
    """
    fixed=read(ROUND/'事前固定.json');configs={c['id']:c for c in fixed['catalog']}
    paths={k:ROUND/'observed/results'/(k+'.json') for k in configs}
    assert len(paths)==13 and all(p.exists() for p in paths.values()),'全十三条件完了が必要'
    results={k:read(p) for k,p in paths.items()}
    ledgers={}
    for k in paths:
        p=ROUND/'observed/ledgers'/(k+'.pkl');assert sha(p)==results[k]['ledger_SHA256']
        ledgers[k]=pickle.loads(p.read_bytes())
    prepare=module('wave85_prepare',ROOT/'work/wave_v85/prepare.py')
    time_filter=module('wave85_time_filter_diagnose11',ROOT/'work/wave_v85/time_filter.py')
    inputs,_,_=prepare.load_inputs(True)
    baseline=ledgers['P_E0_H0'];universe={key:source_entries(x['core_ledger']) for key,x in baseline.items()}
    pairs=[('入口見送り','P_E0_H0',f'P_E{e}_H0') for e in (1,2,3)]
    pairs += [('相手同方向からの入口強化','P_E1_H0',f'P_E{e}_H0') for e in (2,3)]
    pairs += [('同入口の途中判断',f'P_E{e}_H0',f'P_E{e}_H{h}') for e in range(4) for h in (1,2)]
    pairs += [('固定主案','P_E0_H0','P_E1_H1'),('観測一回待ちの対照','P_GU_IDEAL','P_E0_H0')]
    out=dict(対象='相手元GU参照の十三固定条件。全30場は既知。無取引親は0円対応し勝ちに数えない。',
        診断と判断の区別='後の回復・損失拡大の分類は保存済み結果の原因説明だけ。条件選択・通知・発注へ戻さない。',
        主仮説='P_E1_H1',比較=[],全親組=[],具体例=[],通知全件=[],全条件期間={},
        実装SHA256=fixed['code_SHA256'],結果SHA256={k:sha(p) for k,p in paths.items()})
    # ----------------------------------------
    # 全条件で自己の源口座が不変であることを保存台帳から再確認する。
    for identifier,books in ledgers.items():
        for key,book in books.items():
            for nested in ('core_ledger','virtual_ledger'):
                old=baseline[key]['core_ledger'];cur=book[nested]
                for name in ('orders','trades','cycles','fees'):np.testing.assert_array_equal(old[name],cur[name])
                assert old['curve_SHA256']==cur['curve_SHA256'] and old['net_trades']==cur['net_trades']
    out['自己仮想源の全件不変']=True
    for kind,aid,bid in pairs:
        parentrows=[];checks=[]
        for key,ready in sorted(inputs.items()):
            a=ledgers[aid][key];b=ledgers[bid][key];ag=groups(a);bg=groups(b)
            assert not (set(ag)|set(bg))-set(universe[key])
            if kind=='同入口の途中判断':
                np.testing.assert_array_equal(a['orders'][a['orders'][:,7]==1],b['orders'][b['orders'][:,7]==1])
                ae=a['peer_events'][a['peer_events'][:,1]==1];be=b['peer_events'][b['peer_events'][:,1]==1]
                np.testing.assert_array_equal(ae[:,[0,2,14]],be[:,[0,2,14]])
            for cid,entry in universe[key].items():
                z=dict(gross=0.,fees=0.,net=0.,legs=0,lots=0);av=ag.get(cid,z);bv=bg.get(cid,z)
                if kind in ('入口見送り','相手同方向からの入口強化') and cid in bg:
                    np.testing.assert_array_equal(group_orders(a,cid),group_orders(b,cid))
                    assert abs(av['net']-bv['net'])<1e-6
                change=bv['net']-av['net'];gross=bv['gross']-av['gross'];fees=bv['fees']-av['fees']
                assert abs(change-(gross-fees))<1e-5
                parentrows.append(dict(比較種別=kind,元ID=aid,変更ID=bid,session=key[0],symbol=key[1],組=cid,
                    元源新規行=int(entry[0]),方向=int(entry[3]),元活動=cid in ag,変更活動=cid in bg,
                    元収支=av['net'],変更収支=bv['net'],料金前差=gross,料金差=fees,収支差=change,
                    元料金=av['fees'],変更料金=bv['fees'],元返済枚数=av['lots'],変更返済枚数=bv['lots']))
            checks.append(dict(session=key[0],symbol=key[1],源親数=len(universe[key]),
                初回新規完全一致=kind=='同入口の途中判断',入口制限の採用親は経路不変=kind in ('入口見送り','相手同方向からの入口強化')))
        periods={period:{s:summarize([r for r in parentrows if r['symbol']==s and r['session'] in fixed[period]],fixed[period])
            for s in ('TOPIX','NK225')} for period in ('前16','後14','全30')}
        sides={s:{'買い' if d>0 else '売り':summarize([r for r in parentrows if r['symbol']==s and r['方向']==d],fixed['全30']) for d in (1,-1)} for s in ('TOPIX','NK225')}
        out['比較'].append(dict(種別=kind,元ID=aid,変更ID=bid,期間=periods,買売=sides,検算=checks));out['全親組'].extend(parentrows)
        if kind=='同入口の途中判断':
            for s in ('TOPIX','NK225'):
                candidates=[]
                for r in parentrows:
                    if r['symbol']!=s or abs(r['収支差'])<EPS:continue
                    key=(r['session'],s);peerkey=(r['session'],'NK225' if s=='TOPIX' else 'TOPIX')
                    example=concrete(r,ledgers[aid][key],ledgers[bid][key],inputs[key],inputs[peerkey])
                    if example is not None:candidates.append(example)
                bad=[x for x in candidates if x['自己が後に回復'] and x['収支差']<0]
                good=[x for x in candidates if x['元収支']<0 and x['収支差']>0 and x['元の損失が通知後さらに増加']]
                out['具体例'].append(dict(元ID=aid,変更ID=bid,symbol=s,
                    後に回復した自己を先に削った例=sorted(bad,key=lambda x:x['収支差'])[:3],
                    通知後に増えた損失を先に減らした例=sorted(good,key=lambda x:-x['収支差'])[:3],
                    前者全件数=len(bad),後者全件数=len(good)))
    # ----------------------------------------
    # 全通知を初公開時の情報だけで分類。代表例だけを救済成績に置き換えない。
    for identifier,config in configs.items():
        notes=notification_reasons(identifier,config,ledgers[identifier],inputs,time_filter.features)
        out['通知全件'].extend(notes)
        out.setdefault('通知集計',{})[identifier]={s:dict(
            公開通知=sum(n['symbol']==s for n in notes),発火=sum(n['symbol']==s and n['発火'] for n in notes),
            不採用理由重複あり=dict(Counter(reason for n in notes if n['symbol']==s for reason in n['不採用理由']))) for s in ('TOPIX','NK225')}
        out['全条件期間'][identifier]={}
        for period in ('前16','後14','全30'):
            out['全条件期間'][identifier][period]={}
            for s in ('TOPIX','NK225'):
                values=[v['net'] for key,book in ledgers[identifier].items() if key[1]==s and key[0] in fixed[period] for v in groups(book).values()]
                gain=sum(v for v in values if v>0);loss=-sum(v for v in values if v<0);share=gain/(gain+loss) if gain+loss else None
                saved=results[identifier]['periods'][period][s]
                assert abs(sum(values)-saved['net'])<1e-5
                out['全条件期間'][identifier][period][s]=dict(
                    net=saved['net'],gross=saved['gross'],fees=saved['fees'],利益=gain,損失=loss,金額利益割合=share,
                    活動親数=len(values),二十親未満=len(values)<20,八割以上観測=share is not None and share>=.8,
                    黒字場=saved['positive_sessions'],赤字場=saved['negative_sessions'],無取引場=saved['no_trade_sessions'],
                    最大下落=saved['max_drawdown'],最良1場除外=saved.get('best_session_removed'),
                    解釈='少数例の観測。主案へ昇格させない。' if len(values)<20 else '固定した全結果として提示。後半で選び直さない。')
    out['差額集計の注意']='元赤字改善額と元黒字取り逃し額はいずれも正の絶対額。逆方向の元赤字悪化・元黒字上積みも合算し、全元親の収支差へ一致させる。'
    destination=HERE/'相手GUの入口見送りと途中縮小の全親分解.json'
    destination.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False,default=scalar)+'\n',encoding='utf-8')
    print('十五比較・全元親・全通知・後の回復反例と救済例を保存',flush=True)


if __name__=='__main__':main()
