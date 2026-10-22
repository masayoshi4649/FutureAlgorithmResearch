"""既存E01と格子O00の保存会計だけから、二つの日境界の活動を再集計する。"""

from collections import defaultdict
import math
import json

from daily_specs125 import HERE,ROOT,load


def e01_quantity(row: dict) -> tuple[int,dict]:
    """
    機能: 旧集計の返済枚数と注文別料金範囲から、場内往復の新規数量を照合する。
    引数: row(dict)は返済完了を監査した保存E01場会計。
    返り値: tuple[int,dict]は新規枚数と料金からの独立範囲。残玉未知は零補完しない。
    """
    assert row['verified_flat'] is True
    fee=float(row['fees']);top=row['symbol']=='TOPIX';single=41.8 if top else 11.
    minimum=2*math.floor(single);maximum=2*single
    candidates=[q for q in range(max(0,math.ceil(fee/maximum-1e-9)),math.floor(fee/minimum+1e-9)+1)
        if minimum*q-1e-8<=fee<=maximum*q+1e-8]
    assert len(candidates)==1, ('料金から数量が一意でない',row['session'],row['symbol'],fee,candidates)
    quantity=candidates[0]
    assert quantity==row['winning_lots']+row['losing_lots']
    assert (quantity>0)==(row['campaigns']>0)
    return quantity,dict(lower_fee_per_roundtrip_lot=minimum,upper_fee_per_roundtrip_lot=maximum,
        fee=fee,integer_quantity_candidates=candidates,
        explanation='場内返済監査を引用し新規数量=返済数量。各注文floor(q*片道料)はq*floor(片道料)以上q*片道料以下。保存全料金の可能整数数量が一意で勝負枚数和と一致。旧残玉null自体を0へ変えない。')


def grouped(rows: list[dict],mapping: dict[str,str],dates: list[str],complete: dict[str,dict]) -> dict:
    """
    機能: 同じ場会計を仮の日境界で足し合わせ、活動日と数量を記録する。
    引数: rows(list[dict])、mapping(dict[str,str])、dates(list[str])、complete(dict)は場行と日対応・境界情報。
    返り値: dictは日別と商品手法別の集計。利益率の合否は判定しない。
    """
    output=[]
    for method in ('E01_FIXED','GRID_O00'):
        for symbol in ('TOPIX','NK225'):
            for date in dates:
                own=[r for r in rows if r['method']==method and r['symbol']==symbol and mapping[r['session']]==date]
                assert own
                quantity=sum(r['new_quantity'] for r in own)
                output.append(dict(method=method,symbol=symbol,date=date,sessions=[r['session'] for r in own],
                    new_quantity=quantity,active=quantity>0,active_sessions=sum(r['active'] for r in own),
                    profit=sum(r['profit'] for r in own),loss=sum(r['loss'] for r in own),net=sum(r['net'] for r in own),
                    boundary=complete[date]))
    summaries={method:{symbol:dict(days=len(dates),active_days=sum(r['active'] for r in output if r['method']==method and r['symbol']==symbol),
        inactive_days=sum(not r['active'] for r in output if r['method']==method and r['symbol']==symbol),
        total_new_quantity=sum(r['new_quantity'] for r in output if r['method']==method and r['symbol']==symbol),
        incomplete_days=[d for d in dates if not complete[d]['complete_under_this_definition']])
        for symbol in ('TOPIX','NK225')} for method in ('E01_FIXED','GRID_O00')}
    return dict(rows=output,summaries=summaries)


