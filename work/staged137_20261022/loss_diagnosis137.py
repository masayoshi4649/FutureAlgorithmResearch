"""保存注文と因果特徴の読取りだけで、米前反復と追撃の損失を診断する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "work/visual_pdca129_20261020"))
import features129


def clock(value):
    """
    機能: 価格時計を日本時間で表示する。
    引数: value(float)は秒単位時刻。
    返り値: strは日本時間。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo("Asia/Tokyo")).isoformat()


def clean(value):
    """
    機能: 未知の浮動小数をJSONのnullへ変換する。
    引数: value(float)は診断数値。
    返り値: float又はNone。
    """
    return float(value) if np.isfinite(value) else None


def historical(times, mid, i):
    """
    機能: 判断以前だけの五分・二十分価格帯と方向効率を求める。
    引数: times/mid(ndarray)、i(int)は原行と判断行。
    返り値: dictは観測済み範囲。欠測は補間しない。
    """
    out = {}
    for seconds in (300, 1200):
        first = int(np.searchsorted(times, times[i]-seconds, side="left"))
        values = mid[first:i+1]
        values = values[np.isfinite(values)]
        if not len(values):
            out[str(seconds)] = None
            continue
        high, low = float(values.max()), float(values.min())
        path = np.abs(np.diff(values)).sum()
        prior_last=int(np.searchsorted(times,times[i]-30.,side='left'))
        prior=mid[first:prior_last];prior=prior[np.isfinite(prior)]
        out[str(seconds)] = dict(first_time=clock(times[first]),last_time=clock(times[i]),low=low,high=high,
            current=clean(mid[i]),change=float(values[-1]-values[0]),position=(float(values[-1])-low)/(high-low) if high>low else None,
            efficiency=float(abs(values[-1]-values[0])/path) if path else None,rows=len(values),
            prior_30s_high=float(prior.max()) if len(prior) else None,prior_30s_low=float(prior.min()) if len(prior) else None)
    return out


def order_detail(order, ready, quotes, market):
    """
    機能: 保存注文の判断・約定時刻と、その時点までの支持を取り出す。
    引数: order(ndarray)、ready/quotes(dict)、market(ndarray)は保存結果と特徴。
    返り値: dictは再生を伴わない注文診断。
    """
    fill, decision, parent, side, qty = (int(v) for v in order[:5])
    m = market[decision]
    position_side = side if int(order[7]) else -side
    return dict(fill_row=fill,decision_row=decision,fill_time=clock(ready['time_s'][fill]),
        decision_time=clock(ready['time_s'][decision]),parent=parent,side=side,quantity=qty,price=float(order[5]),
        reason=int(order[6]),new=bool(order[7]),leg=int(order[8]),fee=float(order[9]),
        decision_bid=clean(quotes['bid'][decision]),decision_ask=clean(quotes['ask'][decision]),
        decision_atr=clean(ready['atr'][decision]),known=bool(m[11]==1),peer_time=clock(m[8]) if np.isfinite(m[8]) else None,
        support=dict(own30=clean(position_side*m[4]),own120=clean(position_side*m[5]),
            peer30=clean(position_side*m[6]),peer120=clean(position_side*m[7])),
        historical=historical(ready['time_s'],ready['last'],decision))


