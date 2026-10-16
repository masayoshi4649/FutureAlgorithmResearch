"""E01の二商品差と固定16対照を、完成小会計だけから短い暗色HTMLへ表示する。"""

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HELPERS = ROOT/'work/wave_v106'
sys.path.insert(0, str(HELPERS))
import e01_trade_report
import goal_anchor_report
import risk_sizing_report

PUBLIC = ROOT/'アルゴリズム調査/00104_E01の銘柄差の原因と修正検証'
TITLE = 'E01の銘柄差と修正後の全セッション損益'
ACCOUNTING_TITLE = 'E01の銘柄差と固定16対照の公開会計.json'
BASE_ID = 'E01_ANCHOR_W60_CONFIRM_D0_P1_L2_A1'
MIDDLE_ID = 'E01_CROSS_B01'
INITIAL_ID = 'E01_CROSS_B03'
BASE_PLAN = HERE/'diagnosis/同母二商品差の診断固定計画.json'
CAUSE = HERE/'diagnosis/同母二商品43実親の原因射影.json'
ENTRY_FOLLOWUP = HERE/'entry_diagnosis/実公開票と事後逆行の追加射影.json'
FOLLOWUP_AGGREGATE = HERE/'判断に必要な昼夜活動と少数票及び途中逆行.json'
BASE_PLAN_SHA = 'a6bb77dce45c4a7325acb605d5c883e10837c9a06dc20947bbae8d39488dcf96'
CAUSE_SHA = 'e8451fd00380d04199072443f4f6c04e6561de039bad20e6b698a59a8279da73'
ENTRY_FOLLOWUP_SHA = 'bc44cdd7dbf0f69f737a559c9af0bd912fb3dca7d4722e8b5a884a3d028ded60'
FOLLOWUP_AGGREGATE_SHA = '06fbc8a7340c5b0873d17adb5ea4d7e2e51980940e5773ea9e86e98a9745feb7'
SYMBOLS = ('TOPIX', 'NK225')
LABELS = risk_sizing_report.LABELS
TESTS = risk_sizing_report.TESTS
FIVE = ('収支変化', '避けた基準損失', '失った基準利益', '共通入口の数量/出口差', '新たな入口の収支')
EXPECTED_COUNTS = dict(既input一読=33, 旧P1台帳一読=66, 保存GU再利用=66,
    新GUengine=264, 新政策会計=1056, 旧基準経済同値確認=66)


def read(path: Path) -> tuple:
    """
    機能: 完成小JSONを同bytesで読み、指紋へ結ぶ。
    引数: path(Path)は正式結果・計画・固定又は表示説明。
    返り値: tuple[dict,str]は内容とSHA256。packet・台帳・金融を読まない。
    """
    saved = path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')), hashlib.sha256(saved).hexdigest()


def money(value: float | None) -> str:
    """
    機能: 円額又は未定義値を表示する。
    引数: value(float|None)は完成会計の数値。
    返り値: strは桁区切り額又は「—」。未定義を0へ置換しない。
    """
    return '—' if value is None else f'{value:,.0f}'


def pct(value: float | None) -> str:
    """
    機能: 0〜1の割合を百分率へ変換する。
    引数: value(float|None)は金額又は場割合。
    返り値: strは百分率又は「未定義」。
    """
    return '未定義' if value is None else f'{100*value:.1f}%'


def cell(value: float | None, loss: bool = False) -> str:
    """
    機能: 円額を符号色と検算用数値付きで表示する。
    引数: value(float|None)、loss(bool)は保存額と正数損失の指定。
    返り値: strはtd。勝ち負け枚数は負数表示しない。
    """
    signed = None if value is None else -value if loss else value
    color = '' if signed is None or signed == 0 else 'negative' if signed < 0 else 'positive'
    numeric = '' if signed is None else repr(float(signed))
    return f'<td class="{color}" data-value="{numeric}">{money(signed)}</td>'


def summaries(rows: list) -> tuple:
    """
    機能: 全33場の三基準と上位三利益場除外を純集計する。
    引数: rows(list[dict])は保存66口座の共通表示schema。
    返り値: tuple[dict,dict]は全33と除外後。無取引を黒字に数えない。
    """
    return goal_anchor_report.summaries(rows)


def subset(rows: list, sessions: list) -> dict:
    """
    機能: 前16/後17など固定された場集合を純集計する。
    引数: rows(list[dict])、sessions(list[str])は完成行と時系列場名。
    返り値: dictは同商品指標。開発使用データを未見検証と呼ばない。
    """
    selected = [r for r in rows if r['session'] in set(sessions)]
    assert len(selected) == 2*len(sessions)
    return {s: goal_anchor_report.variable_summary(selected, s) for s in SYMBOLS}


