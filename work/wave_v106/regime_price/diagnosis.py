"""固定26金融の安定性と赤字親を事後に診断し、条件へ戻さない。"""

from collections import defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path

import numpy as np

import common
import prepare
import runner

HERE=Path(__file__).resolve().parent
JST=timezone(timedelta(hours=9))


def clock(stamp: float) -> str:
    """
    機能: 保存epochを日本時間の具体的判断時刻へ表す。
    引数: stamp(float)は当時価格代理時計。
    返り値: strはISO形式。板受信時刻とは呼ばない。
    """
    return datetime.fromtimestamp(float(stamp),JST).isoformat()


def stability(rows: list, symbol: str, sessions: list) -> dict:
    """
    機能: 前後・活動中央値・上位3除外と買売別を金額で計算する。
    引数: rows(list[dict])、symbol(str)、sessions(list[str])は固定時系列会計。
    返り値: dictは後付け診断。無取引は勝ちへ含めない。
    """
    selected=[next(r for r in rows if r['session']==s and r['symbol']==symbol) for s in sessions]
    all_values=[r['net'] for r in selected];active=[r['net'] for r in selected if r['campaigns']>0]
    ordered=sorted((r for r in selected if r['net']>0),key=lambda r:(-r['net'],r['session']))[:3]
    days=defaultdict(float)
    for r in selected:days[r['session'][:10]]+=r['net']
    best_days=sorted((d for d in days if days[d]>0),key=lambda d:(-days[d],d))[:3]
    return dict(全33=runner.TOTALS.aggregate(rows,symbol,sessions),
        前16=runner.TOTALS.aggregate(rows,symbol,sessions[:16]),後17=runner.TOTALS.aggregate(rows,symbol,sessions[16:]),
        全場中央値=float(np.median(all_values)),活動場中央値=float(np.median(active)) if active else None,
        黒字上位3場除外=dict(除外場=[r['session'] for r in ordered],除外場数=len(ordered),
            収支=float(sum(all_values)-sum(r['net'] for r in ordered))),
        黒字上位3日除外=dict(除外日=best_days,除外日数=len(best_days),収支=float(sum(all_values)-sum(days[d] for d in best_days))),
        定義='中央値は場ごとの手数料後収支。活動だけと全33を別記。上位3日除外は同暦日のDay/Night両方を除く。無取引は勝ちへ含めない。')


def parent(record: dict, ledger: dict, trade: np.ndarray) -> dict:
    """
    機能: 最大赤字親の当時6点、支持根拠、約定差と事後MFE/MAEを分ける。
    引数: record/ledger(dict)、trade(ndarray)は保存正常列・台帳・実親。
    返り値: dictは時刻付き原因材料。事後最大順行を売買規則へ戻さない。
    """
    ident=int(trade[0]);entry,exit=int(trade[2]),int(trade[3]);side=int(trade[4]);q=int(trade[5]);decision=int(trade[15])
    diagnostic=next(d for d in ledger['raw_entry_diagnostics'] if int(d['parent_id'])==ident)
    selection=next(d for d in ledger['selection_diagnostics'] if int(d['row'])==decision)
    tick=float(record['tick']);m=1000. if record['symbol']=='TOPIX' else 10.;E=float(trade[6])
    indexes=np.arange(entry,exit+1);valid=record['quote_valid'][indexes]&np.isfinite(record['bid'][indexes])&np.isfinite(record['ask'][indexes])
    indexes=indexes[valid];liquidation=record['bid'][indexes] if side==1 else record['ask'][indexes]
    movement=side*(liquidation-E);best=int(np.argmax(movement));worst=int(np.argmin(movement))
    mfe=max(0.,float(movement[best]));mae=max(0.,float(-movement[worst]));fees=float(trade[8]+trade[9])
    judgments=ledger['judgments'][ledger['judgments'][:,3]==ident]
    active=bool(np.any(judgments[:,15]>0)) if len(judgments) else False
    stop=float(judgments[0,17]) if len(judgments) else None
    risk=float(judgments[0,27]) if len(judgments) else None
    decision_price=float(record['ask'][decision] if side==1 else record['bid'][decision])
    gap=side*(E-decision_price)/tick
    category='順行後の利益返し' if mfe>4*tick else '入口後に継続せず反転'
    if gap>1:category='新規判断後の不利約定差を伴う'+category
    if stop is not None and side*((record['bid'][entry] if side==1 else record['ask'][entry])-stop)<=0:
        category='実fill時点ですでに停止線へ到達'
    return dict(parent_id=ident,family='C' if trade[1]==0 else 'R',side='買い' if side==1 else '売り',quantity=q,
        判断=dict(normal_row=decision,raw_seq=int(record['seq'][decision]),clock=clock(record['time_s'][decision]),
            bid=float(record['bid'][decision]),ask=float(record['ask'][decision]),state=selection['state'],
            observed_pair=selection['observed_pair'],range_order=selection['range_order']),
        自己根拠=diagnostic['episode']['selected_support_roots'],固定支持価格=diagnostic['fixed_support_price'],
        新規=dict(row=entry,raw_seq=int(record['seq'][entry]),clock=clock(record['time_s'][entry]),price=E,
            判断からの不利差呼値=gap,初回停止線=stop,初回予定料込損失=risk),
        返済=dict(row=exit,raw_seq=int(record['seq'][exit]),clock=clock(record['time_s'][exit]),price=float(trade[7]),
            reason=int(trade[13]),理由={1:'固定支持境界',2:'初期保険',3:'広い価格追尾',4:'狭い利益追尾',5:'費用床',6:'場内timer',9:'静観timer',10:'R固定中心到達'}.get(int(trade[13]),'その他')),
        手数料後収支=float(trade[11]),手数料=fees,MFE呼値=mfe/tick,MAE呼値=mae/tick,
        最大順行時計=clock(record['time_s'][indexes[best]]),最大逆行時計=clock(record['time_s'][indexes[worst]]),
        最良時点の料込清算収支=float(movement[best]*q*m-fees),利益追尾発動済み=active,分類=category,
        因果的対策の候補='入口判定と保有撤退の証拠は別に設計する。支持破れ又は新しい反対方向合意を当時観測して切替する対照は、今回結果から閾値を作らず別登録で比較する。',
        限界='MFE/MAEと最大時刻は事後材料。ラージBBO保存正常行だけであり、真の受信時計・約定方向・相手注文意図は観測していない。')


