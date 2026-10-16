"""前16場の固定3代表について、方向が変わるまで待つ損益と取引費用を診断する。"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import pickle
import sys
import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
JST=timezone(timedelta(hours=9))
HASHES={}
PHASES=('共同支持','共同反対','片側反対','中立を含む','欠測又は未準備','返済発注後')


def load(path):
    """
    機能: 保存済みの入力と前半結果を読み、出典指紋を残す。
    引数: path (Path)。
    返り値: object のJSON又はpickle内容。後半結果を読まない。
    """
    raw=path.read_bytes();HASHES[str(path.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest()
    return pickle.loads(raw) if path.suffix=='.pkl' else json.loads(raw.decode('utf-8'))


# ----------------------------------------
def stamp(value):
    """
    機能: 保存代理時計を日本時間へ表示変換する。
    引数: value (float)。
    返り値: str の日時。
    """
    return datetime.fromtimestamp(float(value),JST).isoformat()


# ----------------------------------------
def clean(value):
    """
    機能: NumPy値と非数をJSON互換へ変換する。
    引数: value (object)。
    返り値: object の保存可能値。
    """
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not np.isfinite(value):return None
    return value


# ----------------------------------------
def snapshot(key,index,ready,books):
    """
    機能: 元の原板行に対応する時計・気配・数量を保存する。
    引数: key (tuple)、index (int)、ready/books (dict)。
    返り値: dict 又はNone。
    """
    if index<0:return None
    r,b=ready[key],books[key]
    return dict(準備行=int(index),原本seq=int(r['seq'][index]),代理時計=stamp(r['time_s'][index]),
                bid=float(b['bid'][index]),ask=float(b['ask'][index]),買数量=float(b['bid_qty'][index]),売数量=float(b['ask_qty'][index]))


# ----------------------------------------
def evidence(key,index,model,ready,books,signal):
    """
    機能: 判断時点に見えていた両市場の方向・OFI・参照原本を記録する。
    引数: key (tuple)、index/model (int)、ready/books/ signal (dict)。
    返り値: dict の因果的根拠。方向は現在自己行と厳密過去の相手行。
    """
    out={}
    for suffix,symbol in [('self',key[1]),('peer','NK225' if key[1]=='TOPIX' else 'TOPIX')]:
        source=int(signal['source_'+suffix][index]);other=(key[0],symbol)
        update=int(signal['last_flow_update_'+suffix][index])
        out[symbol]=dict(方向=int(signal['states_'+suffix][model,index]),有効=bool(signal['valid_'+suffix][model,index]),
                         価格方向k1_2_4_8=signal['states_'+suffix][:4,index].tolist(),
                         価格方向有効=signal['valid_'+suffix][:4,index].tolist(),
                         OFI正規化N8_32_128=signal['flow_'+suffix][:,index].tolist(),
                         OFI最終更新=snapshot(other,update,ready,books),参照原板=snapshot(other,source,ready,books),
                         参照古さ秒=float(signal['age_'+suffix][index]))
    return out


# ----------------------------------------
def trade_diagnostic(config,key,ledger,ready,books,signal):
    """
    機能: 全決済を価格経路・状態別継続・一時含み益・再参加に分ける。
    引数: config/ledger/ready/books/signal (dict)、key (tuple)。
    返り値: list[dict] の全組診断。新しい戦略の損益再生は行わない。
    """
    r,b=ready[key],books[key];times=r['time_s'];bid,ask=b['bid'],b['ask'];mid=(bid+ask)/2
    m=config['model'];own=signal['states_self'][m];peer=signal['states_peer'][m]
    vo=signal['valid_self'][m];vp=signal['valid_peer'][m]
    value=1000. if key[1]=='TOPIX' else 10.
    output=[]
    for t in ledger['trades']:
        cid,ei,xi=map(int,t[:3]);side=int(t[3]);scale=t[4]*value;fees=t[7]+t[8]
        orders=ledger['orders'][ledger['orders'][:,2]==cid]
        e=orders[orders[:,7]==1][0];x=orders[orders[:,7]==0][0]
        di,xd=int(e[1]),max(ei,int(x[1]));q=bid if side==1 else ask
        path=side*(q[ei:xi+1]-t[5])*scale-fees
        pi=ei+int(np.argmax(path));mi=ei+int(np.argmin(path))
        first={}
        masks={
            '共同支持が消失':vo[ei:xd+1]&vp[ei:xd+1]&((own[ei:xd+1]!=side)|(peer[ei:xd+1]!=side)),
            '一市場が反対':(vo[ei:xd+1]&(own[ei:xd+1]==-side))|(vp[ei:xd+1]&(peer[ei:xd+1]==-side)),
            '有効な中立を観測':vo[ei:xd+1]&vp[ei:xd+1]&((own[ei:xd+1]==0)|(peer[ei:xd+1]==0))}
        for label,mask in masks.items():
            found=np.flatnonzero(mask)
            if not len(found):first[label]=None;continue
            j=ei+int(found[0]);arrival=times[j]+config['latency']
            fill=max(j+1,int(np.searchsorted(times,arrival,side='left')))
            assert fill<len(times)
            known_pnl=side*(q[j]-t[5])*scale-fees
            diagnostic_exit=side*(q[fill]-t[5])*scale-fees
            first[label]=dict(準備行=j,時計=stamp(times[j]),その時の両市場=evidence(key,j,m,ready,books,signal),
                              その時の清算含み損益円=float(known_pnl),実返済までの増減円=float(t[10]-known_pnl),
                              両反対判断まで秒=float(x[10]-times[j]),診断単発返済時計=stamp(times[fill]),
                              診断単発返済円=float(diagnostic_exit),実返済との差円=float(t[10]-diagnostic_exit),
                              注意='診断用に同じ入口を一度だけ5秒待ち返済した比較。以後の再参加・建玉経路を再生した戦略収支ではない。')
        length=xi-ei
        phase=np.full(length,4,dtype=np.int8)
        if length:
            a=own[ei:xi];p=peer[ei:xi];v=vo[ei:xi]&vp[ei:xi]
            phase[v]=3;phase[v&((a==-side)|(p==-side))]=2
            phase[v&(a==-side)&(p==-side)]=1
            phase[v&(a==side)&(p==side)]=0
            phase[np.arange(ei,xi)>=xd]=5
        mid_changes=side*np.diff(mid[ei:xi+1])*scale
        quote_changes=side*np.diff(q[ei:xi+1])*scale
        durations=np.diff(times[ei:xi+1])
        partitions={label:dict(行間数=int(np.sum(phase==i)),秒=float(durations[phase==i].sum()),
                               中値変化円=float(mid_changes[phase==i].sum()),返済側気配変化円=float(quote_changes[phase==i].sum()))
                    for i,label in enumerate(PHASES)}
        entry_friction=side*(t[5]-mid[ei])*scale;exit_friction=-side*(t[6]-mid[xi])*scale
        mid_net=side*(mid[xi]-mid[ei])*scale
        assert abs(t[10]-(mid_net-entry_friction-exit_friction-fees))<1e-6
        assert abs(sum(v['中値変化円'] for v in partitions.values())-mid_net)<1e-6
        prior=output[-1] if output else None
        same=bool(prior and prior['方向値']==side)
        phase_col=3 if config['family']=='D1' else 2
        turn=int(signal['last_price_turn_self'][phase_col,di])
        in_phase=(signal['states_self'][phase_col,di]==side)
        same_phase=bool(same and prior['自己価格方向一致'] and in_phase and turn>=0 and turn==prior['自己価格転換行'])
        points={label:snapshot(key,j,ready,books) for label,j in [('新規判断',di),('新規約定',ei),('返済判断',xd),('返済約定',xi),('最大含み益',pi),('最大含み損',mi)]}
        for label,info in first.items():
            if info is not None:points[label]=snapshot(key,info['準備行'],ready,books)
        output.append(dict(ID=f'{config["id"]}:{key[0]}:{key[1]}:{cid}',手法=config['id'],セッション=key[0],商品=key[1],組=cid,
                           方向値=side,方向='買い' if side==1 else '売り',新規判断=stamp(e[10]),新規約定=stamp(e[12]),
                           返済判断=stamp(x[10]),返済約定=stamp(x[12]),新規価格=float(t[5]),返済価格=float(t[6]),
                           返済理由=int(x[6]),保有秒=float(x[12]-e[12]),新規待ち秒=float(e[12]-e[10]),返済待ち秒=float(x[12]-x[10]),
                           収支円=float(t[10]),中値進行円=float(mid_net),新規中値差円=float(entry_friction),返済中値差円=float(exit_friction),手数料円=float(fees),
                           新規判断後の不利円=float(side*(t[5]-(ask[di] if side==1 else bid[di]))*scale),
                           返済判断後の不利円=float(-side*(t[6]-q[xd])*scale),
                           新規時根拠=evidence(key,di,m,ready,books,signal),新規約定時根拠=evidence(key,ei,m,ready,books,signal),
                           返済判断時根拠=evidence(key,xd,m,ready,books,signal),最初の根拠変化=first,
                           最大清算含み益円=float(max(0.,path.max())),最大清算含み損円=float(min(0.,path.min())),
                           含み益から返済までの減少円=float(max(0.,path.max()-t[10])) if path.max()>0 else 0.,
                           含み益から負けへ転落=bool(path.max()>0 and t[10]<0),
                           新規約定時に共同支持あり=bool(vo[ei] and vp[ei] and own[ei]==side and peer[ei]==side),
                           状態別継続=partitions,時点原板=points,
                           同方向で次の取引=same,直前返済行で同方向再参加=bool(same and di==prior['返済行']),
                           自己価格方向一致=bool(in_phase),自己価格転換行=turn,同一自己価格方向内の再参加=same_phase,
                           返済行=xi,新規判断行=di))
    return output


# ----------------------------------------
def aggregate(trades):
    """
    機能: 含み益を確定利益と混同せず、価格経路と費用を商品内で集計する。
    引数: trades (list[dict])。
    返り値: dict の損益・支持変化後の経路・再参加統計。
    """
    fields=('収支円','中値進行円','新規中値差円','返済中値差円','手数料円','新規判断後の不利円','返済判断後の不利円',
            '最大清算含み益円','含み益から返済までの減少円')
    out={name:sum(t[name] for t in trades) for name in fields}
    out.update(取引数=len(trades),利益円=sum(max(0.,t['収支円']) for t in trades),損失円=sum(max(0.,-t['収支円']) for t in trades),
               勝ち数=sum(t['収支円']>0 for t in trades),負け数=sum(t['収支円']<0 for t in trades),
               負けのうち一度は含み益=sum(t['含み益から負けへ転落'] for t in trades),
               約定時に共同支持消失数=sum(not t['新規約定時に共同支持あり'] for t in trades),
               約定時に共同支持消失組収支=sum(t['収支円'] for t in trades if not t['新規約定時に共同支持あり']),
               保有秒中央値=float(np.median([t['保有秒'] for t in trades])) if trades else None,
               保有秒最大=max((t['保有秒'] for t in trades),default=None))
    out['状態別継続']={phase:{f:sum(t['状態別継続'][phase][f] for t in trades) for f in ('行間数','秒','中値変化円','返済側気配変化円')} for phase in PHASES}
    out['最初の根拠変化から返済まで']={}
    for event in ('共同支持が消失','一市場が反対','有効な中立を観測'):
        pairs=[(t,t['最初の根拠変化'][event]) for t in trades if t['最初の根拠変化'][event] is not None]
        a=dict(該当組数=len(pairs),初回から両反対判断秒中央値=float(np.median([v['両反対判断まで秒'] for t,v in pairs])) if pairs else None)
        for field in ('その時の清算含み損益円','実返済までの増減円','診断単発返済円','実返済との差円'):
            a[field]=sum(v[field] for t,v in pairs)
        a['その時含み益から実現負け数']=sum(v['その時の清算含み損益円']>0 and t['収支円']<0 for t,v in pairs)
        a['その時含み益組の以降悪化円']=sum(max(0.,v['その時の清算含み損益円']-t['収支円']) for t,v in pairs if v['その時の清算含み損益円']>0)
        a['その時既に損失組の以降悪化円']=sum(max(0.,v['その時の清算含み損益円']-t['収支円']) for t,v in pairs if v['その時の清算含み損益円']<=0)
        a['実現勝ち組の単発早期返済差円']=sum(v['診断単発返済円']-t['収支円'] for t,v in pairs if t['収支円']>0)
        a['実現負け組の単発早期返済差円']=sum(v['診断単発返済円']-t['収支円'] for t,v in pairs if t['収支円']<0)
        out['最初の根拠変化から返済まで'][event]=a
    out['再参加']={}
    for label in ('同方向で次の取引','直前返済行で同方向再参加','同一自己価格方向内の再参加'):
        group=[t for t in trades if t[label]]
        out['再参加'][label]=dict(取引数=len(group),収支円=sum(t['収支円'] for t in group),
                                 中値進行円=sum(t['中値進行円'] for t in group),
                                 気配差円=sum(t['新規中値差円']+t['返済中値差円'] for t in group),手数料円=sum(t['手数料円'] for t in group))
    return out


# ----------------------------------------
def verify_raw(examples):
    """
    機能: 最悪組の判断・約定・根拠変化・一時含み益の原板行を独立照合する。
    引数: examples (list[dict])。
    返り値: dict の原本照合件数。事後の最大点を売買判定には使わない。
    """
    targets={}
    for t in examples:
        key=(t['セッション'],t['商品'])
        for row in t['時点原板'].values():targets.setdefault(key,{})[row['原本seq']]=row
        for field in ('新規時根拠','新規約定時根拠','返済判断時根拠'):
            for symbol,info in t[field].items():
                for name in ('参照原板','OFI最終更新'):
                    row=info[name]
                    if row is not None:targets.setdefault((t['セッション'],symbol),{})[row['原本seq']]=row
        for event in t['最初の根拠変化'].values():
            if event is None:continue
            for symbol,info in event['その時の両市場'].items():
                row=info['参照原板']
                if row is not None:targets.setdefault((t['セッション'],symbol),{})[row['原本seq']]=row
    verified=0
    for (session,symbol),want in targets.items():
        path=ROOT/'book'/symbol/(session+'.jsonl');found=0;h=hashlib.sha256()
        with path.open('rb') as stream:
            for seq,line in enumerate(stream):
                h.update(line)
                if seq not in want:continue
                raw=json.loads(line);r=want[seq]
                assert datetime.fromisoformat(raw['CurrentPriceTime'])==datetime.fromisoformat(r['代理時計'])
                assert raw['Buy1']['Price']==r['bid'] and raw['Sell1']['Price']==r['ask']
                assert raw['Buy1']['Qty']==r['買数量'] and raw['Sell1']['Qty']==r['売数量']
                found+=1
        assert found==len(want);verified+=found
        HASHES[str(path.relative_to(ROOT))]=h.hexdigest()
    return dict(全合格=True,口座数=len(targets),独立照合行数=verified,項目='代理時計・最良価格2・最良数量2',
                注意='表示変化から成行/取消/補充の内訳やトレーダーの意図を断定しない。')


# ----------------------------------------
def main():
    """
    機能: 初回3代表と同じ入口の既存出口対照を、前16だけで診断する。
    引数: なし。
    返り値: None。新戦略の再生や後14の閲覧は行わない。
    """
    HERE.mkdir(exist_ok=True)
    selection=load(BASE/'初回前半選定.json');fixed=load(BASE/'初回事前固定.json');sessions=fixed['前16'];allowed=set(sessions)
    meta=load(ROOT/'work/wave_v77/inputs/metadata.json');ready={};books={}
    for kind,target,extra in [('ready',ready,'extra_inputs.pkl'),('features',books,'extra_features.pkl')]:
        for name in meta['input_paths'][kind]+['work/wave_v77/inputs/'+extra]:
            target.update({k:v for k,v in load(ROOT/name).items() if k[0] in allowed})
    signals={k:v for k,v in load(BASE/'prepared/signals.pkl').items() if k[0] in allowed}
    all_trades={};summaries={};controls={};examples=[]
    for config in selection['代表']:
        ident=config['id'];result=load(BASE/'first/results'/(ident+'.json'));ledgers=load(BASE/'first/ledgers'/(ident+'.pkl'))
        assert all(k[0] in allowed for k in ledgers)
        group=[]
        for key,ledger in ledgers.items():group.extend(trade_diagnostic(config,key,ledger,ready,books,signals[key]))
        all_trades[ident]=group;summaries[ident]={}
        for symbol in ('TOPIX','NK225'):
            market=[t for t in group if t['商品']==symbol];a=aggregate(market);saved=result['periods']['前16'][symbol]
            assert a['収支円']==saved['net'] and a['取引数']==saved['trades']
            assert abs(a['新規中値差円']+a['返済中値差円']-saved['spread_drag'])<1e-6
            assert abs(a['新規判断後の不利円']+a['返済判断後の不利円']-saved['decision_to_fill_cost'])<1e-6
            summaries[ident][symbol]=a
            examples.extend(sorted(market,key=lambda t:t['収支円'])[:3])
        controls[ident]={}
        for x in (0,1,2):
            other=ident.replace('_X2_',f'_X{x}_')
            controls[ident][other]=load(BASE/'first/results'/(other+'.json'))['periods']['前16']
    raw=verify_raw(examples)
    out=dict(対象='前16の事前選定済み3代表と、同じ入口の既存X0/X1/X2。後14は未参照。',新戦略再生=False,
             注意=['一時的な清算含み益は確定利益ではない。最大含み益からの減少は事後診断で、最大点の予見やそこで約定できるとの仮定を置かない。',
                   '状態別経路は各原板行で判別できた状態へ次行までの価格変化を帰属する。中値は実際に約定できる価格ではない。',
                   '最初の支持消失での単発返済比較は、その後の新規・返済を再生しない診断値。新アルゴの利益として掲載しない。',
                   '板OFIは観測済み価格数量の圧力。参加者の焦りや将来の成行量を識別しない。'],
             主3商品別=summaries,既存出口3対照=controls,最悪3組ずつの具体例=examples,原本照合=raw,全取引=all_trades,出典SHA256=HASHES)
    target=HERE/'初回3代表の方向継続と損失原因.json'
    target.write_text(json.dumps(clean(out),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(clean(dict(保存=str(target),原本照合=raw,商品別={m:{s:{k:v[k] for k in ('取引数','収支円','中値進行円','新規中値差円','返済中値差円','手数料円','負けのうち一度は含み益','約定時に共同支持消失数','保有秒中央値','保有秒最大')} for s,v in groups.items()} for m,groups in summaries.items()})),ensure_ascii=False))


if __name__=='__main__':main()
