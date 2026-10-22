"""実市場と無関係な三十六配分を作り、順位・枚数対照・全場表示を検査する。"""

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

import report_v3 as R


HERE = Path(__file__).resolve().parent
COUNTS = {}


def check(value: bool, label: str) -> None:
    """
    機能: 人工の期待値と表示の一致を件数付きで記録する。
    引数: value(bool)は一致条件、label(str)は検査項目。
    返り値: None。不一致はAssertionErrorとする。
    """
    assert value, label
    COUNTS[label] = COUNTS.get(label, 0) + 1


def fixture() -> dict:
    """
    機能: 六入口・三配分・二追尾幅・四十場の完全合成会計を作る。
    引数: なし。
    返り値: dictは金融結果予定schemaと同じ形の人工値。
    """
    scenes = [str(date(2032, 1, 1) + timedelta(days=i//2)) + ('_Day' if i%2 == 0 else '_Night') for i in range(40)]
    specs = []
    for family in range(6):
        for mode in range(3):
            for trail in (.5, 1.):
                ident = f'F{family}_M{mode}_T{int(trail*10)}'
                specs.append(dict(id=ident, family=f'F{family}', entry_id=f'F{family}',
                    name='合成入口'+str(family)+'・配分'+str(mode)+'・追尾'+str(trail),
                    description='過去の公開値で方向と復帰を確認します。',
                    allocation_mode=mode, allocation_name=('20%固定', '100%固定', '順行増加')[mode], trail_multiple=trail))
    runs = []
    for k, spec in enumerate(specs):
        for i, scene in enumerate(scenes):
            for symbol in R.SYMBOLS:
                cap = 10 if symbol == 'TOPIX' else 20
                initial = cap if spec['allocation_mode'] == 1 else cap//5
                net = 200.+k if 4 <= i < 32 else -40. if i >= 32 else 0.
                active = i >= 4
                fee = 2*int(initial*(41.8 if symbol == 'TOPIX' else 11.)) if active else 0
                runs.append(dict(method=spec['id'], session=scene, symbol=symbol, net=net, realized=net,
                    profit=max(net, 0), loss=max(-net, 0), fees=fee,
                    max_drawdown=80. if active else 0, parents=int(active), wins=int(net>0), losses=int(net<0),
                    closed_quantity=initial if active else 0, fills=2 if active else 0, unclosed=0,
                    canceled=0, halted=0, protected_fallbacks=None, protected_wait_rows=None, rejected_entries=None,
                    max_quantity=(cap if spec['allocation_mode'] == 2 else initial) if active else 0,
                    initial_quantity_min=initial if active else None, initial_quantity_max=initial if active else None,
                    add_fills=3 if active and spec['allocation_mode'] == 2 else 0))
    return dict(sessions=scenes, splits={'全40':scenes}, specs=specs, runs=runs,
        source_SHA256={'完全合成源':'c'*64}, episodes=[], cache=[])


def shown(value: float | None, signed: bool = False) -> str:
    """
    機能: 表示の独立期待文字列を作る。
    引数: value(float|None)は人工値、signed(bool)は符号の指定。
    返り値: strは円表示又は未評価記号。
    """
    if value is None:
        return '—'
    if abs(value) < 1e-7:
        return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def reject(call: object, label: str) -> None:
    """
    機能: 不完全な会計や仕様を成功の表示へ変えず拒否することを確認する。
    引数: call(Callable[[],object])は人工の呼出、label(str)は検査名。
    返り値: None。
    """
    try:
        call()
    except (AssertionError, ValueError, KeyError):
        check(True, label)
    else:
        raise AssertionError(label)


def main() -> None:
    """
    機能: 実結果未読で全表示・共通順位・配分対照を検査して証跡を保存する。
    引数: なし。
    返り値: None。人工用フォルダへだけ出力する。
    """
    folder = HERE/'report_fixture/public'
    target = HERE/'report_fixture/全三十六共通規則と三配分及び全場表示の純人工.json'
    assert not target.exists()
    data = fixture()
    proof = R.generate(data, folder, 'b'*64, '合成専用/三配分.json', fixture=True)
    public = json.loads((folder/'data.json').read_text(encoding='utf8'))
    html = (folder/R.HTML_NAME).read_text(encoding='utf8')
    page = BeautifulSoup(html, 'html.parser')
    check(len(public['common_ranking']) == 36 and len(public['cases']) == 36, '全三十六を除外せず共通比較')
    check(len(public['main_ids']) == len({public['cases'][i]['spec']['family'] for i in public['main_ids']}) == 3, '主三つの異入口家族')
    check(len(public['sizing_comparisons']) == 24, '十二同入口同追尾幅の二商品比較')
    source = {(v['method'], v['session'], v['symbol']):v for v in data['runs']}
    tables = page.select('table.sessions')
    check(len(tables) == 39 and {t['data-method'] for t in tables} == set(public['cases']), '主三再掲と全条件の表')
    for table in tables:
        ident = table['data-method']
        check(len(table.select('tbody tr')) == 40, '各表四十行')
        for scene, tr in zip(data['sessions'], table.select('tbody tr')):
            expected = []
            for symbol in R.SYMBOLS:
                r = source[ident, scene, symbol]
                expected.extend([shown(r['profit']), shown(r['loss']), shown(r['net'], True), str(r['parents']), shown(r['fees']), str(r['unclosed'])])
            check([td.get_text(strip=True) for td in tr.select('td')] == expected, '全場金額親数料金未返済')
        expected = []
        for symbol in R.SYMBOLS:
            values = [source[ident, scene, symbol] for scene in data['sessions']]
            expected.extend([shown(sum(r['profit'] for r in values)), shown(sum(r['loss'] for r in values)), shown(sum(r['net'] for r in values), True),
                str(sum(r['parents'] for r in values)), shown(sum(r['fees'] for r in values)), '0場'])
        check([td.get_text(strip=True) for td in table.select('tfoot td')] == expected, '全場合計の独立足算')
    for ident, case in public['cases'].items():
        mode = case['spec']['allocation_mode']
        for symbol in R.SYMBOLS:
            values = [source[ident, scene, symbol] for scene in data['sessions']]
            m = case['metrics'][symbol]
            check(m['inactive'] == 4 and m['black'] == 28 and m['red'] == 8, '無取引を勝ちに加えない')
            check(m['max_quantity'] == max(r['max_quantity'] for r in values), '実最大枚数の集計')
            check(m['add_fills'] == sum(r['add_fills'] for r in values), '追加約定は枚数と区別')
            initial = (10 if symbol == 'TOPIX' else 20) if mode == 1 else (2 if symbol == 'TOPIX' else 4)
            check(m['initial_quantity_known'] and m['initial_quantity_min'] == m['initial_quantity_max'] == initial, '無取引場のnullを初回零枚としない')
    for comparison in public['sizing_comparisons']:
        ids = comparison['methods'];symbol = comparison['symbol']
        nets = {int(mode):sum(source[ident, scene, symbol]['net'] for scene in data['sessions']) for mode, ident in ids.items()}
        check(comparison['grow_minus_scout'] == nets[2]-nets[0] and comparison['grow_minus_full'] == nets[2]-nets[1], '両固定対照への収支差')
    text = page.get_text(' ', strip=True)
    check('追加だけの独立寄与ではありません' in text and '未知検証ではありません' in text, '増加因果と既知開発の留保')
    check('TOPIXミニ10枚' in text and '日経マイクロ20枚' in text, '実数量上限の表示')
    check('実最大枚数' in text and '初回枚数' in text and '追加約定数' in text, '枚数と追加の説明')
    check(not page.select('script[src],img[src]'), '外部通信なし')
    # ----------------------------------------
    # 円額の倍率と不活動は共通順位の成功判定を恣意的に変えない。
    scaled = deepcopy(data)
    for row in scaled['runs']:
        if row['symbol'] == 'NK225':
            for key in R.MONEY:
                row[key] *= 1_000_000
    _, scaled_public, _ = R.render(scaled, 'd'*64, '合成専用')
    check([r['id'] for r in public['common_ranking']] == [r['id'] for r in scaled_public['common_ranking']], '円倍率で共通順位を変えない')
    check(public['main_ids'] == scaled_public['main_ids'], '円倍率で主三家族を変えない')
    failed = deepcopy(data)
    for row in failed['runs']:
        row.update(net=0., realized=0., profit=0., loss=0., parents=0, wins=0, losses=0, closed_quantity=0,
            fees=0., max_drawdown=0., fills=0, max_quantity=None, initial_quantity_min=None, initial_quantity_max=None, add_fills=None)
    doc, quiet, _ = R.render(failed, 'e'*64, '合成専用')
    check(quiet['qualification_count'] == 0 and '<strong>毎セッションの安定黒字は未達です。</strong>' in doc, '無活動に太字未達')
    check(all(v['metrics'][s]['black'] == 0 and v['metrics'][s]['inactive'] == 40 and v['metrics'][s]['max_quantity'] is None and v['metrics'][s]['add_fills'] is None for v in quiet['cases'].values() for s in R.SYMBOLS), '未保存数量と活動なしを成功にしない')
    bad = deepcopy(data);bad['runs'].pop();reject(lambda:R.validate(bad), '欠場を拒否')
    bad = deepcopy(data);bad['specs'][0]['allocation_mode'] = 3;reject(lambda:R.validate(bad), '未定義配分を拒否')
    bad = deepcopy(data);bad['runs'][0]['max_quantity'] = 100;reject(lambda:R.validate(bad), '数量上限超過を拒否')
    bad = deepcopy(data);bad['runs'][0]['net'] += 1;reject(lambda:R.validate(bad), '親損益と場収支不一致を拒否')
    reject(lambda:R.generate(data, folder, 'b'*64, '合成専用', True), '既存出力の上書き拒否')
    result = dict(全合格=True, 範囲='三十六共通規則の人工だけ。実結果・原市場・金融を一切読まない。',
        検査件数=COUNTS, 総検査件数=sum(COUNTS.values()), 生成証跡=proof,
        source_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'report_v3.py', Path(__file__))},
        実結果読取=0, 原市場読取=0, 金融再生=0, API=0)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps(dict(全合格=True, 検査件数=sum(COUNTS.values()), SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
