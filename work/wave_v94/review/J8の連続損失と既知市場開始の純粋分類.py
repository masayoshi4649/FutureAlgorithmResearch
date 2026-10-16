"""旧素材で入口を固定したJ8の赤字集中及び前決済・市場開始時間を分類する。"""

from datetime import date,datetime,time,timedelta,timezone
from pathlib import Path

import numpy as np

import 共通独立読取 as R


JST = timezone(timedelta(hours=9))
HOLIDAYS = {date.fromisoformat(value) for value in ('2026-01-01','2026-01-19','2026-02-16','2026-04-03',
    '2026-05-25','2026-06-19','2026-07-03','2026-09-07','2026-11-26','2026-12-25')}
SOURCES = [dict(名称='NYSEの通常立会開始及び2026休日',URL='https://www.nyse.com/trade/hours-calendars',
                確認日='2026-10-12',内容='通常開始9:30ET。全休日を日付固定。'),
           dict(名称='NISTの2026米国夏時間',URL='https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst',
                確認日='2026-10-12',内容='2026年03/08から11/01まで。今回の価格期間は夏時間。')]


def opening(day: date) -> datetime | None:
    """
    機能: NYSE取引日の通常開始9:30ETを、日本時間へ日付及び夏時間だけで変換する。
    引数: day(date)は米国の取引日。2026だけを検証する。
    返り値: datetime|Noneは日本時間の開始。休日又は週末はNone。
    """
    assert day.year==2026
    if day.weekday()>=5 or day in HOLIDAYS:
        return None
    summer = date(2026,3,8)<=day<date(2026,11,1)
    return datetime.combine(day,time(22 if summer else 23,30),JST)


def labels(stamp: float, session: str) -> dict:
    """
    機能: 判断時刻をDay09:15及び既知NYSE開始前後15分へ固定分類する。
    引数: stamp(float)は判断の代理時計、session(str)。
    返り値: dictは日中開始区分と米市場開始距離。価格又は損益は参照しない。
    """
    current = datetime.fromtimestamp(stamp,JST)
    day = current.date()
    candidates = [opening(day+timedelta(days=offset)) for offset in (-1,0,1)
                  if (day+timedelta(days=offset)).year==2026]
    available = [value for value in candidates if value is not None]
    nearest = min(available,key=lambda value:abs((current-value).total_seconds())) if available else None
    difference = (current-nearest).total_seconds() if nearest is not None else None
    cash = 'Day開始から09:15前' if session.endswith('_Day') and current.time()<time(9,15) else 'Day09:15以降' if session.endswith('_Day') else 'Night'
    return dict(日中開始区分=cash,米開始区分='米開始前後15分' if difference is not None and -900<=difference<900 else '米開始近辺以外',
                最寄りNYSE開始=nearest.isoformat() if nearest is not None else None,米開始から秒=difference)


def totals(rows: list[dict]) -> dict:
    """
    機能: 既存親群の費用後G/L、親勝率、平均勝負額を独立集計する。
    引数: rows(list[dict])は固定した親の診断。
    返り値: dictは親群会計。条件を実施した策略損益ではない。
    """
    profit = sum(max(row['収支円'],0.) for row in rows)
    loss = -sum(min(row['収支円'],0.) for row in rows)
    wins = sum(row['収支円']>0 for row in rows)
    losses = sum(row['収支円']<0 for row in rows)
    return dict(親=len(rows),利益円=profit,損失円=loss,収支円=profit-loss,
                利益親=wins,損失親=losses,親勝率=wins/len(rows) if rows else None,
                金額利益割合=profit/(profit+loss) if profit+loss else None,
                平均利益円=profit/wins if wins else None,平均損失円=loss/losses if losses else None,
                活動場=len({row['場'] for row in rows}),
                最悪親損失円=max([-row['収支円'] for row in rows if row['収支円']<0],default=0.))


def grouped(rows: list[dict], field: str) -> dict:
    """
    機能: 事前に定義した診断ラベルごとに既存親会計を分ける。
    引数: rows(list[dict])、field(str)。
    返り値: dictはラベル別会計。
    """
    return {label:totals([row for row in rows if str(row[field])==label]) for label in sorted({str(row[field]) for row in rows})}


def concentration(rows: list[dict]) -> dict:
    """
    機能: 一場の連続赤字親と、固定30/60分区間の損失集中を事後測定する。
    引数: rows(list[dict])は判断順の同商品同場の親。
    返り値: dictは事後集中診断。最大区間を新規停止判断へ使わない。
    """
    losing = [row for row in rows if row['収支円']<0]
    loss = -sum(row['収支円'] for row in losing)
    consecutive = best = 0
    current,best_group = [],[]
    for row in rows:
        if row['収支円']<0:
            consecutive+=1;current.append(row)
            if consecutive>best:
                best=consecutive;best_group=current.copy()
        else:
            consecutive=0;current=[]
    windows = {}
    for minutes in (30,60):
        candidates = []
        for start in losing:
            chosen = [row for row in losing if start['判断秒']<=row['判断秒']<start['判断秒']+minutes*60]
            candidates.append((sum(-row['収支円'] for row in chosen),start,chosen))
        amount,start,chosen = max(candidates,key=lambda value:value[0]) if candidates else (0.,None,[])
        windows[str(minutes)+'分'] = dict(損失円=amount,全損失割合=amount/loss if loss else None,
            開始判断時刻=start['判断時刻'] if start else None,親=[row['親'] for row in chosen],
            注意='事後に最も損失が集中した区間。各親全損失を判断時刻で帰属し、当時既知の確定損失累計とは異なる。')
    return dict(利益親=sum(row['収支円']>0 for row in rows),損失親=len(losing),損失円=loss,
                最大連続損失親=best,最大連続損失親ID=[row['親'] for row in best_group],
                最大連続損失区間開始=best_group[0]['判断時刻'] if best_group else None,
                最大連続損失区間終了=best_group[-1]['返済時刻'] if best_group else None,
                損失親上位2集中割合=sum(sorted((-row['収支円'] for row in losing),reverse=True)[:2])/loss if loss else None,
                固定幅の損失集中=windows)