def parent_detail(orders, ready, quotes, market):
    """
    機能: 一親の脚別損益と返済までの価格経路を保存注文から再集計する。
    引数: orders/market(ndarray)、ready/quotes(dict)は保存結果と特徴。
    返り値: dictは時刻・損益・説明用の事後順逆行。売買を作り直さない。
    """
    legs = []
    initial=orders[orders[:,7]==1][0]
    fixed_risk=max(20.,float(ready['atr'][int(initial[1])]))
    for leg in sorted(set(orders[:,8].astype(int))):
        rows=orders[orders[:,8]==leg]
        first=rows[rows[:,7]==1][0]
        side,qty,entry=int(first[3]),int(first[4]),float(first[5])
        closing=rows[rows[:,7]==0]
        gross=float(sum(side*(o[5]-entry)*o[4]*100 for o in closing))
        fees=float(rows[:,9].sum())
        i,j=int(first[0]),int(rows[-1,0])
        valid=quotes['quote_valid'][i:j+1]
        mark=(quotes['bid'] if side>0 else quotes['ask'])[i:j+1]
        good=valid&np.isfinite(mark)
        path=side*(mark[good]-entry)
        pos=np.flatnonzero(good)
        mfe=int(pos[np.argmax(path)])+i if len(path) else i
        mae=int(pos[np.argmin(path)])+i if len(path) else i
        legs.append(dict(leg=int(leg),gross=gross,fees=fees,net=gross-fees,side=side,quantity=qty,
            risk=fixed_risk,
            future_explanation_only=dict(mfe_points=float(max(path)) if len(path) else None,mae_points=float(min(path)) if len(path) else None,
                mfe_time=clock(ready['time_s'][mfe]),mae_time=clock(ready['time_s'][mae])),
            orders=[order_detail(o,ready,quotes,market) for o in rows]))
    return dict(parent=int(orders[0,2]),net=sum(x['net'] for x in legs),legs=legs)


