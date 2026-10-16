"""全53の保存注文について、運用区切り・連続立会末・立会末を独立に区別する新補足。"""

from datetime import datetime,time,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import common
import full


def boundaries(session: str) -> tuple:
    """
    機能: JPX指数先物の連続立会末及びクロージング時刻を日付から独立算定する。
    引数: session(str)、開始日とDay/Night。
    返り値: tuple[float,float]、連続立会末と立会末の代理epoch秒。
    """
    date=datetime.fromisoformat(session[:10]).date();night=session.endswith('_Night')
    if night:date+=timedelta(days=1)
    zone=ZoneInfo('Asia/Tokyo')
    regular=datetime.combine(date,time(5,55) if night else time(15,40),zone)
    auction=datetime.combine(date,time(6,0) if night else time(15,45),zone)
    return regular.timestamp(),auction.timestamp()


def iso(stamp: float) -> str:
    """
    機能: 約定代理時計と各区切りを日本時間へ表示する。
    引数: stamp(float)、Unix秒。
    返り値: str、RFC3339。
    """
    return datetime.fromtimestamp(stamp,ZoneInfo('Asia/Tokyo')).isoformat()


def main() -> None:
    """
    機能: 許可済み正式3286口座の全約定を3つの区切りと独立照合する。
    引数: なし。
    返り値: None、新補足JSON。凍結181依存と売買・会計・既存証跡を変更しない。
    """
    fixed=full.read(common.WORK/'事前固定.json')
    for relative,digest in fixed['SHA256'].items():assert common.sha(common.ROOT/relative)==digest,relative
    data=common.module('境界補足だけの修正版入力94',common.WORK/'data_r1.py')
    material=data.load_inputs()
    accounts=orders=after_cut=after_regular=after_auction=before_start=0
    examples=[];fingerprints={};last_by_account=[]
    for stage in ('front','back'):
        for path in sorted((common.WORK/stage/'ledgers').glob('*.pkl')):
            ledger=full.read(path);fingerprints.update(common.fingerprint([path]))
            for key,value in ledger.items():
                record=material['prices'][key];regular,auction=boundaries(key[0])
                assert record['end']==regular and record['limit']==regular-300.
                assert value['input_rows']==len(record['time_s'])
                accounts+=1
                maximum=None
                for order in value['orders']:
                    orders+=1;stamp=float(order[11]);row=int(order[0])
                    assert stamp==record['time_s'][row]
                    before_start+=stamp<record['start'];after_regular+=stamp>=regular;after_auction+=stamp>=auction
                    maximum=max(maximum,stamp) if maximum is not None else stamp
                    if stamp<record['limit']:continue
                    after_cut+=1
                    examples.append(dict(ID=path.stem,場=key[0],商品=key[1],源=int(order[3]),親=int(order[2]),
                        新規=bool(order[7]),理由=int(order[8]),数量=int(order[5]),約定原本seq=int(record['seq'][row]),
                        運用区切り=iso(record['limit']),返済判断=iso(float(order[10])),実約定代理時計=iso(stamp),
                        運用区切り超過秒=stamp-record['limit'],連続立会末=iso(regular),立会末=iso(auction),
                        連続立会末まで秒=regular-stamp,立会末まで秒=auction-stamp))
                last_by_account.append(dict(ID=path.stem,場=key[0],商品=key[1],最終約定=iso(maximum) if maximum is not None else None,
                                            運用区切り=iso(record['limit']),連続立会末=iso(regular),立会末=iso(auction)))
    assert accounts==53*31*2 and before_start==after_regular==after_auction==0
    assert all(not row['新規'] for row in examples),'運用cut後に新規約定を混入'
    local=Path('S:/GitHub/masayoshi4649/kabus-controller/docs/01-configuration.md')
    old=common.ROOT/'work/wave_v93/audit/session_boundary_supplement.py'
    source=common.ROOT/'work/wave_v83/data.py'
    fingerprints.update(common.fingerprint([Path(__file__),common.WORK/'事前固定.json',old,source]))
    common.save('全3286口座の運用区切りと連続立会末及び立会内約定の独立補足.json',
        dict(全合格=True,全31既知=True,口座数=accounts,全注文数=orders,運用区切り以降約定=after_cut,
             連続立会末以降約定=after_regular,立会末以降約定=after_auction,立会開始以前約定=before_start,
             区別='旧limitは連続立会末から300秒前の保守的運用区切り。cut以降約定を真の場跨ぎへ読み替えず、cut内約定の保証とも説明しない。',
             具体例=examples,全口座の最後約定=last_by_account,
             根拠=dict(保存入力定義='work/wave_v83/data.py:203',ローカル仕様=str(local),ローカル仕様SHA256=common.sha(local),
                       一次資料='https://www.jpx.co.jp/derivatives/rules/trading-hours/',
                       一次資料確認='指数先物の連続立会08:45～15:40／17:00～翌05:55、クロージング15:45／翌06:00。'),
             限界='CurrentPriceTime代理時計と保存seqによる仮想約定の範囲。真の受信・実発注・実約定時計はこの保存原本で証明できない。',
             固定売買変更=0,固定会計変更=0,固定181依存変更=0,既存証跡変更=0,現在価格API取得=0,実注文=0,SHA256=fingerprints))
    print(f'{accounts}口座{orders}注文、運用cut以降{after_cut}返済、連続末・立会末以降0。',flush=True)


if __name__=='__main__':main()