def main() -> None:
    """
    機能: 既存164場行を二日境界で機械集計し、仮定と終端未揃いを保存する。
    引数: なし。
    返り値: None。原板・価格配列・新金融・率目標の判定を行わない。
    """
    old,old_ref=load('work/stability119_20261017/v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json')
    new,new_ref=load('work/stability124_20261019/e01c/追加一場の固定少額E01二商品.json')
    grid,grid_ref=load('work/stability124_20261019/grid/十二IV条件の全四十一場と旧十九条件の追加一場.json')
    rows=[]
    for row in old['rows']+new['rows']:
        quantity,basis=e01_quantity(row)
        rows.append(dict(method='E01_FIXED',symbol=row['symbol'],session=row['session'],new_quantity=quantity,
            active=quantity>0,profit=row['profit'],loss=row['loss'],net=row['net'],fees=row['fees'],
            source_method=row['method'],quantity_basis=basis,source_unclosed=row['unclosed'],verified_flat=row['verified_flat']))
    for row in grid['rows']:
        if row['method']!='O00':continue
        quantity=int(row['entries']);assert quantity==row['wins']+row['losses']==row['closed_lots']
        assert row['unclosed']==0
        rows.append(dict(method='GRID_O00',symbol=row['symbol'],session=row['session'],new_quantity=quantity,
            active=quantity>0,profit=row['profit'],loss=row['loss'],net=row['net'],fees=row['fees'],source_method='O00',
            quantity_basis='保存entries。各新規注文一枚、代理終端全完結玉と同数。',source_unclosed=0,verified_flat=True))
    assert len(rows)==164
    sessions=grid['sessions'];assert len(sessions)==41
    dates=sorted({s[:10] for s in sessions});assert len(dates)==21
    first={s:s[:10] for s in sessions}
    labels={d:dict(complete_under_this_definition={d+'_Day',d+'_Night'}.issubset(sessions),
        expected_sessions=[d+'_Day',d+'_Night'],missing_sessions=[s for s in (d+'_Day',d+'_Night') if s not in sessions]) for d in dates}
    second={}
    for scene in sessions:
        if scene.endswith('_Day'):second[scene]=scene[:10]
        else:
            later=[d for d in dates if d>scene[:10]]
            assert later, ('保存Nightに対応する次Dayがない',scene)
            second[scene]=later[0]
    trading={}
    for i,d in enumerate(dates):
        previous=dates[i-1] if i else None
        expected=[d+'_Day']+([previous+'_Night'] if previous else [])
        trading[d]=dict(complete_under_this_definition=previous is not None and all(s in sessions for s in expected),
            expected_sessions=expected,missing_previous_night=previous is None,
            missing_sessions=[] if previous else ['保存開始前のNightはデータなし・補完しない'])
    one=grouped(rows,first,dates,labels);two=grouped(rows,second,dates,trading)
    for method in ('E01_FIXED','GRID_O00'):
        for symbol in ('TOPIX','NK225'):
            original=[r for r in rows if r['method']==method and r['symbol']==symbol]
            for variant in (one,two):
                own=[r for r in variant['rows'] if r['method']==method and r['symbol']==symbol]
                for key in ('new_quantity','profit','loss','net'):
                    assert abs(sum(r[key] for r in original)-sum(r[key] for r in own))<1e-6
    result=dict(passed=True,references=[old_ref,new_ref,grid_ref],session_rows=rows,
        definitions=dict(label_day='セッション名先頭日付。Dayと同日ラベルNightをまとめる。実カレンダー日の夜中を分割してはいない。',
            next_saved_day='Dayは当日、Nightは保存Day一覧で直後の日へ。公的営業日カレンダーを推測せず、欠測日もその一覧に従う仮集計。'),
        by_label_day=one,by_next_saved_day=two,
        end_boundary='2026-10-19はDayだけ。先頭日付集計はNight欠測の未完日。次保存Day集計は10/16Night+10/19Dayで揃うが、最初9/21の前Nightが不明。日次の合否にどちらも使用しない。',
        new_financial_accounts=0,original_market_reads=0,numerical_array_reads=0,API=0,real_orders=0,
        profit_rate_judgment=None,reason='0.5%の分母・日付定義のユーザー回答待ち。既存保存値の再集計で新しい有効性標本ではない。')
    target=HERE/'既存E01とO00の全164場数量と二通りの日次活動.json'
    assert not target.exists();target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    import hashlib
    print(json.dumps(dict(passed=True,path=target.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        first=one['summaries'],second=two['summaries'],new_financial_accounts=0),ensure_ascii=False))


if __name__=='__main__':
    main()
