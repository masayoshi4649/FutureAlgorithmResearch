"""③WIDEの保存66台帳を各一読し、FAKの受理・試行・失効を分離する。"""

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import pickle
from statistics import median
import traceback

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parents[1]
ROOT=HERE.parents[3]
CASE='E01_CURRENT_VOL_PRICE_RESPONSE_WIDE_TRAIL'
META=WORK/'root_review/主候補の約定選択診断用66台帳目録.json'
META_SHA='294df9f0179099c2f80dce6a910027f7b80ae053e91b2bd0cbaa80188f059741'
RESULT_SHA='ad0df26bb40ae4bc1b37700decec1d1dbabc60efc4419871665b0d23208cb31b'
PLAN=HERE/'保存66台帳の約定選択だけを調べる一読計画.json'
ART=HERE/'FAK受理試行失効取消と原seq差の純人工.json'
OUTPUT=HERE/'主反応WIDEのFAK公開受理と約定失効の選択.json'
REPORT=HERE/'FAKの約定選択と方向損益を混同しない補助診断.md'
CAP={'TOPIX':10,'NK225':20}
TICK={'TOPIX':.5,'NK225':10.}


def sha(path: Path) -> str:
    """
    機能: 私有源又は小目録の指紋を求める。
    引数: path(Path) はsource又は準備済み資料。
    返り値: str はSHA256。台帳本文の事前読取には使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources() -> dict:
    """
    機能: 経済17源と今回の診断一源を読み取り専用の指紋へ束縛する。
    引数: なし。
    返り値: dict は変更監視用SHA。旧JITをimportしない。
    """
    paths=sorted((WORK/'engine').glob('*.py'))+[WORK/'root_review'/n for n in ('plan.py','finance.py','financial_metrics.py')]
    assert len(paths)==17
    return dict(経済源={p.relative_to(ROOT).as_posix():sha(p) for p in paths},診断源=sha(Path(__file__)))


def write(path: Path, value: dict) -> None:
    """
    機能: 所有域の新JSONを有限・日本語で保存し、既存証跡を上書きしない。
    引数: path(Path)、value(dict) は新保存先と内容。
    返り値: None。欠測の数値補完は行わない。
    """
    assert path.parent==HERE and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def delay(source: dict, arrival: dict) -> dict:
    """
    機能: 当時公開と後の到来行の観測差だけを測る。
    引数: source/arrival(dict) は保存snapshot。
    返り値: dict は行・原seq・価格代理秒の差。真の受信遅延ではない。
    """
    assert source['row']<arrival['row'] and source['raw_seq']<arrival['raw_seq']
    values=dict(normal_rows=arrival['row']-source['row'],raw_seq=arrival['raw_seq']-source['raw_seq'],
                price_proxy_seconds=arrival['price_time_s']-source['price_time_s'])
    assert values['price_proxy_seconds']>=0
    return values


def inspect(saved: dict) -> list[dict]:
    """
    機能: 候補評価と受理予約を実試行・失効・試行前取消へ一意に対応させる。
    引数: saved(dict) は同bytes一読復元した主条件一台帳。
    返り値: list[dict] は候補の処理結果。未約定後の仮想成績は計算しない。
    """
    assert saved['config']['id']==CASE and saved['symbol'] in CAP
    symbol=saved['symbol'];pub=np.asarray(saved['publication_events']);events=np.asarray(saved['execution_events'])
    orders=np.asarray(saved['orders']);uids=np.asarray(saved['order_uids']);origins=np.asarray(saved['actual_origins'])
    assert pub.ndim==events.ndim==orders.ndim==origins.ndim==2
    assert pub.shape[1]==24 and events.shape[1]==14 and orders.shape[1]==8 and origins.shape[1]==16
    assert len(orders)==len(uids)
    snapshots={int(p['row']):p for p in saved['snapshots']}
    assert len(snapshots)==len(saved['snapshots'])
    entries=orders[orders[:,7]==1];out=[];accepted=set();handled=set()
    for v in pub:
        row,cid,side,allow,ok,reason=map(int,(v[0],v[1],v[2],v[11],v[12],v[13]))
        assert side in (-1,1) and allow in (0,1) and ok in (0,1)
        source=snapshots[row];assert int(v[7])==CAP[symbol]
        quote=source['ask'] if side>0 else source['bid']
        if source['quote_valid'] and quote is not None:
            assert math.isclose(v[10],quote+side*allow*TICK[symbol],abs_tol=1e-8)
        record=dict(session=saved['session'],symbol=symbol,pub_row=row,pub_raw_seq=source['raw_seq'],
            pub_price_time_s=source['price_time_s'],side=side,allowance_ticks=allow,accepted=bool(ok),
            fixed_cap=float(v[10]) if math.isfinite(v[10]) else None,reason=reason,
            source_bid=source['bid'],source_ask=source['ask'])
        if not ok:
            assert cid==-1 and reason!=0
            record['status']='評価拒否';out.append(record);continue
        assert cid>=0 and cid not in accepted and reason==0;accepted.add(cid)
        terminal=events[(events[:,2]==cid)&np.isin(events[:,1],(1,3))]
        assert len(terminal)==1,('受理予約の終端が一意でない',cid,len(terminal))
        e=terminal[0];kind,at,origin_row,code,filled=map(int,(e[1],e[0],e[3],e[7],e[8]))
        assert origin_row==row and int(e[4])==side and int(e[5])==CAP[symbol] and int(e[9])==allow
        target=snapshots[at];record['delay']=delay(source,target);record['arrival_row']=at;record['arrival_raw_seq']=target['raw_seq']
        record['arrival_price_time_s']=target['price_time_s'];record['terminal_reason']=code;handled.add(cid)
        match=entries[entries[:,2]==cid]
        if kind==3:
            assert filled==0 and code in (92,93,161,162) and not len(match)
            record['status']='試行前取消'
        else:
            assert kind==1 and code in (90,98) and filled in (0,1) and target['quote_valid']
            price=target['ask'] if side>0 else target['bid'];assert math.isclose(e[6],price,abs_tol=1e-8)
            reached=price<=v[10] if side>0 else price>=v[10]
            assert bool(filled)==reached and (code==90)==reached
            record.update(arrival_bid=target['bid'],arrival_ask=target['ask'],arrival_side_price=price,
                adverse_movement_ticks=side*(price-quote)/TICK[symbol])
            if filled:
                assert len(match)==1 and int(match[0,0])==at and int(match[0,1])==row and int(match[0,4])==CAP[symbol]
                assert math.isclose(match[0,5],price,abs_tol=1e-8)
                uid=uids[np.flatnonzero((orders[:,2]==cid)&(orders[:,7]==1))[0]];assert uid>=0
                origin=origins[origins[:,0]==cid];assert len(origin)==1 and int(origin[0,2])==at and int(origin[0,3])==row
                record['status']='約定'
            else:
                assert not len(match) and not np.any(origins[:,0]==cid)
                record['status']='価格失効'
        out.append(record)
    assert accepted==handled and len(entries)==sum(v['status']=='約定' for v in out)==len(origins)
    assert sum(int(e[1]) in (1,3) for e in events)==len(accepted)
    return out


def aggregate(records: list[dict]) -> dict:
    """
    機能: 候補・受理・実試行を別分母にして約定率と観測差を集計する。
    引数: records(list[dict]) は同群の処理結果。
    返り値: dict は母数・比率・原seq等の分布。資格数を勝率へ読み替えない。
    """
    count=Counter(v['status'] for v in records)
    accepted=sum(v['accepted'] for v in records);attempts=count['約定']+count['価格失効']
    assert len(records)==accepted+count['評価拒否'] and accepted==attempts+count['試行前取消']
    delays={}
    for status in ('約定','価格失効','試行前取消'):
        own=[v['delay'] for v in records if v['status']==status]
        delays[status]={k:dict(count=len(own),minimum=min(v[k] for v in own) if own else None,
            median=median(v[k] for v in own) if own else None,maximum=max(v[k] for v in own) if own else None)
            for k in ('normal_rows','raw_seq','price_proxy_seconds')}
    return dict(候補評価=len(records),受理予約=accepted,評価拒否=count['評価拒否'],実試行=attempts,
        約定=count['約定'],価格失効=count['価格失効'],試行前取消=count['試行前取消'],
        受理予約に対する約定率=count['約定']/accepted if accepted else None,
        実試行に対する約定率=count['約定']/attempts if attempts else None,
        全候補評価に対する約定率=count['約定']/len(records) if records else None,
        拒否の先着理由=dict(Counter(str(v['reason']) for v in records if not v['accepted'])),
        試行前取消理由=dict(Counter(str(v['terminal_reason']) for v in records if v['status']=='試行前取消')),
        観測差=delays,
        到来側価格の順方向移動T={status:dict(Counter(str(v['adverse_movement_ticks']) for v in records if v['status']==status))
                             for status in ('約定','価格失効')})


def fixture(symbol: str, side: int, allowance: int) -> dict:
    """
    機能: 実約定・価格失効・試行前取消・評価拒否の四状態を合成する。
    引数: symbol(str)、side/allowance(int) は商品と売買/許容。
    返り値: dict は最小保存台帳。元経済sourceやJITを実行しない。
    """
    snapshots=[]
    for row in (1,3,4,10,12,20,21,30):
        bid,ask=100.,101.
        if row==3:
            if side>0:ask+=allowance*TICK[symbol]
            else:bid-=allowance*TICK[symbol]
        if row==12:
            if side>0:ask+=(allowance+1)*TICK[symbol]
            else:bid-=(allowance+1)*TICK[symbol]
        snapshots.append(dict(row=row,raw_seq=100+2*row,price_time_s=1000.+row//2,bid=bid,ask=ask,quote_valid=True))
    pubs=np.zeros((4,24));events=np.zeros((3,14));q=CAP[symbol];quote=101. if side>0 else 100.
    cap=quote+side*allowance*TICK[symbol]
    for i,row in enumerate((1,10,20,30)):
        pubs[i,[0,1,2,7,10,11,12,13]]=[row,i if i<3 else -1,side,q,cap,allowance,int(i<3),0 if i<3 else 94]
    fill=next(p for p in snapshots if p['row']==3);price=fill['ask'] if side>0 else fill['bid']
    fail=next(p for p in snapshots if p['row']==12);badprice=fail['ask'] if side>0 else fail['bid']
    events[0,:10]=[3,1,0,1,side,q,price,90,1,allowance]
    events[1,:10]=[12,1,1,10,side,q,badprice,98,0,allowance]
    events[2,:10]=[21,3,2,20,side,q,cap,92,0,allowance]
    orders=np.array([[3,1,0,side,q,price,90,1],[4,3,0,-side,q,price,143,0]],float)
    origin=np.zeros((1,16));origin[0,[0,2,3]]=[0,3,1]
    return dict(config=dict(id=CASE),symbol=symbol,session='合成_Day',publication_events=pubs,execution_events=events,
                orders=orders,order_uids=np.array([0,-1]),actual_origins=origin,snapshots=snapshots)


def artificial() -> dict:
    """
    機能: 買売・0/1T・受付分母・原seq差・JSON保存・不整合拒否を人工で固定する。
    引数: なし。
    返り値: dict はSOURCE_ONLY検査数と実読取0。
    """
    checks=0
    for symbol in CAP:
        for side in (-1,1):
            for allow in (0,1):
                saved=fixture(symbol,side,allow);records=inspect(saved);a=aggregate(records)
                assert [a[k] for k in ('候補評価','受理予約','評価拒否','実試行','約定','価格失効','試行前取消')]==[4,3,1,2,1,1,1];checks+=7
                assert a['受理予約に対する約定率']==1/3 and a['実試行に対する約定率']==.5;checks+=2
                assert a['観測差']['約定']['raw_seq']['median']==4;checks+=1
                json.loads(json.dumps(a,allow_nan=False));checks+=1
                saved['execution_events'][1,8]=1
                try:
                    inspect(saved)
                except AssertionError:
                    checks+=1
                else:
                    raise AssertionError('価格不成立のfillを受理')
    empty=aggregate([]);assert empty['実試行に対する約定率'] is None;checks+=1
    return dict(全合格=True,検査数=checks,台帳本文=0,金融=0,cache=0,API=0)


def prepare() -> None:
    """
    機能: 純人工と固定66path/SHAを結び、大型台帳読取前に目的を保存する。
    引数: なし。
    返り値: None。台帳はstatだけで本文を開かない。
    """
    assert not PLAN.exists() and not ART.exists()
    before=sources();raw=META.read_bytes();assert hashlib.sha256(raw).hexdigest()==META_SHA
    meta=json.loads(raw);assert meta['全合格'] and meta['case']==CASE and meta['出典SHA256']==RESULT_SHA
    assert len(meta['sessions'])==33 and len(meta['ledgers'])==66
    assert {(v['session'],v['symbol']) for v in meta['ledgers']}=={(s,k) for s in meta['sessions'] for k in CAP}
    items=[]
    for item in meta['ledgers']:
        path=ROOT/item['path'];assert path.parent.name==CASE and path.is_file()
        items.append(dict(**item,stat_bytes=path.stat().st_size))
    art=artificial();art['source_SHA256']=before;write(ART,art)
    write(PLAN,dict(全合格=True,目的='完結親方向損益とFAK約定選択の分母を分ける補助診断。効果の追加根拠ではない。',
        case=CASE,出典結果SHA256=RESULT_SHA,目録=dict(path=META.relative_to(ROOT).as_posix(),SHA256=META_SHA),
        source_SHA256=before,ledgers=items,sessions=meta['sessions'],
        読取予定=dict(台帳本文=66,各台帳回数=1,元金融結果=0,同bytes結果=0,cache=0,原板=0,NPZ=0,API=0,新金融=0),
        使用項目=['publication_events','execution_events','orders','order_uids','actual_origins','snapshots','config','session','symbol'],
        出力='商品・固定許容0/1・昼夜・売買別の候補/受理/拒否/試行/fill/価格失効/試行前取消と原seq等の差。',
        禁止='失効の未来成績/仮想成行成績/再金融。約定率を勝率又は信号の良否にしない。',
        不足時停止=True,自動再開始=False,人工=dict(path=ART.name,SHA256=sha(ART))))
    print(json.dumps(dict(準備完了=True,人工検査数=art['検査数'],planSHA256=sha(PLAN),artSHA256=sha(ART)),ensure_ascii=False))


def run() -> None:
    """
    機能: 根授権の保存66台帳を各同bytes一読で集計し、保存だけの補助診断を完成する。
    引数: なし。
    返り値: None。失敗時の読取数を保全し、自動再読しない。
    """
    plan=json.loads(PLAN.read_text(encoding='utf-8'));source=sources()
    assert source==plan['source_SHA256'] and sha(ART)==plan['人工']['SHA256']
    assert not any(p.exists() for p in (OUTPUT,REPORT,HERE/'開始.json',HERE/'False.json'))
    write(HERE/'開始.json',dict(計画SHA256=sha(PLAN),source_SHA256=source,根授権=True))
    counts=dict(台帳本文=0,元金融結果=0,同bytes結果=0,cache=0,原板=0,NPZ=0,API=0,新金融=0)
    all_records=[];sessions=[]
    try:
        for item in plan['ledgers']:
            counts['台帳本文']+=1;raw=(ROOT/item['path']).read_bytes()
            assert len(raw)==item['stat_bytes'] and hashlib.sha256(raw).hexdigest()==item['SHA256']
            saved=pickle.load(gzip.GzipFile(fileobj=io.BytesIO(raw),mode='rb'))
            assert saved['session']==item['session'] and saved['symbol']==item['symbol']
            records=inspect(saved);all_records.extend(records)
            a=aggregate(records)
            sessions.append(dict(session=item['session'],symbol=item['symbol'],**{k:a[k] for k in (
                '候補評価','受理予約','評価拒否','実試行','約定','価格失効','試行前取消')}))
            del saved,raw
        assert counts['台帳本文']==66 and source==sources()
        symbols={}
        for symbol in CAP:
            pp=[p for p in all_records if p['symbol']==symbol]
            symbols[symbol]=dict(全体=aggregate(pp),
                固定許容={str(t):aggregate([v for v in pp if v['allowance_ticks']==t]) for t in (0,1)},
                昼夜={tag:aggregate([v for v in pp if v['session'].endswith('_'+tag)]) for tag in ('Day','Night')},
                売買={str(side):aggregate([v for v in pp if v['side']==side]) for side in (-1,1)})
        output=dict(全合格=True,source開始終端一致=True,source_SHA256=source,計画SHA256=sha(PLAN),読取計数=counts,
            case=CASE,出典結果SHA256=RESULT_SHA,目録SHA256=META_SHA,symbols=symbols,by_session=sessions,
            留保='FAKによる約定選択の存在可能性と信号の方向性能を区別する。失効後成績・成行対照成績は未測。原seq差は受信遅延ではない。')
        write(OUTPUT,output)
        lines=['FAKの約定率を、入口信号そのものの勝率と分けて集計した。③WIDEの保存66台帳だけを各一読し、金融再計算・入力cache・原板・APIは0。',
            '',f"[計画](保存66台帳の約定選択だけを調べる一読計画.json)／[検算小会計](主反応WIDEのFAK公開受理と約定失効の選択.json)。元結果SHA `{RESULT_SHA}`。",'',
            '|商品・許容|候補評価|受理予約|実試行|約定|価格失効|試行前取消|試行に対する約定率|','|---|---:|---:|---:|---:|---:|---:|---:|']
        for s,z in symbols.items():
            for label,a in [('全体',z['全体'])]+[(t+'T',a) for t,a in z['固定許容'].items()]:
                rate=a['実試行に対する約定率'];rate='未定義' if rate is None else f'{rate:.1%}'
                lines.append(f"|{s} {label}|{a['候補評価']}|{a['受理予約']}|{a['実試行']}|{a['約定']}|{a['価格失効']}|{a['試行前取消']}|{rate}|")
        lines += ['','候補評価にはbusy・静観・期間外・費用余裕などの評価拒否を含む。これは板へ発注した注文数ではない。拒否はsourceの優先順による先着理由で、重複原因の独立比率ではない。',
            '', '0T/1T価格限界は、公開後の順方向に進んだ到来気配を失効させ得る。このため約定親だけの中値損益から、全入口信号が同じく逆行したと一般化できない。一方、この集計は失効後の保有損益を持たないので、成行なら利益だった、FAKだけが赤字原因だった、という結論も出せない。',
            '', '公開→約定のnormal行差・原seq差・価格代理秒差はJSONへ保存。真の受信時計・注文応答時間は未保存。異なるrawseqでもPriceTimeが同秒なら代理秒差は0になる。',
            '', '次に約定方法の部品対照を行うなら、同じ公開候補から成行とFAKを全後続・同じ会計で別固定して初めて選択の金額効果を測れる。今回はその追加金融を行っていない。']
        REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        write(HERE/'完了.json',dict(全合格=True,読取計数=counts,結果SHA256=sha(OUTPUT),MD_SHA256=sha(REPORT),source開始終端一致=True))
        print(json.dumps(dict(全合格=True,読取計数=counts,結果SHA256=sha(OUTPUT),symbols={s:z['全体'] for s,z in symbols.items()}),ensure_ascii=False))
    except BaseException:
        write(HERE/'False.json',dict(全合格=False,読取計数=counts,原因=traceback.format_exc(),自動再開始=False))
        raise


def main() -> None:
    """
    機能: 計画・人工先固定と根授権後の保存台帳一読を分けて受け付ける。
    引数: CLI --prepare(bool) 又は --root-ledgers-authorized(bool)。
    返り値: None。元経済sourceや金融結果を更新しない。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--root-ledgers-authorized',action='store_true')
    args=parser.parse_args()
    if args.prepare:
        prepare()
    else:
        run()


if __name__=='__main__':
    main()