def rank(case: dict) -> tuple:
    """
    機能: 同一条件が両商品で安定するかを優先して、群内の比較代表を選ぶ。
    引数: case(dict)は両商品の完成会計。
    返り値: tupleは比較順。利益金額を二商品間で合算せず、全場の事後選択を明記する。
    """
    values = [case['summary'][s] for s in SYMBOLS]
    active = all(v['active'] > 0 for v in values)
    both_tests = sum(all(v['tests'][k] for v in values) for k in TESTS)
    worst_red_rate = max(v['red_all'] for v in values)
    worst_coverage = max(v['worst_session_loss']/v['mean_positive_session_net']
        if v['mean_positive_session_net'] not in (None, 0) else math.inf for v in values)
    low_share = min(v['profit_share'] if v['profit_share'] is not None else -1 for v in values)
    return (active, both_tests == len(TESTS), both_tests, -worst_red_rate, -worst_coverage, low_share)


def description(value: dict) -> dict:
    """
    機能: 結果前に固定した短い表示説明を検査する。
    引数: value(dict)は条件名・群・入口・途中・出口の説明。
    返り値: dictは同説明。不明な正式条件を推測して埋めない。
    """
    assert set(('name', 'group', 'entry', 'middle', 'exit')).issubset(value)
    assert all(isinstance(value[k], str) and value[k] for k in ('name', 'group', 'entry', 'middle', 'exit'))
    return value


def descriptions_for(configs: list) -> dict:
    """
    機能: 正式catalog互換の機械条件から短い入口・途中・出口だけを作る。
    引数: configs(list[dict])は指紋照合済み正式16条件。
    返り値: dictは四群の表示説明。金融moduleや追加設定をimportしない。
    """
    entries = {
        'CONFIRM25': '元E01の候補で、直近60代理秒の方向票2以上・同方向の釣合い0.25以上を確認。',
        'CONFIRM50': '元E01の候補で、直近60代理秒の方向票2以上・同方向の釣合い0.5以上を確認。',
        'CONFIRM75': '元E01の候補で、直近60代理秒の方向票2以上・同方向の釣合い0.75以上を確認。',
        'SELF10': '旧0.25の方向票確認に、10代理秒前の端点との比較で自己のbidとaskが両方1呼値以上順行する条件を追加。',
        'PEER10': '旧0.25の方向票確認に、10代理秒前の端点との比較で相手のbidとaskが両方1呼値以上同方向へ動く条件を追加。'}
    middle = '当時ATR・気配差・料に応じて実枚数を選ぶ。出口線は最初の受理qと当時ATRから固定し、半減等の途中判断は元E01のまま。'
    values = {BASE_ID: dict(name='旧基準：方向票0.25・比例1呼値利確', group='基準',
        entry=entries['CONFIRM25'], middle=middle,
        exit='初回受理qの1呼値相当を純利確。損失はTOPIX5,000円・日経2,000円。発火で残玉を返済しその場を終了。')}
    for config in configs:
        ident = config['id']; assert ident.startswith('E01_CROSS_') and config['baseline_id'] == BASE_ID
        code = ident.removeprefix('E01_CROSS_'); assert code[0] in 'ABC'
        assert config['quantity'] == {'TOPIX': 5, 'NK225': 10} and config['cap'] == {'TOPIX': 10, 'NK225': 20}
        group = '入口の票比率' if code[0] == 'B' else '入口の価格応答' if code[0] == 'C' else '利益保全' if config['exit_kind'] == 'protect' else '出口の値幅'
        hard = '損失TOPIX5,000円・日経2,000円' if config['hard_basis'] == 'BUDGET' else f'初回受理建玉の{config["hard_multiple"]:g}ATR相当＋公開費用の損失'
        if config['exit_kind'] == 'fixed':
            basis = config['target_basis']
            target = '初回受理qの1呼値相当の純利益' if basis == 'P1' else '1呼値粗利から往復料を引いた純利益' if basis == 'TICK_NET' else f'初回受理建玉の{config["target_multiple"]:g}ATR相当の純利益'
            exit_text = target+'又は'+hard+'で残玉を返済し、その場を終了。'
        else:
            assert config['exit_kind'] == 'protect'
            arm = '初回受理qの1呼値相当の純利益' if config['arm_basis'] == 'P1' else f'初回受理建玉の{config["arm_multiple"]:g}ATR相当の純利益'
            exit_text = arm+f'で保全開始。当場の純清算高値から{config["draw_multiple"]:g}ATR相当戻すか、純清算0円へ戻ったら返済。'+hard+'も維持。'
        values[ident] = dict(name=code+'：'+config['title'], group=group,
            entry=entries[config['entry_id']], middle=middle, exit=exit_text)
    return dict(全合格=True, case_SHA256=goal_anchor_report.case_hashes(configs), cases=values,
        comparison_groups=['出口の値幅', '利益保全', '入口の票比率', '入口の価格応答'])


def check_aggregate(value: dict, saved: dict) -> None:
    """
    機能: 任意期間の表示金額・決済枚数・場数を保存aggregateへ照合する。
    引数: value/saved(dict)は純表示集計と正式保存の同期間指標。
    返り値: None。上位三除外後へ全33固定の照合関数を誤用しない。
    """
    fields = {'profit': '利益', 'loss': '損失', 'net': '収支', 'winning_lots': '勝ち枚数',
        'losing_lots': '負け枚数', 'positive': '黒字場', 'negative': '赤字場', 'no_trade': '無取引場'}
    for actual, target in fields.items():
        assert abs(value[actual]-saved[target]) < 1e-5, (actual, value[actual], saved[target])