def main() -> None:
    """
    機能: 完了した26金融を一度読取り、全条件の安定性と赤字上位3場を保存する。
    引数: なし。
    返り値: None。金融や原板を再生せず、条件を変更しない。
    """
    target=HERE/'finance/全26の前後安定性と赤字上位3場の具体時刻.json';assert not target.exists()
    result=common.read(HERE/'finance/results.json');assert result['全合格'] and result['account_count']==1716
    start=runner.sources();assert start==common.read(HERE/'事前固定.json')['sources']
    output={};jobs=defaultdict(list);ledger_reads=0
    for config in result['configs']:
        ident=config['id'];case=result['cases'][ident];output[ident]={}
        for symbol in ('TOPIX','NK225'):
            item=stability(case['rows'],symbol,result['sessions']);losers=sorted((r for r in case['rows'] if r['symbol']==symbol and r['net']<0),key=lambda r:(r['net'],r['session']))[:3]
            item['赤字上位3場']={r['session']:dict(会計=r,最大損失2親=[]) for r in losers};output[ident][symbol]=item
            for r in losers:jobs[r['session']].append((ident,symbol))
    for session in result['sessions']:
        if session not in jobs:continue
        packet=prepare.load_session(session)
        for ident,symbol in jobs[session]:
            item=result['cases'][ident]['ledgers'][session][symbol];ledger=common.unpack(item);ledger_reads+=1
            trades=sorted((t for t in ledger['trades'] if t[11]<0),key=lambda t:(t[11],t[0]))[:2]
            record=packet['prepared'][symbol]['record'];entry=output[ident][symbol]['赤字上位3場'][session]
            entry['最大損失2親']=[parent(record,ledger,t) for t in trades]
            entry['台帳']=item
        del packet
    assert start==runner.sources()
    common.save(target,dict(全合格=True,事後診断専用=True,金融結果参照あり=True,results=output,対象条件=26,対象口座=1716,
        inputcache読取=len(jobs),台帳読取=ledger_reads,新金融再生=0,原板読取=0,API取得=0,
        SHA256={str((HERE/'finance/results.json').relative_to(common.ROOT)):common.digest(HERE/'finance/results.json'),
                str(Path(__file__).relative_to(common.ROOT)):common.digest(Path(__file__))},
        source_SHA256=start,開始終端source一致=True,
        制約=['無取引を勝ちに含めない。','R_ONLY及びAUTOのR活動不足はR切替の成功と表現しない。',
              '前16/後17と上位3除外は既知データの頑健性材料であり、未見将来の証明ではない。',
              '赤字場/親の順位は事後原因説明だけ。別ケース選び直しや金融再生に使っていない。']))
    print('全26の安定性と赤字上位場の時刻診断を保存、金融再生0',flush=True)


if __name__=='__main__':main()
