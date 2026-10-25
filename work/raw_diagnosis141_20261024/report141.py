"""保存済み22条件から昼夜別の比較案を集計し、公開帳票の入力を作る。"""

import json
from pathlib import Path
from analyze141 import aggregate, read

HERE=Path(__file__).resolve().parent


def main():
    """
    機能: 個別結果を再売買せず、既知標本で選んだ昼夜切替案と新旧全50場を整理する。
    引数: なし。
    返り値: None。Mは研究内の事後選択で、未見検証とは表示しない。
    """
    result=read(HERE/('結果141_二巡統合.json' if (HERE/'結果141_二巡統合.json').exists() else '結果141.json'));comparison=read(HERE/'比較集計141.json')
    mapping={'NK225':{'M1':{'Day':'G02','Night':'G10'},'M2':{'Day':'G02','Night':'G01'}},
             'TOPIX':{'M1':{'Day':'G06','Night':'H02'},'M2':{'Day':'C33','Night':'G02'}}}
    source={(r['symbol'],r['method'],r['session']):r for r in result['rows']}
    sessions=sorted({r['session'] for r in result['rows']})
    rows=[];selected=[];names=dict(comparison['names'],M1='今回の損失削減を重視する昼夜別案',M2='異なる優先順位の昼夜別案')
    for symbol in ('NK225','TOPIX'):
        previous='S36' if symbol=='NK225' else 'C33'
        for method in ('B5',previous,'M1','M2'):
            routes=mapping[symbol].get(method,{'Day':method,'Night':method})
            selected.append(dict(symbol=symbol,method=method,label=names[method],name=names[method],day_method=routes['Day'],night_method=routes['Night']))
            for scene in sessions:
                chosen=routes[scene.split('_')[1]]
                row=dict(source[symbol,chosen,scene],method=method,component_method=chosen)
                rows.append(row)
    summary,parts=aggregate(rows,names)
    events=[]
    clocks={('NK225','2026-10-22_Night'):('2026-10-23T00:17:35+09:00',132833,'反発後に追撃。利益保護前にリスクが約3倍へ拡大'),
        ('NK225','2026-10-23_Day'):('2026-10-23T14:15:39+09:00',156839,'両市場40分上昇中の小反落を売った'),
        ('NK225','2026-10-23_Night'):('2026-10-23T23:00:02+09:00',105715,'始値票が直近反転を上書き。補完置換案は過去悪化のため未採用'),
        ('TOPIX','2026-10-22_Night'):('2026-10-23T00:17:38+09:00',125124,'反発買いは利益。初回の板支持だけでは日経との差を説明できない'),
        ('TOPIX','2026-10-23_Day'):('2026-10-23T10:17:22+09:00',49285,'売り直後に反転。午後の逆張り売りも損失を重ねた'),
        ('TOPIX','2026-10-23_Night'):('2026-10-23T22:48:52+09:00',97521,'40分上昇中の短い下向きへ売り。再進行確認を比較')}
    # ----------------------------------------
    # 比較単位が変わるため、消えた親をゼロ利益と捏造せず場全体の前後を並べる。
    for row in rows:
        if row['method']!='M1' or row['session']<'2026-10-22_Night':continue
        key=row['symbol'],row['session'];time,seq,change=clocks[key]
        old=source[row['symbol'],'S36' if row['symbol']=='NK225' else 'C33',row['session']]
        events.append(dict(session=row['session'],symbol=row['symbol'],time=time,seq=seq if seq else None,old_net=old['net'],new_net=row['net'],change=change))
    output=dict(rows=rows,summary=summary,parts=parts,selected=selected,
        comparisons=comparison['parts'],comparison_summary=comparison['summary'],names=names,
        loss_events=events,loss_event_basis='時刻は原因を調べた原板の価格時計。金額はそのセッション全体の前回手法→M1の収支。特定の玉だけの損益差ではありません。',
        selection_note='全50場は既知。M1/M2は結果を見て昼夜別に選んだ研究内比較案で、独立した未見検証ではありません。日経mini・TOPIXminiは片方向上限10枚。標準手数料込み、ラージ次正常BBOの約定模型。受信時計がないため、時刻と秒数判定は保存価格時計に基づきます。')
    (HERE/'report_data141.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for row in summary:
        if row['scope'] in ('all','new'):
            print({k:row[k] for k in ('symbol','method','scope','net','losses','avg_loss','worst','ex_top3','entries')})
    for row in events:print(row)


if __name__=='__main__':
    main()