def check_stability(value: dict, saved: dict, count: int) -> None:
    """
    機能: 表示三基準と赤字/活動/平均黒字を、正式保存のstabilityへ照合する。
    引数: value/saved(dict)、count(int)は同期間指標と正しい場数。
    返り値: None。未定義を0として照合しない。
    """
    assert saved['session_count'] == count
    fields = {'active': 'active_sessions', 'positive': 'positive_sessions', 'negative': 'losing_sessions',
        'no_trade': 'no_trade_sessions', 'red_all': 'red_full_rate', 'red_active': 'red_active_rate',
        'profit_share': 'profit_share', 'mean_positive_session_net': 'mean_positive_session_net_yen',
        'worst_session_loss': 'worst_negative_session_abs_yen'}
    for actual, target in fields.items():
        a, b = value[actual], saved[target]
        if a is None or b is None:
            assert a is b
        else:
            assert abs(a-b) < 1e-5
    assert value['active']-value['positive']-value['negative'] == saved['flat_active_sessions']
    assert tuple(value['tests'][k] for k in TESTS) == (saved['target65'], saved['target_red20'], saved['target_worst_mean'])
    assert value['pass_all'] == saved['all_targets']


def check_boundary(rows: list, config: dict, sessions: list) -> None:
    """
    機能: 新受理アンカーと固定円/保全線の66境界を原会計へ束縛する。
    引数: rows(list[dict])、config(dict)、sessions(list[str])は境界・正式条件・全33場。
    返り値: None。未受理の線や保全型の目標無しを0へ補完しない。
    """
    assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 66
    assert {r['session'] for r in rows} == set(sessions)
    for row in rows:
        anchor, lines, symbol = row['anchor'], row['exit_boundary'], row['symbol']
        assert row['目標円'] == lines['target_yen'] and row['損失予算円'] == lines['hard_loss_yen']
        assert row['新規数量選択予算円'] == lines['quantity_selection_budget_yen'] == config['quantity_selection_budget_yen'][symbol]
        for control, boundary in (('目標', '目標円'), ('損失予算', '損失予算円')):
            a, b = row['停止判断'][control], row[boundary]
            if a is None or b is None:
                assert a is b
            else:
                assert abs(a-b) < 1e-5
        assert anchor['成立'] == (lines['anchor'] is not None) and anchor['通常全量'] == config['quantity'][symbol]
        if not anchor['成立']:
            assert anchor['数量'] is None
            assert all(lines[k] is None for k in ('target_yen', 'hard_loss_yen', 'arm_yen', 'drawdown_yen', 'floor_yen'))
            continue
        assert isinstance(anchor['数量'], int) and 0 < anchor['数量'] <= config['quantity'][symbol]
        assert anchor['数量'] == lines['anchor']['quantity']
        if config['exit_kind'] == 'fixed':
            assert lines['target_yen'] > 0 and lines['arm_yen'] is lines['drawdown_yen'] is lines['floor_yen'] is None
        else:
            assert lines['target_yen'] is None and lines['arm_yen'] > 0 and lines['drawdown_yen'] > 0 and lines['floor_yen'] == 0


