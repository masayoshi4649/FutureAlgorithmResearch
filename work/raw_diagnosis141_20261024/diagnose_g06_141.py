"""G06の悪化三場を、同じ入口の出口差と新たに採用された親へ分解する。"""

import hashlib
import json
import pickle
import sys
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=ROOT/'work/aggressive140_20261024'
sys.path.insert(0,str(OLD))
from diagnose_changes140 import parents
import active140_v2 as active


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は位置。
    返り値: dict/listは内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def identity(parent, force_add=False):
    """
    機能: 出口変更で連番がずれた親を、役割と新規判断原行で照合する。
    引数: parent(dict)、force_add(bool)は親と単独追加列の指定。
    返り値: tupleは役割・新規判断原行・方向・初回枚数。
    """
    o=parent['orders'][0]
    return ('追加' if force_add or parent['parent']>=3_000_000 else 'B5',o['source'],o['side'],o['quantity'])


def describe(parent, features):
    """
    機能: 親の入口時に公開済みの長短方向を添付する。
    引数: parent(dict)、features(ndarray)は親と当時特徴。
    返り値: dictは方向情報を加えた親。
    """
    result=dict(parent);i=parent['entry_source'];a=features[i]
    result['entry_context']=dict(own40=float(a[4]),peer40=float(a[15]),own30=float(a[12]),peer30=float(a[20]),
                                 efficiency=float(a[2]),both40_opposite=bool(parent['side']*a[4]<0 and parent['side']*a[15]<0))
    return result


