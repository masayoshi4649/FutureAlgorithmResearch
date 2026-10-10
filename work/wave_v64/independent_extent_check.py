"""判断後の最高値・最安値から最大順行と逆行の限界値を別式で検算する。"""

from collections import Counter
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np

from independent_check import TableRows


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00061_入口の方向予測精度を出口と分離'


def same(actual, expected):
    """機能: 辞書・配列の構造と有限数値を許容誤差付きで比較する。

    引数: actual/expected(object)。返り値: なし(None)。不一致なら例外。
    """
    if isinstance(actual, dict):
        assert actual.keys() == expected.keys(), (actual.keys(), expected.keys())
        for key in actual:
            same(actual[key], expected[key])
    elif isinstance(actual, list):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            same(a, b)
    elif isinstance(actual, float):
        assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (actual, expected)
    else:
        assert actual == expected, (actual, expected)


def distribution(values):
    """機能: 昇順列の線形補間から分布を独立計算する。

    引数: values(list[float])。返り値: 件数・四分位・平均の辞書(dict)。
    """
    ordered = sorted(values)
    if not ordered:
        return dict(件数=0,最小=None,四分位25=None,中央値=None,四分位75=None,最大=None,平均=None)
    quantiles = []
    for fraction in (.25, .5, .75):
        position = fraction * (len(ordered) - 1)
        lower, upper = math.floor(position), math.ceil(position)
        quantiles.append(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))
    return dict(件数=len(ordered),最小=ordered[0],四分位25=quantiles[0],中央値=quantiles[1],四分位75=quantiles[2],
        最大=ordered[-1],平均=math.fsum(ordered)/len(ordered))