def build(finance: dict, fixed: dict, plan: dict, base: dict, cause: dict,
          descriptions: dict, sources: dict, followup: dict, followup_aggregate: dict) -> dict:
    """
    機能: 正式完成16会計と既測基準を指紋・条件・33場へ束縛する。
    引数: finance/fixed/plan/base/cause/descriptions/sources/followup/followup_aggregate(dict)は完成小資料と指紋。
    返り値: dictは公開用会計。新schemaの接続は正式runner確定後に確認する。
    """
    assert finance['全合格'] and fixed['全合格'] and plan['正式freeze'] and base['全合格'] and cause['全合格']
    assert finance['source開始終端一致']
    assert finance['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    assert finance['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
    assert goal_anchor_report.case_hashes(finance['configs']) == finance['case_SHA256'] == fixed['case_SHA256']
    assert descriptions['全合格'] and descriptions['case_SHA256'] == finance['case_SHA256']
    assert finance['counts'] == EXPECTED_COUNTS
    assert finance['会計口座数'] == 1056 and finance['新GUengine'] == 264
    assert finance['保存GU再利用'] == finance['旧基準経済同値確認'] == 66
    assert all(finance[k] == 0 for k in ('原板', 'NPZ', 'API', '現在入力', '旧金融再生'))
    assert finance['baseline'] == {k: v for k, v in fixed['baseline'].items() if k != 'ledgers'}
    assert finance['baseline']['id'] == BASE_ID
    assert finance['baseline']['SHA256'] == base['小資料'][finance['baseline']['source']]
    assert finance['boundary'] == finance['初回受理と費用後目標境界']
    sessions = finance['sessions']; assert sessions == fixed['sessions'] == base['sessions']
    assert len(sessions) == len(set(sessions)) == 33 and sessions == sorted(sessions)
    configs = {c['id']: c for c in finance['configs']}
    assert len(configs) == 16 and set(configs) == set(finance['results']) and BASE_ID not in configs
    assert set(descriptions['cases']) == set(configs)|{BASE_ID}
    base_rows = [e01_trade_report.mapped(r) for r in base['rows'].values()]
    base_summary, base_top3 = summaries(base_rows)
    for s in SYMBOLS:
        goal_anchor_report.saved_check(base_summary[s], base['expected'][s])
        goal_anchor_report.saved_check(base_summary[s], finance['baseline']['symbols'][s])
    assert sorted(base_rows, key=lambda r: (r['session'], r['symbol'])) == sorted(
        [e01_trade_report.mapped(r) for r in finance['baseline']['rows']], key=lambda r: (r['session'], r['symbol']))
    assert cause['条件ID'] == BASE_ID and cause['source開始終端一致']
    assert cause['集計']['TOPIX']['負親']['診断分類']['一度も費用後黒字なし'] == 6
    assert cause['集計']['TOPIX']['全親']['負け'] == 7
    assert cause['集計']['NK225']['買い']['収支'] == 4 and cause['集計']['NK225']['売り']['収支'] == 3382
    assert all('損失予算停止' not in cause['集計'][s]['全親']['出口理由'] for s in SYMBOLS)
    cases = {BASE_ID: dict(config=base['config'], description=description(descriptions['cases'][BASE_ID]),
        rows=base_rows, summary=base_summary, top3=base_top3,
        chronology=dict(前16=subset(base_rows, sessions[:16]), 後17=subset(base_rows, sessions[16:])),
        baseline=True, boundary=list(base['boundary'].values()), direction_source='保存43実親（全親部分返済0）')}
    for ident, raw in finance['results'].items():
        rows = [e01_trade_report.mapped(r) for r in raw['rows']]
        assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 66
        assert {r['session'] for r in rows} == set(sessions)
        summary, top3 = summaries(rows)
        chronology = dict(前16=subset(rows, sessions[:16]), 後17=subset(rows, sessions[16:]))
        for s in SYMBOLS:
            goal_anchor_report.saved_check(summary[s], raw['symbols'][s])
            assert abs(summary[s]['net']-raw['actual_leg_symbols'][s]['収支']) < 1e-5
            check_stability(summary[s], raw['stability'][s], 33)
            periods = raw['periods'][s]
            for tag, metrics, size in (('全33', summary[s], 33), ('前16', chronology['前16'][s], 16),
                ('後17', chronology['後17'][s], 17), ('上位3正収支場除外', top3[s], top3[s]['sessions'])):
                check_aggregate(metrics, periods[tag]['aggregate'])
                check_stability(metrics, periods[tag]['stability'], size)
                assert len(periods[tag]['sessions']) == size
            assert periods['除外場'] == top3[s]['removed_sessions']
            directions = raw['directional_symbols'][s]
            assert set(directions) == {'long', 'short'}
            for field, actual in (('利益', 'profit'), ('損失', 'loss'), ('収支', 'net')):
                assert abs(sum(directions[tag][field] for tag in ('long', 'short'))-summary[s][actual]) < 1e-5
        changes = finance['各場寄与'][ident]
        assert len(changes) == len({(r['session'], r['symbol']) for r in changes}) == 66
        assert all(r['baseline_id'] == BASE_ID for r in changes)
        for s in SYMBOLS:
            own = [r for r in changes if r['symbol'] == s]; assert len(own) == 33
            expected = finance['diagnosis'][ident][s]
            assert all(abs(sum(r[f] for r in own)-expected[f]) < 1e-5 for f in FIVE)
            assert expected['元勝ち親が赤字化'] == sum(len(r['元勝ち親が赤字化']) for r in own)
            assert abs(expected['収支変化']-(summary[s]['net']-base_summary[s]['net'])) < 1e-5
            assert abs(expected['収支変化']-(expected['避けた基準損失']-expected['失った基準利益']+
                expected['共通入口の数量/出口差']+expected['新たな入口の収支'])) < 1e-5
        check_boundary(finance['boundary'][ident], configs[ident], sessions)
        cases[ident] = dict(config=configs[ident], description=description(descriptions['cases'][ident]),
            rows=rows, summary=summary, top3=top3,
            chronology=chronology,
            baseline=False, boundary=finance['初回受理と費用後目標境界'][ident],
            contribution=finance['各場寄与'][ident], actual_legs=raw['actual_leg_symbols'],
            directions={s: {'買い': raw['directional_symbols'][s]['long'], '売り': raw['directional_symbols'][s]['short']} for s in SYMBOLS},
            direction_source='完結実親の初回新規方向。副表の枚数は勝敗親の建玉総数であり、主表の決済玉勝敗枚数とは別。')
    # ----------------------------------------
    # 旧基準は保存43親から方向を復元し、新条件はrunner保存の方向別親を使用する。
    baseline_directions = {}
    for s in SYMBOLS:
        baseline_directions[s] = {}
        for tag, side in (('買い', 1), ('売り', -1)):
            own = [r for r in cause['実親'] if r['symbol'] == s and r['side'] == side]
            assert all(not r['部分返済あり'] for r in own)
            baseline_directions[s][tag] = dict(利益=sum(max(0., r['実親']['収支']) for r in own),
                損失=sum(max(0., -r['実親']['収支']) for r in own), 収支=sum(r['実親']['収支'] for r in own),
                勝ち枚数=sum(r['実初回q'] for r in own if r['実親']['収支'] > 0),
                負け枚数=sum(r['実初回q'] for r in own if r['実親']['収支'] < 0))
    cases[BASE_ID]['directions'] = baseline_directions
    cases[BASE_ID]['direction_source'] = '保存43完結親の方向別net。旧基準は全親部分返済0のため、親建玉枚数と決済枚数が一致。'
    groups = descriptions['comparison_groups']
    assert groups and all(any(c['description']['group'] == g and not c['baseline'] for c in cases.values()) for g in groups)
    selected = [BASE_ID]
    for group in groups:
        own = [(ident, c) for ident, c in cases.items() if not c['baseline'] and c['description']['group'] == group]
        assert own
        selected.append(sorted(own, key=lambda item: (rank(item[1]), item[0]), reverse=True)[0][0])
    assert len(selected) == len(set(selected))
    assert MIDDLE_ID in cases and INITIAL_ID in cases
    assert followup['全合格'] and followup['開始終端source一致'] and followup_aggregate['全合格']
    assert followup['保存結果SHA256'] == followup_aggregate['正式結果SHA256']
    assert followup['保存結果SHA256'] in sources.values()
    assert followup_aggregate['診断射影SHA256'] == ENTRY_FOLLOWUP_SHA
    actual = [r for r in followup['parent_projections'] if r['case_id'] == INITIAL_ID]
    assert len(actual) == followup_aggregate['B03実親数'] == 15
    assert sum(r['publication']['direction_votes'] == 2 for r in actual) == followup_aggregate['B03二票親数'] == 7
    assert sum(r['session'].endswith('_Night') for r in actual) == followup_aggregate['B03ナイト親数'] == 13
    for s in SYMBOLS:
        own = [r for r in actual if r['symbol'] == s]; selected = followup_aggregate['B03標本診断'][s]
        assert len(own) == selected['実親数']
        assert abs(sum(r['actual_net_yen'] for r in own)-cases[INITIAL_ID]['summary'][s]['net']) < 1e-5
        assert sum(r['publication']['direction_votes'] == 2 for r in own) == selected['二票親数']
        assert max(r['risk']['fee_liquidation_MAE_yen'] for r in own) == selected['最大事後清算逆行円']
        assert sum(r['session'].endswith('_Day') for r in own) == 1
    return dict(全合格=True, title=TITLE, sessions=sessions, cases=cases, selected=selected,
        main=[BASE_ID, MIDDLE_ID, INITIAL_ID], initial_case=INITIAL_ID,
        comparison_groups=groups, sources=sources, 金融source_SHA256=finance['source_SHA256'], case_SHA256=finance['case_SHA256'],
        both_net_positive=sum(all(c['summary'][s]['net'] > 0 for s in SYMBOLS) for c in cases.values() if not c['baseline']),
        both_goal_pass=sum(all(c['summary'][s]['pass_all'] for s in SYMBOLS) for c in cases.values() if not c['baseline']),
        selection='全33場の事後選択。両商品が活動→両商品で三基準達成→両商品共通達成基準数→大きい方の赤字率が小さい→大きい方の最大赤字/平均黒字が小さい→低い方の金額利益割合が高い。同値はID降順。',
        criteria=dict(金額利益割合=.65, 赤字全場割合=.2, 一場損失='最大赤字場net絶対額<=平均黒字場net'),
        b03_diagnostics=followup_aggregate, 原因資料SHA256=CAUSE_SHA,
        金融再生=0, API=0, packet=0, ledger=0, 原板=0, NPZ=0)


# ----------------------------------------
def overview(data: dict, identifiers: list, table_id: str) -> str:
    """
    機能: 基準又は修正条件を同一IDの二商品ずつ表示する。
    引数: data(dict)、identifiers(list[str])、table_id(str)は検算会計と対象。
    返り値: strは概要表。同商品最良を混ぜた組を共通条件と呼ばない。
    """
    rows = []
    for ident in identifiers:
        case = data['cases'][ident]
        for s in SYMBOLS:
            v = case['summary'][s]
            markers = ' / '.join('○' if v['tests'][k] else '×' for k in TESTS)
            common = all(case['summary'][symbol]['pass_all'] for symbol in SYMBOLS)
            rows.append(f'<tr data-case-id="{html.escape(ident, quote=True)}" data-symbol="{s}">'
                f'<td>{html.escape(case["description"]["name"])}<small>{html.escape(ident)}</small></td><td>{LABELS[s]}</td>'
                +cell(v['profit'])+cell(v['loss'], True)+cell(v['net'])
                +f'<td>{pct(v["profit_share"])}</td><td>{v["positive"]}/{v["negative"]}/{v["no_trade"]}</td>'
                +cell(v['mean_positive_session_net'])+cell(v['worst_session_loss'], True)
                +f'<td>{markers}</td><td>{"両商品達成" if common else "両商品未達"}</td></tr>')
    return (f'<div class="scroll"><table id="{table_id}" class="overview"><thead><tr><th>同じ条件</th><th>商品</th>'
        '<th>利益（円）</th><th>損失（円）</th><th>収支（円）</th><th>金額利益割合</th><th>黒字/赤字/無</th>'
        '<th>平均黒字場（円）</th><th>最大赤字場（円）</th><th>割合/赤字率/損失</th><th>共通判定</th></tr></thead><tbody>'
        +''.join(rows)+'</tbody></table></div>')


def session_table(data: dict, ident: str) -> str:
    """
    機能: 同一条件の全33場と合計の金額・勝負枚数を表示する。
    引数: data(dict)、ident(str)は検算会計と条件ID。
    返り値: strは34行10数値列の表。無取引も実測0を掲載する。
    """
    case = data['cases'][ident]; indexed = {(r['session'], r['symbol']): r for r in case['rows']}
    rows = []
    for session in data['sessions']:
        label = session.replace('_Day', ' デイ').replace('_Night', ' ナイト')
        cells = []
        for s in SYMBOLS:
            v = indexed[session, s]
            cells.extend((cell(v['profit']), cell(v['loss'], True), cell(v['net']),
                f'<td>{v["winning_lots"]}</td>', f'<td>{v["losing_lots"]}</td>'))
        rows.append(f'<tr data-session="{session}"><th>{label}</th>'+''.join(cells)+'</tr>')
    cells = []
    for s in SYMBOLS:
        v = case['summary'][s]
        cells.extend((cell(v['profit']), cell(v['loss'], True), cell(v['net']),
            f'<td>{v["winning_lots"]}</td>', f'<td>{v["losing_lots"]}</td>'))
    rows.append('<tr class="total"><th>全33場合計</th>'+''.join(cells)+'</tr>')
    return ('<div class="scroll"><table class="sessions"><thead><tr><th rowspan="2">セッション</th>'
        '<th colspan="5">TOPIXミニ・片方向10枚まで</th><th colspan="5">日経マイクロ・片方向20枚まで</th></tr><tr>'
        +('<th>利益（円）</th><th>損失（円）</th><th>収支（円）</th><th>勝ち枚数</th><th>負け枚数</th>'*2)
        +'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>')


def extra(case: dict) -> str:
    """
    機能: 大勝ち除外、時系列二分、買売の補足を折り畳む。
    引数: case(dict)は検算済み同条件会計。
    返り値: strは補足表。未保存の買売値を0や仮成績にしない。
    """
    trim, period, direction = [], [], []
    for s in SYMBOLS:
        v = case['top3'][s]
        trim.append(f'<tr data-symbol="{s}"><td>{LABELS[s]}</td>'+cell(v['net'])
            +f'<td>{pct(v["profit_share"])}</td><td>{v["positive"]}/{v["negative"]}/{v["no_trade"]}</td>'
            +cell(v['mean_positive_session_net'])+cell(v['worst_session_loss'], True)+'</tr>')
        for tag in ('前16', '後17'):
            p = case['chronology'][tag][s]
            period.append(f'<tr data-period="{tag}" data-symbol="{s}"><td>{tag}場</td><td>{LABELS[s]}</td>'
                +cell(p['profit'])+cell(p['loss'], True)+cell(p['net'])
                +f'<td>{pct(p["profit_share"])}</td><td>{p["positive"]}/{p["negative"]}/{p["no_trade"]}</td></tr>')
        if case.get('directions') is not None:
            for tag in ('買い', '売り'):
                p = case['directions'][s][tag]
                direction.append(f'<tr data-side="{tag}" data-symbol="{s}"><td>{tag}</td><td>{LABELS[s]}</td>'
                    +cell(p['利益'])+cell(p['損失'], True)+cell(p['収支'])
                    +f'<td>{p["勝ち枚数"]}</td><td>{p["負け枚数"]}</td></tr>')
    tables = '<details><summary>上位3利益場を除いた安定性</summary><div class="scroll"><table class="top3"><thead><tr>'
    tables += '<th>商品</th><th>除外後収支</th><th>金額割合</th><th>黒字/赤字/無</th><th>平均黒字場</th><th>最大赤字場</th></tr></thead><tbody>'+''.join(trim)+'</tbody></table></div></details>'
    tables += '<details><summary>前16場・後17場</summary><p class="note">時系列の偏り確認。両期間とも開発に使ったため未見検証ではありません。</p><div class="scroll"><table class="chronology"><thead><tr>'
    tables += '<th>期間</th><th>商品</th><th>利益</th><th>損失</th><th>収支</th><th>金額割合</th><th>黒字/赤字/無</th></tr></thead><tbody>'+''.join(period)+'</tbody></table></div></details>'
    tables += '<details><summary>買い・売りの偏り</summary>'
    if direction:
        tables += '<p class="note">'+html.escape(case['direction_source'])+'</p><div class="scroll"><table class="directions"><thead><tr><th>方向</th><th>商品</th><th>利益</th><th>損失</th><th>収支</th><th>勝ち親の建玉枚数</th><th>負け親の建玉枚数</th></tr></thead><tbody>'+''.join(direction)+'</tbody></table></div>'
    else:
        tables += '<p>この完成小会計に買売別の保存値がありません。商品合計から推定しません。</p>'
    return tables+'</details>'


def render(data: dict) -> str:
    """
    機能: 原因四点、少数代表、固定16条件と基準の全場切替を短い暗色HTMLへまとめる。
    引数: data(dict)は検算済み公開会計。
    返り値: strは単一HTML。通信や金融の再実行を含めない。
    """
    all_ids = list(data['cases']); options, sections = [], []
    for ident in all_ids:
        case = data['cases'][ident]; d = case['description']; safe = html.escape(ident, quote=True)
        chosen = ' selected' if ident == data['initial_case'] else ''
        options.append(f'<option value="{safe}"{chosen}>{html.escape(d["name"])} / {html.escape(ident)}</option>')
        sections.append(f'<section data-case="{safe}" hidden><h2>{html.escape(d["name"])}</h2><p>'
            f'<b>入口：</b>{html.escape(d["entry"])}<br><b>途中：</b>{html.escape(d["middle"])}<br>'
            f'<b>出口：</b>{html.escape(d["exit"])}</p>'+session_table(data, ident)+extra(case)+'</section>')
    css = '*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#dce4f2;font:16px/1.6 system-ui}main{max-width:1480px;margin:auto;padding:24px 20px}h1{font-size:27px}h2{font-size:21px}.note,small{color:#a9bbd5}small{display:block;white-space:normal;overflow-wrap:anywhere;font-size:11px}a{color:#91c2ff}select{width:100%;padding:12px;background:#18283f;color:#edf4ff;border:1px solid #6c839f;font:inherit}.scroll{overflow:auto;max-width:100%;margin:14px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px 11px;border-bottom:1px solid #35455e;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}.overview{min-width:1180px}.overview td:first-child{width:280px;min-width:280px;white-space:normal}.sessions{min-width:1160px}thead th,.total{background:#1c2e47}tbody tr:nth-child(even){background:#132238}.positive{color:#59dfb3}.negative{color:#ff949b}.total{font-weight:bold}details{margin:15px 0}summary{cursor:pointer;color:#b8d3fa}section[hidden]{display:none}section{margin-top:22px}@media(max-width:600px){main{padding:16px 12px}h1{font-size:22px}}'
    script = '''/**
 * 保存された同一条件の全場表を切り替える。
 * @param {string} key - 表示する条件ID。
 * @returns {undefined} 表示だけを更新し、通信と金融再生を行わない。
 */
function showCase(key){for(const section of document.querySelectorAll('[data-case]'))section.hidden=section.dataset.case!==key;document.getElementById('case').value=key;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase(document.getElementById('case').value);'''
    candidate = data['cases'][INITIAL_ID]
    top, nk = candidate['summary']['TOPIX'], candidate['summary']['NK225']
    claim = '今回の共通候補はB03です。' if top['pass_all'] and nk['pass_all'] else '今回のB03も共通三基準には未達です。'
    main_result = f'TOPIXは{money(top["net"])}円（{top["positive"]}黒字・{top["negative"]}赤字・{top["no_trade"]}無取引）、日経は{money(nk["net"])}円（{nk["positive"]}黒字・{nk["negative"]}赤字・{nk["no_trade"]}無取引）。'
    tail = f'利益上位3場を除いてもTOPIX{money(candidate["top3"]["TOPIX"]["net"])}円・日経{money(candidate["top3"]["NK225"]["net"])}円。'
    moderate = data['cases'][MIDDLE_ID]['summary']['TOPIX']
    evidence = data['b03_diagnostics']; risk = evidence['B03標本診断']
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{TITLE}</title><style>{css}</style></head><body><!--\n[コンポーネント概要]\n#case は基準と固定16条件を選びます。\n[data-case] は同じ条件IDの二商品全場と補足を表示します。\n.overview は金額と三基準、.sessions は全33場と合計、.scroll は横スクロール領域です。\n--><main><h1>{TITLE}</h1>'
        +f'<p><b>{claim}</b> 方向の取引更新票が大きくそろった時だけ入り、小幅の純利益でその場を終えます。{main_result}{tail}</p>'
        +f'<p>B01は入口をほどほどに厳しくして活動を残しますが、TOPIXの最大赤字{money(moderate["worst_session_loss"])}円を平均黒字場{money(moderate["mean_positive_session_net"])}円で補えていません。出口幅や保全、10秒価格応答の追加は共通改善になりませんでした。</p>'
        +'<p class="note">旧TOPIXは7敗中6敗が料金後黒字を経験せず、料金前でも赤字。損失予算停止は0件で、主に元E01の損切り・追跡返済が損失を確定しました。旧日経＋3,386円の内訳は<b>買い＋4円・売り＋3,382円</b>です。</p>'
        +f'<p class="note">共通三基準達成{data["both_goal_pass"]}/16・両商品黒字{data["both_net_positive"]}/16。B03は実働TOPIX{top["active"]}/33・日経{nk["active"]}/33場で、15取引中7が2票、13が夜間です。無敗でも途中清算逆行TOPIX{money(risk["TOPIX"]["最大事後清算逆行円"])}円・日経{money(risk["NK225"]["最大事後清算逆行円"])}円を含みます。損失枠は5,000円/2,000円で、将来の損小利大は保証されません。</p>'
        '<p class="note">金額利益割合65%以上 / 赤字場20%以下 / 最大赤字≦平均黒字場。無取引は黒字に含めません。</p>'
        +overview(data, data['main'], 'main-overview')
        +'<details><summary>出口値幅・利益保全・入口票比率・価格応答の各群代表</summary>'
        +'<p class="note">全場での事後選択：両商品活動、共通三基準の達成数、悪い方の赤字頻度、最大赤字/平均黒字、金額割合の順。未達を成功と呼ばず、商品別の最良を組み合わせていません。</p>'
        +overview(data, data['selected'], 'selected-overview')+'</details>'
        +'<details><summary>基準＋固定16条件の全一覧</summary>'+overview(data, all_ids, 'all-overview')+'</details>'
        +'<label for="case">全セッション損益を表示する条件</label><select id="case">'+''.join(options)+'</select>'+''.join(sections)
        +'<p class="note">金額は完結実親の料金後利益・損失、枚数は実決済玉の勝ち・負け。ラージ気配と料金を使用し、場内で全玉返済します。入口資格だけの表や元親削除の推定を修正後損益にしていません。</p>'
        +f'<p><a href="{ACCOUNTING_TITLE}">表示会計と指紋</a> · <a href="../共通/知見台帳/入口.md">入口の知見</a></p></main><script>'+script+'</script></body></html>')


