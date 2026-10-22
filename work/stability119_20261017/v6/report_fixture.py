"""実測を読まず、旧六十六引用と新十四口座の表示と欠測を合成検査する。"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

import report_v6 as R


HERE = Path(__file__).resolve().parent
OUT = HERE / 'report_fixture'
COUNTS = Counter()


def check(value: bool, label: str) -> None:
    """
    機能: 合成値の独立期待と表示の一致を記録する。
    引数: value(bool)は期待、label(str)は検査項目。
    返り値: None。不一致なら停止する。
    """
    assert value, label
    COUNTS[label] += 1


def fixture() -> dict:
    """
    機能: 零取引・赤字・低活動・旧未保存終端を持つ完全合成会計を作る。
    引数: なし。
    返り値: dictは四十場八十行。市場や金融を読み込まない。
    """
    scenes = [f'2034-01-{i // 2 + 1:02d}_' + ('Day' if i % 2 == 0 else 'Night') for i in range(40)]
    new = scenes[-7:]
    rows = []
    for i, scene in enumerate(scenes):
        for s in R.SYMBOLS:
            net = 100 + i if (s == 'TOPIX' and i % 5 == 0 or s == 'NK225' and i % 3 != 0) else 0
            if i in (35, 39):
                net = -310 - i
            n = int(net != 0)
            rows.append(dict(session=scene, symbol=s, method=R.METHOD, actual_config=R.ACTUAL[s], profit=max(net, 0),
                loss=max(-net, 0), net=net, campaigns=n, winning_campaigns=int(net > 0), losing_campaigns=int(net < 0),
                winning_lots=2 * int(net > 0), losing_lots=3 * int(net < 0), fees=83 * n,
                origin='追加七場の新金融' if scene in new else '旧33保存会計の引用', unclosed=0 if scene in new else None))
    return dict(method=R.METHOD, actual_config=R.ACTUAL, sessions=scenes, new_sessions=new, rows=rows,
        old_reference=dict(path='完全合成/旧保存会計.json', SHA256='a' * 64), source_SHA256={'完全合成/経済源.py': 'b' * 64})


def main() -> None:
    """
    機能: 一政策の全行・旧新内訳・未保存・非採用を独立期待で検査する。
    引数: なし。
    返り値: None。合成専用出力と証跡だけを新設する。
    """
    OUT.mkdir(exist_ok=True)
    target = OUT / '商品別固定一組と旧引用及び追加七場の純表示検査.json'
    assert not target.exists()
    data = fixture()
    generated = R.generate(data, OUT / 'public', 'c' * 64, '完全合成/少額固定設定.json', True)
    public = json.loads((OUT / 'public/data.json').read_text(encoding='utf8'))
    page = BeautifulSoup((OUT / 'public' / R.HTML_NAME).read_text(encoding='utf8'), 'html.parser')
    check(generated['fixture'] is True and generated['policies'] == 1, '商品固定二設定は一つの組合わせ')
    check(generated['reused_account_rows'] == 66 and generated['new_accounts'] == 14, '旧六十六引用と新十四を区別')
    check(len(page.select('table.sessions tbody tr')) == 80, '四十場両商品を全掲載')
    check(len(page.select('table.summary tbody tr')) == 2 and len(page.select('table.periods tbody tr')) == 4, '全期二行と旧新四行')
    case = public['cases'][R.METHOD]
    for tr, row in zip(page.select('table.sessions tbody tr'), data['rows']):
        expect = [row['symbol'], '追加7' if row['session'] in data['new_sessions'] else '旧33引用', R.fmt(row['profit']),
            R.fmt(row['loss']), R.fmt(row['net'], True), R.fmt(row['fees']), str(row['winning_lots']), str(row['losing_lots']),
            str(row['campaigns']), '未保存' if row['unclosed'] is None else str(row['unclosed'])]
        check(tr['data-session'] == row['session'] and tr['data-symbol'] == row['symbol'] and [c.get_text(strip=True) for c in tr.select('td')] == expect, '全八十行の金額料金枚数と未保存')
    for symbol in R.SYMBOLS:
        for period, scenes in (('全40', data['sessions']), ('旧33引用', data['sessions'][:-7]), ('追加7新規', data['new_sessions'])):
            own = [r for r in data['rows'] if r['symbol'] == symbol and r['session'] in scenes]
            m = case['metrics'][symbol] if period == '全40' else case['periods'][period][symbol]
            for key in ('profit', 'loss', 'net', 'fees', 'winning_lots', 'losing_lots'):
                check(m[key] == sum(r[key] for r in own), '旧新商品別の独立再加算')
            check(m['parents'] == sum(r['campaigns'] for r in own), '親数を枚数と混同しない')
            expect = sum(r['net'] for r in own) - sum(sorted([r['net'] for r in own if r['net'] > 0], reverse=True)[:3])
            check(m['top3_removed'] == expect, '上位三黒字除外の独立算数')
        check(case['metrics'][symbol]['unclosed_unknown_sessions'] == 33 and case['metrics'][symbol]['zero_lots'] is None, '旧終端と零枚数を零補完しない')
    top = case['metrics']['TOPIX']
    check(top['median'] == 0 and top['black'] > 0 and top['red'] == 2, '低活動中央値零を全赤字と呼ばない')
    check(public['qualification_count'] == 0 and '<strong>毎セッションの安定黒字は未達です。</strong>' in str(page), '未達は未達を太字表示')
    text = page.get_text(' ', strip=True)
    for phrase in ('商品別の閾値が異なる', '新たな実行は追加7場14口座だけ', '旧33を新証拠へ数え直しません', '低活動による中央値0円と赤字は区別', '実小型商品の最小呼値と混同しません'):
        check(phrase in text, '比較範囲と呼値の限界を明示')
    check(not page.select('script[src],img[src]'), '外部通信なし')
    damaged = deepcopy(data)
    damaged['rows'][0]['net'] += 1
    try:
        R.validate(damaged)
    except AssertionError:
        check(True, '改竄金額拒否')
    else:
        raise AssertionError('改竄金額拒否')
    duplicated = deepcopy(data)
    duplicated['rows'][-1] = duplicated['rows'][0]
    try:
        R.validate(duplicated)
    except AssertionError:
        check(True, '重複場商品拒否')
    else:
        raise AssertionError('重複場商品拒否')
    proof = dict(passed=True, scope='完全合成の表示・再加算だけ。実測又は経済エンジンの検証ではない。', counts=dict(COUNTS),
        total_checks=sum(COUNTS.values()), generation=generated,
        source_SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE / 'report_v6.py', Path(__file__))},
        actual_result_reads=0, market_reads=0, financial_replay=0, API=0)
    target.write_bytes(R.encoded(proof))
    print(json.dumps(dict(passed=True, checks=sum(COUNTS.values()), sha256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
