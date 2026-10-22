"""保存監査の所有写しから追加一場の両建て損失を算術分解する。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from io import BytesIO
import hashlib
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
OWNED=HERE/'result/owned'
JST=timezone(timedelta(hours=9))


def clock(value: float) -> str:
    """
    機能: 保存価格時計を日本時間の可読文字列へ変換する。
    引数: value(float)はUNIX秒。
    返り値: strは日本時間ISO8601。
    """
    return datetime.fromtimestamp(value,JST).isoformat()


def main() -> None:
    """
    機能: 両側上限到達・固定建値差・最悪売り玉を所有copyだけで示す。
    引数: なし。
    返り値: None。金融・原市場・正式sourceの変更は行わない。
    """
    data=json.loads((OWNED/'完成結果.json').read_text(encoding='utf-8'))
    scene='2026-10-19_Day'
    rows={(r['symbol'],r['session'],r['method']):r for r in data['rows']}
    row=rows['TOPIX',scene,'O00'];ledger=row['reference']['ledger_id']
    path=OWNED/f'TOPIX_{scene}.npz';payload=path.read_bytes()
    reference=next(r for r in data['cache'] if r['symbol']=='TOPIX' and r['session']==scene)
    assert hashlib.sha256(payload).hexdigest()==reference['sha256']
    with np.load(BytesIO(payload),allow_pickle=False) as saved:
        orders=saved[ledger+'__orders'].copy();proxy=saved[ledger+'__proxy_lots'].copy()
    long=orders[orders[:,2]==1];short=orders[orders[:,2]==-1]
    assert len(long)==len(short)==10 and len(orders)==len(proxy)==20
    long_count=np.cumsum(orders[:,2]==1);short_count=np.cumsum(orders[:,2]==-1)
    at=int(np.flatnonzero((long_count==10)&(short_count==10))[0]);last=orders[at]
    buy_average=float(long[:,7].mean());sell_average=float(short[:,7].mean())
    fixed_basis=float((short[:,7].sum()-long[:,7].sum())*1000)
    context=row['context'];spread=context['reference_ask']-context['reference_bid']
    spread_cost=10*spread*1000;fees=20*82;net=fixed_basis-spread_cost-fees
    assert buy_average==4040.2 and sell_average==4029.85
    assert fixed_basis==-103500 and spread_cost==5000 and fees==1640 and net==row['net']==-110140
    worst=min((p for p in proxy if p[1]==-1),key=lambda p:p[12])
    entry=next(o for o in orders if o[0]==worst[0])
    worst_record=dict(uid=int(worst[0]),side='売り',rung=int(worst[2]),quantity=1,
        decision_at=clock(entry[5]),entry_at=clock(entry[6]),entry_price=float(worst[6]),
        reference_at=clock(worst[8]),scheduled_exit_at=clock(worst[13]),exit_ask=float(worst[9]),
        gross=float(worst[10]),fees=float(worst[11]),net=float(worst[12]),
        注意='返済は引け前六分以内の最終正常askを使う代理会計。実引け約定ではない。')

    # ----------------------------------------
    # O01の全差が追加一場だけなのかを、全41場の保存小会計で確認する。
    differences=[]
    for symbol in ('TOPIX','NK225'):
        details=[]
        for session in data['sessions']:
            base=rows[symbol,session,'O00'];changed=rows[symbol,session,'O01']
            if changed['net']!=base['net'] or changed['entries']!=base['entries']:
                details.append(dict(session=session,net_difference=changed['net']-base['net'],
                    baseline_entries=base['entries'],changed_entries=changed['entries']))
        assert len(details)==1 and details[0]['session']==scene
        differences.append(dict(symbol=symbol,different_sessions=len(details),sessions=details))
    result=dict(passed=True,session=scene,symbol='TOPIX',method='O00',equivalent_previous_method='I3_G3',
        source_cache=dict(path=str(path.relative_to(HERE.parent)),sha256=reference['sha256'],ledger_id=ledger),
        saturation=dict(first_full_raw_row=int(last[4]),first_full_at=clock(last[6]),completed_by_uid=int(last[0]),
            completed_by_side='買い' if last[2]==1 else '売り',completed_by_side_quantity=10,long=10,short=10,
            buy_average=buy_average,sell_average=sell_average,
            同じ行に成立した両方向の処理順='保存注文順で最後に10枚となった方向を記す。価格時計は真受信時計ではない。'),
        fixed_identity=dict(sell_basis_minus_buy_basis=fixed_basis,terminal_bid=context['reference_bid'],
            terminal_ask=context['reference_ask'],terminal_spread=spread,spread_liability=spread_cost,
            fees=fees,net=net,equation='−103,500 − 5,000 − 1,640 = −110,140円'),
        worst_short=worst_record,O01_difference=differences,financial_replay=0,original_market_reads=0,
        限界='同枚数をその後固定保持した在庫の恒等式。将来の相場に関係なく全戦略が固定赤字という証明ではない。')
    target=HERE/'TOPIX追加一場の両側上限と固定損失.json'
    assert not target.exists();target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    note=f'''# TOPIX・2026-10-19デイの損失原因

O00（初回3pt・追加3pt、途中返済なし）は、**{clock(last[6])}**に{'買い' if last[2]==1 else '売り'}の10枚目が入って、買い10枚・売り10枚になりました。

買い平均は**{buy_average:,.2f}**、売り平均は**{sell_average:,.2f}**。買いを高く、売りを安く抱えたため、この後どちらへ動いても同じ10枚ずつの値動きは相殺され、建値差の**−103,500円**が残ります。終端の気配差0.5pt×10枚＝5,000円と往復料1,640円を加え、**−110,140円**です。

最も負けた売り1枚は**{worst_record['entry_at']}に{worst_record['entry_price']:,.1f}で売り**。終端代理の**{worst_record['reference_at']}のask {worst_record['exit_ask']:,.1f}**で返済すると、値幅損{worst_record['gross']:,.0f}円・料金{worst_record['fees']:,.0f}円、**収支{worst_record['net']:,.0f}円**です。予定精算は15:45であり、記載価格は実引け約定ではありません。

つまり、売り側の玉が存在しないのではありません。安く売った玉を保持し、戻りで含み損が増える一方、既に両側上限なので新しい玉で修正できなくなっています。単に両側を持つだけでは、過去の不利な建値差を回収できません。対策として両側上限前の反対新規を元玉の減玉に使う、飽和前に全体損を限定する等は考えられますが、今回それを追加実行した結果ではありません。利益を失う面も含め別条件で測る必要があります。

O01（前場IVで追加幅を緩く変える方法）の基準との差は、全41場のうち**この1場だけ**。TOPIXは+16,582円（20→19枚）、日経は+1,744円（29→27枚）。複数場で安定して改善した証拠ではありません。

出典：[保存算術](TOPIX追加一場の両側上限と固定損失.json)。監査の所有NPZ写し1件と所有小会計のみを使用。金融再生・原市場読取・実注文0。価格時計は板全体の受信時計ではありません。
'''
    target_md=HERE/'TOPIX追加一場の両側上限と固定損失.md'
    assert not target_md.exists();target_md.write_text(note,encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