# ----------------------------------------
def load_and_build(result_path: Path, fixed_path: Path, plan_path: Path) -> dict:
    """
    機能: 正式結果が揃った時だけ完成小資料を読み、sourceへ束縛する。
    引数: result_path/fixed_path/plan_path(Path)は正式確定後の小資料位置。
    返り値: dictは検算済み表示値。現時点はschema接続準備のみで実行しない。
    """
    result_path, fixed_path, plan_path = tuple(
        (p if p.is_absolute() else ROOT/p).resolve()
        for p in (result_path, fixed_path, plan_path))
    assert all(p.is_relative_to(ROOT/'work') for p in (result_path, fixed_path, plan_path))
    assert not (result_path.parent/'False.json').exists()
    paths = (result_path, fixed_path, plan_path, BASE_PLAN, CAUSE, ENTRY_FOLLOWUP, FOLLOWUP_AGGREGATE)
    content, sources = {}, {}
    for p in paths:
        content[p], sources[p.relative_to(ROOT).as_posix()] = read(p)
    assert sources[BASE_PLAN.relative_to(ROOT).as_posix()] == BASE_PLAN_SHA
    assert sources[CAUSE.relative_to(ROOT).as_posix()] == CAUSE_SHA
    assert sources[ENTRY_FOLLOWUP.relative_to(ROOT).as_posix()] == ENTRY_FOLLOWUP_SHA
    assert sources[FOLLOWUP_AGGREGATE.relative_to(ROOT).as_posix()] == FOLLOWUP_AGGREGATE_SHA
    assert sources[plan_path.relative_to(ROOT).as_posix()] == content[fixed_path]['計画SHA256']
    for relative, wanted in content[result_path]['source_SHA256'].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == wanted
    descriptions = descriptions_for(content[result_path]['configs'])
    data = build(content[result_path], content[fixed_path], content[plan_path], content[BASE_PLAN],
        content[CAUSE], descriptions, sources, content[ENTRY_FOLLOWUP], content[FOLLOWUP_AGGREGATE])
    data['表示source_SHA256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), HELPERS/'goal_anchor_report.py', HELPERS/'risk_sizing_report.py',
            HELPERS/'e01_trade_report.py', HELPERS/'range_report.py', HELPERS/'trade_report.py')}
    return data


