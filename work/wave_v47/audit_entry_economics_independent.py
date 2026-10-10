"""入口114条件の保存台帳を、再生器の集計関数を使わず独立照合する。"""

from __future__ import annotations

import ast
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASES = ('A0__V000', 'G000_F25_N1__V000', 'G150_F50_N1__V000')
SYMBOLS = ('TOPIX', 'NK225')
FIELDS = ('gross_profit_yen', 'gross_loss_yen', 'net_yen',
          'profit_units', 'loss_units', 'zero_units', 'closed_units')
REFERENCES: dict[str, str] = {}
COUNTS = defaultdict(int)


def digest(path: Path) -> str:
    """機能: 読み込んだ証拠の指紋を記録する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8388608):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> object:
    """機能: 明示した旧条件証拠だけを読み、追加ナイトを拒否する。

    引数: path (Path)。返り値: JSON内容 (object)。
    複合口座資料・新入力・追加ナイト結果を監査範囲へ混入させない。
    """
    assert not path.name.startswith(('new_', 'combined_', '追加', '統合'))
    assert path.suffix in ('.json', '.gz')
    raw = path.read_bytes()
    value = json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)
    REFERENCES[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
    return value


def equal(left: float | None, right: float | None, label: str) -> None:
    """機能: 有限数又は未定義値を独立計算結果と照合する。

    引数: left/right (float|None)、label (str)。返り値: なし (None)。
    """
    if left is None or right is None:
        assert left is right, (label, left, right)
        return
    assert abs(left - right) <= max(1e-6, 1e-10 * max(abs(left), abs(right))), (label, left, right)
    COUNTS['数式照合項目数'] += 1


def tree_equal(left: object, right: object, label: str) -> None:
    """機能: 旧中央結果の全保存列を型別に照合する。

    引数: left/right (object)、label (str)。返り値: なし (None)。
    """
    if isinstance(left, dict):
        assert isinstance(right, dict) and left.keys() == right.keys(), label
        for key in left:
            tree_equal(left[key], right[key], label + '/' + key)
    elif isinstance(left, list):
        assert isinstance(right, list) and len(left) == len(right), label
        for index, (a, b) in enumerate(zip(left, right)):
            tree_equal(a, b, label + '/' + str(index))
    elif isinstance(left, (float, int)) and not isinstance(left, bool):
        equal(left, right, label)
    else:
        assert left == right, (label, left, right)


def session_formula(ledger: dict, row: dict) -> dict:
    """機能: 返済脚と注文キャッシュフローの別経路で一口座を検算する。

    引数: ledger/row (dict)。返り値: 独立した損益・枚数・元組一覧 (dict)。
    再生器・既存監査・既存集計の実行関数は呼ばない。
    """
    symbol = ledger['symbol']
    mult = {'TOPIX': 1000., 'NK225': 10.}[symbol]
    equal(ledger['config']['point_value'], mult, '銘柄倍率')
    assert ledger['config']['initial_qty'] == {'TOPIX': 5, 'NK225': 10}[symbol]
    assert ledger['config']['audit_cap'] == {'TOPIX': 10, 'NK225': 20}[symbol]
    result = dict.fromkeys(FIELDS, 0.)
    cycle_money = defaultdict(float)
    repayment_groups = defaultdict(float)
    trade_quantities = defaultdict(float)
    for trade in ledger['trades']:
        assert len(trade) == 11
        campaign, leg, side, quantity, initial, final, start, end, kind, reason, saved = trade
        assert side in (-1, 1) and quantity > 0 and quantity == int(quantity)
        assert end >= start and start >= 0
        points = side * quantity * (final - initial)
        equal(points, saved, '返済脚ポイント')
        money = points * mult
        category = 'profit' if money > 0 else 'loss' if money < 0 else 'zero'
        result[category + '_units'] += quantity
        if money > 0:
            result['gross_profit_yen'] += money
        elif money < 0:
            result['gross_loss_yen'] -= money
        cycle_money[campaign] += money
        repayment_groups[campaign, end, -side, final, reason] += quantity
        trade_quantities[campaign, side] += quantity
    result['net_yen'] = result['gross_profit_yen'] - result['gross_loss_yen']
    result['closed_units'] = sum(result[key] for key in ('profit_units', 'loss_units', 'zero_units'))
    # ----------------------------------------
    # 注文列から売り受取－買い支払を直接計算し、返済脚の建値対応とも照合する。
    cash = 0.
    inventory = defaultdict(float)
    opens = defaultdict(float)
    closes = defaultdict(float)
    order_groups = defaultdict(float)
    maximum = {1: 0., -1: 0.}
    previous_row = -1
    for order in ledger['orders']:
        row_number, source, campaign, side, quantity, price, reason, opening = order
        assert side in (-1, 1) and quantity > 0 and quantity == int(quantity)
        assert row_number >= previous_row and source < row_number
        previous_row = row_number
        assert opening in (0, 1)
        cash -= side * quantity * price * mult
        held_side = side if opening else -side
        key = (campaign, held_side)
        if opening:
            opens[key] += quantity
            inventory[key] += quantity
        else:
            closes[key] += quantity
            inventory[key] -= quantity
            assert inventory[key] >= 0, ('過剰返済', key)
            order_groups[campaign, row_number, side, price, reason] += quantity
        for direction in (1, -1):
            now = sum(value for (_, d), value in inventory.items() if d == direction)
            maximum[direction] = max(maximum[direction], now)
            assert now <= {'TOPIX': 10, 'NK225': 20}[symbol]
    assert all(value == 0 for value in inventory.values()), '場末残玉'
    assert dict(opens) == dict(closes) == dict(trade_quantities), '新規返済枚数保存'
    assert dict(repayment_groups) == dict(order_groups), '返済脚と注文価格数量'
    equal(cash, result['net_yen'], '注文キャッシュフロー')
    equal(sum(closes.values()), result['closed_units'], '全注文返済枚数')
    equal(maximum[1], row['max_long'], '最大買枚数')
    equal(maximum[-1], row['max_short'], '最大売枚数')
    # ----------------------------------------
    # 元組集計も脚の純損益から作り直し、上位二組除外を脚単位と取り違えない。
    assert len(ledger['cycles']) == len(cycle_money)
    net_r = 0.
    for cycle in ledger['cycles']:
        assert len(cycle) == 10
        equal(cycle_money[cycle[0]], cycle[3] * mult, '元組純損益')
        assert cycle[4] > 0
        net_r += cycle_money[cycle[0]] / (cycle[4] * mult)
    values = list(cycle_money.values())
    result.update(cycles=len(values), cycle_wins=sum(v > 0 for v in values),
        cycle_losses=sum(v < 0 for v in values),
        cycle_profit_yen=sum(v for v in values if v > 0),
        cycle_loss_yen=-sum(v for v in values if v < 0), net_r=net_r)
    for key, value in result.items():
        equal(value, row[key], 'セッション/' + key)
    top = sorted((v for v in values if v > 0), reverse=True)[:2]
    tree_equal(top, row['two_largest_cycle_profits'], '上位二組')
    result['cycle_values'] = values
    COUNTS['返済脚数'] += len(ledger['trades'])
    COUNTS['注文数'] += len(ledger['orders'])
    COUNTS['元組数'] += len(values)
    COUNTS['口座数'] += 1
    return result


def period_formula(chosen: list[dict], summary: dict, assessment: dict) -> None:
    """機能: セッション検算値から全期間・後半の集計と採否を照合する。

    引数: chosen (list[dict])、summary/assessment (dict)。返り値: なし (None)。
    """
    additive = FIELDS + ('cycles', 'cycle_wins', 'cycle_losses', 'cycle_profit_yen', 'cycle_loss_yen', 'net_r')
    for key in additive:
        expected = sum(item[key] for item in chosen)
        equal(expected, summary[key], '期間/' + key)
        equal(expected, assessment[key], '判定期間/' + key)
    gp, gl = summary['gross_profit_yen'], summary['gross_loss_yen']
    win, loss = summary['profit_units'], summary['loss_units']
    payoff = (gp / win) / (gl / loss) if win and loss and gl else None
    equal(payoff, summary['average_unit_payoff'], '一枚勝敗比')
    equal(payoff, assessment['average_unit_payoff'], '判定一枚勝敗比')
    top = sorted((v for item in chosen for v in item['cycle_values'] if v > 0), reverse=True)[:2]
    removed = sum(item['net_yen'] for item in chosen) - sum(top)
    equal(removed, assessment['top2_removed'], '期間上位二組除外')
    expected_pass = summary['net_yen'] > 0 and payoff is not None and payoff > 1 and removed > 0
    assert assessment['基礎合格'] == expected_pass
    COUNTS['期間銘柄セル数'] += 1


def report_functions() -> dict:
    """機能: 報告器から入口向け純粋関数だけを抽出して呼び出せる状態にする。

    引数: なし。返り値: 表示集計の名前空間 (dict)。
    mainやimportを実行せず、新ナイト・統合損益・他部品結果へアクセスしない。
    """
    path = HERE / 'financial_report.py'
    source = path.read_text(encoding='utf-8')
    REFERENCES[path.relative_to(ROOT).as_posix()] = digest(path)
    tree = ast.parse(source)
    names = {'minimal', 'display_rows', 'entry_description'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == 3
    space = {'FIELDS': FIELDS[:-1]}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), space)
    assert '先行価格' not in source and 'forward/' not in source and 'forward_actual/' not in source
    assert "component_signals.catalog()+warm_component_signals.catalog()" in source
    assert "rows=read('entry_sessions/'+identifier+'.json.gz')" in source
    return space


def main() -> None:
    """機能: 全114条件を独立監査して専用JSONだけへ証拠を保存する。

    引数: なし。返り値: なし (None)。原コード・経済結果・公表資料は編集しない。
    """
    reset_fixed = read(HERE / '入口経済比較の固定.json')
    warm_fixed = read(HERE / '暖機経済比較の固定.json')
    reset_signals = read(HERE / 'component_signals_fixed.json')
    warm_signals = read(HERE / 'warm_signals_fixed.json')
    reset_eval = read(HERE / 'entry_assessment.json')
    warm_eval = read(HERE / 'warm_assessment.json')
    old_fixed = read(HERE.parent / 'wave_v38/探索条件の固定.json')
    sessions = old_fixed['全セッション']
    later = set(old_fixed['後半7セッション'])
    assert len(sessions) == 13 and len(later) == 7 and '2026-09-29_Night' not in sessions
    expected_keys = {(session, symbol) for session in sessions for symbol in SYMBOLS}
    assert reset_fixed['管理条件'] == warm_fixed['管理条件'] == list(BASES)
    assert reset_fixed['条件数'] == 78 and warm_fixed['条件数'] == 36
    assert reset_fixed['入口条件'] == reset_signals['条件']
    assert warm_fixed['条件'] == warm_signals['条件']
    specs = reset_fixed['入口条件'] + warm_fixed['条件']
    assert len(specs) == 38 and len({v['id'] for v in specs}) == 38
    for path, expected in reset_fixed['参照SHA256'].items():
        assert digest(ROOT / path) == expected, ('凍結指紋', path)
    assert digest(HERE / 'replay_parts.py') == warm_fixed['経済実装SHA256']
    assert digest(HERE / 'warm_signals_fixed.json') == warm_fixed['暖機信号固定SHA256']
    for fixed in (reset_signals, warm_signals):
        for path, expected in fixed['入口保存列SHA256'].items():
            assert digest(ROOT / path) == expected, path
    # ----------------------------------------
    # 完了ファイルと実データの集合一致を先に要求し、成績による欠落を許さない。
    expected_ids = {spec['id'] + '__' + base for spec in specs for base in BASES}
    assert {p.stem for p in (HERE / 'entry_completed').glob('*.json')} == {spec['id'] for spec in specs}
    for folder, suffix in (('entry_ledgers', '.json.gz'), ('entry_sessions', '.json.gz'),
                           ('entry_audits', '.json.gz'), ('entry_summaries', '.json')):
        assert {p.name[:-len(suffix)] for p in (HERE / folder).glob('*' + suffix)} == expected_ids, folder
    assert len(expected_ids) == 114
    assessments = {(r['id'], r['period'], r['symbol']): r
                   for value in (reset_eval, warm_eval) for r in value['期間銘柄セル']}
    assert len(assessments) == 456
    report = report_functions()
    verified_rows = {}
    old_central = {}
    for base in BASES:
        old_central[base] = {(r['session'], r['symbol']): r for r in read(HERE.parent / 'wave_v45/ledgers' / (base + '.json.gz'))}
    for spec in specs:
        done = read(HERE / 'entry_completed' / (spec['id'] + '.json'))
        assert done['全合格'] and done['入力会計数'] == 78 and done['入口'] == spec['id']
        assert set(done['条件']) == {spec['id'] + '__' + base for base in BASES}
        for base in BASES:
            identifier = spec['id'] + '__' + base
            rows = read(HERE / 'entry_sessions' / (identifier + '.json.gz'))
            ledgers = read(HERE / 'entry_ledgers' / (identifier + '.json.gz'))
            summary = read(HERE / 'entry_summaries' / (identifier + '.json'))
            proofs = read(HERE / 'entry_audits' / (identifier + '.json.gz'))
            assert summary['id'] == identifier and summary['entry'] == spec and summary['base_id'] == base and summary['全合格']
            lookup = {(r['session'], r['symbol']): r for r in rows}
            assert len(rows) == len(ledgers) == len(proofs) == 26
            assert set(lookup) == expected_keys == {(r['session'], r['symbol']) for r in ledgers}
            assert {(r['session'], r['symbol']) for r in proofs} == expected_keys
            own = {}
            for ledger in ledgers:
                key = ledger['session'], ledger['symbol']
                own[key] = session_formula(ledger, lookup[key])
                verified_rows[identifier, *key] = own[key]
                if spec['id'] == 'M100_S100_P1_C1_D100':
                    prior_ledger = old_central[base][key]
                    assert prior_ledger.keys() - ledger.keys() == {'shadow_fingerprints', 'gate_fingerprints', 'arm_events'}
                    assert not ledger.keys() - prior_ledger.keys()
                    tree_equal(ledger, {name: prior_ledger[name] for name in ledger}, '中央旧共通台帳全列/' + base)
                    COUNTS['中央旧全台帳一致数'] += 1
            if spec['id'] == 'M100_S100_P1_C1_D100':
                prior = read(HERE.parent / 'wave_v45/summaries' / (base + '.json'))
                for period in ('all_symbols', 'symbols'):
                    tree_equal(summary[period], prior[period], '中央旧期間/' + base)
            for period in ('all_symbols', 'symbols'):
                for symbol in SYMBOLS:
                    chosen = [value for (session, sym), value in own.items() if sym == symbol and (period == 'all_symbols' or session in later)]
                    assert len(chosen) == (13 if period == 'all_symbols' else 7)
                    period_formula(chosen, summary[period][symbol], assessments[identifier, period, symbol])
            # ----------------------------------------
            # 入口のHTML用純粋関数で週・全期間表示を作り、検算済み口座値と再照合する。
            display = report['display_rows'](rows)
            assert len(display) == 32
            for view in display:
                if not view['total']:
                    continue
                chosen = [value for (session, symbol), value in own.items() if symbol == view['symbol'] and
                          (view['label'].startswith('全') or
                           view['label'].startswith('第1週') and session[:10] <= '2026-09-25' or
                           view['label'].startswith('第2週') and session[:10] >= '2026-09-28')]
                for field in FIELDS[:-1]:
                    equal(sum(r[field] for r in chosen), view[field], '表示週全期間/' + field)
                COUNTS['表示週全期間行数'] += 1
            description = report['entry_description'](spec)
            v = spec['reset'] if 'reset' in spec else spec
            assert f"EMA{round(15*v['main_scale'])}/{round(60*v['main_scale'])}" in description
            if v['short_confirm']:
                assert f"短期{round(30*v['short_scale'])}秒" in description
            else:
                assert '保持時間も変化' in description
    # ----------------------------------------
    # 判定の主窓近傍は短期窓固定、相手遅延の二条件は近傍三点へ混入させない。
    for value, count in ((reset_eval, 24), (warm_eval, 12)):
        assert len(value['主時計領域']) == count
        for region in value['主時計領域']:
            selected = [spec for spec in specs if spec['id'] in region['members']]
            values = [spec['reset'] if 'reset' in spec else spec for spec in selected]
            assert len(values) == 3 and {v['main_scale'] for v in values} == {.8, 1., 1.2}
            assert len({v['short_scale'] for v in values}) == len({v['short_confirm'] for v in values}) == len({v['peer_confirm'] for v in values}) == 1
            assert {v['peer_scale'] for v in values} == {1.}
            group = [assessments[member + '__' + region['base_id'], period, symbol]
                     for member in region['members'] for period in ('all_symbols', 'symbols') for symbol in SYMBOLS]
            assert region['全12セル合格'] == all(row['基礎合格'] for row in group)
            COUNTS['主窓固定近傍領域数'] += 1
    # ----------------------------------------
    # 全セッション対応差を保存口座ではなく独立再計算値に突き合わせる。
    def entry_id(main: float, short: float, peer: bool, confirm: bool) -> str:
        """機能: 対応比較の識別子を単純な固定書式で再構成する。

        引数: main/short (float)、peer/confirm (bool)。返り値: 入口ID (str)。
        """
        return f'M{round(main*100):03d}_S{round(short*100):03d}_P{int(peer)}_C{int(confirm)}_D100'
    for pair in reset_eval['対応差']:
        if pair['部品'] == '相手あり－なし':
            short = pair['短期倍率']
            a = entry_id(pair['主倍率'], short or 1., True, short is not None)
            b = entry_id(pair['主倍率'], short or 1., False, short is not None)
        else:
            assert pair['部品'] == '短期あり－なし'
            a = entry_id(pair['主倍率'], pair['短期倍率'], pair['相手あり'], True)
            b = entry_id(pair['主倍率'], 1., pair['相手あり'], False)
        av = verified_rows[a + '__' + pair['base_id'], pair['session'], pair['symbol']]
        bv = verified_rows[b + '__' + pair['base_id'], pair['session'], pair['symbol']]
        equal(av['net_yen'] - bv['net_yen'], pair['差円'], '部品対応差円')
        equal(av['net_r'] - bv['net_r'], pair['差R'], '部品対応差R')
        COUNTS['初期化対応差数'] += 1
    for pair in warm_eval['初期化とのセッション差']:
        av = verified_rows[pair['id'], pair['session'], pair['symbol']]
        bv = verified_rows[pair['reset_id'], pair['session'], pair['symbol']]
        for field, suffix in (('net_yen', '収支円'), ('gross_profit_yen', '利益円'), ('gross_loss_yen', '損失円')):
            equal(av[field] - bv[field], pair['差' + suffix], '暖機対応差/' + suffix)
        COUNTS['暖機対応差数'] += 1
    assert COUNTS['口座数'] == 114 * 26 and COUNTS['中央旧全台帳一致数'] == 78
    assert COUNTS['期間銘柄セル数'] == 456 and COUNTS['表示週全期間行数'] == 684
    # ----------------------------------------
    # 検証中に他処理が根拠を上書きしていないことも最後に確かめる。
    for path, expected in REFERENCES.items():
        assert digest(ROOT / path) == expected, ('監査中変更', path)
    result = dict(全合格=True,監査範囲='reset78＋warm36、旧13場×2銘柄。新ナイト未読。',
        集計=dict(COUNTS),重大矛盾=[],
        検査=['全114条件・2964口座の保存集合完備', '方向×価格差×数量×銘柄倍率による返済脚集計',
              '注文現金差分の別経路一致・場末残玉0・新規返済数量保存', '中央78口座の旧共通保存列全部・実15配列指紋一致',
              '456期間銘柄セル・上位利益二元組除外・採否・全対応差一致',
              '主EMA窓と短期価格窓の分離・主窓三点では短期固定',
              '口座表示の旧13場・週集計照合。先行価格ラベルは損益入力に不使用'],
        限界=['値動き診断は予測のラベルであり口座利益ではない。元初回の選択効果と追跡単独の効果は区別する。',
              '短期確認の有無はTTLも変わるため価格方向情報だけの純寄与ではない。',
              'DDの全原本行再生は今回重複実行せず、既存全行会計監査と保存指紋を参照。',
              '旧台帳だけにあるshadow_fingerprints・gate_fingerprints・arm_eventsの三監査補助列は新台帳に未保存。実15配列指紋と共通経済保存列は全部一致。',
              '複数の仮説は既知13場に繰り返し適用されており、将来利益の確率保証にはならない。'],
        参照SHA256=REFERENCES,監査実装SHA256=digest(Path(__file__)),新ナイト読取=False)
    path = HERE / '入口経済114条件の独立監査.json'
    path.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True,集計=dict(COUNTS),重大矛盾=[]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
