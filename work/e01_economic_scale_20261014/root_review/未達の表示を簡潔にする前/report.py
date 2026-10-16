"""保存完成会計だけから、保有容量と損失・無取引を含む一場平均を表示する。"""

import argparse
import hashlib
import html
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGINE = HERE/'engine'
PUBLIC = ROOT/'アルゴリズム調査/00107_保有容量と一取引利益の再検証'
TITLE = '容量を使うE01と一場平均収支及び全セッション損益'
ACCOUNTING_TITLE = '容量別E01の一場平均と全場会計.json'
SCHEMA_READY = True
NEW_COUNT = 14
EXPECTED_COUNTS = {'既input一読': 33, '新account金融': 924}
PAIR_ID = 'E01_SYMBOL_FIXED'
SYMBOLS = ('TOPIX', 'NK225')
LABELS = {'TOPIX': 'TOPIXミニ', 'NK225': '日経マイクロ'}
CAPACITY = {'TOPIX': 10, 'NK225': 20}
MULTIPLIER = {'TOPIX': 1000., 'NK225': 10.}
ECONOMIC_FLOOR = {'TOPIX': 100000., 'NK225': None}
REGISTERED_ECONOMIC_FLOOR = {'TOPIX': 100000, 'NK225': '円額目標の対象外（未指定）'}
REGISTERED_PROFIT_STOP = '不使用（利益後も候補継続）'
OLD_SELECTED = {'TOPIX': 'E01_ADAPT_G50_ADAPT75_P1', 'NK225': 'E01_ADAPT_G25_ADAPT100_P1'}
SELECTION_PLAN = HERE/'報告書選定の事前固定_v2.json'
SELECTION_SHA = '145de1fef9b8527a66f74623fd45a77a297789b770ad10ed4d8bf26ecd5679a4'
REFERENCE = ROOT/'work/e01_adaptive_price_20261014/report.py'
REFERENCE_SHA = '537e664ba6c352d92916c9b0b5155180581872302a4420ffc51595aa13136174'
EVIDENCE = {
    'work/e01_adaptive_price_20261014/audit/owned/旧00106の実容量使用と一取引10万円床の独立算術.json':
        '74bdcae31ce9f0693876aa3b9c42d97d9eecca5a333030ca6c12fd26f5e4bada',
    'work/e01_adaptive_price_20261014/audit/owned/経済床の固定全量値幅と可変数量容量換算の範囲補足.json':
        '0782d71de54ef0b55b6abc138914dc6d13d51a53b720251828d36ceb3d7711f7'}