def main():
    """
    機能: 最悪三場と最悪三追撃を事後説明用に選び、元注文を診断する。
    引数: なし。
    返り値: None。JSONとMarkdownを作成。金融再生・API・発注は行わない。
    """
    result=json.loads((HERE/'結果.json').read_text(encoding='utf8'))
    plan=json.loads((HERE/'試行計画_v3.json').read_text(encoding='utf8'))
    refs={x['session']:x for x in plan['inputs']}
    early=[];adds=[]
    for row in result['rows']:
        if row['method']=='H_RT02' and row['kind']=='Night':
            value=sum(sum(x['net'] for k,x in p['legs'].items() if int(k)>=10) for p in row['parents'])
            early.append((value,row['session']))
        if row['method']=='C02a':
            for p in row['parents']:
                if '1' in p['legs']:
                    adds.append((p['legs']['1']['net'],row['session'],p['id']))
    worst_early=sorted(early)[:3]
    worst_add=sorted(adds)[:3]
    targets=sorted(set([s for _,s in worst_early]+[s for _,s,_ in worst_add]))
    observations=[]
    for scene in targets:
        packet=pickle.loads((ROOT/refs[scene]['input']['path']).read_bytes())
        inputs=features129.prices_for(packet,'mid');key=(scene,'NK225')
        market=features129.markets(inputs)[key];ready=inputs[key];q=packet['quotes'][key]
        record=dict(session=scene,input=refs[scene]['input'])
        with np.load(HERE/'measurement'/f'{scene}.npz',allow_pickle=False) as data:
            if scene in [s for _,s in worst_early]:
                orders=data['H_RT02_early']
                record['early']=[parent_detail(orders[orders[:,2]==p],ready,q,market) for p in np.unique(orders[:,2])]
                record['early_net']=sum(p['net'] for p in record['early'])
                assert record['early_net']==next(v for v,s in worst_early if s==scene)
            if scene in [s for _,s,_ in worst_add]:
                orders=data['C02a'];ids=[p for _,s,p in worst_add if s==scene]
                record['addition']=[parent_detail(orders[orders[:,2]==p],ready,q,market) for p in ids]
                for p in record['addition']:
                    observed=next(z['net'] for z in p['legs'] if z['leg']==1)
                    assert observed==next(v for v,s,cid in worst_add if s==scene and cid==p['parent'])
        observations.append(record)
        print(scene,'保存注文診断完了',flush=True)
    output=dict(financial_replays=0,api=0,result_sha256=hashlib.sha256((HERE/'結果.json').read_bytes()).hexdigest(),
        selection='事後の失敗機構説明として米前追加収支最悪三場と追加脚収支最悪三親を選択。将来選別条件に使わない。',
        worst_early=worst_early,worst_addition=worst_add,observations=observations,
        conclusions=[
            '短期支持は直近の値動きと一致していたが、古い価格帯を抜けて定着した証拠ではない。9月28日は帯上部で買い、数分後に帯下部で売る反復になった。',
            '10月15日の元玉は180円順行しても初期R212.88円に届かず、利益追尾が起動しないまま損切りまで戻った。方向が一度も当たらなかった損失と区別する。',
            '追撃三最悪例は元玉二枚が全て黒字。後から不利な建値で三枚を加え、元玉より狭い0.5R停止で戻りを実現損にした。',
            '長い価格帯の突破、戻りで境界が保たれること、再進行の順に確認する仮説には同帯反復を抑える理屈がある。しかし9月28日21時45分は直近30秒を除く二十分高値65875円を中値65890円で上回っても負けており、突破単独では十分でない。',
            '改善案は事後最悪例からの仮説で、当該報告は修正売買の性能を検証していない。既存NV25の米前適用は別の登録試行で確認する。'])
    (HERE/'loss_diagnosis137.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    lines=['# 米国前の反復参加と追撃の損失診断','',
        '保存済み注文の再集計。金融再生0、API0。日経mini、倍率100円、手数料38.5円/枚を注文ごと切捨て。最悪例の選択・最大順行逆行は事後説明専用で、注文判定には使用しない。','',
        '## 米国前の追加参加 H_RT02','',
        '現行主担当と補完の損益を除き、米現物開始15分前までの追加担当だけを見る。短期共通支持からの反復新規が対象。','',
        '| 場 | 追加分収支 | 親数 |','|---|---:|---:|']
    for value,scene in worst_early:
        r=next(x for x in observations if x['session']==scene)
        lines.append(f'| {scene} | {value:+,.0f}円 | {len(r["early"])} |')
    lines += ['', '損失は「米国前だから」だけでは説明できない。①帯の往復を短期支持で追う、②一度順行しても追尾起動幅に届かず戻る、③後から増やした玉だけ戻りで切られる、の三つを分ける。']
    for _,scene in worst_early:
        r=next(x for x in observations if x['session']==scene)
        lines += ['',f'### {scene}','', '| 親／玉 | 判断→約定 | 方向・枚数・価格 | 返済時刻・価格・枚数 | 玉収支 |','|---|---|---|---|---:|']
        for p in r['early']:
            for leg in p['legs']:
                o=leg['orders'][0]
                exit_text=' / '.join(f'{z["fill_time"][11:19]} {z["price"]:,.0f}×{z["quantity"]}' for z in leg['orders'][1:])
                lines.append(f'| {p["parent"]}／{"元" if leg["leg"]==10 else "追加"} | {o["decision_time"][11:19]}→{o["fill_time"][11:19]} | {"買" if o["side"]>0 else "売"}{o["quantity"]}枚 {o["price"]:,.0f} | {exit_text} | {leg["net"]:+,.0f}円 |')
        lines += ['', '元玉の判断時に見えていた支持と価格帯：','']
        for p in r['early']:
            leg=p['legs'][0];o=leg['orders'][0]
            s=o['support'];f=leg['future_explanation_only'];h=o['historical']['1200']
            lines += [f'- 親{p["parent"]}、判断時支持（建玉方向、ATR比）: 日経30秒 {s["own30"]:.3f}／120秒 {s["own120"]:.3f}、TOPIX30秒 {s["peer30"]:.3f}／120秒 {s["peer120"]:.3f}。初期R={leg["risk"]:.2f}円。直前20分変化 {h["change"]:+.0f}円、帯 {h["low"]:.0f}〜{h["high"]:.0f}円。返済までの最大順行 {f["mfe_points"]:+.0f}円／逆行 {f["mae_points"]:+.0f}円（事後）。']
    lines += ['','## C02aの追撃損失三件','',
        '元玉2枚と追撃3枚を分離する。追撃条件は0.25R順行、初回後30秒以上、新しい相手観測、両市場30秒0.05ATR・120秒0.2ATR以上を15秒継続。追撃だけに0.5R停止を置く。','',
        '| 場 | 追撃判断→約定 | 方向・枚数・価格 | 追撃返済 | 追撃収支 | 元玉収支 |','|---|---|---|---|---:|---:|']
    addition_notes=[]
    for _,scene,cid in worst_add:
        r=next(x for x in observations if x['session']==scene);p=next(x for x in r['addition'] if x['parent']==cid)
        add=next(x for x in p['legs'] if x['leg']==1);core=next(x for x in p['legs'] if x['leg']==0)
        a,b=add['orders'][0],add['orders'][-1]
        lines.append(f'| {scene} | {a["decision_time"][11:19]}→{a["fill_time"][11:19]} | {"買" if a["side"]>0 else "売"}{a["quantity"]}枚 {a["price"]:,.0f} | {b["fill_time"][11:19]} {b["price"]:,.0f}×{b["quantity"]} | {add["net"]:+,.0f}円 | {core["net"]:+,.0f}円 |')
        s=a['support'];f=add['future_explanation_only'];c=core['orders'][0]
        core_exits='、'.join(f'{z["fill_time"][11:19]} {z["price"]:,.0f}円×{z["quantity"]}枚' for z in core['orders'][1:])
        addition_notes += [f'- {scene}：元玉は {c["fill_time"][11:19]} {c["price"]:.0f}円、返済は{core_exits}。追加判断時支持（建玉方向、ATR比）: 日経30秒 {s["own30"]:.3f}／120秒 {s["own120"]:.3f}、TOPIX30秒 {s["peer30"]:.3f}／120秒 {s["peer120"]:.3f}。固定R={core["risk"]:.2f}円、追撃停止幅={core["risk"]*.5:.2f}円。最大順行 {f["mfe_points"]:+.0f}円／逆行 {f["mae_points"]:+.0f}円（事後）。']
    lines += ['',*addition_notes,'','## 当時分かったことと、修正仮説','',
        '1. 9月28日18:00の買いは直前20分帯65,375〜65,500の上部、18:10の売りは65,305〜65,505の下部だった。二市場同方向でも、数分の往復の端で反応していた。短期支持の大きさを確信度と呼ぶ根拠はない。既知の価格帯を固定し、突破後の戻りで境界が保たれて再進行するまで追加しない仮説には、同じ帯の端を繰り返し追う回数を減らす理屈がある。',
        '2. ただし境界突破単独では不足する。9月28日21:45の判断中値65,890は、直近30秒を除いた20分高値65,875を上回っても、買65,900→返済65,860で−8,154円だった。また10月15日17:37の買64,700は途中180円順行したが、初期R212.88円に届かず追尾が起動せず、元玉は−42,154円。長期境界は入口の文脈であり、その後の継続と出口を保証しない。戻りを待てば取得価格が改善する可能性と、強い一方向相場を逃す可能性を両方測る必要がある。',
        '3. 追撃最悪三親の元玉はすべて黒字だった。追撃は元玉より80〜110円不利な価格で三枚を追加し、元玉より狭い0.5Rで返している。損失原因は必ずしも方向誤認でなく、途中の戻りに対する取得価格と停止線の組合せだった。直前の押し安値・戻り高値の外へ停止を置き、その距離で枚数を減らす、追撃は二枚以下にする、追撃なしの二〜三枚固定と比べる、という修正仮説が考えられる。停止を広げるだけでは真の反転時の損失が増えるため、数量と同時に比較する必要がある。',
        '4. 10月16日19:07には売り追加65,390、19:11返済65,440で−15,230円。一方、18:57の元玉65,480は同じ19:11返済65,440で＋7,846円だった。同じ出口時刻でも、後発三枚の不利な建値が先発二枚の利益を上回る。順行後の追撃は、含み益を安全余裕と見なして自動的に枚数を増やせる仕組みではない。','',
        '以上は保存された失敗機構からの仮説。修正後の売買成績をここでは計算していない。NV25の既知価格帯・戻り・再進行を米前へ適用する第二巡は別登録の比較であり、当資料の最悪三場が改善するだけでは採用根拠にならない。全場・勝ち反例・上位利益除外・無取引を併せて確認する。','',
        '時刻が同じ秒でも判断原行と約定原行は異なる。原行番号、返済判断時刻、全玉の支持値、資料指紋はJSONに保存。板中値由来の価格変化であり、注文主体の心理や補充意図を直接観測したものではない。']
    (HERE/'loss_diagnosis137.md').write_text('\n'.join(lines)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
