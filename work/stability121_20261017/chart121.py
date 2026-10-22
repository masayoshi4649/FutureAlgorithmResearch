"""新提案の九月二十四日を、保存した売買と既存一分足だけで図示する。"""

from collections import defaultdict
import csv
from datetime import datetime,timedelta,timezone
from io import BytesIO
import json
import numpy as np
from register121 import HERE,ROOT,read,save,sha

PUBLIC=ROOT/'アルゴリズム調査/00121_三ポイント間隔と五ポイント追尾'
SESSION='2026-09-24_Day'
METHOD='G3_T5_RESET'
JST=timezone(timedelta(hours=9))


def stamp(epoch: float) -> str:
    """
    機能: 当日のUNIX秒を日本時刻へ変換する。
    引数: epoch(float)は約定又は判断時刻。
    返り値: strは時分秒。
    """
    return datetime.fromtimestamp(epoch,JST).strftime('%H:%M:%S')


def main() -> None:
    """
    機能: 提案の全玉を個別追跡できる一分足HTMLを新規作成する。
    引数: なし。完成金融結果と当日のローカル一分足だけを読む。
    返り値: None。売買再生と原板読み取りは行わない。
    """
    result=read(HERE/'三ポイント間隔と五ポイント追尾の全四十場.json')
    index=next(i for i,s in enumerate(result['specs']) if s['id']==METHOD)
    expected=next(r for r in result['runs'] if r['method']==METHOD and r['session']==SESSION)
    reference=next(r for r in result['cache'] if r['session']==SESSION)
    path=ROOT/reference['path']
    assert sha(path)==reference['sha256']
    with np.load(BytesIO(path.read_bytes()),allow_pickle=False) as source:
        raw=source['lots'];orders=source['orders']
        save(HERE/'九月二十四日_全三条件の注文と玉.json',dict(
            specs=result['specs'],orders=orders.tolist(),lots=raw.tolist(),
            order_columns=result['order_columns'],lot_columns=result['lot_columns'],
            source_sha256=reference['sha256'],financial_replay=0))
        values=raw[raw[:,0]==index,1:].copy()
        orders=orders[orders[:,0]==index,1:].copy()
    lots=[];events=[]
    for v in values:
        uid=int(v[0]);entry=orders[(orders[:,0]==uid)&(orders[:,1]==1)][0]
        exit_=orders[(orders[:,0]==uid)&(orders[:,1]==2)][0]
        lot=dict(uid=uid,side=int(v[1]),rung=int(v[2]),entry_epoch=float(v[5]),exit_epoch=float(v[9]),
            entry_time=stamp(v[5]),exit_time=stamp(v[9]),entry_price=float(v[6]),exit_price=float(v[10]),
            entry_row=int(v[4]),exit_row=int(v[8]),entry_decision_epoch=float(entry[5]),exit_decision_epoch=float(exit_[5]),
            entry_decision_time=stamp(entry[5]),exit_decision_time=stamp(exit_[5]),
            points=float(v[1]*(v[10]-v[6])),quantity=1,gross=float(v[11]),fees=float(v[12]),net=float(v[13]),reason=int(v[14]))
        assert lot['points']*1000==lot['gross'] and lot['gross']-82==lot['net']
        lots.append(lot)
        events.extend([(lot['entry_row'],lot['entry_epoch'],lot['side'],1),
                       (lot['exit_row'],lot['exit_epoch'],lot['side'],-1)])
    assert len(lots)==expected['closed_lots'] and sum(v['net'] for v in lots)==expected['net']
    buckets=defaultdict(list)
    for lot in lots:
        key=tuple(lot[k] for k in ['side','entry_epoch','entry_price','exit_epoch','exit_price','reason',
            'entry_decision_epoch','exit_decision_epoch'])
        buckets[key].append(lot)
    groups=[]
    for members in buckets.values():
        row=dict(members[0]);row.update(quantity=len(members),uids=[v['uid'] for v in members],
            gross=sum(v['gross'] for v in members),fees=sum(v['fees'] for v in members),net=sum(v['net'] for v in members))
        groups.append(row)
    groups.sort(key=lambda r:(r['exit_epoch'],r['entry_epoch'],r['side'],r['uids']))
    # ----------------------------------------
    # 保存済み一分足と約定だけを同じ時間軸へ整える。
    candlepath=ROOT/'candle_1min/TOPIX/2026-09-24_Day.csv'
    with candlepath.open(encoding='utf-8-sig',newline='') as handle:
        candles=[[datetime.fromisoformat(r['time']).timestamp(),*[float(r[k]) for k in ['open','high','low','close']],
            float(r['volume']),r['volume_complete']=='true'] for r in csv.DictReader(handle)]
    inventory=[[candles[0][0],0,0]];counts={1:0,-1:0}
    for raw,t,side,delta in sorted(events):
        counts[side]+=delta;assert counts[side]>=0
        inventory.append([t,counts[1],counts[-1]])
    assert counts=={1:0,-1:0}
    data=dict(session=SESSION,method=METHOD,symbols=dict(TOPIX=dict(label='TOPIX',product='TOPIXミニ',unit='pt',
        candles=candles,groups=groups,inventory=inventory,summary=expected,lot_count=len(lots),group_count=len(groups))))
    # ----------------------------------------
    # 検証済み暗色描画部を再利用し、新提案のデータだけを埋め込む。
    source=ROOT/'work/stability120_20261017/chart_1min_20260924/chart_template.html'
    template=source.read_text(encoding='utf-8')
    template=template.replace('<option value="NK225">日経225</option>','')
    template=template.replace('ROTATE_S2_T1',METHOD)
    template=template.replace('全売買の表','比較と全40場の損益').replace('2026-09-24_Dayの売買と利確明細.html','三ポイント間隔と五ポイント追尾の比較.html')
    template=template.replace('段階トレーリングの結論と全セッション損益.html','../00120_段階トレーリング新規と利益玉の部分回転/2026-09-24_Dayの1分足と売買.html').replace('全セッションの結果','旧1pt追尾のチャート')
    template=template.replace('2026-09-24 デイ｜1分足と売買','2026-09-24 デイ｜3pt間隔・5pt追尾')
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    PUBLIC.mkdir(exist_ok=True)
    target=PUBLIC/'2026-09-24_Dayの1分足と売買.html'
    assert not target.exists()
    target.write_bytes(template.replace('__CHART_DATA__',payload).encode('utf-8'))
    save(HERE/'九月二十四日の図示元.json',dict(passed=True,lots=lots,groups=groups,summary=expected,
        candles_sha256=sha(candlepath),npz_sha256=reference['sha256'],html_sha256=sha(target),financial_replay=0))
    print(json.dumps(dict(day=expected,html=str(target.relative_to(ROOT)),lots=len(lots)),ensure_ascii=False))


if __name__=='__main__':
    main()