def main():
    """
    機能: 保存結果の悪化上位三場を寄与分解し、同方向の再失敗を列挙する。
    引数: なし。
    返り値: None。新条件を金融再生せず、観測された再入場だけを記述する。
    """
    results=read(HERE/'結果141.json')
    rows={(r['session'],r['method']):r for r in results['rows'] if r['symbol']=='TOPIX'}
    scenes=sorted({s for s,m in rows})
    ranked=sorted((rows[s,'G06']['net']-rows[s,'C33']['net'],s) for s in scenes)[:3]
    packets={x['session']:x for path in (OLD/'known_manifest140.json',OLD/'inputs/input_manifest.json') for x in read(path)['packets']}
    details=[]
    lines=['# G06早期退出の副作用：悪化上位三場','',
        '保存注文の分解。新金融再生0。親IDは再準備で変わるため、同じ役割・入口判断原行・方向・初回枚数で照合した。',
        '「両市場40分逆方向の継続」は、新規時点までの特徴だけから観測する。ここでは停止条件を実装せず、禁止した場合の損益を算出しない。','']
    for delta,scene in ranked:
        item=packets[scene];path=ROOT/item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        packet=pickle.loads(path.read_bytes());ready=packet['inputs'][scene,'TOPIX'];times=ready['time_s']
        features=active.prepare(packet,40)['TOPIX']['features']
        with np.load(HERE/'results/measurement'/f'TOPIX_{scene}.npz') as z:
            before=parents(z['C33'],'TOPIX',times);after=parents(z['G06'],'TOPIX',times)
            new_standalone=parents(z['A_G06'],'TOPIX',times)
        split='round2_known' if scene<'2026-10-22_Night' else 'round2_new'
        with np.load(OLD/split/'measurement'/f'TOPIX_{scene}.npz') as z:
            original_standalone=parents(z['A33'],'TOPIX',times)
        b={identity(p):describe(p,features) for p in before.values()}
        a={identity(p):describe(p,features) for p in after.values()}
        original_add={identity(p,True) for p in original_standalone.values()}
        new_add={identity(p,True) for p in new_standalone.values()}
        common=[];added=[];removed=[]
        for key in b.keys()&a.keys():
            common.append(dict(old=b[key],new=a[key],delta=a[key]['net']-b[key]['net']))
        for key in a.keys()-b.keys():
            why='早期退出後にB5の先着採用が増加' if key[0]=='B5' else ('旧単独にも存在した追加候補が先着採用へ' if key in original_add else '早期退出で再準備した追加担当の新取引')
            added.append(dict(why=why,delta=a[key]['net'],parent=a[key]))
        for key in b.keys()-a.keys():
            why='新しい先着保有により見送り' if key in new_add else '早期退出後の状態変化で旧入口が消失'
            if key[0]=='B5':why='新しい先着保有によりB5見送り'
            removed.append(dict(why=why,delta=-b[key]['net'],parent=b[key]))
        parts=dict(same_entry_exit_change=sum(x['delta'] for x in common),
            newly_adopted_base=sum(x['delta'] for x in added if x['parent']['parent']<3_000_000),
            newly_adopted_extra=sum(x['delta'] for x in added if x['parent']['parent']>=3_000_000),
            removed_old=sum(x['delta'] for x in removed))
        assert abs(sum(parts.values())-delta)<1e-6
        # ----------------------------------------
        # 同方向の直前損失と現在入口の間に、二市場の長い逆向きが解消した観測があるか。
        extra=sorted((p for p in a.values() if p['parent']>=3_000_000),key=lambda p:p['entry_row'])
        repeats=[]
        for p in extra:
            prior=[x for x in extra if x['side']==p['side'] and x['net']<0 and x['exit_row']<p['entry_source']]
            if not prior:continue
            last=max(prior,key=lambda x:x['exit_row'])
            lo,hi=last['exit_row'],p['entry_source']
            known=np.isfinite(features[lo:hi+1,4])&np.isfinite(features[lo:hi+1,15])
            still=(p['side']*features[lo:hi+1,4]<0)&(p['side']*features[lo:hi+1,15]<0)
            resolved=np.flatnonzero(known&~still)
            repeats.append(dict(previous_parent=last['parent'],previous_net=last['net'],
                current_parent=p['parent'],current_net=p['net'],entry=p['orders'][0],
                entry_context=p['entry_context'],first_resolution_row=int(lo+resolved[0]) if len(resolved) else None,
                both_opposite_without_resolution=bool(not len(resolved) and known.all())))
        detail=dict(session=scene,old_net=rows[scene,'C33']['net'],new_net=rows[scene,'G06']['net'],delta=delta,
            old_parents=len(before),new_parents=len(after),parts=parts,common=common,added=added,removed=removed,
            chronological_new=sorted(a.values(),key=lambda p:p['entry_row']),same_direction_repeats=repeats)
        details.append(detail)
        lines += [f'## {scene}','',f'C33 {detail["old_net"]:+,.0f}円 → G06 {detail["new_net"]:+,.0f}円（差 {delta:+,.0f}円）、親数 {len(before)}→{len(after)}。',
            f'寄与: 同じ入口の出口差 {parts["same_entry_exit_change"]:+,.0f}円、新採用B5 {parts["newly_adopted_base"]:+,.0f}円、新採用追加 {parts["newly_adopted_extra"]:+,.0f}円、消えた旧親の差引 {parts["removed_old"]:+,.0f}円。','',
            '|G06親|役割|方向|新規→最終返済|建値→返済値|枚数|手数料後|入口の自/他40分差|最後の返済理由|','|---:|---|---|---|---|---:|---:|---|---:|']
        for p in detail['chronological_new']:
            first,last=p['orders'][0],p['orders'][-1];c=p['entry_context']
            lines.append(f'|{p["parent"]}|{"追加" if p["parent"]>=3000000 else "B5"}|{"買" if p["side"]>0 else "売"}|{first["time"]}→{last["time"]}|{first["price"]:g}→{last["price"]:g}|{p["quantity"]}|{p["net"]:+,.0f}|{c["own40"]:g}/{c["peer40"]:g}|{last["reason"]}|')
        lines += ['', '|同じ入口|旧返済・旧収支|新返済・新収支|差|','|---|---|---|---:|']
        for x in common:
            if x['delta']==0:continue
            p,n=x['old'],x['new']
            lines.append(f'|{p["orders"][0]["time"]} {"買" if p["side"]>0 else "売"}|{p["orders"][-1]["time"]} {p["net"]:+,.0f}円|{n["orders"][-1]["time"]} {n["net"]:+,.0f}円|{x["delta"]:+,.0f}|')
        lines += ['', '|直前の同方向負け親→再参加親|今回収支|二市場40分の逆向きが一度も解消せず|','|---|---:|---|']
        for x in repeats:
            lines.append(f'|{x["previous_parent"]}→{x["current_parent"]} / {x["entry"]["time"]}|{x["current_net"]:+,.0f}|{"継続" if x["both_opposite_without_resolution"] else "解消あり又は欠測"}|')
    report=dict(purpose='G06悪化の保存注文分解。新金融再生0。',sessions=details)
    (HERE/'G06悪化三場の寄与分解141.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (HERE/'G06悪化三場の寄与分解141.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ('session','old_net','new_net','delta','parts')} for r in details],ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
