"""完成した小会計から、銘柄別に一度固定する E01 の設定と全場損益を表示する。"""

import argparse
import hashlib
import html
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
PUBLIC = ROOT/'アルゴリズム調査/00105_公開価格を追わないE01の改善'
TITLE = '公開価格を追わないE01と銘柄別固定設定の全セッション損益'
ACCOUNTING_TITLE = '公開価格を追わないE01の全比較と銘柄別固定会計.json'
PAIR_ID = 'E01_SYMBOL_FIXED'
SYMBOLS = ('TOPIX', 'NK225')
LABELS = {'TOPIX': 'TOPIXミニ', 'NK225': '日経マイクロ'}
OLD_PARAMETERS = {
    'E01_ANCHOR_W60_CONFIRM_D0_P1_L2_A1': ('G25', 'P1'),
    'E01_CROSS_A02': ('G25', 'ATR25'),
    'E01_CROSS_B01': ('G50', 'P1'), 'E01_CROSS_B02': ('G50', 'ATR25'),
    'E01_CROSS_B03': ('G75', 'P1'), 'E01_CROSS_B04': ('G75', 'ATR25')}
GATES = {'G25': (.25, 2), 'G50': (.5, 2), 'G75': (.75, 2), 'G50N4': (.5, 4)}
EVIDENCE = HERE/'diagnosis/旧小事実と銘柄別候補及び次十八対照の因果順序.json'
EVIDENCE_SHA = '3dfa13e8e081acc166fe1336e21fe8aba702d52465698cd23cd2cc9ffbb745cf'
OLD_FINANCE_SHA = 'dd52f4401096942c5001b73306a3365759826611f18936192d7ec524c3a48585'
EXPECTED_COUNTS = dict(既input一読=33, 旧市場台帳一読=396, 保存GU再利用=198,
    新GUengine=594, 新政策会計=1188, 旧基準経済同値確認=396)
ACTIVITY_FIELDS = ('paper_candidates', 'known_votes', 'gate_accepted', 'actual_accepted', 'actual_newfills', 'fak_expired')
FAK_FIELDS = ('公開受理', '試行約定', '試行失効', '未試行取消')
CONTRIBUTIONS = ('収支変化', '避けた基準損失', '失った基準利益', '共通入口の数量/出口差', '新たな入口の収支')


