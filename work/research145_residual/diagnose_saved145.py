"""保存済み約定の改善・悪化箇所を、原板行に結び付けて抽出する。"""

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pickle
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TZ = timezone(timedelta(hours=9))
CASES = [('P01','2026-10-13_Day'), ('P01','2026-10-20_Day'),
         ('P01','2026-09-28_Day'), ('P02','2026-10-22_Day'),
         ('R06','2026-09-29_Day'), ('R06','2026-10-15_Day'),
         ('R04','2026-10-19_Day'), ('R09','2026-09-29_Day')]


def main():
    """保存約定と原板のSHAを検査して、比較対象の親注文を抽出する。

    引数: なし。
    返り値: None。金融再生・手法変更・会計再計算は実行しない。
    """
    accounts=json.loads((HERE/'残玉と部分利確後の全場結果145.json').read_text(encoding='utf-8'))
    index={(r['method'],r['session']):r for r in accounts['rows']}
    cases=[]
    for method,scene in CASES:
        with (ROOT/'work/research145_engine/cache'/f'{scene}.pkl').open('rb') as stream:
            packet,data,raw,baseline,label=pickle.load(stream)
        rawdata=np.load(ROOT/'work/raw_diagnosis141_20261024/raw_features'/f'NK225_{scene}.npz')
        orders=np.load(HERE/'orders'/f'{scene}.npz')
        traces=np.load(HERE/'traces'/f'{scene}.npz')
        clock=data['ready']['time_s']
        source=Path(str(rawdata['source_path']))
        snapshots={}

        def snap(row):
            """原板の一行をSHA照合して抽出する。

            引数: row(int)は準備済み入力の行番号。
            返り値: dictは原板証跡と当時の価格・公開特徴。
            """
            row=int(row)
            if row in snapshots:
                return snapshots[row]
            seq=int(data['ready']['seq'][row])
            offset=int(rawdata['byte_offset'][seq]); length=int(rawdata['byte_length'][seq])
            with source.open('rb') as stream:
                stream.seek(offset); content=stream.read(length)
            assert hashlib.sha256(content).digest()==rawdata['line_sha256'][seq].tobytes()
            body=json.loads(content)
            item=dict(row=row,raw_seq0=seq,line_number=int(rawdata['line_no'][seq]),
                      byte_offset=offset,line_sha256=hashlib.sha256(content).hexdigest(),
                      price_clock=datetime.fromtimestamp(clock[row],TZ).isoformat(),
                      bid=float(data['quotes']['bid'][row]),ask=float(data['quotes']['ask'][row]),
                      own30=float(data['features'][row,12]) if np.isfinite(data['features'][row,12]) else None,
                      own120=float(data['features'][row,13]) if np.isfinite(data['features'][row,13]) else None,
                      raw=body)
            snapshots[row]=item
            return item

        def events(array):
            """保存約定を人が追える時刻・方向・数量に変換する。

            引数: array(ndarray)は対象親の保存約定。
            返り値: list[dict]は約定明細。
            """
            result=[]
            for order in array:
                fill,decision,parent,side,qty,price,reason,new,uid,fee=order
                fill=int(fill); decision=int(decision)
                snap(decision);snap(fill)
                result.append(dict(fill_row=fill,decision_row=decision,
                    fill_price_clock=datetime.fromtimestamp(clock[fill],TZ).isoformat(),
                    decision_price_clock=datetime.fromtimestamp(clock[decision],TZ).isoformat(),
                    action='新規' if new else '返済',side='買' if side>0 else '売',
                    quantity=int(qty),price=float(price),reason=int(reason),uid=int(uid)))
            return result

        changes=[]
        for role in ('CG','CS'):
            old=orders[role+'_R00'];new=orders[role+'_'+method]
            ids=sorted(set(old[:,2])|set(new[:,2]))
            for parent in ids:
                a=old[old[:,2]==parent];b=new[new[:,2]==parent]
                if np.array_equal(a,b):
                    continue
                oldnet=-float(np.sum(a[:,3]*a[:,4]*a[:,5])*100)
                newnet=-float(np.sum(b[:,3]*b[:,4]*b[:,5])*100)
                trace=traces[role+'_'+method]
                selected=trace[trace[:,1]==parent]
                traceitems=[]
                for record in selected:
                    traceitems.append(dict(row=int(record[0]),price_clock=snap(record[0])['price_clock'],
                        kind=int(record[2]),reason=int(record[5]),quantity=int(record[4]),
                        realized=float(record[7]),fixed_r=float(record[9]),best=float(record[11])))
                changes.append(dict(role=role,parent=int(parent),baseline_net=oldnet,variant_net=newnet,
                    difference=newnet-oldnet,baseline=events(a),variant=events(b),trace=traceitems))
        old=index['R00',scene];new=index[method,scene]
        case=dict(method=method,session=scene,baseline_net=old['net'],variant_net=new['net'],
                  difference=new['net']-old['net'],changes=changes,
                  raw_source=str(source),snapshots=list(snapshots.values()))
        cases.append(case)
        print(method,scene,'全場',int(old['net']),int(new['net']),'差',int(case['difference']))
        for change in changes:
            print(' ',change['role'],'親',change['parent'],'差',int(change['difference']))
            for label,rows in [('基準',change['baseline']),('比較',change['variant'])]:
                print('   ',label,[(e['fill_price_clock'][11:19],e['action'],e['side'],e['quantity'],e['price'],e['reason']) for e in rows])
    (HERE/'改善悪化の原板時刻診断145.json').write_text(json.dumps(dict(
        cases=cases,financial_replays=0,
        limitation='時刻は原板の価格時刻。独立した受信時計はない。判定と約定が同秒でも原板の先後行は厳密に分離。'),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':
    main()