def run(result_path: Path, fixed_path: Path, plan_path: Path, destination: Path | None = None) -> dict:
    """
    機能: 正式schema接続後、根の公開又は出力無しの小会計確認を行う。
    引数: 三正式小資料Path、destination(Path|None)は根の公開先又は出力なし。
    返り値: dictは17切替・全場件数と動的達成数。金融/API/packet/台帳は0。
    """
    data = load_and_build(result_path, fixed_path, plan_path)
    document = render(data)
    assert len(data['cases']) == document.count('data-case="') == document.count('class="sessions"') == 17
    assert not any(t in document for t in ('NaN', 'Infinity'))
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination/ACCOUNTING_TITLE).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
        (destination/(TITLE+'.html')).write_text(document, encoding='utf-8', newline='\n')
    proof = dict(全合格=True, 表示条件=17, 全場口座=17*66, 全場金額枚数セル=17*34*10,
        両商品黒字=data['both_net_positive'], 両商品三基準=data['both_goal_pass'], 公開=destination is not None,
        金融=0, API=0, packet=0, ledger=0)
    print(json.dumps(proof, ensure_ascii=False), flush=True)
    return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--check-only', action='store_true'); actions.add_argument('--root-publish', action='store_true')
    parser.add_argument('--result', type=Path, required=True); parser.add_argument('--fixed', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=PUBLIC)
    args = parser.parse_args()
    run(args.result, args.fixed, args.plan, None if args.check_only else args.output_dir)
