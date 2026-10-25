"""条件切替と参加拡大の全場会計を、短い説明と銘柄手法別帳票へ渡す。"""

import json
from pathlib import Path
from analyze142 import read,save,aggregate,add_group_metrics

HERE=Path(__file__).resolve().parent


def main():
    """
    機能: 全場を見た比較案と活動拡大型を、元会計を変えず四手法ずつ取りまとめる。
    引数: なし。
    返り値: None。全場の事後選択を未見性能と表示しない。
    """
    comparison=read(HERE/'比較集計142.json');source={(r['symbol'],r['method'],r['session']):r for r in comparison['rows']}
    sessions=sorted({r['session'] for r in comparison['rows']})
    mapping={'NK225':{'Day':'M1','Night':'J04'},'TOPIX':{'Day':'C06','Night':'C13'}}
    names=dict(comparison['names'],F1='赤字場数を重視した条件切替案')
    names['V04']='参加拡大の比較対照・安定性は悪化'
    selected=[];rows=[]
    for symbol in ('NK225','TOPIX'):
        for method in ('B5','M1','F1','V04'):
            route=mapping[symbol] if method=='F1' else {'Day':method,'Night':method}
            selected.append(dict(symbol=symbol,method=method,name=names[method],label=names[method],day_method=route['Day'],night_method=route['Night']))
            for scene in sessions:
                component=route[scene.split('_')[1]];row=source[symbol,component,scene]
                rows.append(dict(row,method=method,component_method=component))
    summary,parts=aggregate(rows,names);add_group_metrics(summary,parts,rows)
    events=[]
    for symbol,scene,time,seq,text in (
        ('NK225','2026-10-23_Night','2026-10-23T23:00:02+09:00',105715,'始値票と反対に双方5分・20分・120秒が揃った時だけ買いへ切替。方向切替の改善はこの1夜に集中。'),
        ('NK225','2026-09-29_Night','2026-09-29T23:02:50+09:00',74315,'短い反落中も20分支持を維持。以前の一律早期返済で失った勝ちを残した。'),
        ('NK225','2026-09-29_Day','2026-09-29T13:23:49+09:00',99791,'巡回P04は狭い往復に反復参加。短期支持は入口に実在したが、気配差を繰り返し負担。'),
        ('NK225','2026-10-13_Day','2026-10-13T12:54:16+09:00',100920,'巡回の中期支持と板支持が一致しても小往復の端で買い。保有状態の維持と再参加回復を第三巡で比較。'),
        ('NK225','2026-09-28_Night','2026-09-28T22:51:40+09:00',None,'巡回の短期は両市場下向きでも20分・平均位置は不一致。短期一致を市場全体方向とみなさない。'),
        ('TOPIX','2026-10-23_Day','2026-10-23T10:17:22+09:00',49285,'旧主担当は売りの直後に反転。巡回追加だけでは安定性を改善できず、全場の副作用を残した。')):
        new=next(r for r in rows if r['symbol']==symbol and r['session']==scene and r['method']=='F1')
        old=source[symbol,'M1',scene]
        events.append(dict(symbol=symbol,session=scene,time=time,seq=seq,old_net=old['net'],new_net=new['net'],change=text))
    note='全50場は既知開発。F1の昼夜構成は全結果を見た比較案。日経mini/TOPIXmini・片方向最大10枚・標準手数料後・ラージ次正常BBO代理。独立受信時計はなく、秒数は保存価格時計基準。保有率はDay420分/Night780分を各場の分母にした単純平均。約50%は目安で無動意の強制保有はしない。'
    output=dict(rows=rows,summary=summary,parts=parts,selected=selected,names=names,
        comparisons=comparison['parts'],comparison_summary=comparison['summary'],loss_events=events,
        loss_event_basis='時刻は原因を確認した原行の価格時計。併記額は当該玉の差ではなく、セッション全体の前回M1→条件切替F1。巡回P04の診断事例をF1の約定とは読み替えない。',selection_note=note)
    save('report_data142.json',output)
    for r in summary:
        if r['scope']=='all':print({k:r[k] for k in ('symbol','method','profit','loss','net','losses','avg_loss','worst','ex_top3','mean_holding_ratio','avg_held_quantity')})


if __name__=='__main__':
    main()
