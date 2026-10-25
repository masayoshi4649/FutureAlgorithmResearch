"""確定M1の追加三場を、保存注文の同じ入口と変化した入口へ分けて再会計する。"""

import hashlib
import json
import pickle
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'work/aggressive140_20261024'
sys.path.insert(0,str(OLD))
from diagnose_changes140 import parents


def read(path):
    """
    機能: 保存済みJSONを読み込む。
    引数: path(Path)は入力位置。
    返り値: dict/listは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def identity(parent, seq):
    """
    機能: 状態更新で変わる親番号を使わず、役割と初回判断の原板行で接続する。
    引数: parent(dict)は親会計、seq(ndarray)は原行番号対応。
    返り値: tuple[str,int,int]は役割・原行0始まり・売買方向。
    """
    return ('追加' if parent['parent']>=3_000_000 else '主担当',
            int(seq[parent['entry_source']]),parent['side'])


def describe(parent, seq):
    """
    機能: 保存注文へ初回と各判断の原行番号を付ける。
    引数: parent(dict)は親会計、seq(ndarray)は原行番号対応。
    返り値: dictは接続根拠を含む会計。
    """
    p = dict(parent)
    p['role'],p['first_decision_seq0'],_ = identity(parent,seq)
    p['orders'] = [dict(o,decision_seq0=int(seq[o['source']]),fill_seq0=int(seq[o['row']]))
                   for o in parent['orders']]
    return p


def main():
    """
    機能: 旧S36/C33とM1の保存注文を独立会計し、追加三場の寄与を保存する。
    引数: なし。
    返り値: None。売買判断は一切再生せず、既存集計との一致を検査する。
    """
    rows = {(r['symbol'],r['session'],r['method']):r for r in read(HERE/'結果141_二巡統合.json')['rows']}
    reported = {(r['symbol'],r['session'],r['method']):r for r in read(HERE/'report_data141.json')['rows']}
    result=[]
    for item in read(OLD/'inputs/input_manifest.json')['packets']:
        scene = item['session']
        path = ROOT/item['path']
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==item['sha256']
        packet = pickle.loads(raw)
        for symbol in ('NK225','TOPIX'):
            old_id = 'S36' if symbol=='NK225' else 'C33'
            new_id = ('G02' if scene.endswith('_Day') else 'G10') if symbol=='NK225' else ('G06' if scene.endswith('_Day') else 'H02')
            ready = packet['inputs'][scene,symbol]
            with np.load(HERE/'results/measurement'/f'{symbol}_{scene}.npz') as z:
                before=z[old_id].copy()
                after=z[new_id].copy() if new_id in z.files else None
            if after is None:
                with np.load(HERE/'round2/measurement'/f'{symbol}_{scene}.npz') as z:
                    after=z[new_id].copy()
            b = {identity(p,ready['seq']):describe(p,ready['seq']) for p in parents(before,symbol,ready['time_s']).values()}
            a = {identity(p,ready['seq']):describe(p,ready['seq']) for p in parents(after,symbol,ready['time_s']).values()}
            same=[dict(old=b[k],new=a[k],delta=a[k]['net']-b[k]['net']) for k in sorted(b.keys()&a.keys())]
            removed=[b[k] for k in sorted(b.keys()-a.keys())]
            added=[a[k] for k in sorted(a.keys()-b.keys())]
            old_net=sum(p['net'] for p in b.values())
            new_net=sum(p['net'] for p in a.values())
            assert abs(old_net-rows[symbol,scene,old_id]['net'])<1e-6
            assert abs(new_net-rows[symbol,scene,new_id]['net'])<1e-6
            assert abs(new_net-reported[symbol,scene,'M1']['net'])<1e-6
            parts=dict(same=sum(x['delta'] for x in same),removed=-sum(p['net'] for p in removed),added=sum(p['net'] for p in added))
            assert abs(sum(parts.values())-(new_net-old_net))<1e-6
            item=dict(symbol=symbol,session=scene,old_method=old_id,new_method=new_id,
                      old_net=old_net,new_net=new_net,delta=new_net-old_net,parts=parts,
                      old_parents=len(b),new_parents=len(a),same=same,removed=removed,added=added)
            result.append(item)
            print(f'\n{symbol} {scene}: {old_id} {old_net:+,.0f} -> {new_id} {new_net:+,.0f} | {parts}')
            for label,group in [('同一入口旧',[x['old'] for x in same if x['delta']]),
                                ('同一入口新',[x['new'] for x in same if x['delta']]),('消失',removed),('新出現',added)]:
                for p in group:
                    orders='; '.join(f"{o['time']} {'新' if o['new'] else '返'}{'買' if o['side']>0 else '売'}{o['quantity']} @{o['price']:g} 理由{o['reason']}" for o in p['orders'])
                    print(f"{label} {p['role']} 原行{p['first_decision_seq0']} {p['net']:+,.0f}: {orders}")
    (HERE/'M1追加三場の保存注文寄与141.json').write_text(
        json.dumps(dict(新金融再生=0,照合='役割と初回判断原板0始まり行と売買方向',sessions=result),ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