def digest(path: Path) -> str:
    """
    機能: 小source又は保存小資料を指紋へ結ぶ。
    引数: path(Path)は指紋を求める保存位置。
    返り値: strはSHA256。入力・台帳を探索しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def old_helpers() -> object:
    """
    機能: 不変の旧表示sourceから純集計・表示関数だけを利用する。
    引数: なし。REFERENCE(Path)とREFERENCE_SHA(str)は固定した旧source。
    返り値: moduleは旧表示関数。金融・API・mainを呼ばない。
    """
    assert digest(REFERENCE) == REFERENCE_SHA
    spec = importlib.util.spec_from_file_location('旧表示の純会計補助', REFERENCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPERS = old_helpers()
number, percent, cell, mapped, same = HELPERS.number, HELPERS.percent, HELPERS.cell, HELPERS.mapped, HELPERS.same


def economic_summary(rows: list, symbol: str) -> dict:
    """
    機能: 損失・無取引を含む全場平均と従来三基準を独立集計する。
    引数: rows(list[dict])は同商品・任意場数の会計、symbol(str)は商品。
    返り値: dictは場平均net・参考親平均・容量換算pt・主条件。場平均から無取引を除かない。
    """
    result = HELPERS.summary(rows)
    count = result['campaigns']
    mean_parent = result['net']/count if count else None
    mean_session = result['net']/result['sessions']
    floor = ECONOMIC_FLOOR[symbol]
    economic_pass = None if floor is None else mean_session >= floor
    result.update(mean_parent_net=mean_parent, mean_session_net=mean_session, economic_floor=floor, economic_pass=economic_pass,
        primary_pass=result['pass_all'] and (floor is None or economic_pass),
        capacity_net_points=result['net']/(CAPACITY[symbol]*MULTIPLIER[symbol]),
        mean_parent_capacity_net_points=None if mean_parent is None else mean_parent/(CAPACITY[symbol]*MULTIPLIER[symbol]),
        mean_session_capacity_net_points=mean_session/(CAPACITY[symbol]*MULTIPLIER[symbol]))
    return result


def metrics(rows: list, sessions: list, symbol: str) -> dict:
    """
    機能: 全場・上位三場除外・昼夜・前後を同じ親定義で集計する。
    引数: rows(list[dict])、sessions(list[str])、symbol(str)は同商品会計と固定場順。
    返り値: dictは主条件と別の頑健性確認。場の結果で運転設定を切り替えない。
    """
    assert len(rows) == len(sessions) == len(set(sessions))
    assert {r['session'] for r in rows} == set(sessions)
    removed = sorted((r for r in rows if r['net'] > 0), key=lambda r: (-r['net'], r['session']))[:3]
    excluded = {r['session'] for r in removed}
    full = economic_summary(rows, symbol)
    trim = economic_summary([r for r in rows if r['session'] not in excluded], symbol)
    trim['removed_sessions'] = [r['session'] for r in removed]
    robust = trim['tests']['share65'] and trim['tests']['coverage']
    economic_robust = robust and (ECONOMIC_FLOOR[symbol] is None or trim['economic_pass'])
    cut = min(16, len(sessions)//2)
    scopes = {'day': [r for r in rows if r['session'].endswith('_Day')],
        'night': [r for r in rows if r['session'].endswith('_Night')],
        'first': [r for r in rows if r['session'] in set(sessions[:cut])],
        'last': [r for r in rows if r['session'] in set(sessions[cut:])]}
    return dict(full=full, top3=trim, robustness_pass=bool(robust), economic_robustness_pass=bool(economic_robust),
        qualified=bool(full['primary_pass'] and robust),
        **{k: economic_summary(v, symbol) if v else None for k, v in scopes.items()})


def select(cases: dict, symbol: str) -> tuple:
    """
    機能: 商品別に一つの固定設定を選び、最大収益を順位へ使わない。
    引数: cases(dict)は検算済み候補、symbol(str)は商品。
    返り値: tuple[str,dict]は固定IDと選定根拠。未達の参考選択を成功と呼ばない。
    """
    def primary(ident: str) -> tuple:
        """
        機能: 主条件・別頑健性・活動と最大赤字の順で候補を比較する。
        引数: ident(str)は候補ID。
        返り値: tupleは金融前に固定する比較順。円合算・日別選択はしない。
        """
        m = cases[ident]['metrics'][symbol]
        full = m['full']
        return (full['primary_pass'], m['robustness_pass'], full['pass_all'],
            sum(full['tests'].values()), full['active'],
            m['day']['active'] if m['day'] is not None else 0, -full['worst_session_loss'])
    highest = max(primary(cid) for cid in cases)
    tied = [cid for cid in cases if primary(cid) == highest]
    risks = [cases[cid]['risk'][symbol] for cid in tied]
    complete = all(r is not None and r['complete'] and isinstance(r['maximum_fee_liquidation_MAE_yen'], (int, float)) for r in risks)
    if complete:
        minimum = min(r['maximum_fee_liquidation_MAE_yen'] for r in risks)
        tied = [cid for cid in tied if cases[cid]['risk'][symbol]['maximum_fee_liquidation_MAE_yen'] == minimum]
    chosen = sorted(tied)[0]
    return chosen, dict(primary=list(highest), 最終同順位=tied, 同範囲逆行で判別=complete,
        未達時='全場平均10万円又は従来三基準を満たさない候補は参考設定として表示する。',
        固定単位='商品ごとに一組を全33場へ固定。同じ保存場での既知内選択。')


def guard(finance: dict, fixed: dict, plan: dict, plan_sha: str) -> None:
    """
    機能: 正式結果を固定条件・実装・計画・開始終端へ束縛する。
    引数: finance/fixed/plan(dict)、plan_sha(str)は根完了後だけ読む小資料。
    返り値: None。schema接続前・未完成・source不一致は表示を停止する。
    """
    assert SCHEMA_READY, '00107正式driver schema接続前は結果を読みません。'
    assert finance['全合格'] and fixed['全合格'] and fixed['正式freeze'] and plan['正式freeze']
    assert finance['source開始終端一致']
    assert finance['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    assert all(digest(ROOT/p) == sha for p, sha in finance['source_SHA256'].items())
    assert fixed['計画SHA256'] == plan_sha
    assert finance['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
    assert HELPERS.case_hashes(finance['configs']) == fixed['case_SHA256'] == finance['case_SHA256']
    assert len(finance['configs']) == len(finance['results']) == NEW_COUNT
    assert {c['id'] for c in finance['configs']} == set(finance['results'])
    assert finance['sessions'] == fixed['sessions'] and len(set(finance['sessions'])) == len(finance['sessions']) == 33
    assert finance['counts'] == EXPECTED_COUNTS
    assert all(plan['予定'][k] == v for k, v in EXPECTED_COUNTS.items())
    assert finance['旧GU再利用'] == finance['旧台帳本文'] == 0
    assert finance['reused_results'] == fixed['reused_results'] and set(finance['reused_results']) == set(OLD_SELECTED.values())
    assert set(finance['actual_parent_diagnostics']) == set(finance['results'])
    assert finance['API'] == finance['原板'] == finance['NPZ'] == finance['現在入力'] == 0


def parameters(config: dict) -> dict:
    """
    機能: 金融前固定の数量・入口・価格・出口設定を表示へ写す。
    引数: config(dict)は正式catalogの条件。
    返り値: dict[str,dict]は商品別設定と短い説明。規則を実績から作らない。
    """
    route, quantity, exit_id = config['entry_route'], config['quantity_mode'], config['exit_id']
    assert route in ('SELECTED', 'COMMON25') and quantity in ('HALF', 'FULL', 'RISK')
    assert exit_id in ('GU', 'TARGET', 'TRAIL', 'PARTIAL')
    assert config['id'] == 'E01_SCALE_'+route+'_'+quantity+'_'+exit_id
    assert config['cap'] == CAPACITY and config['target_session_mean_net_yen'] == REGISTERED_ECONOMIC_FLOOR
    coefficients = {'quantity_budget_fraction': .00125, 'parent_stop_fraction': .00125,
        'parent_target_fraction': .005, 'arm_fraction': .00375, 'draw_fraction': .00125,
        'floor_fraction': .0025, 'partial_fraction': .25, 'partial_arm_fraction': .0025,
        'session_stop_fraction': .0025, 'risk_atr_multiple': 1.}
    assert all(config[k] == v for k, v in coefficients.items()) and config['session_profit_stop_yen'] == REGISTERED_PROFIT_STOP
    result = {}
    for s in SYMBOLS:
        gate, strong = config['entry_parameters'][s]
        assert gate in ('G25', 'G50') and strong in (.75, 1.)
        threshold = {'G25': .25, 'G50': .5}[gate]
        qty = CAPACITY[s]//2 if quantity == 'HALF' else CAPACITY[s]
        qlabel = ('固定'+str(qty)+'枚') if quantity != 'RISK' else '公開予定リスクで選択（上限'+str(qty)+'枚）'
        xlabel = {'GU': '元E01返済＋新しい親/場の損失停止', 'TARGET': '初回建玉金額の0.5%純利益で全量返済',
            'TRAIL': '0.375%から0.125%幅で利益追尾', 'PARTIAL': '0.25%で枚数の25%を切捨て返済＋残玉追尾'}[exit_id]
        result[s] = dict(entry_route=route, entry_id=gate, balance_threshold=threshold, min_votes=2,
            strong_balance_threshold=strong, quantity_mode=quantity, requested_quantity=qty,
            exit_id=exit_id, quantity_label=qlabel, exit_label=xlabel,
            entry_label=f'60秒票釣合い{threshold:g}以上、{strong:g}以上で不利1呼値を許容')
    return result


def attach_economic_details(case: dict, raw: dict, parents: list) -> None:
    """
    機能: 実親の数量・途中リスクを同じ保存範囲だけで接続する。
    引数: case/raw(dict)、parents(list[dict])は完成表示・正式結果・小親射影。
    返り値: None。初回数量と最大同時保有を区別し、欠測を0にしない。
    """
    assert len(parents) == len({(r['session'], r['symbol'], r['parent']) for r in parents})
    for s in SYMBOLS:
        own = [r for r in parents if r['symbol'] == s]
        full = case['metrics'][s]['full']
        assert len(own) == full['campaigns']
        same(sum(r['net_yen'] for r in own), full['net'])
        same(sum(max(r['net_yen'], 0.) for r in own), full['profit'])
        same(sum(max(-r['net_yen'], 0.) for r in own), full['loss'])
        same(sum(r['fees_yen'] for r in own), full['fees'])
        assert all(r['hindsight_only'] and r['capacity'] == CAPACITY[s] for r in own)
        for r in own:
            assert isinstance(r['entry_quantity'], int) and 0 < r['entry_quantity'] <= CAPACITY[s]
            assert r['entry']['quantity'] == r['entry_quantity'] and r['entry']['row'] <= r['exits'][-1]['row']
            assert sum(e['quantity'] for e in r['exits']) == r['entry_quantity']
            assert 0 <= r['maximum_held_quantity'] <= CAPACITY[s]
            assert all(math.isfinite(r[k]) for k in ('net_yen', 'fees_yen', 'parent_mae_yen', 'parent_mfe_yen', 'holding_price_proxy_seconds'))
            assert r['parent_mae_yen'] >= 0
        qs = [r['entry_quantity'] for r in own]
        max_held = max((r['maximum_held_quantity'] for r in own), default=0)
        case['capacity'][s] = dict(observed_parents=len(own),
            mean_initial_quantity=statistics.mean(qs) if qs else None,
            mean_initial_capacity_fraction=statistics.mean(qs)/CAPACITY[s] if qs else None,
            maximum_same_side_holding=max_held,
            maximum_holding_capacity_fraction=max_held/CAPACITY[s],
            mean_holding_price_proxy_seconds=statistics.mean(r['holding_price_proxy_seconds'] for r in own) if own else None,
            partial_exit_parents=sum(len(r['exits']) > 1 for r in own),
            scope='全完結実親。初回数量と実保有期間内の最大片方向保有を分ける。保持は価格代理秒。')
        case['risk'][s] = dict(observed_parents=len(own), actual_parents=full['campaigns'], complete=bool(own) and len(own) == full['campaigns'],
            maximum_fee_liquidation_MAE_yen=max((r['parent_mae_yen'] for r in own), default=None),
            two_vote_parents=sum(r['published_direction_votes'] == 2 for r in own),
            scope='同一次sourceの全完結実親局所清算。事後だけであり別出口収益ではない。')
    case['parents'] = parents


def check_economic_saved(saved: dict, rows: list, parents: list, symbol: str) -> None:
    """
    機能: 正式保存の場平均・参考親平均・数量・容量ptを独立小算術へ照合する。
    引数: saved(dict)、rows/parents(list[dict])、symbol(str)は同じ期間の保存集計と実親。
    返り値: None。実使用枚数や全親平均を予算又は名目目標で代用しない。
    """
    m = economic_summary(rows, symbol)
    own = [r for r in parents if r['symbol'] == symbol]
    qs = [r['entry_quantity'] for r in own]
    pairs = dict(mean_session_net_yen=m['mean_session_net'], mean_parent_net_yen=m['mean_parent_net'],
        session_count=m['sessions'], parent_count=m['campaigns'],
        mean_initial_quantity=statistics.mean(qs) if qs else None,
        maximum_same_direction_quantity=max((r['maximum_held_quantity'] for r in own), default=0),
        mean_initial_capacity_ratio=statistics.mean(qs)/CAPACITY[symbol] if qs else None,
        net_capacity_points=m['capacity_net_points'], target_floor_yen=ECONOMIC_FLOOR[symbol])
    for key, expected in pairs.items(): same(saved[key], expected)
    assert saved['target_mean_success'] == m['economic_pass']
    assert len(own) == m['campaigns'] and abs(sum(r['net_yen'] for r in own)-m['net']) < 1e-5


def check_session_economic(saved: dict, row: dict, parents: list, symbol: str) -> None:
    """
    機能: 正式の場別小保存を、同場の実親と場会計へ照合する。
    引数: saved/row(dict)、parents(list[dict])、symbol(str)は一場の保存と同商品実親。
    返り値: None。場別保存にない期間平均のキーを補完しない。
    """
    qs = [p['entry_quantity'] for p in parents]
    expected = dict(net_yen=row['net'], parent_count=row['campaigns'],
        mean_parent_net_yen=row['net']/row['campaigns'] if row['campaigns'] else None,
        mean_initial_quantity=statistics.mean(qs) if qs else None,
        maximum_same_direction_quantity=max((p['maximum_held_quantity'] for p in parents), default=0),
        net_capacity_points=row['net']/(CAPACITY[symbol]*MULTIPLIER[symbol]),
        worst_parent_liquidation_yen=min([0.]+[p['worst_parent_liquidation_yen'] for p in parents]) if parents else None)
    assert len(parents) == row['campaigns'] and saved['session'] == row['session']
    for key, value in expected.items(): same(saved[key], value)


def build(finance: dict, fixed: dict, plan: dict, sources: dict) -> dict:
    """
    機能: 完成小会計を照合し、全十四条件と商品別固定一組を作る。
    引数: finance/fixed/plan/sources(dict)は根授権後の正式小資料と指紋。
    返り値: dictは公開会計。金融・原入力・台帳をimport又は再生しない。
    """
    guard(finance, fixed, plan, sources['plan'])
    sessions = finance['sessions']
    configs = {c['id']: c for c in finance['configs']}
    cases = {}
    for cid, raw in finance['results'].items():
        rows = [mapped(r) for r in raw['rows']]
        assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 66
        m = {s: metrics([r for r in rows if r['symbol'] == s], sessions, s) for s in SYMBOLS}
        for s in SYMBOLS:
            HELPERS.check_saved(m[s]['full'], raw['symbols'][s], raw.get('stability', {}).get(s))
            same(m[s]['full']['net'], raw['actual_leg_symbols'][s]['収支'])
        case = dict(rows=rows, metrics=m, parameters=parameters(configs[cid]),
            risk={s: None for s in SYMBOLS}, capacity={s: None for s in SYMBOLS},
            directions=raw.get('directional_symbols'), actual_legs=raw['actual_leg_symbols'])
        attach_economic_details(case, raw, finance['actual_parent_diagnostics'][cid])
        for s in SYMBOLS:
            own_rows = [r for r in rows if r['symbol'] == s]
            check_economic_saved(raw['economic'][s], own_rows, case['parents'], s)
            by_session = raw['economic'][s]['by_session']
            assert len(by_session) == len({e['session'] for e in by_session}) == len(sessions)
            for e in by_session:
                own_row = [r for r in own_rows if r['session'] == e['session']]
                assert len(own_row) == 1
                check_session_economic(e, own_row[0],
                    [p for p in case['parents'] if p['session'] == e['session'] and p['symbol'] == s], s)
            for tag, field in (('全33', 'full'), ('前16', 'first'), ('後17', 'last'), ('上位3正収支場除外', 'top3')):
                if field == 'full': scope = set(sessions)
                elif field == 'first': scope = set(sessions[:16])
                elif field == 'last': scope = set(sessions[16:])
                else: scope = set(sessions)-set(m[s]['top3']['removed_sessions'])
                value = raw['periods'][s][tag]
                HELPERS.check_saved(m[s][field], value['aggregate'], value['stability'])
                assert value['stability']['target_mean_session_net'] == m[s][field]['economic_pass']
                assert value['stability']['all_economic_targets'] == m[s][field]['primary_pass']
                check_economic_saved(value['economic'], [r for r in own_rows if r['session'] in scope],
                    [p for p in case['parents'] if p['session'] in scope], s)
            assert raw['periods'][s]['除外場'] == m[s]['top3']['removed_sessions']
        cases[cid] = case
    choices = {s: select(cases, s) for s in SYMBOLS}
    ids = {s: choices[s][0] for s in SYMBOLS}
    pair = dict(selected=ids,
        rows=[r for t in sessions for s in SYMBOLS for r in cases[ids[s]]['rows'] if r['session'] == t and r['symbol'] == s],
        parents=[p for s in SYMBOLS for p in cases[ids[s]]['parents'] if p['symbol'] == s],
        **{name: {s: cases[ids[s]][name][s] for s in SYMBOLS} for name in ('metrics', 'risk', 'capacity')},
        parameters={s: cases[ids[s]]['parameters'][s] for s in SYMBOLS},
        directions={s: cases[ids[s]]['directions'][s] if cases[ids[s]]['directions'] is not None else None for s in SYMBOLS})
    old_reference = {}
    for s in SYMBOLS:
        cid = OLD_SELECTED[s]
        old_rows = [mapped(r) for r in finance['reused_results'][cid]['rows'] if r['symbol'] == s]
        assert len(old_rows) == len(sessions) and {r['session'] for r in old_rows} == set(sessions)
        old_reference[s] = dict(id=cid, metrics=metrics(old_rows, sessions, s),
            source=finance['reused_results'][cid].get('source'), reuse_scope='旧選択の完成rows引用だけ。新候補・新観測・途中リスク選定には使わない。')
    same(old_reference['TOPIX']['metrics']['full']['mean_session_net'], 8260/33)
    same(old_reference['TOPIX']['metrics']['full']['mean_parent_net'], 1032.5)
    return dict(全合格=True, title=TITLE, sessions=sessions, cases=cases, pair=pair,
        old_reference=old_reference,
        sources=sources, 金融source_SHA256=finance['source_SHA256'], case_SHA256=finance['case_SHA256'],
        selection={s: choices[s][1] for s in SYMBOLS}, new_count=NEW_COUNT,
        main_achieved_symbols=sum(pair['metrics'][s]['full']['primary_pass'] for s in SYMBOLS),
        stability_achieved_symbols=sum(pair['metrics'][s]['full']['pass_all'] for s in SYMBOLS),
        robustness_qualified_symbols=sum(pair['metrics'][s]['qualified'] for s in SYMBOLS),
        criteria=dict(TOPIX全場平均net円=100000, NK225円額床=None, 金額割合=.65, 赤字率=.2,
            補填力='最大赤字場net<=平均黒字場net', 頑健性='主条件と別に上位3利益場を除外した残場平均net・65%・補填力'),
        correction=dict(旧TOPIX全場平均net円=8260/33, 旧TOPIX完結親平均net円=1032.5,
            旧TOPIX全量固定価格事後親平均円=9789., 新金融ではない=True),
        主金額='場内の完結実親net合計。場平均は損失・無取引込みの全場数で割る。親平均は参考。',
        主枚数='実決済玉net正負の勝ち枚数と負け枚数。親の勝敗枚数ではない。',
        容量換算='net円/(片方向保有上限×一枚倍率)。生の価格値幅でも追加金融でもない。',
        selection_rule='主条件→別頑健性→従来三基準→活動→Day活動→最大赤字の小ささ→同範囲MAE→ID。最大netで選ばない。',
        留保='同じ33場の既知内探索。価格代理時計・ラージ気配によるmini/micro代理約定。実キュー・部分約定・市場影響・未来勝率は未測。')


# ----------------------------------------
def row_table(headers: list, rows: list, name: str) -> str:
    """
    機能: 文字列セルの短い表を横スクロール領域へ包む。
    引数: headers(list[str])、rows(list[list[str]])、name(str)は見出し・セル・class。
    返り値: strはHTML。保存文字をエスケープする。
    """
    head = ''.join('<th>'+html.escape(h)+'</th>' for h in headers)
    body = ''.join('<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in r)+'</tr>' for r in rows)
    return '<div class="scroll"><table class="'+name+'"><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table></div>'


def overview_rows(data: dict, identifiers: list) -> list:
    """
    機能: 候補比較の親平均と安定性を共通の表示列へ並べる。
    引数: data(dict)、identifiers(list[str])は検算会計と表示候補。
    返り値: list[list[str]]は概要セル。平均勝ち親損益と混同しない。
    """
    rows = []
    for cid in identifiers:
        item = data['pair'] if cid == PAIR_ID else data['cases'][cid]
        for s in SYMBOLS:
            m = item['metrics'][s]
            f = m['full']
            rows.append([cid, LABELS[s], number(f['profit']), number(-f['loss']), number(f['net']),
                number(f['campaigns']), number(f['mean_session_net'], 1), number(f['mean_parent_net'], 1), percent(f['profit_share']),
                str(f['positive'])+'/'+str(f['negative'])+'/'+str(f['no_trade']),
                '○' if f['primary_pass'] else '未達', '○' if m['robustness_pass'] else '未達'])
    return rows


def session_table(item: dict, sessions: list) -> str:
    """
    機能: 全場と合計の親金額・実決済枚数を両商品並列表示する。
    引数: item(dict)、sessions(list[str])は検算済み候補と固定場順。
    返り値: strは一場十数値のHTML表。全合計に親平均の単純和を使わない。
    """
    index = {(r['session'], r['symbol']): r for r in item['rows']}
    rows = []
    for t in sessions+[None]:
        cells = '<th>'+('合計' if t is None else html.escape(t.replace('_Day', ' デイ').replace('_Night', ' ナイト')))+'</th>'
        for s in SYMBOLS:
            f = item['metrics'][s]['full'] if t is None else index[t, s]
            cells += cell(f['profit'])+cell(f['loss'], True)+cell(f['net'])+cell(f['winning_lots'])+cell(f['losing_lots'])
        rows.append('<tr'+(' class="total"' if t is None else '')+'>'+cells+'</tr>')
    head = '<tr><th rowspan="2">セッション</th><th colspan="5">TOPIXミニ・保有上限10枚</th><th colspan="5">日経マイクロ・保有上限20枚</th></tr><tr>'+('<th>利益円</th><th>損失円</th><th>収支円</th><th>勝ち枚数</th><th>負け枚数</th>'*2)+'</tr>'
    return '<div class="scroll"><table class="sessions"><thead>'+head+'</thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def detail_rows(item: dict, name: str) -> list:
    """
    機能: 主平均・容量利用・除外確認・昼夜を別の小表に分ける。
    引数: item(dict)、name(str)は候補と対象表。
    返り値: list[list[str]]は表示セル。未測定と無取引を区別する。
    """
    rows = []
    for s in SYMBOLS:
        m = item['metrics'][s]
        if name == 'economic':
            for title, f in (('全33場', m['full']), ('上位3利益場除外', m['top3'])):
                rows.append([LABELS[s], title, number(f['sessions']), number(f['campaigns']), number(f['mean_session_net'], 1), number(f['mean_parent_net'], 1),
                    '円床未指定' if f['economic_floor'] is None else ('○' if f['economic_pass'] else '未達'),
                    number(f['mean_session_capacity_net_points'], 4), percent(f['profit_share']),
                    percent(f['red_all']), number(f['mean_positive_session_net'], 1), number(-f['worst_session_loss'])])
        elif name == 'activity':
            for title, f in (('デイ', m['day']), ('ナイト', m['night'])):
                if f is not None: rows.append([LABELS[s], title, str(f['active'])+'/'+str(f['sessions']),
                    number(f['campaigns']), number(f['net']), number(f['mean_session_net'], 1), number(f['mean_parent_net'], 1)])
        elif name == 'capacity':
            saved = item['capacity'][s]
            rows.append([LABELS[s], str(CAPACITY[s]), number(None if saved is None else saved['mean_initial_quantity'], 2),
                percent(None if saved is None else saved['mean_initial_capacity_fraction']),
                number(None if saved is None else saved['maximum_same_side_holding']),
                percent(None if saved is None else saved['maximum_holding_capacity_fraction']),
                number(m['full']['capacity_net_points'], 4)])
        elif name == 'risk':
            saved = item['risk'][s]
            rows.append([LABELS[s], number(None if saved is None else saved['observed_parents']),
                number(None if saved is None else saved['maximum_fee_liquidation_MAE_yen']),
                number(None if saved is None else saved['two_vote_parents'])])
        elif name == 'session-economic':
            for r in (v for v in item['rows'] if v['symbol'] == s):
                own = [p for p in item['parents'] if p['symbol'] == s and p['session'] == r['session']]
                qs = [p['entry_quantity'] for p in own]
                rows.append([r['session'], LABELS[s], number(r['campaigns']),
                    number(r['net']/r['campaigns'] if r['campaigns'] else None, 1),
                    number(r['net']/(CAPACITY[s]*MULTIPLIER[s]), 4),
                    number(statistics.mean(qs) if qs else None, 2),
                    number(max((p['maximum_held_quantity'] for p in own), default=0)),
                    number(max((p['parent_mae_yen'] for p in own), default=None))])
    return rows


def supplements(item: dict) -> str:
    """
    機能: 経済床・容量・リスク・昼夜の検算表を折り畳む。
    引数: item(dict)は検算済み表示候補。
    返り値: strは詳細HTML。事後逆行は収益へ加算しない。
    """
    heads = {
        'economic': ['商品', '範囲', '全場数', '完結親数', '全場平均net円', '参考親平均円', '経済床', '全場平均容量pt', '金額利益割合', '赤字場率', '平均黒字場円', '最大赤字場円'],
        'capacity': ['商品', '保有上限', '初回平均枚数', '初回平均使用率', '最大片方向保有', '最大保有使用率', '全場合計容量pt'],
        'activity': ['商品', '時間帯', '活動場/全場', '完結親数', '収支円', '全場平均円', '参考親平均円'],
        'risk': ['商品', '観測親数', '最大事後親逆行円', '2票の親数']}
    tables = ''.join(row_table(headers, detail_rows(item, name), name) for name, headers in heads.items())
    local = row_table(['セッション', '商品', '完結親数', '親平均net円', '容量netpt', '初回平均枚数', '最大同時保有', '最大事後親逆行円'],
        detail_rows(item, 'session-economic'), 'session-economic')
    return '<details><summary>場平均の定義・容量・上位3除外・昼夜・途中逆行</summary>'+tables+'<p class="note">容量ptはnet円を上限枚数の倍率で割った会計尺度です。部分返済・可変枚数では平均の生値幅に置き換えません。途中逆行は事後診断です。TARGETの0.5%は初回約定建玉金額に対する注文規則で、全セッション平均10万円の実績とは別です。部分返済は25%を整数切捨てするため、初回10枚なら2枚（20%）です。GU対照にも新しい親/場の損失停止を加えており、旧GUの完全同値ではありません。</p></details><details><summary>場別の参考親平均と実使用枚数</summary>'+local+'</details>'


def render(data: dict) -> str:
    """
    機能: 結論・商品別設定・全場表を優先した短い暗色HTMLを作る。
    引数: data(dict)は検算済み公開会計。
    返り値: strはHTML。未達を形式合格だけで実用成功にしない。
    """
    pair = data['pair']
    top = pair['metrics']['TOPIX']['full']
    conclusion = 'TOPIXの損失・無取引込み一場平均10万円と三基準を満たしました。' if top['primary_pass'] else 'TOPIXの損失・無取引込み一場平均10万円と三基準を同時に満たす結論は得られていません。'
    conclusion += ' 日経の従来三基準は'+('合格です。' if pair['metrics']['NK225']['full']['pass_all'] else '未達です。')
    settings = [[LABELS[s], pair['selected'][s], pair['parameters'][s]['quantity_label'],
        pair['parameters'][s]['entry_label'], pair['parameters'][s]['exit_label']] for s in SYMBOLS]
    reference = [[LABELS[s], number(data['old_reference'][s]['metrics']['full']['mean_session_net'], 1),
        number(pair['metrics'][s]['full']['mean_session_net'], 1),
        number(data['old_reference'][s]['metrics']['full']['mean_parent_net'], 1),
        number(pair['metrics'][s]['full']['mean_parent_net'], 1)] for s in SYMBOLS]
    options = ['<option value="'+PAIR_ID+'" selected>商品別に固定した一組</option>']
    sections = ['<section data-case="'+PAIR_ID+'"><h2>固定設定の全セッション損益</h2>'+session_table(pair, data['sessions'])+supplements(pair)+'</section>']
    for cid, item in data['cases'].items():
        options.append('<option value="'+html.escape(cid)+'">'+html.escape(cid)+'</option>')
        sections.append('<section data-case="'+html.escape(cid)+'" hidden><h2>'+html.escape(cid)+'</h2>'+session_table(item, data['sessions'])+supplements(item)+'</section>')
    css = '*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#dce4f2;font:16px/1.55 system-ui}main{max-width:1450px;margin:auto;padding:24px 20px}h1{font-size:25px}h2{font-size:20px}a{color:#91c2ff}.note{color:#adbad1}select{width:100%;padding:10px;background:#18283f;color:#edf4ff;border:1px solid #6881a1;font:inherit}.scroll{max-width:100%;overflow:auto;margin:12px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px;border-bottom:1px solid #344660;white-space:nowrap;text-align:right}th:first-child,td:first-child{text-align:left}thead th,.total{background:#1c2e47}.sessions{min-width:1110px}.overview{min-width:1230px}.settings td{white-space:normal;overflow-wrap:anywhere}.positive{color:#64dfb7}.negative{color:#ff9ca1}.total{font-weight:bold}tbody tr:nth-child(even){background:#142137}details{margin:18px 0}summary{cursor:pointer;color:#b8d3fa}section[hidden]{display:none}@media(max-width:600px){main{padding:16px 12px}h1{font-size:22px}}'
    head = ['条件', '商品', '利益円', '損失円', '収支円', '完結親数', '全場平均net円', '参考親平均円', '金額利益割合', '黒/赤/無', '主条件', '上位3別確認']
    algorithm = '入口：二市場の方向が合う元E01候補に、60秒代理方向票と公開価格の許容上限を加え、表の枚数で一回だけ注文します。途中・出口：初回建玉金額に対する表の利確・追尾・部分返済を行い、0.125%の損失停止も併用します。利確後も次の候補へ参加し、静観時間とセッション終了で全量返済します。'
    script = '''<script>
/**
 * 固定組と候補の全セッション表を一つだけ表示する。
 * @param {string} id - 選択した固定候補ID。
 * @returns {void} 返り値はありません。金融や通信を行いません。
 */
function showCase(id){for(const section of document.querySelectorAll('section[data-case]'))section.hidden=section.dataset.case!==id;}
document.getElementById('case').addEventListener('change',function(){showCase(this.value);});
</script>'''
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><!--\n[コンポーネント概要]\n#case は商品別固定組と十四候補を切り替えます。\n[data-case] は全場の親金額と実決済玉枚数を表示します。\n.scroll は狭い画面の横スクロール領域です。\n--><main><h1>'+TITLE+'</h1><p>'+conclusion+' 日経の円額床は未指定です。</p><p class="note">旧版TOPIXの全33場平均は250.3円（参考親平均1,032.5円）でした。旧約定価格を10枚へ固定した9,789円も参考親平均で、新バックテストではありません。形式三基準の合格を利益規模の成功と扱った評価を訂正します。</p>'+row_table(['商品', '固定ID', '数量', '入口', '返済'], settings, 'settings')+row_table(head, overview_rows(data, [PAIR_ID]), 'overview principal')+row_table(['商品', '旧P1・全場平均円', '新・全場平均円', '旧・参考親平均円', '新・参考親平均円'], reference, 'baseline-comparison')+'<p>'+algorithm+'</p><p class="note">主評価は損失・無取引を含む全33場の平均収支です。活動場平均や参考親平均で代用しません。同じ33場の既知内選択で、未知の勝率は未確認です。</p><label for="case">全セッションの表示</label><select id="case">'+''.join(options)+'</select>'+''.join(sections)+'<details><summary>全十四候補の比較</summary>'+row_table(head, overview_rows(data, list(data['cases'])), 'overview all-cases')+'</details><p class="note">ラージ気配を価格代理にし、mini/microの料金を使用。価格代理時計、注文キュー・部分約定・市場影響は未測です。上位3除外は主条件と別の確認です。</p></main>'+script+'</body></html>'


# ----------------------------------------
def artificial() -> dict:
    """
    機能: 全場平均・参考親平均・無取引分母・容量換算・主/除外条件を人工確認する。
    引数: なし。実金融・保存結果は読まない。
    返り値: dictは純算術の検査件数。
    """
    rows = [dict(session='2026-01-'+str(i+1).zfill(2)+('_Day' if i%2 == 0 else '_Night'),
        symbol='TOPIX', profit=max(v, 0), loss=max(-v, 0), net=v,
        campaigns=1 if v else 0, winning_campaigns=int(v > 0), losing_campaigns=int(v < 0),
        winning_lots=int(v > 0)*10, losing_lots=int(v < 0)*10, fees=0.)
        for i, v in enumerate((300000., 200000., 180000., -80000., 0.))]
    value = economic_summary(rows, 'TOPIX')
    assert value['mean_parent_net'] == 150000. and value['economic_pass'] and value['primary_pass']
    assert value['mean_session_net'] == 120000. and value['mean_session_capacity_net_points'] == 12.
    assert value['campaigns'] == 4 and value['no_trade'] == 1 and value['losing_campaigns'] == 1
    assert value['mean_parent_capacity_net_points'] == 15. and value['capacity_net_points'] == 60.
    m = metrics(rows, [r['session'] for r in rows], 'TOPIX')
    assert m['full']['primary_pass'] and not m['robustness_pass'] and not m['qualified']
    nk = economic_summary(rows, 'NK225')
    assert nk['economic_pass'] is None and nk['economic_floor'] is None and nk['primary_pass']
    empty = economic_summary([dict(rows[-1], symbol='TOPIX')], 'TOPIX')
    assert empty['mean_parent_net'] is None and not empty['economic_pass'] and not empty['primary_pass']
    assert empty['mean_session_net'] == 0.
    sparse = economic_summary([dict(r, profit=200000. if i == 0 else 0., loss=0., net=200000. if i == 0 else 0.,
        campaigns=int(i == 0), winning_campaigns=int(i == 0), losing_campaigns=0, winning_lots=10 if i == 0 else 0, losing_lots=0)
        for i, r in enumerate(rows)], 'TOPIX')
    assert sparse['mean_parent_net'] == 200000. and sparse['mean_session_net'] == 40000.
    assert sparse['pass_all'] and not sparse['economic_pass'] and not sparse['primary_pass']
    assert number(-0.) == '0' and number(-.00001) == '0' and number(None) == '未定義'
    fixture = {cid: dict(metrics={'TOPIX': m}, risk={'TOPIX': None}) for cid in ('B', 'A')}
    chosen, trace = select(fixture, 'TOPIX')
    assert chosen == 'A' and not trace['同範囲逆行で判別']
    return dict(全合格=True, 純算術=12, 金融=0, API=0, input=0, ledger=0)


def main() -> None:
    """
    機能: 準備・人工又は根授権後の小会計確認と公開を実行する。
    引数: CLI --prepare-only/--artificial/--check-only/--root-publish と三小資料位置。
    返り値: None。準備は結果読0、公開は根専用。金融・APIを実行しない。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare-only', 'artificial', 'check-only', 'root-publish'):
        mode.add_argument('--'+name, action='store_true')
    for name in ('result', 'fixed', 'plan'): parser.add_argument('--'+name, type=Path)
    args = parser.parse_args()
    if args.prepare_only:
        print(json.dumps(dict(prepared=True, source_SHA256=digest(Path(__file__)),
            schema接続済み=SCHEMA_READY, 新条件=NEW_COUNT, title=TITLE, 会計名=ACCOUNTING_TITLE,
            TOPIX主経済床=100000, NK円額床=None, 金融=0, API=0, 結果読取=0, input=0, ledger=0, 公開=0), ensure_ascii=False))
        return
    if args.artificial:
        print(json.dumps(artificial(), ensure_ascii=False)); return
    assert SCHEMA_READY, '正式schema接続と根の金融完了通知前は結果を読みません。'
    assert all(getattr(args, key) is not None for key in ('result', 'fixed', 'plan'))
    values = {key: HELPERS.read_small(getattr(args, key)) for key in ('result', 'fixed', 'plan')}
    sources = {key: pair[1] for key, pair in values.items()}
    assert digest(SELECTION_PLAN) == SELECTION_SHA
    sources.update(display_source=digest(Path(__file__)), pure_reference=REFERENCE_SHA, economic_evidence=EVIDENCE,
        selection_plan=SELECTION_SHA)
    assert all(digest(ROOT/path) == sha for path, sha in EVIDENCE.items())
    data = build(*(values[key][0] for key in ('result', 'fixed', 'plan')), sources)
    if args.root_publish:
        PUBLIC.mkdir(parents=True, exist_ok=True)
        (PUBLIC/ACCOUNTING_TITLE).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        (PUBLIC/(TITLE+'.html')).write_text(render(data), encoding='utf-8')
    print(json.dumps(dict(全合格=True, selected=data['pair']['selected'], 主条件合格商品=data['main_achieved_symbols'],
        従来三基準合格商品=data['stability_achieved_symbols'], 別頑健性資格商品=data['robustness_qualified_symbols'],
        新条件=NEW_COUNT, 公開=int(args.root_publish), 金融=0, API=0, input=0, ledger=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