def main():
    """機能: 同じ281判断の最大幅・初回頂点前の逆行・全幅先着・表示表を独立確認する。

    引数: なし。返り値: なし(None)。元実装を実行せず原本と既存条件を変更しない。
    """
    packet = json.loads((HERE / '最大順行と入口採点.json').read_text(encoding='utf-8'))
    old = json.loads((HERE / '方向採点.json').read_text(encoding='utf-8'))
    frozen = json.loads((HERE / '限界値採点前固定.json').read_text(encoding='utf-8'))
    ready = pickle.loads((HERE.parent / 'wave_v60/inputs.pkl').read_bytes())
    quotes = pickle.loads((HERE.parent / 'wave_v60/quotes.pkl').read_bytes())
    source_counter = Counter((r['method'],r['session'],r['symbol'],r['decision_i'],r['decision_seq'],r['side'],r['decision_time'],r['decision_mid']) for r in old['rows'])
    new_counter = Counter((r['method'],r['session'],r['symbol'],r['decision_i'],r['decision_seq'],r['side'],r['decision_time'],r['decision_mid']) for r in packet['rows'])
    assert source_counter == new_counter
    assert packet['新規数'] == len(packet['rows']) == 281
    assert packet['除外数'] == 0
    checked_fields, checked_labels, summaries = 0, 0, []
    rebuilt = []
    for row in packet['rows']:
        key = (row['session'],row['symbol'])
        account, quote = ready[key],quotes[key]
        index, side, start = row['decision_i'],row['side'],row['decision_mid']
        assert account['seq'][index] == row['decision_seq']
        assert account['time_s'][index] == row['decision_time']
        assert quote['mid'][index] == start
        assert (account['time_s'] < account['limit'] + 300).all()
        after = quote['mid'][index+1:]
        assert len(after)
        high, low = float(after.max()),float(after.min())
        favorable_price = high if side == 1 else low
        adverse_price = low if side == 1 else high
        favorable = max(0.,side*favorable_price-side*start)
        adverse = max(0.,side*start-side*adverse_price)
        if favorable > 0:
            peak = index + 1 + int(np.flatnonzero(after == favorable_price)[0])
            before_peak = quote['mid'][index+1:peak+1]
            before_adverse_price = float(before_peak.min() if side == 1 else before_peak.max())
            before_adverse = max(0.,side*start-side*before_adverse_price)
        else:
            peak, before_adverse = None,None
        extent = dict(最大順行=favorable,最大順行割合=favorable/start,最大逆行=adverse,最大逆行割合=adverse/start,
            最大順行前の逆行=before_adverse,最大順行行=peak,最大順行価格=float(quote['mid'][peak]) if peak is not None else None,
            一呼値順行=favorable>=account['tick'],最大値までの利益幅が途中逆行以上=favorable>0 and before_adverse<=favorable,
            最大値までの利益幅が途中逆行の二倍以上=favorable>0 and 2*before_adverse<=favorable,到達={})
        for text,label in (('0.0005','0.05'),('0.001','0.10'),('0.002','0.20')):
            width = float((Decimal(str(start))*Decimal(text)/Decimal(str(account['tick']))).to_integral_value(rounding=ROUND_CEILING)*Decimal(str(account['tick'])))
            plus_price, minus_price = start+side*width,start-side*width
            positive = np.flatnonzero(after>=plus_price if side==1 else after<=plus_price)
            negative = np.flatnonzero(after<=minus_price if side==1 else after>=minus_price)
            pi = int(positive[0]) if len(positive) else len(after)
            ni = int(negative[0]) if len(negative) else len(after)
            verdict = 1 if pi<ni else -1 if ni<pi else 0
            first = index+1+min(pi,ni) if verdict else None
            extent['到達'][label] = dict(幅=width,順行到達=bool(len(positive)),逆行到達=bool(len(negative)),先着=verdict,先着行=first)
            checked_labels += 1
        if peak is not None:
            extent['最大順行原本行'] = int(account['seq'][peak])
        same(row['extent'],extent)
        checked_fields += len(extent)
        rebuilt.append(dict(method=row['method'],symbol=row['symbol'],extent=extent))
    for method in packet['methods']:
        for symbol in ('TOPIX','NK225'):
            rows = [r['extent'] for r in rebuilt if r['method']==method['id'] and r['symbol']==symbol]
            n = len(rows)
            measured = dict(新規数=n,一呼値順行数=sum(r['一呼値順行'] for r in rows),一度も順行しなかった数=sum(r['最大順行']==0 for r in rows))
            for label in ('最大順行','最大順行割合','最大逆行','最大逆行割合','最大順行前の逆行'):
                measured[label] = distribution([r[label] for r in rows if r[label] is not None])
            measured['一呼値順行率'] = measured['一呼値順行数']/n
            measured['最大値までの利益幅が途中逆行以上率'] = sum(r['最大値までの利益幅が途中逆行以上'] for r in rows)/n
            measured['最大値までの利益幅が途中逆行の二倍以上率'] = sum(r['最大値までの利益幅が途中逆行の二倍以上'] for r in rows)/n
            measured['到達'] = {}
            for label in ('0.05','0.10','0.20'):
                reached = [r['到達'][label] for r in rows]
                positive = sum(r['順行到達'] for r in reached)
                negative = sum(r['逆行到達'] for r in reached)
                pg, ng = sum(r['先着']==1 for r in reached),sum(r['先着']==-1 for r in reached)
                measured['到達'][label] = dict(順行到達=positive,逆行到達=negative,両側到達=sum(r['順行到達'] and r['逆行到達'] for r in reached),
                    順行到達率=positive/n,逆行到達率=negative/n,順行先着=pg,逆行先着=ng,未到達=n-pg-ng,
                    全入口での順行先着率=pg/n,到達内順行先着率=pg/(pg+ng) if pg+ng else None)
            same(method['summary'][symbol],measured)
            summaries.append(dict(候補=method['number'],銘柄=symbol,新規数=n,最大順行中央値=measured['最大順行']['中央値'],
                最大値前逆行中央値=measured['最大順行前の逆行']['中央値'],到達0_10=measured['到達']['0.10'],
                一度も順行なし=measured['一度も順行しなかった数']))
    # ----------------------------------------
    # 公開HTMLの主表6行・幅別表6行を独立集計値と照合する。
    parser = TableRows()
    parser.feed((PUBLIC / '入口の方向予測精度.html').read_text(encoding='utf-8'))
    cells = [r for r in parser.rows if r and r[0].startswith('候補')]
    assert len(cells)==12
    expected_cells=[]
    for method in packet['methods']:
        for symbol in ('TOPIX','NK225'):
            a=method['summary'][symbol];b=a['到達']['0.10']
            expected_cells.append([f'候補{method["number"]}',symbol,str(a['新規数']),f'{a["最大順行"]["中央値"]:,.2f}',f'{a["最大順行割合"]["中央値"]*100:.1f}%',
                f'{a["最大順行前の逆行"]["中央値"]:,.2f}',f'{a["一呼値順行率"]*100:.1f}%',f'{b["順行到達率"]*100:.1f}% ({b["順行到達"]})',
                f'{b["逆行到達率"]*100:.1f}% ({b["逆行到達"]})',f'{b["全入口での順行先着率"]*100:.1f}% ({b["順行先着"]})'])
    for method in packet['methods']:
        for symbol in ('TOPIX','NK225'):
            a=method['summary'][symbol]
            display=[f'候補{method["number"]} {symbol}']
            for label in ('0.05','0.10','0.20'):
                b=a['到達'][label]
                display.extend([f'{b["順行到達率"]*100:.1f}%',f'{b["全入口での順行先着率"]*100:.1f}%'])
            expected_cells.append(display)
    assert cells==expected_cells
    same(json.loads((PUBLIC / '最大順行と入口採点.json').read_text(encoding='utf-8')),packet)
    assert hashlib.sha256((HERE/'entry_extent.py').read_bytes()).hexdigest()==frozen['コードSHA']
    for path,sha in frozen['入力SHA'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    report=dict(結論='元281新規が不変。最大順行・初回最大値前逆行・全逆行・3幅到達先着・分布・HTML12行が別式と一致',
        新規判断数=281,除外数=0,最大幅等の照合項目数=checked_fields,幅ごとの採点数=checked_labels,
        集計群=6,分布集計数=30,到達先着集計数=18,HTML表行数=12,主表=summaries,
        留意点=['セッション末まで一度でも進んだ到達率であり、どちらに先に進むかを当てた率や実決済勝率と区別する。',
        '候補3のNK 0.10%順行到達22/23=95.7%には先に同幅逆行した入口が含まれる。同幅順行先着14/23=60.9%。',
        '最大順行の中央値と最大値前逆行の中央値は別々の分布であり、二つを割った数値を平均取引の損益比として解釈しない。',
        '実際の返済後の価格も含む事後経路。最大値そのものを未来の入口条件には使わず、最大値で全部を利確した実現利益も計算していない。',
        '保存された同一場の通常区間末が評価終端。無期限・次セッション以降の将来限界ではない。',
        '25場の選定済み候補での観測であり、一般的に優位な入口や未知将来の高精度を確立したものではない。'],
        検査コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'限界値の独立検査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','新規判断数','除外数','最大幅等の照合項目数','幅ごとの採点数','集計群','HTML表行数')},ensure_ascii=False))


if __name__=='__main__':
    main()
