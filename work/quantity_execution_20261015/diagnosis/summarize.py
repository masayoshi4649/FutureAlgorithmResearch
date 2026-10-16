"""同bytes私有完成結果だけから、公開時と約定時のずれを非再生で集計する。"""

from collections import Counter
from fractions import Fraction
import json

import reader


def main() -> None:
    """
    機能: 主候補の全親分母と公開から新規までの気配変化を私有コピーから一回射影する。
    引数: なし。
    返り値: None。元結果・台帳・原入力・保存event・APIは追加で読まない。
    """
    output = reader.HERE / '主候補全親の公開後変化と損失単位の追加射影.json'
    assert not output.exists()
    raw = (reader.HERE / '完成結果の同bytes私有コピー.json').read_bytes()
    expected = 'f2a61c69044487164dd119aa97faf37be71f1a48683e784bea2531e237861a80'
    assert reader.digest(raw) == expected
    result = json.loads(raw.decode('utf-8'))
    report = {}
    for symbol, tick in (('TOPIX', Fraction(1, 2)), ('NK225', Fraction(10))):
        pp = [p for p in result['parents'] if p['case'] == reader.MAIN and p['symbol'] == symbol]
        dd = [d for d in result['diagnostics'] if d['case'] == reader.MAIN and d['symbol'] == symbol]
        snaps = {(d['session'], s['parent'], s['uid']):s for d in dd for s in d['snapshots']}
        totals = {k:float(sum((reader.number(d[k]) for d in dd), Fraction())) for k in
                  ('中値差粗損益','気配差負担','手数料','収支')}
        assert reader.number(totals['中値差粗損益'])-reader.number(totals['気配差負担'])-reader.number(totals['手数料']) == reader.number(totals['収支'])
        flags, parent_classes, examples = Counter(), Counter(), []
        for p in pp:
            s = snaps[p['session'], p['parent'], p['uid']]
            a, b, side = s['公開'], s['新規'], p['side']
            assert int(b['raw_seq']) == int(a['raw_seq'])+1
            entry_spread = (reader.number(b['ask'])-reader.number(b['bid']))/tick
            public_spread = (reader.number(a['ask'])-reader.number(a['bid']))/tick
            shift = [side*(reader.number(b[k])-reader.number(a[k]))/tick for k in ('bid','ask')]
            quote_key = 'ask' if side > 0 else 'bid'
            unfavorable = side*(reader.number(b[quote_key])-reader.number(a[quote_key]))/tick
            categories = dict(公開から新規で両気配が同方向1T以上=min(shift)>=1,
                公開から新規が不利=unfavorable>0, 新規時拡幅=entry_spread>public_spread,
                新規時すでに粗損切線以下=entry_spread>=2,
                保有中粗ピーク0T未満=reader.number(p['peak_gross_ticks'])<0,
                保有中粗ピーク2T未達=reader.number(p['peak_gross_ticks'])<2)
            label = '勝ち親' if p['net_yen']>0 else '負け親' if p['net_yen']<0 else '零親'
            flags[label] += 1
            for key, yes in categories.items():
                if yes:
                    flags[key] += 1
                    flags[key+'_'+label] += 1
            parent_classes['新規spread_'+str(entry_spread)+'T'] += 1
            own = next(d for d in dd if d['session'] == p['session'])
            breakdown = [x for x in own['parent_breakdown'] if x['parent'] == p['parent'] and x['uid'] == p['uid']]
            assert len(breakdown) == 1
            v = breakdown[0]
            mid, crossing, fee, net = [reader.number(v[k]) for k in ('中値差粗損益','気配差負担','手数料','収支')]
            assert mid-crossing-fee == net == reader.number(p['net_yen'])
            if net < 0:
                category = '負け親_中値も逆行' if mid < 0 else '負け親_中値非負だが気配差後負' if mid-crossing < 0 else '負け親_粗利非負だが料で負'
                flags[category] += 1
            examples.append(dict(session=p['session'], parent=p['parent'], uid=p['uid'], side=side,
                net_yen=p['net_yen'], peak_gross_ticks=p['peak_gross_ticks'],
                public_spread_ticks=float(public_spread), entry_spread_ticks=float(entry_spread),
                public_to_entry_unfavorable_ticks=float(unfavorable), bbo_shift_ticks=[float(x) for x in shift],
                public_raw_seq=a['raw_seq'], entry_raw_seq=b['raw_seq'],
                公開価格時計=reader.clock(a['price_time_s']), 新規価格時計=reader.clock(b['price_time_s']),
                中値差粗損益=float(mid), 気配差負担=float(crossing), 手数料=float(fee), flags=categories))
        assert flags['勝ち親']+flags['負け親']+flags['零親'] == len(pp)
        report[symbol] = dict(全親=len(pp), 金額分解=totals, 件数=dict(flags), 新規気配差分布=dict(parent_classes), 親小観測=examples)
    reader.write(output, dict(全合格=True, 金融結果SHA256=expected, 主候補=reader.MAIN, 商品=report,
        範囲='既私有同bytesコピーの一回再射影。実結果の記述であり新しい金融や114との事象照合ではない。',
        元金融結果追加読=0, 元台帳追加読=0, 原NPZ=0, eventNPZ=0, API=0))
    print(json.dumps({symbol:{k:v for k,v in own.items() if k!='親小観測'} for symbol,own in report.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
