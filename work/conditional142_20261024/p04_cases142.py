"""P04赤字上位3場の損失連鎖を元の板原文と判断特徴へ接続する。"""

import json
import pickle
import numpy as np
import run142
import patrol_features142
from loss_raw141 import snapshot,clean
from implementation_audit141 import stamp

HERE,ROOT=run142.HERE,run142.ROOT


def main():
    """
    機能: 指定した損失連鎖の全新規・返済判断を両市場の当時原板へ接続する。
    引数: なし。
    返り値: None。売買再生なしで原文行番号・SHA・板・特徴の診断JSONを保存する。
    """
    source=json.loads((HERE/'P04追いかけ出口中期支持と反復損失142_v2.json').read_text(encoding='utf8'))
    selected={'2026-09-29_Day':range(28,44),'2026-10-13_Day':range(19,31),'2026-09-28_Night':range(17,32)}
    packets,_,_=run142.first.material();out=[]
    for scene,ids in selected.items():
        item=next(p for p in packets if p['session']==scene);packet=pickle.loads((ROOT/item['path']).read_bytes())
        original,inputs,_,history=run142.prepared(packet);data=patrol_features142.prepare(packet,original)
        raw={}
        for symbol in ('NK225','TOPIX'):
            with np.load(ROOT/'work/raw_diagnosis141_20261024/raw_features'/f'{symbol}_{scene}.npz') as z:raw[symbol]={k:z[k] for k in z.files}
        r=inputs[scene,'NK225'];peer=inputs[scene,'TOPIX'];a=data['NK225']['features'];h=history[scene,'NK225'];ph=history[scene,'TOPIX']
        for parent in source['records']:
            if parent['symbol']!='NK225' or parent['session']!=scene or parent['parent'] not in ids:continue
            p=dict(parent,decisions={})
            for name,row in (('entry',parent['decision_row']),('exit',parent['exit_decision_row'])):
                time=r['time_s'][row];pi=int(np.searchsorted(peer['time_s'],time,side='left')-1)
                assert pi>=0
                p['decisions'][name]=dict(price_clock=stamp(time),row=row,features36=a[row],history15=h[row],
                    own=snapshot(raw['NK225'],int(r['seq'][row])),peer=snapshot(raw['TOPIX'],int(peer['seq'][pi])),
                    peer_history15=ph[pi],peer_price_clock=stamp(peer['time_s'][pi]),
                    own_mid_vs_mean20=float(a[row,10]-h[row,1]),peer_mid_vs_mean20=float(a[row,19]-ph[pi,1]))
            out.append(p)
        print(scene,'原板接続',flush=True)
    with (HERE/'P04最大赤字3場の原板付き損失連鎖142.json').open('x',encoding='utf8') as f:
        json.dump(clean(dict(financial_replays=0,API=0,records=out,limitations=['原板数量変化は参加者の意図や約定/取消を識別しない。','未来中値を新規判定に用いず、保存済み損失を事後診断する。'])),f,ensure_ascii=False,indent=2,allow_nan=False)


if __name__=='__main__':main()