def main() -> None:
    """
    機能: 根の許可後、固定J8の前決済・時刻・連続損失を前後別に分類する。
    引数: --根許可後(bool)。
    返り値: None。新規注文や停止策略の再生を行わず、旧イベント対照の親を変更しない。
    """
    R.permission()
    fixed,assembled = R.validate()
    assert opening(date(2026,3,6)).hour==23 and opening(date(2026,3,9)).hour==22
    assert opening(date(2026,10,30)).hour==22 and opening(date(2026,11,2)).hour==23
    assert opening(date(2026,9,7)) is None and opening(date(2026,10,10)) is None
    boundaries = datetime(2026,10,2,22,30,tzinfo=JST).timestamp()
    assert labels(boundaries-900,'2026-10-02_Night')['米開始区分']=='米開始前後15分'
    assert labels(boundaries+900,'2026-10-02_Night')['米開始区分']=='米開始近辺以外'
    ledger = R.load_ledgers('J8')
    parents,per_session = [],{}
    for session in fixed['全31']:
        for symbol in R.SYMBOLS:
            account = ledger[session,symbol]
            trades = sorted(account['trades'],key=lambda trade:trade[15])
            previous = None
            streak = 0
            current = []
            for trade in trades:
                assert trade[1]==0
                orders = account['orders'][account['orders'][:,2]==trade[0]]
                assert len(orders)==2 and orders[0,7]==1 and orders[1,7]==0
                previous_label = 'セッション初回' if previous is None else '前決済損失' if previous['収支円']<0 else '前決済利益' if previous['収支円']>0 else '前決済ゼロ'
                if previous is not None:
                    assert previous['返済行']<trade[15]
                row = dict(場=session,商品=symbol,親=int(trade[0]),方向=int(trade[4]),枚数=int(trade[5]),収支円=float(trade[11]),
                    判断行=int(trade[15]),返済行=int(trade[3]),判断秒=float(orders[0,10]),返済秒=float(orders[1,11]),
                    判断時刻=R.clock(orders[0,10]),返済時刻=R.clock(orders[1,11]),前決済区分=previous_label,
                    直前連続損失数=streak,直前連続損失区分='2以上' if streak>=2 else str(streak),
                    前回方向との関係='初回' if previous is None else '同方向' if previous['方向']==trade[4] else '反対方向',
                    前決済から新規判断秒=float(orders[0,10]-previous['返済秒']) if previous is not None else None,
                    返済理由=account['reasons'][int(trade[13])],**labels(float(orders[0,10]),session))
                current.append(row);parents.append(row)
                streak=streak+1 if row['収支円']<0 else 0
                previous=row
            per_session[session+'|'+symbol] = dict(場=session,商品=symbol,会計=totals(current),集中=concentration(current))
    periods = {}
    for label,sessions in (('全31',fixed['全31']),('前16',fixed['前16']),('後15',fixed['後15'])):
        periods[label] = {}
        for symbol in R.SYMBOLS:
            selected = [row for row in parents if row['場'] in sessions and row['商品']==symbol]
            assert totals(selected)['収支円']==assembled['results']['J8']['periods'][label][symbol]['net']
            periods[label][symbol] = dict(全親=totals(selected),前決済別=grouped(selected,'前決済区分'),
                直前連続損失別=grouped(selected,'直前連続損失区分'),日中開始別=grouped(selected,'日中開始区分'),
                米開始別=grouped(selected,'米開始区分'),前決済損失後の同方向反対方向=grouped([row for row in selected if row['前決済区分']=='前決済損失'],'前回方向との関係'),
                前決済利益後の同方向反対方向=grouped([row for row in selected if row['前決済区分']=='前決済利益'],'前回方向との関係'),
                無取引場数=assembled['results']['J8']['periods'][label][symbol]['no_trade_sessions'])
    paths = [R.WORK/'事前固定.json',R.WORK/'analysis/比較結果.json',Path(__file__)]
    R.save('J8旧イベントの前決済と連続損失及び既知市場開始の前後分類.json',dict(
        全合格=True,対象='J8の旧素材固定イベント対照だけ',親=len(parents),期間分類=periods,場別赤字集中=per_session,全親記録=parents,
        時間境界=dict(Day='セッション開始から09:15前と以降。判断時刻で分類。',
                     米開始='NYSE9:30ET、2026DST及び休日/週末を日付だけで固定。開始−15分を含み＋15分は含まない。',
                     検証期間='全31/前16/後15。時間幅を損益で探索していない。'),
        一次仕様参照=SOURCES,
        注意=['群の会計は既存親の分類であり、その親を除外して実装した停止策略の成績ではない。',
              '前決済符号と直前連敗は次判断で既知。損失集中の最大区間は事後診断で、オンライン停止に利用したことにしない。',
              '米開始群の親数が少ない場合は有用性を断定しない。前後で群の符号が揃うか分けて確認する。',
              '全31は既知であり、この分類を新条件に採用する場合は別固定・再検証が必要。',
              '今回はJ8候補生成及びJ2許可を旧素材固定。独立正常LPで追従入口全体を作り直す手法は未検証で、否定していない。',
              '公開市場仕様だけを参照し、現在の相場APIや実注文は利用していない。'],
        根拠SHA256={str(path.relative_to(R.ROOT)):R.digest(path) for path in paths},**R.provenance()))


if __name__=='__main__':
    main()
