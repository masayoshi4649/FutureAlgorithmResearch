"""運用区切りと観測窓終端及び実際の立会終端を、凍結後の全注文で区別する。"""

from datetime import datetime,time,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import common
import full


def boundaries(session):
    """
    機能: ローカルcontroller仕様とJPX立会時間に従い、継続取引末及び立会末を算定する。
    引数: session(str、開始日とDay/Night)。
    返り値: tuple[float,float] の継続取引末・立会末のUnix秒。
    """
    day = datetime.fromisoformat(session[:10]).date()
    night = session.endswith('_Night')
    if night:
        day += timedelta(days=1)
    zone = ZoneInfo('Asia/Tokyo')
    continuous = datetime.combine(day,time(5,55) if night else time(15,40),zone)
    exchange = datetime.combine(day,time(6,0) if night else time(15,45),zone)
    return continuous.timestamp(),exchange.timestamp()


def iso(stamp):
    """
    機能: 原時計を日本時間の読める時刻へ変換する。
    引数: stamp(float、Unix秒)。
    返り値: str、RFC3339日時。
    """
    return datetime.fromtimestamp(stamp,ZoneInfo('Asia/Tokyo')).isoformat()


def main():
    """
    機能: 全992口座の約定を真の立会末と照合し、保守cut不達を別の実例として記録する。
    引数: なし。
    返り値: None。凍結売買・会計・既存証跡は変更しない。
    """
    import sys
    sys.path.insert(0,str(common.WORK))
    import data
    fixed = full.read(common.WORK/'事前固定.json')
    for path,digest in fixed['SHA256'].items():
        assert common.sha(common.ROOT/path)==digest,path
    material = data.load_inputs()
    rows = []
    accounts = orders = after_cut = after_continuous = after_exchange = before_start = 0
    fingerprints = {}
    for stage in ('front','back'):
        for path in sorted((common.WORK/stage/'ledgers').glob('*.pkl')):
            ledgers = full.read(path)
            fingerprints.update(common.fingerprint([path]))
            for key,ledger in ledgers.items():
                record = material['prices'][key]
                continuous,exchange = boundaries(key[0])
                assert record['end']==continuous and record['limit']==continuous-300.
                accounts += 1
                for order in ledger['orders']:
                    orders += 1
                    stamp = float(order[11])
                    before_start += stamp < record['start']
                    after_continuous += stamp >= continuous
                    after_exchange += stamp >= exchange
                    if stamp >= record['limit']:
                        after_cut += 1
                        rows.append(dict(ID=path.stem,場=key[0],商品=key[1],源=int(order[3]),親=int(order[2]),
                                         新規=bool(order[7]),理由=int(order[8]),数量=int(order[5]),
                                         運用区切り=iso(record['limit']),返済判断=iso(float(order[10])),
                                         実約定=iso(stamp),運用区切り超過秒=stamp-record['limit'],
                                         継続取引末=iso(continuous),立会末=iso(exchange),
                                         継続取引末まで秒=continuous-stamp,立会末まで秒=exchange-stamp))
    assert accounts==992 and before_start==after_continuous==after_exchange==0
    assert all(not row['新規'] for row in rows)
    local = Path('S:/GitHub/masayoshi4649/kabus-controller/docs/01-configuration.md')
    old_input = common.ROOT/'work/wave_v83/data.py'
    fingerprints.update(common.fingerprint([Path(__file__),common.WORK/'事前固定.json',old_input]))
    common.save('全992口座の立会内約定と運用区切りの独立補足.json',dict(
        全合格=True,全31既知=True,口座数=accounts,全注文数=orders,運用区切り以降約定=after_cut,
        継続取引末以降約定=after_continuous,立会末以降約定=after_exchange,立会開始以前約定=before_start,
        区別='limitは真の閉場時刻ではなく、観測窓endから300秒前の旧運用区切り。全21例は返済で、継続取引末より前。厳密なcut内約定を保証したとは記述しない。',
        具体例=rows,
        根拠=dict(保存入力定義='work/wave_v83/data.py:203',
                  ローカル仕様=str(local),ローカル仕様SHA256=common.sha(local),
                  一次資料='https://www.jpx.co.jp/derivatives/rules/trading-hours/',
                  確認='日中継続15:40・クロージング15:45、夜間継続翌5:55・クロージング翌6:00。'),
        限界='CurrentPriceTime代理時計と保存seqの仮想約定内の検算。真の受信時計・実際の注文送信又は約定時刻は証明しない。',
        固定売買変更=0,固定会計変更=0,既存証跡変更=0,実注文=0,現在価格API取得=0,SHA256=fingerprints))
    print(f'{accounts}口座{orders}注文、cut以降{after_cut}返済、継続末・立会末以降0。',flush=True)


if __name__=='__main__':
    main()
