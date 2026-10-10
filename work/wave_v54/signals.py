"""銘柄名を使わず、固定した境界の定着と突破失敗を排他的に判定する。"""

from __future__ import annotations

import numpy as np
import pandas as pd


POLICIES = [('F','定着だけを追う'),('R','突破失敗だけを戻す'),('S','観測した状態で両者を選ぶ')]
GATES = [(0,'価格だけ'),(1,'指値供給を確認'),(2,'出来高活動を確認'),(3,'供給と活動を確認')]
MAIN = 'S3_T'
DECISION_COLUMNS = ['raw_index','side','stop','atr_fixed','line','kind','center','planned_risk','event_id']


def finite(*values: float) -> bool:
    """機能: 必要な数値が既に観測可能か確認する。

    引数: values(float可変長)。返り値: 全値が有限(bool)。
    """
    return all(np.isfinite(v) for v in values)


def events(frame: pd.DataFrame, tick: float) -> list[dict]:
    """機能: 固定された20分線を越えた一つの事件を、一度だけ分類する。

    引数: frame(DataFrame:当場の公開済み情報)、tick(float:呼値)。
    返り値: 事件の終了・分類・見送り記録(list[dict])。
    t0を外側確定の1本目とする。線・尺度・平均回帰点・板基準をt0で固定する。
    """
    active, output = None, []
    previous_bar = None
    serial = 0
    for row in frame.itertuples():
        contiguous = previous_bar is None or row.bar_start-previous_bar == 60.
        previous_bar = row.bar_start
        if active is not None and (not contiguous or not row.can_trade or row.time_s>active['deadline']):
            output.append(dict(**active,end_time=float(row.time_s),end_seq=int(row.seq),kind=0,side=0,
                               result='足の欠落・準備不足' if not contiguous or not row.can_trade else '10分で未確定'))
            active = None
            continue
        if not row.can_trade:
            continue
        if active is None:
            if not finite(row.prior20_high,row.prior20_low,row.atr5) or row.atr5<=0:
                continue
            d = 1 if row.close>row.prior20_high+.1*row.atr5 else -1 if row.close<row.prior20_low-.1*row.atr5 else 0
            if not d:
                continue
            serial += 1
            active = dict(event_id=serial,start_time=float(row.time_s),start_bar=float(row.bar_start),start_seq=int(row.seq),
                          deadline=float(row.time_s+600),direction=d,
                          line=float(row.prior20_high if d>0 else row.prior20_low),atr=float(row.atr5),
                          center=float((row.prior20_high+row.prior20_low)/2),
                          extreme=float(row.high if d>0 else row.low),outside_count=1,
                          supply_scale=float(row.past20_supply_abs_median),volume_scale=float(row.past20_volume_median),
                          scale_count=int(row.past20_valid_count))
            continue
        # ----------------------------------------
        # 極値は分類した足まで更新する。後から発生した高安を失敗線へ混ぜない。
        d,a,line = active['direction'],active['atr'],active['line']
        active['extreme'] = max(active['extreme'],row.high) if d>0 else min(active['extreme'],row.low)
        distance = d*(row.close-line)
        active['outside_count'] = active['outside_count']+1 if distance>.1*a else 0
        kind = -1 if distance<-.1*a else 1 if active['outside_count']>=2 else 0
        if not kind:
            continue
        side = d*kind
        stop = line-d*.1*a if kind==1 else active['extreme']+d*.1*a
        planned_risk = side*(row.last-stop)
        room = side*(active['center']-row.last)
        geometry = finite(planned_risk) and 2*tick<=planned_risk<=.75*a
        if kind==-1:
            geometry = geometry and room>=2*planned_risk
        supply_scale,volume_scale = active['supply_scale'],active['volume_scale']
        supply_ok = bool(row.minute_valid) and finite(row.minute_supply_norm,supply_scale) and supply_scale>0 and side*row.minute_supply_norm>=supply_scale
        activity_ok = bool(row.minute_valid) and finite(row.minute_volume,volume_scale) and volume_scale>0 and row.minute_volume>=volume_scale
        output.append(dict(**active,end_time=float(row.time_s),end_seq=int(row.seq),source_seq=int(row.source_last_seq),
                           raw_index=int(row.ready_index),kind=kind,side=side,stop=float(stop),planned_risk=float(planned_risk),
                           room=float(room),geometry=bool(geometry),supply_ok=bool(supply_ok),activity_ok=bool(activity_ok),
                           supply_value=float(row.minute_supply_norm),volume_value=float(row.minute_volume),
                           result='候補確定' if geometry else '反証線から遠い・狭すぎる・回帰余地不足'))
        # ----------------------------------------
        # 確認や保有状況で注文しなくても、この事件を別の未来時点で再利用しない。
        active = None
    if active is not None:
        output.append(dict(**active,end_time=float(frame.time_s.iloc[-1]),end_seq=int(frame.seq.iloc[-1]),kind=0,side=0,result='末尾で観測継続中'))
    return output


def decisions(records: list[dict], policy: str, gate: int) -> np.ndarray:
    """機能: 同じ事件分類から、方向政策と単独の確認部品の対照を作る。

    引数: records(list[dict])、policy(str:F/R/S)、gate(int:0/1/2/3)。
    返り値: 次行発注器向けの指示(ndarray)。銘柄名・成績を条件に使わない。
    """
    output = []
    for r in records:
        if not r['kind'] or not r['geometry']:
            continue
        if policy=='F' and r['kind']!=1 or policy=='R' and r['kind']!=-1:
            continue
        if gate&1 and not r['supply_ok'] or gate&2 and not r['activity_ok']:
            continue
        output.append([r['raw_index'],r['side'],r['stop'],r['atr'],r['line'],r['kind'],r['center'],r['planned_risk'],r['event_id']])
    return np.asarray(output,float).reshape(-1,len(DECISION_COLUMNS))


def methods() -> list[dict]:
    """機能: 共通主案と、部品の役割を調べる14条件を成績と無関係に定義する。

    引数: なし。返り値: 固定条件(list[dict])。
    """
    output = []
    for policy,name in POLICIES:
        for gate,label in GATES:
            output.append(dict(id=f'{policy}{gate}_T',policy=policy,gate=gate,exit='T',name=name+'・'+label,
                               main=policy=='S' and gate==3))
    for gate in (0,3):
        output.append(dict(id=f'S{gate}_F',policy='S',gate=gate,exit='F',name='状態選択・'+GATES[gate][1]+'・2R固定利確',main=False))
    return output
