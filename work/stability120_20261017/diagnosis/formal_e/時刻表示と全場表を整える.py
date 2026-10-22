"""根の自所有二場から時刻表示だけを訂正し、保存小会計の簡潔な診断を作る。"""

from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
BASE=HERE.parent.parent
ROOT=BASE.parents[1]
JST=timezone(timedelta(hours=9))
TARGET='実保有の逆側追越と利確後の残在庫.json'
CASES=('ROTATE_S2_T1','KEEP_S2_T1','RESCUE_S2_T1')
SYMBOLS=('TOPIX','NK225')


def sha(payload: bytes) -> str:
    """
    機能: 読取済み原内容と保存物を内容指紋で識別する。
    引数: payload(bytes)は保存又は読取内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def clock(session: str,epoch: float) -> str:
    """
    機能: 原epoch秒を日本時間へ変換し、場名の翌日だけ翌と表記する。
    引数: session(str)は日付_Day/Night、epoch(float)は保存UNIX秒。
    返り値: strはHH:MM:SS又は翌HH:MM:SS。日付の推測補完はしない。
    """
    value=datetime.fromtimestamp(float(epoch),JST)
    base=datetime.fromisoformat(session.split('_')[0]).date()
    assert (value.date()-base).days in (0,1)
    return ('翌' if value.date()>base else '')+value.strftime('%H:%M:%S')


def money(value: float,signed: bool=True) -> str:
    """
    機能: 診断の保存金額を円表記にする。
    引数: value(float)は金額、signed(bool)は符号の明示。
    返り値: strは千位区切り文字列。実金額自体を変更しない。
    """
    if value==0:return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def main() -> None:
    """
    機能: 二つの根自所有NPZを各一読し、診断JSONの表示時刻だけを訂正する。
    引数: なし。根自所有小会計・統計・formal_eの保存二場だけを使用する。
    返り値: None。金融・原市場・元cache・監査所有を再読せず、JSON・MD・証跡を保存する。
    """
    proofpath=HERE/'epoch時刻の表示訂正と非時刻全項目不変の確認.json'
    mdpath=HERE/'逆側カバーと上下回転の診断.md'
    assert not proofpath.exists() and not mdpath.exists()
    oldraw=(HERE/TARGET).read_bytes();archived=(HERE/'時刻表示修正前'/TARGET).read_bytes()
    assert oldraw==archived,'旧時刻版の同bytes保全が必要'
    old=json.loads(oldraw);fixed=deepcopy(old)
    resultpath=BASE/'root_owned_e/カバーを維持する組全体追尾と全四十場.json';result_raw=resultpath.read_bytes();data=json.loads(result_raw)
    statspath=BASE/'root_owned_e/全条件の場内安定指標.json';stats_raw=statspath.read_bytes();stats=json.loads(stats_raw)
    assert sha(result_raw)==old['result_sha256']==stats['source_sha256']
    specs={s['id']:i for i,s in enumerate(data['specs'])};lc={k:i for i,k in enumerate(data['lot_columns'])}
    assert len(specs)==18 and len(lc)==19 and len(data['runs'])==1440
    groups=sorted({(e['symbol'],e['session']) for e in fixed['examples']})
    assert groups==[('NK225','2026-10-14_Night'),('TOPIX','2026-10-16_Night')]
    changes=[];allowed=set();reads=[];row_lookup_checks=lot_lookup_checks=0
    for symbol,session in groups:
        path=HERE/(symbol+'_'+session+'.npz');payload=path.read_bytes()
        reference=next(c for c in data['cache'] if c['symbol']==symbol and c['session']==session)
        assert sha(payload)==reference['sha256']
        with np.load(BytesIO(payload),allow_pickle=False) as saved:
            names=saved.files
            assert {'quotes__row','quotes__time','lots'}<=set(names)
            rawrows=saved['quotes__row'];times=saved['quotes__time'];lots=saved['lots']
            assert len(rawrows)==len(times) and np.all(np.diff(rawrows)>0) and lots.shape[1]==20
            for ei,example in enumerate(fixed['examples']):
                if (example['symbol'],example['session'])!=(symbol,session):continue
                policy=specs[example['method']];selected=lots[lots[:,0]==policy,1:]
                byuid={int(v[lc['uid']]):v for v in selected};assert len(byuid)==len(selected)

                def correct(value: object,pointer: tuple) -> None:
                    """
                    機能: rawで実時計へ対応できる診断項目のtime文字列だけを訂正する。
                    引数: value(object)はJSON部分木、pointer(tuple)は一意なJSON位置。
                    返り値: None。rawや金額及び件数には書き込まない。
                    """
                    nonlocal row_lookup_checks
                    if isinstance(value,dict):
                        if 'raw' in value and 'time' in value:
                            raw=int(value['raw']);idx=int(np.searchsorted(rawrows,raw));assert idx<len(rawrows) and int(rawrows[idx])==raw
                            destination=clock(session,times[idx]);key=pointer+('time',);allowed.add(key)
                            changes.append(dict(pointer='/'.join(str(v) for v in key),old=value['time'],new=destination,raw=raw,epoch=float(times[idx])))
                            value['time']=destination;row_lookup_checks+=1
                        for k,v in value.items():correct(v,pointer+(k,))
                    elif isinstance(value,list):
                        for j,v in enumerate(value):correct(v,pointer+(j,))

                correct(example,('examples',ei))
                for wi,lot in enumerate(example['worst_lots']):
                    found=byuid[lot['uid']]
                    for field,timekey,rowkey in (('entry','entry_time','entry_row'),('exit','exit_time','exit_row')):
                        raw=int(found[lc[rowkey]]);idx=int(np.searchsorted(rawrows,raw));assert idx<len(rawrows) and int(rawrows[idx])==raw and float(times[idx])==float(found[lc[timekey]])
                        value=clock(session,found[lc[timekey]]);key=('examples',ei,'worst_lots',wi,field);allowed.add(key)
                        changes.append(dict(pointer='/'.join(str(v) for v in key),old=lot[field],new=value,uid=lot['uid'],epoch=float(found[lc[timekey]])))
                        lot[field]=value;lot_lookup_checks+=1
        reads.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(payload),numerical_reads=1,arrays=['quotes__row','quotes__time','lots'],policies=list(CASES)))

    unchanged_leaves=0

    def compare(a: object,b: object,pointer: tuple=()) -> None:
        """
        機能: 指定した時刻文字列以外の全leafを型も含めて厳密に照合する。
        引数: a/b(object)は旧新JSON、pointer(tuple)は現在位置。
        返り値: None。金額・UID・row・件数等の変化があれば保存前に停止する。
        """
        nonlocal unchanged_leaves
        assert type(a) is type(b),pointer
        if isinstance(a,dict):
            assert list(a)==list(b),pointer
            for key in a:compare(a[key],b[key],pointer+(key,))
        elif isinstance(a,list):
            assert len(a)==len(b),pointer
            for i,(v,w) in enumerate(zip(a,b)):compare(v,w,pointer+(i,))
        elif pointer in allowed:
            assert isinstance(a,str) and isinstance(b,str),pointer
        else:
            assert a==b,pointer
            unchanged_leaves+=1

    compare(old,fixed)
    newraw=(json.dumps(fixed,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8')
    (HERE/TARGET).write_bytes(newraw)
    rr={(r['method'],r['session'],r['symbol']):r for r in data['runs']};metrics={r['id']:r['metrics'] for r in stats['rankings']}
    assert stats['qualification_count']==0 and all(metrics[c][s]['net']<0 for c in metrics for s in SYMBOLS)
    examples={(e['method'],e['symbol']):e for e in fixed['examples']}
    text=['# 逆側カバーと上下回転の診断','',
        '**逆側の実枚数が元側を上回る動きは起きた。ただし、そのことだけでは全玉の損失を回収できなかった。** 今回の18条件は日経・TOPIXとも全条件の合計が赤字で、全場の安定黒字には届かなかった。','',
        'ROTATEは利益玉を個別に追尾返済する上下回転、KEEPは勝ちカバーを残して組全体の利益を追尾、RESCUEはKEEPの両側上限時だけ反対の最悪負け玉を1枚整理する。以下は同じ中間幅・追尾1単位（S2_T1）の比較。','',
        '## 同じ固定条件の40場合計','',
        '| 方法 | TOPIX 利益／損失／収支（円） | 黒／赤／無 | 日経 利益／損失／収支（円） | 黒／赤／無 |',
        '| --- | ---: | --- | ---: | --- |']
    for case in CASES:
        a,b=metrics[case]['TOPIX'],metrics[case]['NK225']
        text.append(f"| {case} | {money(a['profit'],False)}／{money(a['loss'],False)}／{money(a['net'])} | {a['black']}/{a['red']}/{a['inactive']} | {money(b['profit'],False)}／{money(b['loss'],False)}／{money(b['net'])} | {b['black']}/{b['red']}/{b['inactive']} |")
    text.extend(['','利益・損失は完結1枚玉の費用後netの正負で、料は内数。組の回収とは別の場全体集計で、前の組の実損も残している。','',
        '## 実際に逆側が追い越した後','',
        '初回向きは組の最初の実約定で固定し、逆側とはその反対方向を指す。枚数は予約でなく実保有。traceは**注文約定があった原行だけ**であり、時間占有率・方向正答率ではない。選択した2場はROTATE_S2_T1の各商品最悪場で、原因を見るための事後選択。','',
        '| 商品・場／方法 | 初回向き | 逆側が初めて超過したJST時刻／買・売枚数 | 個別利確で超過を失った最初の時刻／買・売枚数 | 両側上限に初めて達した時刻 | 場収支円 |',
        '| --- | --- | --- | --- | --- | ---: |'])
    for symbol,session in groups:
        for case in CASES:
            e=examples[case,symbol];first=e['trace'][0] if e['trace'] else None;cross=e['first_counter_excess'];lost=e['counter_excess_lost_on_profit_exit'];caps=e['first_both_caps']
            sign='買い' if first and first['initial_side']==1 else '売り' if first else '—'
            describe=lambda v: f"{v['time']}／{v['long']}・{v['short']}" if v else '観測なし'
            text.append(f"| {symbol} {session}／{case.split('_')[0]} | {sign} | {describe(cross)} | {describe(lost[0] if lost else None)} | {caps['time'] if caps else '観測なし'} | {money(e['net'])} |")
    top=examples['ROTATE_S2_T1','TOPIX']
    for longs,shorts,eq,cash in ((2,3,-10796.,13409.),(6,4,-33436.,37474.)):
        found=next((v for v in top['trace'] if v['long']==longs and v['short']==shorts and v['equity']==eq and v['cash']==cash),None)
        if found:text.extend(['',f"TOPIX {found['time']}は買い{longs}・売り{shorts}枚、現金増減{money(cash)}円でも全玉清算時価は{money(eq)}円だった。"])
    text.extend(['','cashは未返済玉の新規手数料も差し引いた**現金増減**で、確定利益ではない。利益の出たカバーを返済すると超過方向が消える場合があり、残玉込みの損失は別に残る。KEEPの両側同枚数ロックは、その後の同幅の価格進行だけでは損失を回収しない。RESCUEの整理損も同じ組に計上しており、損失を消した扱いにはしていない。','',
        '## 最も負けた玉の実時刻','',
        '| 商品／方法 | UID・向き | 新規JST時刻・価格 | 返済JST時刻・価格 | 純損益円 | 返済理由 |',
        '| --- | --- | --- | --- | ---: | --- |'])
    reasons={1:'個別利益追尾',9:'場末返済',10:'組利益追尾',11:'飽和時の一枚整理'}
    for symbol,session in groups:
        for case in CASES:
            e=examples[case,symbol]
            if not e['worst_lots']:continue
            lot=e['worst_lots'][0];side='買い' if lot['side']==1 else '売り'
            text.append(f"| {symbol}／{case.split('_')[0]} | {lot['uid']}・{side} | {lot['entry']}・{lot['entry_price']:g} | {lot['exit']}・{lot['exit_price']:g} | {money(lot['net'])} | {reasons.get(lot['reason'],str(lot['reason']))} |")
    text.extend(['','ここでの負け玉は最後まで未返済という意味ではなく、実際に返済した損失玉。今回の全政策は末尾未返済0。特定の一場で回収できたことや、逆側が一時追い越したことを、全40場に通用する回避条件とはしない。','',
        '## S2_T1の全40場','', '以下の3表は全て同じ40場。TOPIXと日経を相殺せず、各商品の利益・損失・収支を掲載する。'])
    for case in CASES:
        text.extend(['',f'<details><summary>{case} の全40場（円）</summary>','',
            '| セッション | TOPIX利益 | TOPIX損失 | TOPIX収支 | 日経利益 | 日経損失 | 日経収支 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: |'])
        for session in data['sessions']:
            cells=[]
            for symbol in SYMBOLS:
                r=rr[case,session,symbol];cells.extend([money(r['profit'],False),money(r['loss'],False),money(r['net'])])
            text.append('| '+session+' | '+' | '.join(cells)+' |')
        total=[]
        for symbol in SYMBOLS:
            m=metrics[case][symbol];total.extend([money(m['profit'],False),money(m['loss'],False),money(m['net'])])
        text.extend(['| **全40場** | '+' | '.join(total)+' |','','</details>'])
    text.extend(['','根拠：[訂正済みの注文行診断JSON](実保有の逆側追越と利確後の残在庫.json)、[時刻表示だけの修正証跡](epoch時刻の表示訂正と非時刻全項目不変の確認.json)、[全18条件の保存統計](../../root_owned_e/全条件の場内安定指標.json)。','',
        '全40場は既知開発。今回行ったのは自所有2NPZの時計・UID時刻の再対応と小会計の転載で、金融再実行・元結果・元cache・監査所有・原市場・APIの再読は0。'])
    mdpath.write_text('\n'.join(text)+'\n',encoding='utf8')
    proof=dict(passed=True,scope='epoch秒のJST表示だけの訂正。旧JSONの金額・UID・row・件数など非時刻全leafを型付き完全同値で検査。金融再生ではない。',
        source_sha256=sha(Path(__file__).read_bytes()),old_diagnosis_sha256=sha(oldraw),archived_diagnosis_sha256=sha(archived),new_diagnosis_sha256=sha(newraw),
        unchanged_non_time_leaves=unchanged_leaves,display_time_fields=len(allowed),raw_to_clock_checks=row_lookup_checks,uid_time_checks=lot_lookup_checks,changes=changes,owned_reads=reads,
        root_owned_result_sha256=sha(result_raw),root_owned_statistics_sha256=sha(stats_raw),markdown_sha256=sha(mdpath.read_bytes()),original_result_reads=0,original_cache_reads=0,audit_owned_reads=0,market_reads=0,financial_replay=0,API=0)
    proofpath.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,unchanged_non_time_leaves=unchanged_leaves,times=len(allowed),json_sha256=sha(newraw),md_sha256=proof['markdown_sha256'],proof_sha256=sha(proofpath.read_bytes()),examples=[dict(symbol=e['symbol'],method=e['method'],first_counter_excess=e['first_counter_excess'],first_both_caps=e['first_both_caps'],first_lost=e['counter_excess_lost_on_profit_exit'][:1]) for e in fixed['examples']]),ensure_ascii=False))


if __name__=='__main__':
    main()