def digest(path: Path) -> str:
    """
    機能: 表示 source 又は小資料の内容を SHA256 に結ぶ。
    引数: path(Path) は指紋を求めるファイル。
    返り値: str は SHA256。原入力・台帳を探索しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_small(path: Path) -> tuple:
    """
    機能: 完成小 JSON を同じ bytes で読み、指紋を返す。
    引数: path(Path) は正式結果・固定・計画・保存小診断。
    返り値: tuple[dict,str] は本文と SHA256。大入力の読取を拒否する。
    """
    assert path.suffix == '.json' and path.stat().st_size < 20_000_000, path
    data = path.read_bytes()
    return json.loads(data.decode('utf-8-sig')), hashlib.sha256(data).hexdigest()


def case_hashes(configs: list) -> dict:
    """
    機能: 条件の全項目を正規 JSON 指紋に結ぶ。
    引数: configs(list[dict]) は正式固定条件。
    返り値: dict[str,str] は条件指紋。表示側で金融条件を生成しない。
    """
    assert len(configs) == len({c['id'] for c in configs})
    return {c['id']: hashlib.sha256(json.dumps(c, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest() for c in configs}


def number(value: float | None, decimals: int = 0) -> str:
    """
    機能: 円額・枚数又は未定義を表示する。
    引数: value(float|None)、decimals(int) は値と小数桁。
    返り値: str は桁区切り数又は「未定義」。None を0へ補完しない。
    """
    if value is None: return '未定義'
    value = 0. if value == 0 else value
    rendered = f'{value:,.{decimals}f}'
    return rendered[1:] if rendered.startswith('-') and float(rendered.replace(',', '')) == 0 else rendered


def percent(value: float | None) -> str:
    """
    機能: 保存割合を百分率にする。
    引数: value(float|None) は0〜1の割合又は未定義。
    返り値: str は百分率文字列。
    """
    return '未定義' if value is None else f'{value*100:.1f}%'


def cell(value: float | None, loss: bool = False) -> str:
    """
    機能: 数値を検算属性・符号色付きセルへ変換する。
    引数: value(float|None)、loss(bool) は額と正数損失の指定。
    返り値: str は td。損失は表示だけ負符号にし、会計は正額のまま。
    """
    signed = None if value is None else -value if loss else value
    if signed == 0: signed = 0.
    style = '' if signed is None or signed == 0 else 'negative' if signed < 0 else 'positive'
    raw = '' if signed is None else repr(float(signed))
    return f'<td class="{style}" data-value="{raw}">{number(signed)}</td>'


def mapped(row: dict) -> dict:
    """
    機能: 保存親金額と実決済玉枚数を短い表示 schema に対応させる。
    引数: row(dict) は同商品・同セッションの完成会計。
    返り値: dict は円額・枚数・親数。金融の再生は行わない。
    """
    value = dict(session=row['session'], symbol=row['symbol'], profit=float(row['利益']),
        loss=float(row['損失']), net=float(row['収支']), campaigns=int(row['親数']),
        winning_campaigns=int(row['勝ち親']), losing_campaigns=int(row['負け親']),
        winning_lots=int(row['勝ち枚数']), losing_lots=int(row['負け枚数']), fees=float(row['費用']))
    assert all(math.isfinite(v) for v in value.values() if isinstance(v, (int, float)))
    assert value['profit'] >= 0 and value['loss'] >= 0
    assert abs(value['profit']-value['loss']-value['net']) < 1e-5
    return value


def summary(rows: list) -> dict:
    """
    機能: 同商品・任意場数の三基準を親金額から純集計する。
    引数: rows(list[dict]) は重複のない同商品表示会計。
    返り値: dict は利益割合・赤字率・補填力と額/実決済枚数。
    """
    assert rows and len(rows) == len({r['session'] for r in rows})
    gain, loss = sum(r['profit'] for r in rows), sum(r['loss'] for r in rows)
    nets = [r['net'] for r in rows]; green = [v for v in nets if v > 0]
    red = [v for v in nets if v < 0]; active = sum(r['campaigns'] > 0 for r in rows)
    share = gain/(gain+loss) if gain+loss else None
    mean = statistics.mean(green) if green else None; worst = max([0.]+[-v for v in red])
    tests = dict(share65=share is not None and share >= .65,
        red20=len(red)/len(rows) <= .2, coverage=mean is not None and worst <= mean)
    return dict(profit=gain, loss=loss, net=gain-loss, profit_share=share,
        sessions=len(rows), positive=len(green), negative=len(red), active=active,
        no_trade=len(rows)-active, red_all=len(red)/len(rows),
        mean_positive_session_net=mean, worst_session_loss=worst,
        campaigns=sum(r['campaigns'] for r in rows), winning_campaigns=sum(r['winning_campaigns'] for r in rows),
        losing_campaigns=sum(r['losing_campaigns'] for r in rows),
        winning_lots=sum(r['winning_lots'] for r in rows), losing_lots=sum(r['losing_lots'] for r in rows),
        fees=sum(r['fees'] for r in rows), tests=tests, pass_all=all(tests.values()))


def metrics(rows: list, sessions: list) -> dict:
    """
    機能: 全場・利益上位三除外・昼夜・前後の固定集合を純集計する。
    引数: rows(list[dict])、sessions(list[str]) は同商品会計と正式場順。
    返り値: dict は期間指標。無取引を勝ちに含めず、将来ルールへ使わない。
    """
    assert len(rows) == len(sessions) == len(set(sessions))
    assert {r['session'] for r in rows} == set(sessions)
    removed = sorted((r for r in rows if r['net'] > 0), key=lambda r: (-r['net'], r['session']))[:3]
    excluded = {r['session'] for r in removed}; trimmed = [r for r in rows if r['session'] not in excluded]
    full, trim = summary(rows), summary(trimmed)
    trim['removed_sessions'] = [r['session'] for r in removed]
    qualified = full['pass_all'] and trim['tests']['share65'] and trim['tests']['coverage']
    return dict(full=full, top3=trim, qualified=qualified,
        day=summary([r for r in rows if r['session'].endswith('_Day')]),
        night=summary([r for r in rows if r['session'].endswith('_Night')]),
        first=summary([r for r in rows if r['session'] in set(sessions[:16])]),
        last=summary([r for r in rows if r['session'] in set(sessions[16:])]))


def same(actual: float | None, expected: float | None) -> None:
    """
    機能: 保存値と表示集計の一致を、未定義を区別して確認する。
    引数: actual/expected(float|None) は同一会計定義の数値。
    返り値: None。不一致は表示公開を止める。
    """
    assert actual is expected if actual is None or expected is None else abs(actual-expected) < 1e-5


def check_saved(value: dict, aggregate: dict, stability: dict | None) -> None:
    """
    機能: 円額・実決済枚数・場数・三基準を正式小保存へ照合する。
    引数: value/aggregate(dict)、stability(dict|None) は表示再集計と保存値。
    返り値: None。親の勝敗を決済玉の勝敗に置き換えない。
    """
    pairs = {'profit': '利益', 'loss': '損失', 'net': '収支', 'winning_lots': '勝ち枚数',
        'losing_lots': '負け枚数', 'campaigns': '親数', 'winning_campaigns': '勝ち親', 'losing_campaigns': '負け親'}
    for a, b in pairs.items(): same(value[a], aggregate[b])
    if stability is None: return
    pairs = {'sessions': 'session_count', 'active': 'active_sessions', 'positive': 'positive_sessions',
        'negative': 'losing_sessions', 'no_trade': 'no_trade_sessions', 'red_all': 'red_full_rate',
        'profit_share': 'profit_share', 'mean_positive_session_net': 'mean_positive_session_net_yen',
        'worst_session_loss': 'worst_negative_session_abs_yen'}
    for a, b in pairs.items(): same(value[a], stability[b])
    assert tuple(value['tests'].values()) == (stability['target65'], stability['target_red20'], stability['target_worst_mean'])
    assert value['pass_all'] == stability['all_targets']


def parameters(ident: str, config: dict | None) -> dict:
    """
    機能: 結果前に固定した機械条件を、短い静的設定表へ対応させる。
    引数: ident(str)、config(dict|None) は正式新条件又は旧保存対照。
    返り値: dict は入口強度・最低票数・新規制限・利益線。収益から規則を作らない。
    """
    if ident in OLD_PARAMETERS:
        gate, target = OLD_PARAMETERS[ident]; execution = 'MARKET'
        if config is not None:
            assert config.get('target_basis') == ('P1' if target == 'P1' else 'ATR')
    else:
        assert config is not None
        gate, target, execution = config['entry_id'], config['target_id'], config['execution_id']
        assert gate in GATES and target in ('P1', 'ATR25') and execution in ('MARKET', 'FAK0', 'FAK1')
        assert (config['balance_threshold'], config['min_votes']) == GATES[gate]
    balance, count = GATES[gate]
    return dict(entry_id=gate, balance_threshold=balance, min_votes=count, execution_id=execution,
        target_id=target, target_label='初回受理枚数の1観測呼値相当を純利確' if target == 'P1' else '初回受理建玉の0.25ATR相当を純利確',
        execution_label={'MARKET': '元成行', 'FAK0': '公開価格を超えない一回FAK',
            'FAK1': '1観測呼値まで不利を許す一回FAK'}[execution])


def risk_evidence(raw: dict, symbol: str) -> dict | None:
    """
    機能: 正式結果にある同範囲の途中逆行根拠だけを保持する。
    引数: raw(dict)、symbol(str) は当該政策保存と商品。
    返り値: dict|None は保存範囲付きリスク根拠又は未保存。未知を0にしない。
    """
    saved = raw.get('holding_diagnostics', {}).get(symbol)
    if saved is None: return None
    assert isinstance(saved['observed_parents'], int) and saved['observed_parents'] >= 0
    assert isinstance(saved['complete'], bool) and saved['maximum_fee_liquidation_MAE_yen'] >= 0
    return saved


def select(cases: dict, symbol: str) -> tuple:
    """
    機能: 商品ごとに一度だけ設定を選び、全場へ固定する。
    引数: cases(dict)、symbol(str) は全保存政策と対象商品。
    返り値: tuple[str,dict] は選択IDと判別根拠。円合算・場別選択を行わない。
    """
    def primary(ident: str) -> tuple:
        """
        機能: 全場と大勝ち除外後の資格を優先して活動を比較する。
        引数: ident(str) は当該政策ID。
        返り値: tuple は資格・基準数・活動・昼活動の順序。
        """
        v = cases[ident]['metrics'][symbol]; full, trim = v['full'], v['top3']
        return (v['qualified'], full['pass_all'], sum(full['tests'].values()),
            trim['tests']['share65']+trim['tests']['coverage'], full['active'], v['day']['active'])
    highest = max(primary(ident) for ident in cases)
    tied = [ident for ident in cases if primary(ident) == highest]
    observed = [cases[ident]['risk'][symbol] for ident in tied]
    complete = all(v is not None and v['complete'] and
        v['observed_parents'] == cases[ident]['metrics'][symbol]['full']['campaigns']
        for ident, v in zip(tied, observed))
    if complete:
        safest = min(v['maximum_fee_liquidation_MAE_yen'] for v in observed)
        tied = [ident for ident in tied if cases[ident]['risk'][symbol]['maximum_fee_liquidation_MAE_yen'] == safest]
    selected = sorted(tied)[0]
    return selected, dict(primary=list(highest), 最終同順位=tied, 途中逆行で判別=complete,
        同値処理='ID昇順。未保存のリスクを0として優遇しない。',
        地位='全33場を使用した既知内の銘柄別固定選択。場の結果や先の方向で切り替えない。')


# ----------------------------------------
def guard(finance: dict, fixed: dict, plan: dict, plan_sha: str) -> None:
    """
    機能: 完成18政策・旧6保存対照を正式固定と source 指紋へ束縛する。
    引数: finance/fixed/plan(dict)、plan_sha(str) は完成小結果・事前固定・計画と直接指紋。
    返り値: None。未完成・金融失敗・未正式固定から公開を作らない。
    """
    assert finance['全合格'] and fixed['全合格'] and plan['正式freeze']
    assert finance['source開始終端一致']
    assert finance['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    assert all(digest(ROOT/path) == sha for path, sha in finance['source_SHA256'].items())
    assert fixed['計画SHA256'] == plan_sha
    assert finance['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
    assert case_hashes(finance['configs']) == fixed['case_SHA256'] == finance['case_SHA256']
    assert len(finance['configs']) == len(finance['results']) == 18
    assert {c['id'] for c in finance['configs']} == set(finance['results'])
    assert set(finance['reused_results']) == set(OLD_PARAMETERS)
    assert finance['counts'] == EXPECTED_COUNTS
    assert all(plan['予定'][k] == v for k, v in EXPECTED_COUNTS.items())
    assert finance['会計口座数'] == EXPECTED_COUNTS['新政策会計']
    for ident, old in finance['reused_results'].items():
        saved = fixed['reused_results'][ident]
        assert all(old[k] == saved[k] for k in ('rows', 'symbols', 'config', 'source', 'SHA256'))
        gate, target = OLD_PARAMETERS[ident]
        assert old['config']['id'] == ident and old['config']['entry_id'] == gate
        assert old['config']['execution_id'] == 'MARKET' and old['config']['target_id'] == target
    assert finance['sessions'] == fixed['sessions'] and len(finance['sessions']) == len(set(finance['sessions'])) == 33
    assert finance['API'] == finance['現在入力'] == finance['原板'] == finance['NPZ'] == finance['旧金融再生'] == 0


def check_diagnostics(finance: dict, sessions: list) -> None:
    """
    機能: 保存した全候補タグと実政策接頭のFAK件数を小JSONだけで再集計する。
    引数: finance(dict)、sessions(list[str]) は正式完成小結果と全33場。
    返り値: None。全判断列や原板を再読せず、重複タグを単一原因にしない。
    """
    routes = {g+'|'+e for g in GATES for e in ('FAK0', 'FAK1', 'MARKET')}
    records = finance['GU_activity']; assert set(records) == set(sessions)
    computed = {}
    for session, accounts in records.items():
        assert set(accounts) == set(SYMBOLS)
        for s, own in accounts.items():
            assert set(own) == routes
            for route, value in own.items():
                assert all(isinstance(value[k], int) and value[k] >= 0 for k in ACTIVITY_FIELDS)
                assert sum(value['overlap_patterns'].values()) == value['paper_candidates']
                assert value['flags'].get('実予約受理', 0) == value['actual_accepted']
                for scope in ('全33', session.rsplit('_', 1)[-1]):
                    box = computed.setdefault(route, {}).setdefault(s, {}).setdefault(scope,
                        dict(sessions=0, **{k: 0 for k in ACTIVITY_FIELDS}, flags={}, overlap_patterns={}))
                    box['sessions'] += 1
                    for k in ACTIVITY_FIELDS: box[k] += value[k]
                    for k in ('flags', 'overlap_patterns'):
                        for label, count in value[k].items(): box[k][label] = box[k].get(label, 0)+count
    assert computed == finance['GU_activity_summary']
    assert set(finance['fak_diagnosis']) == set(finance['fak_summary']) == set(finance['results'])
    for cid, values in finance['fak_diagnosis'].items():
        assert len(values) == len({(r['session'], r['symbol']) for r in values}) == 66
        for s in SYMBOLS:
            own = [r for r in values if r['symbol'] == s]; assert len(own) == 33
            result = {scope: {k: sum(r[scope][k] for r in own) for k in FAK_FIELDS}
                for scope in ('GU全試行', '実政策判断行以下の試行')}
            result.update(初受理と実初回差場数=sum(r['first_anchor_to_actual_diff'] for r in own),
                初受理未約定から後参加への尺度持越し場数=sum(r['carryover_after_unfilled_initial'] for r in own),
                持越し先の数量差場数=sum(r['carryover_quantity_changed'] for r in own))
            assert result == finance['fak_summary'][cid][s]
            for k in FAK_FIELDS:
                assert result['実政策判断行以下の試行'][k] <= result['GU全試行'][k]


def build(finance: dict, fixed: dict, plan: dict, sources: dict, evidence: dict | None = None) -> dict:
    """
    機能: 完成小会計だけを検算し、銘柄別固定の一組と全24政策を作る。
    引数: finance/fixed/plan/sources(dict)、evidence(dict|None) は正式資料と保存小診断。
    返り値: dict は公開小会計。実入力・台帳・金融をimport又は実行しない。
    """
    guard(finance, fixed, plan, sources['plan'])
    sessions = finance['sessions']; configs = {c['id']: c for c in finance['configs']}; cases = {}
    check_diagnostics(finance, sessions)
    for ident, raw in {**finance['reused_results'], **finance['results']}.items():
        rows = [mapped(row) for row in raw['rows']]
        assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 66
        assert {r['symbol'] for r in rows} == set(SYMBOLS)
        m = {s: metrics([r for r in rows if r['symbol'] == s], sessions) for s in SYMBOLS}
        reused = ident not in configs
        if not reused:
            assert all(k in raw for k in ('stability', 'periods', 'directional_symbols'))
        for s in SYMBOLS:
            check_saved(m[s]['full'], raw['symbols'][s], raw.get('stability', {}).get(s))
            same(m[s]['full']['net'], raw['actual_leg_symbols'][s]['収支'])
            if raw.get('periods') is not None:
                for tag, field in (('全33', 'full'), ('前16', 'first'), ('後17', 'last'), ('上位3正収支場除外', 'top3')):
                    check_saved(m[s][field], raw['periods'][s][tag]['aggregate'], raw['periods'][s][tag]['stability'])
                assert m[s]['top3']['removed_sessions'] == raw['periods'][s]['除外場']
            if raw.get('directional_symbols') is not None:
                sides = raw['directional_symbols'][s]
                for field, key in (('profit', '利益'), ('loss', '損失'), ('net', '収支')):
                    same(m[s]['full'][field], sum(sides[t][key] for t in ('long', 'short')))
        cases[ident] = dict(rows=rows, metrics=m, parameters=parameters(ident, configs.get(ident)),
            reused=reused, directions=raw.get('directional_symbols'), actual_legs=raw['actual_leg_symbols'],
            risk={s: risk_evidence(raw, s) for s in SYMBOLS},
            gu_activity=finance['GU_activity_summary'][parameters(ident, configs.get(ident))['entry_id']+'|'+parameters(ident, configs.get(ident))['execution_id']],
            fak_summary=finance['fak_summary'].get(ident), fak_diagnosis=finance['fak_diagnosis'].get(ident),
            boundary=finance['boundary'].get(ident))
    for cid, config in configs.items():
        changes = finance['各場寄与'][cid]
        assert len(changes) == len({(r['session'], r['symbol']) for r in changes}) == 66
        assert all(r['baseline_id'] == config['baseline_id'] for r in changes)
        boundary = finance['boundary'][cid]
        assert len(boundary) == len({(r['session'], r['symbol']) for r in boundary}) == 66
        assert boundary == finance['初回受理と費用後目標境界'][cid]
        for s in SYMBOLS:
            own = [r for r in changes if r['symbol'] == s]; saved = finance['diagnosis'][cid][s]
            for k in CONTRIBUTIONS: same(sum(r[k] for r in own), saved[k])
            same(saved['収支変化'], cases[cid]['metrics'][s]['full']['net']-cases[config['baseline_id']]['metrics'][s]['full']['net'])
            same(saved['収支変化'], saved['避けた基準損失']-saved['失った基準利益']+
                saved['共通入口の数量/出口差']+saved['新たな入口の収支'])
            assert saved['元勝ち親が赤字化'] == sum(len(r['元勝ち親が赤字化']) for r in own)
    if evidence is not None:
        assert evidence['全合格'] and evidence['sources']['十六会計']['SHA256'] == OLD_FINANCE_SHA
        for ident, values in evidence['保存B四条件'].items():
            if ident not in cases: continue
            for s in SYMBOLS: same(cases[ident]['metrics'][s]['full']['net'], values[s]['symbols']['収支'])
        for s in SYMBOLS:
            v = evidence['B03母数と昼夜'][s]
            assert v['実親'] == cases['E01_CROSS_B03']['metrics'][s]['full']['campaigns']
            cases['E01_CROSS_B03']['risk'][s] = dict(observed_parents=v['実親'], complete=True,
                maximum_fee_liquidation_MAE_yen=v['最大事後清算逆行'],
                two_vote_parents=v['二票'], below_four_vote_parents=v['二又は三票'],
                scope='00104保存B03実親全数。次FAK政策へ観測を継承しない。')
    choices = {s: select(cases, s) for s in SYMBOLS}; selected = {s: value[0] for s, value in choices.items()}
    pair_rows = [r for session in sessions for s in SYMBOLS
        for r in cases[selected[s]]['rows'] if r['session'] == session and r['symbol'] == s]
    pair = dict(rows=pair_rows, metrics={s: cases[selected[s]]['metrics'][s] for s in SYMBOLS},
        selected=selected, risk={s: cases[selected[s]]['risk'][s] for s in SYMBOLS},
        parameters={s: cases[selected[s]]['parameters'] for s in SYMBOLS},
        directions={s: cases[selected[s]]['directions'][s] if cases[selected[s]]['directions'] is not None else None for s in SYMBOLS},
        gu_activity={s: cases[selected[s]]['gu_activity'][s] for s in SYMBOLS},
        fak_summary={s: cases[selected[s]]['fak_summary'][s] if cases[selected[s]]['fak_summary'] is not None else None for s in SYMBOLS})
    return dict(全合格=True, title=TITLE, sessions=sessions, cases=cases, pair=pair,
        selection={s: choices[s][1] for s in SYMBOLS}, sources=sources,
        金融source_SHA256=finance['source_SHA256'], case_SHA256=finance['case_SHA256'],
        new_count=18, reused_count=6,
        main_achieved_symbols=sum(pair['metrics'][s]['full']['pass_all'] for s in SYMBOLS),
        selection_qualified_symbols=sum(pair['metrics'][s]['qualified'] for s in SYMBOLS),
        new_common_main_pass=sum(all(cases[cid]['metrics'][s]['full']['pass_all'] for s in SYMBOLS) for cid in configs),
        reused_common_main_pass=sum(all(cases[cid]['metrics'][s]['full']['pass_all'] for s in SYMBOLS) for cid in OLD_PARAMETERS),
        new_common_qualified=sum(all(cases[cid]['metrics'][s]['qualified'] for s in SYMBOLS) for cid in configs),
        reused_common_qualified=sum(all(cases[cid]['metrics'][s]['qualified'] for s in SYMBOLS) for cid in OLD_PARAMETERS),
        selection_rule='全33三基準と上位3除外後65%及び補填力を優先し、その資格内で活動→デイ活動→保存が同範囲で揃う途中逆行。同値ID昇順。未達時の参考選択を成功とはしない。',
        GU_activity_summary=finance['GU_activity_summary'], fak_summary=finance['fak_summary'],
        criteria=dict(share65=.65, red20=.2, coverage='最大赤字場net<=平均黒字場net',
            top3='利益上位3場を除いた金額割合65%以上・最大赤字<=平均黒字'),
        主金額='手数料後の完結実親net正負', 主枚数='実決済玉net正負による勝ち枚数/負け枚数',
        side='完結親の初回方向。方向別枚数は勝敗親の建玉総数。',
        新金融=0, API=0, input=0, ledger=0, 原板=0, NPZ=0, 旧公共変更=0)


# ----------------------------------------
def overview(data: dict, identifiers: list) -> str:
    """
    機能: 全24政策の額・場数・五資格を折り畳み一覧用に表示する。
    引数: data(dict)、identifiers(list[str]) は検算会計と固定政策ID。
    返り値: str は48商品行の概要表。商品間の円額順位を作らない。
    """
    body = []
    for ident in identifiers:
        case = data['cases'][ident]
        for s in SYMBOLS:
            v = case['metrics'][s]; full, trim = v['full'], v['top3']
            body.append(f'<tr data-case-id="{ident}" data-symbol="{s}"><td>{html.escape(ident)}'
                f'<small>{"旧保存対照" if case["reused"] else "新政策"}</small></td><td>{LABELS[s]}</td>'
                +cell(full['profit'])+cell(full['loss'], True)+cell(full['net'])
                +f'<td>{percent(full["profit_share"])}</td><td>{full["positive"]}/{full["negative"]}/{full["no_trade"]}</td>'
                +cell(full['mean_positive_session_net'])+cell(full['worst_session_loss'], True)
                +cell(trim['net'])+f'<td>{"合格" if full["pass_all"] else "未達"} / {"適合" if v["qualified"] else "不適合"}</td></tr>')
    return ('<div class="scroll"><table id="overview"><thead><tr><th>固定政策</th><th>商品</th>'
        '<th>利益円</th><th>損失円</th><th>収支円</th><th>金額利益割合</th><th>黒字/赤字/無</th>'
        '<th>平均黒字場円</th><th>最大赤字円</th><th>上位3除外収支円</th><th>主三基準 / 頑健性選択資格</th>'
        '</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>')


def session_table(rows: list, metrics_by_symbol: dict, sessions: list) -> str:
    """
    機能: 全33場と合計の親金額・実決済玉勝負枚数を表示する。
    引数: rows(list[dict])、metrics_by_symbol(dict)、sessions(list[str]) は検算済み会計。
    返り値: str は34行・10数値列の表。無取引も掲載する。
    """
    indexed = {(r['session'], r['symbol']): r for r in rows}; body = []
    for session in sessions+[None]:
        values = []
        for s in SYMBOLS:
            v = metrics_by_symbol[s]['full'] if session is None else indexed[session, s]
            values.extend((cell(v['profit']), cell(v['loss'], True), cell(v['net']),
                cell(v['winning_lots']), cell(v['losing_lots'])))
        label = '全33場合計' if session is None else session.replace('_Day', ' デイ').replace('_Night', ' ナイト')
        attribute = ' class="total"' if session is None else f' data-session="{session}"'
        body.append(f'<tr{attribute}><th>{label}</th>'+''.join(values)+'</tr>')
    return ('<div class="scroll"><table class="sessions"><thead><tr><th rowspan="2">セッション</th>'
        '<th colspan="5">TOPIXミニ・片方向上限10枚</th><th colspan="5">日経マイクロ・片方向上限20枚</th></tr><tr>'
        +('<th>利益円</th><th>損失円</th><th>収支円</th><th>勝ち枚数</th><th>負け枚数</th>'*2)
        +'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>')


def supplements(item: dict) -> str:
    """
    機能: 三基準・大勝ち除外・昼夜・方向・保存途中逆行を折り畳む。
    引数: item(dict) は銘柄別固定一組又は同一政策の完成指標。
    返り値: str は補足表。未保存の票・逆行を0にせず明示する。
    """
    stability, activity, direction, risk, parents, candidates, rejection, fak = [], [], [], [], [], [], [], []
    for s in SYMBOLS:
        v = item['metrics'][s]
        for tag, metric in (('全33場', v['full']), ('上位3利益場除外', v['top3'])):
            stability.append(f'<tr data-period="{tag}" data-symbol="{s}"><td>{tag}</td><td>{LABELS[s]}</td>'
                +cell(metric['net'])+f'<td>{percent(metric["profit_share"])}</td><td>{percent(metric["red_all"])}</td>'
                +cell(metric['mean_positive_session_net'])+cell(metric['worst_session_loss'], True)
                +f'<td>{" / ".join("○" if p else "×" for p in metric["tests"].values())}</td></tr>')
        for tag in ('day', 'night', 'first', 'last'):
            p = v[tag]; label = {'day': 'デイ', 'night': 'ナイト', 'first': '前16場', 'last': '後17場'}[tag]
            activity.append(f'<tr data-period="{tag}" data-symbol="{s}"><td>{label}</td><td>{LABELS[s]}</td>'
                +cell(p['net'])+f'<td>{p["active"]}/{p["sessions"]}</td><td>{p["positive"]}/{p["negative"]}/{p["no_trade"]}</td></tr>')
        full = v['full']
        parents.append(f'<tr data-symbol="{s}"><td>{LABELS[s]}</td>'
            +cell(full['campaigns'])+cell(full['winning_campaigns'])+cell(full['losing_campaigns'])+'</tr>')
        if item['directions'] is None or item['directions'][s] is None:
            direction.append(f'<tr data-symbol="{s}"><td colspan="7">{LABELS[s]}の方向別親集計は未保存</td></tr>')
        else:
            for side, label in (('long', '買い'), ('short', '売り')):
                p = item['directions'][s][side]
                direction.append(f'<tr data-side="{side}" data-symbol="{s}"><td>{label}</td><td>{LABELS[s]}</td>'
                    +cell(p['利益'])+cell(p['損失'], True)+cell(p['収支'])
                    +cell(p['勝ち枚数'])+cell(p['負け枚数'])+'</tr>')
        saved = item['risk'][s]
        if saved is None:
            risk.append(f'<tr data-symbol="{s}"><td>{LABELS[s]}</td><td colspan="4">票数・保有中の清算逆行はこの小会計に未保存</td></tr>')
        else:
            risk.append(f'<tr data-symbol="{s}"><td>{LABELS[s]}</td><td>{saved["observed_parents"]}</td>'
                +cell(saved['maximum_fee_liquidation_MAE_yen'], True)
                +f'<td>{number(saved.get("two_vote_parents"))}</td><td>{number(saved.get("below_four_vote_parents"))}</td></tr>')
        for scope in ('全33', 'Day', 'Night'):
            observed = item['gu_activity'][s][scope]
            label = {'全33': '全33場', 'Day': 'デイ', 'Night': 'ナイト'}[scope]
            candidates.append(f'<tr data-period="{scope}" data-symbol="{s}"><td>{label}</td><td>{LABELS[s]}</td>'
                +''.join(cell(observed[k]) for k in ACTIVITY_FIELDS)+'</tr>')
            rejection.append(f'<tr data-period="{scope}" data-symbol="{s}"><td>{label}</td><td>{LABELS[s]}</td>'
                +''.join(cell(observed['flags'].get(k, 0)) for k in ('票UNKNOWN', '方向票不足', '釣合い不足',
                    '数量ゼロ', '予定静観期限', '実保有予約busy', 'その他の継続取消状態'))+'</tr>')
        observed = item['fak_summary'][s] if item['fak_summary'] is not None else None
        if observed is None:
            fak.append(f'<tr data-symbol="{s}"><td colspan="8">{LABELS[s]}は旧保存成行対照：FAK試行なし</td></tr>')
        else:
            fak.append(f'<tr data-symbol="{s}"><td>{LABELS[s]}</td>'
                +''.join(cell(observed['実政策判断行以下の試行'][k]) for k in FAK_FIELDS)
                +''.join(cell(observed[k]) for k in ('初受理と実初回差場数', '初受理未約定から後参加への尺度持越し場数',
                    '持越し先の数量差場数'))+'</tr>')
    def table(headers: str, body: list, style: str) -> str:
        """
        機能: 補足表を横スクロール領域へ包む。
        引数: headers(str)、body(list[str])、style(str) は見出し・完成行・検査名。
        返り値: str は補足 table。
        """
        return f'<div class="scroll"><table class="{style}"><thead><tr>{headers}</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'
    return ('<details><summary>三基準・大勝ち除外・活動と途中リスク</summary>'
        +table('<th>範囲</th><th>商品</th><th>収支円</th><th>金額割合</th><th>赤字率</th><th>平均黒字場円</th><th>最大赤字円</th><th>65%/20%/補填力</th>', stability, 'stability')
        +table('<th>範囲</th><th>商品</th><th>収支円</th><th>活動/全場</th><th>黒字/赤字/無</th>', activity, 'activity')
        +table('<th>商品</th><th>診断親数</th><th>最大清算逆行円</th><th>2票親数</th><th>2～3票親数</th>', risk, 'risk')
        +'<p class="note">途中逆行は事後診断で、別出口の実現損失ではありません。未保存を0扱いしません。票は代理更新数で、真の攻撃注文数・独立標本数ではありません。</p>'
        +table('<th>商品</th><th>完結親数</th><th>勝ち親数</th><th>負け親数</th>', parents, 'parents')
        +table('<th>初回方向</th><th>商品</th><th>親利益円</th><th>親損失円</th><th>親収支円</th><th>勝ち親の建玉枚数</th><th>負け親の建玉枚数</th>', direction, 'direction')
        +'<p class="note">買売表の枚数は勝敗親の建玉総数。主表の実決済玉勝敗枚数とは別です。前後両期間とも開発に使用した既知データです。</p></details>'
        +'<details><summary>票数不足・数量0・未約定と後参加の母数</summary>'
        +table('<th>範囲</th><th>商品</th><th>公開候補</th><th>票情報既知候補</th><th>入口票門通過</th><th>数量予約受理</th><th>元模型新規約定</th><th>FAK失効</th>', candidates, 'candidates')
        +table('<th>範囲</th><th>商品</th><th>票不明</th><th>最低票数不足</th><th>釣合い不足</th><th>数量0</th><th>静観/期限</th><th>保有/予約中</th><th>その他取消状態</th>', rejection, 'rejection')
        +'<p class="note">上2表は利益停止後も含む元判断模型の全候補です。タグは重複するため足し算して単独の不足原因にしません。実親の勝率や実政策の取引件数とは別です。</p>'
        +table('<th>商品</th><th>公開受理</th><th>試行約定</th><th>試行失効</th><th>未試行取消</th><th>初受理/実初回差の場数</th><th>未約定後の尺度持越し場数</th><th>持越し先数量差の場数</th>', fak, 'fak')
        +'<p class="note">FAK件数は元判断模型の停止判断行まで。成行にFAK試行はありません。初受理の取消後も利確尺度を固定するため、後参加の実枚数が異なる場を別に示します。</p></details>')


def render(data: dict) -> str:
    """
    機能: 銘柄別固定設定の一組を主表とし、全比較を選べる暗色 HTML を作る。
    引数: data(dict) は検算済み公開会計。
    返り値: str は単一 HTML。金融再生・通信・将来判定を含まない。
    """
    pair = data['pair']; clauses, parameters_rows = [], []
    for s in SYMBOLS:
        v, p = pair['metrics'][s]['full'], pair['parameters'][s]
        clauses.append(f'{LABELS[s]}は{number(v["net"])}円（{v["positive"]}黒字・{v["negative"]}赤字・{v["no_trade"]}無取引）')
        parameters_rows.append(f'<tr data-symbol="{s}"><td>{LABELS[s]}</td><td>{p["balance_threshold"]:g}／{p["min_votes"]}票以上</td>'
            f'<td>{p["execution_label"]}</td><td>{p["target_label"]}</td><td>{pair["selected"][s]}</td></tr>')
    if data['main_achieved_symbols'] == 2:
        claim = '今回の既知データでは、次の銘柄別固定設定が両商品の全33場の主三基準を満たしました。'
    else:
        claim = f'両商品での主三基準達成は未到達です（{data["main_achieved_symbols"]}/2）。以下は未達を含む比較候補です。'
    robustness_note = f'上位3利益場を除く確認も通る選択資格は{data["selection_qualified_symbols"]}/2商品です。主三基準の追加条件としては扱いません。'
    activity_note = ('無取引を含むため、毎場安定した利益の達成とは呼びません。'
        if any(pair['metrics'][s]['full']['no_trade'] > 0 for s in SYMBOLS) else '')
    options = [f'<option value="{PAIR_ID}" selected>商品別に固定した一組</option>']; sections = []
    for ident, case in data['cases'].items():
        safe = html.escape(ident, quote=True)
        options.append(f'<option value="{safe}">{safe}（{"旧保存" if case["reused"] else "新政策"}）</option>')
        sections.append(f'<section data-case="{safe}" hidden><h2>{safe}</h2>'
            +session_table(case['rows'], case['metrics'], data['sessions'])+supplements(case)+'</section>')
    css = '*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#dce4f2;font:16px/1.55 system-ui}main{max-width:1450px;margin:auto;padding:24px 20px}h1{font-size:26px}h2{font-size:20px}a{color:#91c2ff}.note,small{color:#adbad1}small{display:block;font-size:11px}select{width:100%;padding:10px;background:#18283f;color:#edf4ff;border:1px solid #6881a1;font:inherit}.scroll{max-width:100%;overflow:auto;margin:12px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px;border-bottom:1px solid #344660;white-space:nowrap;text-align:right}th:first-child,td:first-child{text-align:left}thead th,.total{background:#1c2e47}.sessions{min-width:1110px}#overview{min-width:1250px}#overview td:first-child{overflow-wrap:anywhere;white-space:normal;max-width:340px}tbody tr:nth-child(even){background:#142137}.positive{color:#64dfb7}.negative{color:#ff9ca1}.total{font-weight:bold}details{margin:18px 0}summary{cursor:pointer;color:#b8d3fa}section[hidden]{display:none}.settings td{white-space:normal;overflow-wrap:anywhere}@media(max-width:600px){main{padding:16px 12px}h1{font-size:22px}}'
    script = '''/**
 * 完成した同一政策又は商品別固定組の全セッション表を表示する。
 * @param {string} key - 固定済み政策 ID。
 * @returns {undefined} 表示だけを変更し、金融計算や通信を行わない。
 */
function showCase(key){for(const s of document.querySelectorAll('[data-case]'))s.hidden=s.dataset.case!==key;document.getElementById('case').value=key;}
document.getElementById('case').addEventListener('change',e=>showCase(e.target.value));showCase(document.getElementById('case').value);'''
    selected_section = f'<section data-case="{PAIR_ID}"><h2>商品別固定設定の全33場</h2>'
    selected_section += session_table(pair['rows'], pair['metrics'], data['sessions'])+supplements(pair)+'</section>'
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{TITLE}</title><style>{css}</style></head><body><!--\n[コンポーネント概要]\n#case は固定組と18新政策・6旧保存対照を選択します。\n[data-case] は全33場と合計を表示します。\n.settings は一度固定する銘柄別設定です。\n.scroll は狭い画面の横スクロール領域です。\n--><main><h1>{TITLE}</h1>'
        f'<p><b>{claim}</b> '+ '。'.join(clauses)+'。</p>'
        +f'<p class="note">{robustness_note} {activity_note}</p>'
        +'<p class="note">全33場の主三基準は金額利益割合65%以上・赤字場20%以下・最大赤字≦平均黒字場。選択では上位3利益場除外後も確認し、資格内で活動→デイ活動→同範囲の保存逆行を優先します。最低活動率の数値は加えず、場ごとに設定を選び直しません。</p>'
        +'<div class="scroll"><table class="settings"><thead><tr><th>商品</th><th>同方向釣合い／最低票数</th><th>新規</th><th>純利確</th><th>固定した政策</th></tr></thead><tbody>'
        +''.join(parameters_rows)+'</tbody></table></div>'
        +'<p><b>入口：</b>日経とTOPIXの主方向が一致し、30秒変化もその方向を支持するとき、安値から0.25ATR反発して買い・高値から0.25ATR反落して売る元E01候補を使います。さらに対象市場の直近60価格代理秒の分類票数・同方向釣合いを上表で確認。<br><b>数量・新規：</b>公開時の1ATR＋気配差＋注文別往復料が5,000円／2,000円以内となる最大整数枚数（最大5枚／10枚）を選択。上表の一回価格制限に合わなければその注文を追わず、次候補を待ちます。成行を選んだ場合は価格制限なし。<br><b>途中：</b>元E01を維持し、1.5ATR順行後に直近2分・30秒がともに逆向きなら一度だけ約半分を返済。2ATR順行でも所定の一部を返済します。<br><b>出口：</b>元E01の初期0.75ATR損切り、順行後の追跡返済・静観・場内期限を維持。これより先に費用後の場口座清算が上表の純利益目標又は損失枠へ届けば、残玉を返済してその場を終了します。</p>'
        +'<p class="note"><a href="../00044_新候補2手法と基準の説明と損益/新候補2手法の説明と損益.html">元E01の候補・半減・損切り・追跡返済の詳細</a>。釣合い＝新規方向×（買い票−売り票）÷全分類票。票は出来高更新と直前気配による方向代理です。</p>'
        +f'<p class="note">新18政策の同条件両商品：主三基準合格{data["new_common_main_pass"]}/18、頑健性選択資格{data["new_common_qualified"]}/18。旧6保存対照：主三基準合格{data["reused_common_main_pass"]}/6、選択資格{data["reused_common_qualified"]}/6。旧対照は新たな検証数に含めません。無取引は黒字に含めません。</p>'
        +'<label for="case">全セッションの表示</label><select id="case">'+''.join(options)+'</select>'
        +selected_section+''.join(sections)
        +'<details><summary>18新政策と6旧保存対照の全比較</summary>'+overview(data, list(data['cases']))+'</details>'
        +'<p class="note">利益・損失は手数料後の完結親net。勝負枚数は実決済玉のnet正負です。無敗の平均損失・平均勝敗比は未定義。損失枠TOPIX5,000円／日経2,000円は次気配約定で超過し得ます。</p>'
        +'<p class="note">過去の原因を見て条件を作り、同じ既知33場で選択した探索です。未見検証や将来勝率ではありません。ラージ気配を価格代理にし、ミニ／マイクロの料金を注文別floorで課します。価格時計は物理受信時計の代理です。一回FAKは次正常気配の全量成立／失効模型で、実板の待ち順位・部分約定・到着遅延は不明です。</p>'
        +f'</main><script>{script}</script></body></html>')


def artificial() -> dict:
    """
    機能: 未定義・大勝ち除外・選択の純人工だけを確認する。
    引数: なし。
    返り値: dict は人工結果。正式結果や仮の金融成績を公開しない。
    """
    def row(session: str, gain: float, loss: float) -> dict:
        """
        機能: 純算術確認用の少数行を作る。
        引数: session(str)、gain/loss(float) は人工ラベルと額。
        返り値: dict は実データから独立した人工会計。
        """
        return dict(session=session, symbol='TOPIX', profit=gain, loss=loss, net=gain-loss,
            campaigns=int(gain+loss > 0), winning_campaigns=int(gain > 0), losing_campaigns=int(loss > 0),
            winning_lots=int(gain > 0), losing_lots=int(loss > 0), fees=0.)
    unknown = summary([row('x', 0., 0.)]); assert not unknown['pass_all'] and unknown['profit_share'] is None
    values = [row(str(i), 100., 0.) for i in range(4)]+[row('4', 0., 500.)]
    losing = summary(values); assert not losing['tests']['coverage'] and not losing['tests']['share65']
    cases = {}
    for ident, active, day in (('A', 4, 1), ('B', 8, 1), ('C', 8, 2)):
        cases[ident] = dict(metrics={'TOPIX': dict(qualified=True,
            full=dict(pass_all=True, tests=dict(share65=True, red20=True, coverage=True), active=active, campaigns=active),
            top3=dict(tests=dict(share65=True, coverage=True)), day=dict(active=day))}, risk={'TOPIX': None})
    chosen, proof = select(cases, 'TOPIX'); assert chosen == 'C' and not proof['途中逆行で判別']
    cases['C']['metrics']['TOPIX']['qualified'] = False
    chosen, proof = select(cases, 'TOPIX'); assert chosen == 'B'
    cases['A']['metrics']['TOPIX']['full'].update(active=8, campaigns=8)
    cases['A']['risk']['TOPIX'] = dict(complete=True, observed_parents=8, maximum_fee_liquidation_MAE_yen=300.)
    chosen, proof = select(cases, 'TOPIX'); assert chosen == 'A' and not proof['途中逆行で判別']
    cases['B']['risk']['TOPIX'] = dict(complete=True, observed_parents=8, maximum_fee_liquidation_MAE_yen=100.)
    chosen, proof = select(cases, 'TOPIX'); assert chosen == 'B' and proof['途中逆行で判別']
    sessions = [f'{i}_Day' for i in range(17)]+[f'{i}_Night' for i in range(16)]
    rows = [row(session, 1000. if i < 3 else 100. if i == 3 else 0., 200. if i == 4 else 0.)
        for i, session in enumerate(sessions)]
    discrepancy = metrics(rows, sessions)
    assert discrepancy['full']['pass_all'] and not discrepancy['qualified']
    assert not discrepancy['top3']['tests']['share65'] and not discrepancy['top3']['tests']['coverage']
    assert number(-0.) == number(0.) == '0' and 'data-value="0.0"' in cell(0., True)
    assert number(None) == '未定義' and cell(None, True).endswith('未定義</td>')
    return dict(全合格=True, 純人工確認=9, 全場合格と除外後不合格を分離=True,
        円負零を表示正規化=True, 正式結果読取=0, 仮金融公開=0)


def main() -> None:
    """
    機能: 準備・小会計検算・根による公開を別の CLI 操作に分離する。
    引数: CLI --prepare-only/--artificial/--check-only/--root-publish、結果/固定/計画(Path)。
    返り値: None。prepared では結果を読まず、公開は根の明示実行だけに限定する。
    """
    parser = argparse.ArgumentParser(); mode = parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare-only', 'artificial', 'check-only', 'root-publish'):
        mode.add_argument('--'+name, action='store_true')
    parser.add_argument('--result', type=Path, default=ENGINE/'finance/結果.json')
    parser.add_argument('--fixed', type=Path, default=ENGINE/'金融事前固定.json')
    parser.add_argument('--plan', type=Path, default=ENGINE/'試行計画.json')
    args = parser.parse_args()
    if args.prepare_only:
        print(json.dumps(dict(prepared=True, source_SHA256=digest(Path(__file__)),
            new_cases=18, reused_cases=6, 金融=0, 結果読取=0, API=0, input=0, ledger=0, 公開=0), ensure_ascii=False)); return
    if args.artificial:
        print(json.dumps(artificial(), ensure_ascii=False)); return
    source = digest(Path(__file__)); refs = {k: getattr(args, k) for k in ('result', 'fixed', 'plan')}
    values = {k: read_small(p) for k, p in refs.items()}; evidence, evidence_sha = read_small(EVIDENCE)
    assert evidence_sha == EVIDENCE_SHA
    sources = {k: v[1] for k, v in values.items()}; sources.update(evidence=evidence_sha, display_source=source)
    data = build(*(values[k][0] for k in ('result', 'fixed', 'plan')), sources, evidence)
    assert digest(Path(__file__)) == source
    if args.root_publish:
        assert not (ENGINE/'finance/False.json').exists()
        PUBLIC.mkdir(parents=True, exist_ok=True)
        (PUBLIC/ACCOUNTING_TITLE).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        (PUBLIC/(TITLE+'.html')).write_text(render(data), encoding='utf-8')
    print(json.dumps(dict(全合格=True, selected=data['pair']['selected'], 主三基準合格商品=data['main_achieved_symbols'],
        頑健性選択資格商品=data['selection_qualified_symbols'],
        new_cases=data['new_count'], reused_cases=data['reused_count'], source_SHA256=source,
        公開=int(args.root_publish), 金融=0, API=0, input=0, ledger=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
