"""完成元を再読せず、自身の公開小会計とHTML表示だけを照合する。"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
PUBLIC = BASE / 'privatev4/public'
TARGET = HERE / '全四十八と順逆時刻及び全四十場の実表示照合.json'
COUNTS = Counter()


def check(value: bool, label: str) -> None:
    """
    機能: 公開済みの小会計と表示の照合件数を記録する。
    引数: value(bool)は一致条件、label(str)は検査名。
    返り値: None。不一致ではAssertionErrorを送出する。
    """
    assert value, label
    COUNTS[label] += 1


def number(value: float | None, signed: bool = False) -> str:
    """
    機能: 表示値の期待文字列を独立に作る。
    引数: value(float|None)は保存値、signed(bool)は符号表示。
    返り値: strは千位区切り又は未評価記号。
    """
    if value is None:
        return '—'
    if abs(value) < 1e-7:
        return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def main() -> None:
    """
    機能: 完成元・原市場・金融を再読せず、生成済み全表を照合する。
    引数: なし。
    返り値: None。別証跡JSONだけを一度保存する。
    """
    assert not TARGET.exists()
    names = ['data.json', '順逆売買と時間回避の比較と全セッション損益.html', 'README.md', '生成証跡.json']
    contents = {name: (PUBLIC / name).read_bytes() for name in names}
    data = json.loads(contents['data.json'])
    page = BeautifulSoup(contents[names[1]].decode('utf8'), 'html.parser')
    expected_sha = '9da66161eeab6557dfca24070dcb32c38d6a23311dc1eb46d68465c4003c406a'
    check(data['source_SHA256'] == expected_sha, '指定元SHAの転載')
    cases = data['cases']
    check(len(cases) == 48 and len(data['sessions']) == 40, '全条件全場の保存')
    own_rows = {}
    metrics = {}
    for ident, case in cases.items():
        rows = case['rows']
        check(len(rows) == 80, '各条件二商品八十行')
        for row in rows:
            key = ident, row['session'], row['symbol']
            check(key not in own_rows, '同条件同場同商品重複なし')
            own_rows[key] = row
        for symbol in ('TOPIX', 'NK225'):
            values = [own_rows[ident, scene, symbol] for scene in data['sessions']]
            net = [r['net'] for r in values]
            black = [v for v in net if v > 1e-7]
            red = [v for v in net if v < -1e-7]
            absent = sum(r['parents'] == r['closed_quantity'] == r['unclosed'] == 0 and r['fees'] == r['net'] == 0 for r in values)
            p, loss = sum(r['profit'] for r in values), sum(r['loss'] for r in values)
            independently = dict(net=sum(net), profit=p, loss=loss, fees=sum(r['fees'] for r in values),
                parents=sum(r['parents'] for r in values), black=len(black), red=len(red), inactive=absent,
                median=statistics.median(net), worst=min(net), mean=statistics.mean(net),
                top3_removed=sum(net)-sum(sorted(black, reverse=True)[:3]),
                mean_abs_net=statistics.mean(abs(v) for v in net),
                unclosed_sessions=sum(r['unclosed'] > 0 for r in values), share=p/(p+loss) if p+loss else None)
            original = case['metrics'][symbol]
            for key, value in independently.items():
                check(original[key] is None if value is None else math.isclose(original[key], value, rel_tol=0, abs_tol=1e-7), '場集計の独立足算と中央値')
            metrics[ident, symbol] = independently
    # ----------------------------------------
    # 五十一表には主三条件の再掲があり、全四十八条件の四十行も必ず残る。
    tables = page.select('table.sessions')
    check(len(tables) == 51 and {t['data-method'] for t in tables} == set(cases), '主三再掲と全四十八表')
    for table in tables:
        ident = table['data-method']
        check(len(table.select('tbody tr')) == 40, '四十場の非省略')
        for scene, tr in zip(data['sessions'], table.select('tbody tr')):
            check(tr['data-session'] == scene, '場の順序')
            expected = []
            for symbol in ('TOPIX', 'NK225'):
                r = own_rows[ident, scene, symbol]
                expected.extend([number(r['profit']), number(r['loss']), number(r['net'], True), str(r['parents']), number(r['fees']), str(r['unclosed'])])
            check([td.get_text(strip=True) for td in tr.select('td')] == expected, '全場の金額親料金未返済表示')
        expected = []
        for symbol in ('TOPIX', 'NK225'):
            m = metrics[ident, symbol]
            expected.extend([number(m['profit']), number(m['loss']), number(m['net'], True), str(m['parents']), number(m['fees']), str(m['unclosed_sessions'])+'場'])
        check([td.get_text(strip=True) for td in table.select('tfoot td')] == expected, '全場フッターの独立合計')
    # ----------------------------------------
    # 集計四表の全八十六行も公開小会計から直接期待値を作る。
    summary = [t for t in page.select('table') if t.caption]
    allids=[r['id'] for r in data['common_ranking']]
    expected_pairs=[[(ident,symbol) for ident in data['main_ids'] for symbol in ('TOPIX','NK225')],
        [(ident,symbol) for ident in allids for symbol in ('TOPIX','NK225')]]
    check(len(summary)==2,'主表と全四十八集計表')
    for table,pairs in zip(summary,expected_pairs):
        trs=table.select('tbody tr');check(len(trs)==len(pairs),'集計表行数')
        for tr,(ident,symbol) in zip(trs,pairs):
            m=cases[ident]['metrics'][symbol]
            expected=[number(m['net'],True),f"{m['black']}/{m['red']}/{m['inactive']}",number(m['median'],True),number(m['worst'],True),number(m['top3_removed'],True),number(m['fees']),str(m['unclosed_sessions']),str(m['flat']),'—' if m['share'] is None else f"{m['share']*100:.1f}%"]
            check([td.get_text(strip=True) for td in tr.select('td')][2:]==expected,'全集計表金額頻度費用割合')
    check(len(allids)==48 and set(allids)==set(cases),'全四十八を共通順位対象')
    qualified=sum(all(metrics[ident,s]['net']>0 and metrics[ident,s]['median']>0 and metrics[ident,s]['top3_removed']>0 and metrics[ident,s]['unclosed_sessions']==0 for s in ('TOPIX','NK225')) for ident in cases)
    check(qualified==data['qualification_count']==0,'資格達成なしの独立確認')
    # ----------------------------------------
    # 円を商品間で足さず、固定順位と家族選択も別計算する。
    independent_rank=[]
    for ident,case in cases.items():
        pair=[metrics[ident,s] for s in ('TOPIX','NK225')]
        good=all(v['net']>0 and v['median']>0 and v['top3_removed']>0 and not v['unclosed_sessions'] for v in pair)
        normalized=[v['median']/v['mean_abs_net'] if v['mean_abs_net'] else None for v in pair]
        risks=[]
        for symbol in ('TOPIX','NK225'):
            net=[own_rows[ident,scene,symbol]['net'] for scene in data['sessions']]
            positives=[v for v in net if v>1e-7]
            risks.append(max([-v for v in net if v<-1e-7],default=0)/statistics.mean(positives) if positives else None)
        independent_rank.append((not good,-min(v['black'] for v in pair),-min(normalized) if all(v is not None for v in normalized) else math.inf,max(risks) if all(v is not None for v in risks) else math.inf,ident))
    expected_order=[r[-1] for r in sorted(independent_rank)]
    check(expected_order==allids,'共通順位の独立数式')
    selected=[];families=set()
    for ident in expected_order:
        family=cases[ident]['spec']['family']
        if family not in families:selected.append(ident);families.add(family)
        if len(selected)==3:break
    check(selected==data['main_ids'],'異なる元入口三つの独立選定')
    # ----------------------------------------
    # 一つの対照行に四通りを置き、順逆差と時刻差を別に検算する。
    comparisons=data['factor_comparisons'];tables=page.select('table.factors')
    check(len(comparisons)==24 and len(tables)==1 and len(tables[0].select('tbody tr'))==24,'因子対照二十四行')
    for item,tr in zip(comparisons,tables[0].select('tbody tr')):
        symbol=item['symbol'];nets={k:metrics[ident,symbol]['net'] for k,ident in item['methods'].items()}
        expected=[item['entry_id'],'対称1幅' if item['exit_mode']==5 else '0.5幅追尾','保護なし' if item['execution_mode']==0 else '両保護',symbol]
        expected.extend(number(nets[k],True) for k in ('direct_T0','reverse_T0','direct_T1','reverse_T1'))
        diffs=(nets['reverse_T0']-nets['direct_T0'],nets['reverse_T1']-nets['direct_T1'],nets['direct_T1']-nets['direct_T0'],nets['reverse_T1']-nets['reverse_T0'])
        expected.extend(number(v,True) for v in diffs)
        for key,value in zip(('reverse_minus_direct_time0','reverse_minus_direct_time1','avoid_minus_all_direct','avoid_minus_all_reverse'),diffs):check(item[key]==value,'四つの因子差を独立計算')
        check([td.get_text(strip=True) for td in tr.select('td')]==expected,'順逆と時刻の対照表示')
    text = page.get_text(' ', strip=True)
    check(page.find('strong', string='毎セッションの安定黒字は未達です。') is not None, '冒頭の太字未達')
    check('未知検証ではありません' in text and '無取引' in text and '勝ちに数えず' in text, '既知開発と無取引の限界')
    check(not page.select('script[src],img[src]'), '外部通信資産なし')
    check(any(a.get('href') == 'data.json' for a in page.select('a')), '公開小会計へのリンク')
    proof = dict(全合格=True, 範囲='自身の生成済み小会計とHTMLの一致。完成元JSON及び金融の独立正当性監査ではない。',
        検査件数=dict(COUNTS), 総検査件数=sum(COUNTS.values()), 商品場行=3840, 全場表=51,
        元結果追加読取=0, 原市場読取=0, 金融再生=0, API=0,
        元結果SHA256=expected_sha, 生成物SHA256={name:hashlib.sha256(raw).hexdigest() for name, raw in contents.items()},
        検査源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        結論='共通資格0/48。順逆と時間回避でも安定黒字未達。参考順位を未知検証成功としない。')
    TARGET.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps(dict(全合格=True, 検査件数=sum(COUNTS.values()), 証跡=str(TARGET), SHA256=hashlib.sha256(TARGET.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
