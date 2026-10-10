"""完備後だけ、全返済価格・元組から採否の全経済ラベルを独立再計算する。"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIMARY = 'G150_F50_N1__V000'
PREVIOUS_PRIMARY = 'G150_F25_N1__V000'
SAME_FRACTION = 'G000_F50_N1__V000'
KNOWN_IDS = {prefix+'__'+variant for prefix in ('A0','G000_F25_N1','G150_F25_N1')
    for variant in ('E080','V000','E120')} | {PRIMARY,SAME_FRACTION}
CONTROL = 'G000_F25_N1__V000'
BASELINE = 'A0__V000'
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('all_symbols', 'symbols')
EPS = 1e-6
REFERENCES = {}


def digest(path: Path) -> str:
    """機能: 内容を変更せず逐次読取でSHA256を計算する。

    引数: path(Path)。返り値: 内容指紋(str)。巨大な原本も一括展開しない。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> object:
    """機能: 読んだ保存資料を指紋へ結び、通常又は圧縮JSONを解釈する。

    引数: path(Path)。返り値: 保存値(object)。新しい売買は計算しない。
    """
    raw = path.read_bytes()
    relative = path.relative_to(ROOT).as_posix()
    actual = hashlib.sha256(raw).hexdigest()
    assert relative not in REFERENCES or REFERENCES[relative] == actual
    REFERENCES[relative] = actual
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def equal(actual: object, expected: object, label: str = '') -> None:
    """機能: 辞書・配列を含む有限な数値と判定の完全な項目一致を確認する。

    引数: actual/expected(object)、label(str)。返り値: なし(None)。
    """
    if isinstance(actual, dict):
        assert isinstance(expected, dict) and set(actual) == set(expected), (label, '項目差')
        for key in actual:
            equal(actual[key], expected[key], label+'/'+str(key))
    elif isinstance(actual, list):
        assert isinstance(expected, list) and len(actual) == len(expected), (label, '長さ差')
        for i,(left,right) in enumerate(zip(actual,expected)):
            equal(left,right,label+'/'+str(i))
    elif type(actual) in (float,int):
        assert type(expected) in (float,int) and math.isfinite(actual) and math.isfinite(expected)
        assert abs(actual-expected) <= EPS, (label,actual,expected)
    else:
        assert type(actual) is type(expected) and actual == expected, (label,actual,expected)


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    """機能: 分母不足を無限大にせず比率を計算する。

    引数: numerator/denominator(float|None)。返り値: 比率又は未定義(float|None)。
    """
    return numerator/denominator if numerator is not None and denominator is not None and denominator > 0 else None


def initial(cycles: list, orders: list, quantity: float) -> dict:
    """機能: 初回注文を復元から分離し、元組の初期尺度を検算する。

    引数: cycles/ orders(list)、quantity(float)。返り値: 組番号別初回署名(dict)。
    """
    starts = {int(o[2]):o for o in orders if o[6] == 20 and o[7] == 1}
    assert len(starts) == sum(o[6] == 20 and o[7] == 1 for o in orders) == len(cycles)
    result = {}
    for cycle in cycles:
        campaign = int(cycle[0])
        assert campaign >= 0 and campaign == cycle[0] and campaign not in result
        order = starts[campaign]
        assert order[0] == cycle[1] and order[3] == cycle[8] and order[4] == quantity
        assert 0 <= order[1] < order[0] and int(order[1]) == order[1]
        assert cycle[5] > 0 and cycle[1] <= cycle[2] and cycle[8] in (-1,1)
        equal(cycle[4],quantity*cycle[5],'q0×初回ATR')
        result[campaign] = (order[0],order[1],order[3],order[4],order[5],cycle[5],cycle[4])
    return result


def account(book: dict, row: dict) -> dict:
    """機能: 全返済の元価格・数量から円損益・枚数・元組Rを再構成する。

    引数: book/row(dict)。返り値: 一口座の別式集計(dict)。保存された脚損益を計算源にしない。
    """
    factor = 1000. if book['symbol'] == 'TOPIX' else 10.
    quantity = 5. if book['symbol'] == 'TOPIX' else 10.
    equal(book['config']['point_value'],factor,'小口倍率')
    equal(book['config']['initial_qty'],quantity,'初回枚数')
    profits = []
    campaign_points = {}
    for trade in book['trades']:
        assert len(trade) == 11 and all(type(x) in (int,float) and math.isfinite(x) for x in trade)
        assert trade[2] in (-1,1) and trade[3] > 0 and trade[3] == int(trade[3])
        amount = (trade[5]-trade[4])*trade[2]*trade[3]
        equal(amount,trade[10],'返済脚の保存損益')
        campaign = int(trade[0])
        assert campaign >= 0 and campaign == trade[0]
        campaign_points[campaign] = campaign_points.get(campaign,0.)+amount
        profits.append(amount*factor)
    cycles = book['cycles']
    own = initial(cycles,book['orders'],quantity)
    shadow = initial(book['shadow_cycles'],book['shadow_orders'],quantity)
    assert own == shadow and set(own) == set(campaign_points)
    shadow_map = {int(c[0]):c for c in book['shadow_cycles']}
    group_map = {}
    for cycle in cycles:
        campaign = int(cycle[0])
        points = campaign_points[campaign]
        equal(points,cycle[3],'全脚から元組損益')
        assert cycle[2] <= shadow_map[campaign][2]
        group_map[campaign] = dict(points=points,pnl=points*factor,risk=quantity*cycle[5],
            risk_yen=quantity*cycle[5]*factor,r=points/(quantity*cycle[5]),signature=own[campaign],side=int(cycle[8]))
    gains = sum(p for p in profits if p > 0)
    losses = -sum(p for p in profits if p < 0)
    group_pnl = [g['pnl'] for g in group_map.values()]
    group_gains = [p for p in group_pnl if p > 0]
    group_losses = [-p for p in group_pnl if p < 0]
    reductions = len({(int(t[0]),int(t[7])) for t in book['trades'] if t[9] == 30})
    restorations = len({(int(o[2]),int(o[0])) for o in book['orders'] if o[6] == 31 and o[7] == 1})
    values = dict(gross_profit_yen=gains,gross_loss_yen=losses,net_yen=sum(profits),
        profit_units=sum(t[3] for t,p in zip(book['trades'],profits) if p>0),
        loss_units=sum(t[3] for t,p in zip(book['trades'],profits) if p<0),
        zero_units=sum(t[3] for t,p in zip(book['trades'],profits) if p==0),
        cycles=len(cycles),cycle_wins=len(group_gains),cycle_losses=len(group_losses),
        cycle_profit_yen=sum(group_gains),cycle_loss_yen=sum(group_losses),reductions=reductions,restorations=restorations,
        net_r=sum(g['r'] for g in group_map.values()),maximum_trade_profit=max([0.]+group_gains))
    for field,value in values.items():
        equal(value,row[field],field)
    equal(sorted(group_gains,reverse=True)[:2],row['two_largest_cycle_profits'],'二勝ち')
    equal(sum(group_pnl),values['net_yen'],'全組と全脚')
    return dict(**values,groups=group_map,group_profits=group_pnl,
        longs=sum(c[8] == 1 for c in cycles),shorts=sum(c[8] == -1 for c in cycles))


def cell(part: list[dict], saved_period: dict) -> dict:
    """機能: 元組・脚・枚数の三つの尺度と集中・活動を独立に集計する。

    引数: part(list[dict])、saved_period(dict)。返り値: 採否の一期間一銘柄と同項目の値(dict)。
    時価DDだけは完備した独立会計値を使用し、ここでは時価曲線を再生しない。
    """
    sums = {field:sum(r[field] for r in part) for field in ('gross_profit_yen','gross_loss_yen','net_yen',
        'profit_units','loss_units','zero_units','cycles','cycle_wins','cycle_losses','cycle_profit_yen',
        'cycle_loss_yen','reductions','restorations','net_r')}
    for field,value in sums.items():
        equal(value,saved_period[field],field)
    pnl = [p for r in part for p in r['group_profits']]
    wins, losses = [v for v in pnl if v>0],[-v for v in pnl if v<0]
    net = sum(pnl)
    win_mean,loss_mean = ratio(sum(wins),len(wins)),ratio(sum(losses),len(losses))
    unit_win,unit_loss = ratio(sums['gross_profit_yen'],sums['profit_units']),ratio(sums['gross_loss_yen'],sums['loss_units'])
    ratios = dict(元組PF=ratio(sum(wins),sum(losses)),平均元組勝敗比=ratio(win_mean,loss_mean),
        平均勝ち元組円=win_mean,平均負け元組円=loss_mean,返済脚金額比=ratio(sums['gross_profit_yen'],sums['gross_loss_yen']),
        一枚平均利益円=unit_win,一枚平均損失円=unit_loss,一枚平均勝敗比=ratio(unit_win,unit_loss))
    equal(ratios['平均元組勝敗比'],saved_period['average_cycle_payoff'],'平均元組比')
    maximum = max([0.]+wins)
    best_session = max([0.]+[r['net_yen'] for r in part])
    excluded = dict(最大勝ち元組除外非負=net-maximum>=-EPS,最大黒字場除外非負=net-best_session>=-EPS)
    checks = dict(収支正=net>0,元組PF1超=ratios['元組PF'] is not None and ratios['元組PF']>1,
        平均元組勝敗比1超=ratios['平均元組勝敗比'] is not None and ratios['平均元組勝敗比']>1)
    base = all(checks.values()) and all(excluded.values())
    longs,shorts = sum(r['longs'] for r in part),sum(r['shorts'] for r in part)
    active = len(pnl)>0 and longs>0 and shorts>0
    two = sorted(wins,reverse=True)[:2]
    return dict(合格=base,基礎検査=checks,最大勝ち除外検査=excluded,最大勝ち除外を採否へ使用=True,
        比率=ratios,最大勝ち元組円=maximum,最大黒字場円=best_session,
        最大勝ち元組除外収支円=net-maximum,最大黒字場除外収支円=net-best_session,
        稼働セッション数=sum(r['cycles']>0 for r in part),減量約定回数=sums['reductions'],復元約定回数=sums['restorations'],
        買い元組数=longs,売り元組数=shorts,実取引と買売双方=active,活動込み基礎候補=base and active,
        一枚平均勝敗比1超=ratios['一枚平均勝敗比'] is not None and ratios['一枚平均勝敗比']>1,
        上位二勝ち元組同時除外収支円=net-sum(two),上位二勝ち元組円=two,
        収支円=net,時価最大下落円=saved_period['drawdown_yen'],元組数=len(pnl))


def distribution(values: list[float]) -> dict:
    """機能: 全対応差を除外せず合計・中央値・符号別に整理する。

    引数: values(list[float])。返り値: 対応差の独立要約(dict)。
    """
    total = sum(values)
    return dict(件数=len(values),合計=total,平均=total/len(values) if values else None,
        中央値=median(values) if values else None,改善数=sum(x>EPS for x in values),
        悪化数=sum(x < -EPS for x in values),同値数=sum(abs(x)<=EPS for x in values),
        最大正差除外=total-max([0.]+values))


def pair(other: str, specs: dict, books: dict, accounts: dict, names: list[str], keep: bool) -> dict:
    """機能: 同じ影と初回の全組を、価格再計算した損益で一対一比較する。

    引数: other(str)、specs/books/accounts(dict)、names(list[str])、keep(bool)。返り値: 全組対応差(dict)。
    """
    fields = ('signal_id','entry_scale','min_delay_seconds','observed_fill')
    assert all(specs[PRIMARY][f] == specs[other][f] for f in fields)
    output = []
    for key in sorted(books[PRIMARY]):
        left,right = books[PRIMARY][key],books[other][key]
        assert left['shadow_fingerprints'] == right['shadow_fingerprints']
        assert left['shadow_orders'] == right['shadow_orders'] and left['shadow_cycles'] == right['shadow_cycles']
        a,b = accounts[PRIMARY][key]['groups'],accounts[other][key]['groups']
        assert set(a) == set(b)
        for campaign in sorted(a):
            one,two = a[campaign],b[campaign]
            assert one['signature'] == two['signature']
            signature = one['signature']
            output.append(dict(session=key[0],symbol=key[1],campaign=campaign,
                初回行=int(signature[0]),初回方向=int(signature[2]),初回枚数=signature[3],初回ATR=signature[5],
                共通初回R円=one['risk_yen'],主案収支円=one['pnl'],対照収支円=two['pnl'],
                主案R=one['r'],対照R=two['r'],差円=one['pnl']-two['pnl'],差R=(one['points']-two['points'])/one['risk']))
    periods = {}
    for period in PERIODS:
        chosen = names if period == 'all_symbols' else names[6:]
        periods[period] = {}
        for symbol in SYMBOLS:
            rows = [r for r in output if r['session'] in chosen and r['symbol'] == symbol]
            periods[period][symbol] = dict(全元組数=len(rows),差円=distribution([r['差円'] for r in rows]),
                                           差R=distribution([r['差R'] for r in rows]))
    value = dict(主案ID=PRIMARY,対照ID=other,共通影と初回全一致=True,全対応元組数=len(output),期間別=periods)
    if keep:
        value['全元組対応'] = output
    return value


def relationship(cells: dict, other: str) -> dict:
    """機能: 中央の円収支・時価DDの交換を独立の比較式で分類する。

    引数: cells(dict)、other(str)。返り値: 4セル差と関係(dict)。
    """
    rows = []
    for period in PERIODS:
        for symbol in SYMBOLS:
            a,b = cells[PRIMARY][period][symbol],cells[other][period][symbol]
            rows.append(dict(期間=period,銘柄=symbol,収支差円=a['収支円']-b['収支円'],
                最大下落差円=a['時価最大下落円']-b['時価最大下落円']))
    positive = all(r['収支差円']>=-EPS and r['最大下落差円']<=EPS for r in rows)
    negative = all(r['収支差円']<=EPS and r['最大下落差円']>=-EPS for r in rows)
    changed = any(abs(r[f])>EPS for r in rows for f in ('収支差円','最大下落差円'))
    return dict(関係='同値' if not changed else '同時改善' if positive else '対照優位' if negative else '交換又は混在',
        同時改善=positive and changed,対照が厳密支配=negative and changed,完全同値=not changed,差=rows)


def provenance(spec: dict, record: dict, source: dict | None) -> bool:
    """機能: 既知引継ぎと新反証の区分を保存実体の契約から検査する。

    引数: spec/record(dict)、source(dict|None)。返り値: 既知引継ぎならTrue(bool)。
    主案中央の既知成績を新たな独立証拠へ数えることを防ぐ。
    """
    identifier = spec['id']
    known = identifier in KNOWN_IDS
    assert record['id'] == identifier and record['全合格'] is True
    assert record['既知成果引継ぎ'] is known and record['新売買再生'] is (not known)
    assert (record['全入力数'],record['因果入力数']) == (26,4)
    if known:
        assert isinstance(source,dict) and set(source) == {'spec','completed','出力SHA256','旧探索固定SHA256'}
        assert record['reuse_source'] == source
        assert set(spec) == set(source['spec'])
        fields = set(spec) - {'primary','role'}
        assert {f:spec[f] for f in fields} == {f:source['spec'][f] for f in fields},'既知経済仕様'
        assert len(source['出力SHA256']) == 8
    else:
        assert source is None and 'reuse_source' in record and record['reuse_source'] is None
    return known


def inherited_summary(current: dict, previous: dict, spec: dict, source: dict, fixed_sha: str) -> None:
    """機能: 引継ぎ要約で経済項目を一つも改変していないことを検査する。

    引数: current/previous/spec/source(dict)、fixed_sha(str)。返り値: なし(None)。
    探索の指紋と表示用仕様以外は完全な項目一致を要求する。
    """
    assert current['id'] == previous['id'] == spec['id']
    assert current['spec'] == spec and previous['spec'] == source['spec']
    assert current['探索固定SHA256'] == fixed_sha
    assert previous['探索固定SHA256'] == source['旧探索固定SHA256']
    fields = set(previous) - {'spec','探索固定SHA256'}
    assert set(current) == set(previous)
    assert {f:current[f] for f in fields} == {f:previous[f] for f in fields},'既知要約の経済情報'


def repaired_record(previous: dict, current: dict, identifier: str) -> None:
    """機能: 新規完了記録が由来None一欄だけ補われたことを独立確認する。

    引数: previous/current(dict)、identifier(str)。返り値: なし(None)。
    経済数値・出力指紋・時刻・IDなどの同時変更は許さない。
    """
    assert previous['id'] == current['id'] == identifier and identifier not in KNOWN_IDS
    assert previous['全合格'] is True and previous['既知成果引継ぎ'] is False
    assert previous['新売買再生'] is True and len(previous['出力SHA256']) == 7
    assert (previous['全入力数'],previous['因果入力数']) == (26,4)
    assert 'reuse_source' not in previous and current['reuse_source'] is None
    assert set(current) == set(previous) | {'reuse_source'}
    assert {k:v for k,v in current.items() if k!='reuse_source'} == previous


def repaired_header(previous: dict, current: dict, identifiers: set[str]) -> None:
    """機能: 一覧で新規の由来一欄以外に変化がないことを独立確認する。

    引数: previous/current(dict)、identifiers(set[str])。返り値: なし(None)。
    既知記録・集計・記録順の変更を拒否する。
    """
    assert set(previous) == set(current)
    assert {k:v for k,v in previous.items() if k!='records'} == {k:v for k,v in current.items() if k!='records'}
    assert len(previous['records']) == len(current['records']) == len(identifiers)
    assert {r['id'] for r in previous['records']} == {r['id'] for r in current['records']} == identifiers
    for old,new in zip(previous['records'],current['records']):
        assert old['id'] == new['id']
        if old['id'] in KNOWN_IDS:
            assert old == new
        else:
            repaired_record(old,new,old['id'])


def verify_metadata_repair(fixed: dict, bound: dict) -> dict:
    """機能: 144元資料と全1071成果から、由来一欄の補完だけを検算する。

    引数: fixed(dict)は探索固定、bound(dict)は完備指紋。返り値: 独立修復照合(dict)。
    元実装の補完関数は呼ばず、保全先のバイトと変更前後の全項目を比較する。
    """
    proof = read(HERE/'metadata_repair.json')
    assert proof['全合格'] is True and (proof['新規条件数'],proof['修復資料数']) == (142,144)
    for flag in ('元資料全バイト保全','変更はreuse_sourceのnull補完のみ','全七成果不変','既知11完了記録不変'):
        assert proof[flag] is True
    assert proof['売買再生数'] == 0 and proof['新損益値の読取'] is False
    fixed_sha = digest(HERE/'探索条件の固定.json')
    assert proof['探索固定SHA256'] == fixed_sha
    implementation = HERE/'metadata_repair.py'
    assert proof['実装SHA256'] == digest(implementation)
    REFERENCES[implementation.relative_to(ROOT).as_posix()] = proof['実装SHA256']
    artificial = proof['人工検査']
    assert artificial['全合格'] is True and (artificial['正常件数'],artificial['不整合拒否件数']) == (1,8)
    specs = fixed['conditions']+fixed['supplementary']
    assert len(specs) == len({s['id'] for s in specs}) == 153
    sources,known,expected = {},{},{}
    artifacts = (('sessions','.json.gz'),('ledgers','.json.gz'),('audits','.json.gz'),
                 ('waves','.json.gz'),('causality','.json'),('gate_use','.json'),('summaries','.json'))
    for spec in specs:
        directory = HERE/'supplementary' if spec['role']=='supplementary' else HERE
        path = directory/'completed'/(spec['id']+'.json')
        relative = path.relative_to(ROOT).as_posix()
        assert relative in bound
        record = read(path)
        assert record['探索固定SHA256'] == fixed_sha
        paths = {(directory/folder/(spec['id']+suffix)).relative_to(ROOT).as_posix() for folder,suffix in artifacts}
        assert set(record['出力SHA256']) == paths and not (set(sources)&paths)
        sources.update(record['出力SHA256'])
        if spec['id'] in KNOWN_IDS:
            known[relative] = digest(path)
        else:
            expected[relative] = spec['id']
    for directory in (HERE,HERE/'supplementary'):
        expected[(directory/'主再生の完了.json').relative_to(ROOT).as_posix()] = None
    assert len(sources) == 1071 and len(known) == 11 and len(expected) == 144
    assert proof['全経済成果SHA256'] == sources and proof['既知11SHA256'] == known
    for relative,sha in {**sources,**known}.items():
        assert bound[relative] == sha and digest(ROOT/relative) == sha
    changes = proof['変更前後']
    assert len(changes) == len({r['対象'] for r in changes}) == 144
    assert {r['対象'] for r in changes} == set(expected)
    before,after,archives = {},{},{}
    for change in changes:
        relative = change['対象']
        path = ROOT/relative
        archive = HERE/'補完前の完了記録'/path.relative_to(HERE)
        archived = archive.relative_to(ROOT).as_posix()
        assert change['保全先'] == archived
        assert digest(path) == change['補完後SHA256'] == bound[relative]
        assert digest(archive) == change['補完前SHA256']
        before[relative] = change['補完前SHA256']; after[relative] = change['補完後SHA256']
        archives[archived] = change['補完前SHA256']
        old,current = read(archive),read(path)
        identifier = expected[relative]
        if identifier is None:
            ids = {s['id'] for s in specs if (s['role']=='supplementary') == (path.parent != HERE)}
            repaired_header(old,current,ids)
        else:
            repaired_record(old,current,identifier)
    assert proof['原資料SHA256'] == before and proof['入力資料SHA256'] == archives and proof['出力資料SHA256'] == after
    return dict(全合格=True,新規完了記録数=142,一覧数=2,保全元資料数=144,
        全経済成果数=1071,既知完了記録不変数=11,一欄補完以外全値同一=True,
        証跡SHA256=digest(HERE/'metadata_repair.json'))


def main() -> None:
    """機能: 完備資料を先に要求し、全153台帳の採否と差を独立検算する。

    引数: なし。返り値: なし(None)。途中損益・採否関数・注文器を使わない。
    """
    guard = read(HERE/'完備監査.json')
    assert guard['全合格'] is True and guard['全原本場内返済'] is True
    assert (guard['全条件数'],guard['主条件数'],guard['補助条件数'],guard['全入力数'],
            guard['因果入力数'],guard['旧単一窓一致入力数'],guard['全指定波数']) == (153,25,128,3978,612,156,1224)
    assert (guard['既知引継条件数'],guard['新規再生条件数'],guard['既知引継入力数'],guard['新規再生入力数'],
            guard['既知引継因果入力数'],guard['新規因果入力数'],guard['既知引継波数'],guard['新規波数']) == (11,142,286,3692,44,568,88,1136)
    assert guard['旧成果六資料全バイト一致'] is True and guard['旧集計経済情報全一致'] is True
    bound = {}
    for group in ('参照資料SHA256','出力SHA256'):
        for relative,sha in guard[group].items():
            assert relative not in bound or bound[relative] == sha
            assert digest(ROOT/relative) == sha,relative
            bound[relative] = sha
    fixed = read(HERE/'探索条件の固定.json')
    assert guard['探索固定SHA256'] == REFERENCES[(HERE/'探索条件の固定.json').relative_to(ROOT).as_posix()]
    decision = read(HERE/'assess_results.json')
    specs = {s['id']:s for s in fixed['conditions']+fixed['supplementary']}
    assert len(fixed['conditions']) == 25 and len(fixed['supplementary']) == 128 and len(specs) == 153
    assert set(decision['全条件']) == set(specs)
    assert set(fixed['既知再利用']) == KNOWN_IDS
    selftest = read(HERE/'post_audit_selftest.json')
    assert selftest['全合格'] is True and selftest['新実相場損益読取'] is False
    assert selftest['実装SHA256'] == digest(Path(__file__))
    assert selftest['検査実装SHA256'] == digest(HERE/'post_audit_selftest.py')
    REFERENCES[Path(__file__).relative_to(ROOT).as_posix()] = selftest['実装SHA256']
    REFERENCES[(HERE/'post_audit_selftest.py').relative_to(ROOT).as_posix()] = selftest['検査実装SHA256']
    repair_check = verify_metadata_repair(fixed,bound)
    names = fixed['全セッション']
    assert len(names) == len(set(names)) == 13 and names == sorted(names)
    assert names[6:] == fixed['後半7セッション']
    expected_keys = {(n,s) for n in names for s in SYMBOLS}
    books,accounts,summaries,cells,checks = {},{},{},{},{}
    row_count = leg_count = group_count = known_count = 0
    origins = []
    for identifier,spec in specs.items():
        directory = HERE/'supplementary' if spec['role'] == 'supplementary' else HERE
        done_path = directory/'completed'/(identifier+'.json')
        assert done_path.relative_to(ROOT).as_posix() in bound
        record = read(done_path)
        inherited = provenance(spec,record,fixed['既知再利用'].get(identifier))
        known_count += int(inherited)
        origins.append(dict(id=identifier,既知引継ぎ=inherited,新反証=not inherited,入力数=26))
        for folder,suffix in (('ledgers','.json.gz'),('sessions','.json.gz'),('summaries','.json'),('waves','.json.gz')):
            path = directory/folder/(identifier+suffix)
            assert path.relative_to(ROOT).as_posix() in bound
        records = read(directory/'ledgers'/(identifier+'.json.gz'))
        rows = read(directory/'sessions'/(identifier+'.json.gz'))
        summary = read(directory/'summaries'/(identifier+'.json'))
        waves = read(directory/'waves'/(identifier+'.json.gz'))
        assert summary['spec'] == spec and summary['id'] == identifier
        if inherited:
            source = fixed['既知再利用'][identifier]
            for relative,sha in source['出力SHA256'].items():
                assert bound[relative] == sha and digest(ROOT/relative) == sha
            for folder,suffix in (('sessions','.json.gz'),('ledgers','.json.gz'),('audits','.json.gz'),
                                  ('waves','.json.gz'),('causality','.json'),('gate_use','.json')):
                current_path = directory/folder/(identifier+suffix)
                previous_path = HERE.parent/'wave_v44'/folder/(identifier+suffix)
                assert digest(current_path) == digest(previous_path)
            previous = read(HERE.parent/'wave_v44/summaries'/(identifier+'.json'))
            inherited_summary(summary,previous,spec,source,guard['探索固定SHA256'])
        summary_map = {(r['session'],r['symbol']):r for r in rows}
        book_map = {(r['session'],r['symbol']):r for r in records}
        assert len(records) == len(rows) == len(summary_map) == len(book_map) == 26
        assert set(summary_map) == set(book_map) == expected_keys
        accounts[identifier] = {key:account(record,summary_map[key]) for key,record in book_map.items()}
        summaries[identifier],books[identifier] = summary,book_map
        details = {}
        for period in PERIODS:
            used = names if period == 'all_symbols' else names[6:]
            details[period] = {}
            for symbol in SYMBOLS:
                details[period][symbol] = cell([accounts[identifier][(n,symbol)] for n in used],summary[period][symbol])
        collection = [c for part in details.values() for c in part.values()]
        assert len(waves) == len({(w['wave'],w['session'],w['symbol']) for w in waves}) == 8
        passed = sum(w['正方向ネット保有分'] >= 20-1e-9 for w in waves)
        assert passed == summary['wave_passes']
        one = dict(基礎候補=all(c['活動込み基礎候補'] for c in collection),
            元組基礎と大勝ち除外=all(c['合格'] for c in collection),
            実取引と買売双方=all(c['実取引と買売双方'] for c in collection),
            全セル一枚平均勝敗比1超=all(c['一枚平均勝敗比1超'] for c in collection),
            指定八波=passed == 8,波通過数=passed,期間別=details)
        equal(one,decision['全条件'][identifier],identifier)
        cells[identifier],checks[identifier] = details,one
        row_count += len(records)
        leg_count += sum(len(b['trades']) for b in records)
        group_count += sum(len(b['cycles']) for b in records)

    # ----------------------------------------
    # 主案を固定したまま、採否の各層を保存価格由来の集計から再判定する。
    pairs = {}
    for identifier in (CONTROL,BASELINE,PREVIOUS_PRIMARY,SAME_FRACTION,'G150_F50_N1__INV','G150_F50_N1__AV_ALL'):
        pairs[identifier] = pair(identifier,specs,books,accounts,names,True)
    equal(pairs,decision['同じ影の元組差'],'同じ影全組差')
    central = {}
    for identifier in (CONTROL,BASELINE,PREVIOUS_PRIMARY,SAME_FRACTION):
        relation = relationship(cells,identifier)
        later = all(r['収支差円']>EPS for r in relation['差'] if r['期間']=='symbols')
        full = all(r['収支差円']>=-EPS for r in relation['差'] if r['期間']=='all_symbols')
        central[identifier] = dict(後七両銘柄増益=later,全十三両銘柄非減益=full,
            中央収益追加改善=later and full,収益DD関係=relation)
    equal(central,decision['中央比較'],'中央改善')
    categories = {'順行閾値':('A120','A180'),'入口時計':('E080','E120'),
                  '悪化窓':('D080','D120'),'回復窓':('G080','G120'),'執行':('L001','L005','L015','O000')}
    sensitivities = {}
    for category,variants in categories.items():
        selected = {}
        for variant in variants:
            identifier = 'G150_F50_N1__'+variant
            later = all(all(c['基礎検査'].values()) for c in cells[identifier]['symbols'].values())
            selected[variant] = dict(id=identifier,後七両銘柄の収支PF平均比=later,**checks[identifier])
        sensitivities[category] = dict(全変形の後七基礎=all(v['後七両銘柄の収支PF平均比'] for v in selected.values()),
            全変形の四セル集中活動込み基礎=all(v['基礎候補'] for v in selected.values()),条件別=selected)
    equal(sensitivities,decision['十二感度'],'十二感度')
    clocks = {}
    for name,prefix in (('主案','G150_F50_N1'),('直前25パーセント','G150_F25_N1'),('無ゲートC01','G000_F25_N1'),('A0','A0')):
        group = {v:checks[prefix+'__'+v] for v in ('E080','V000','E120')}
        clocks[name] = dict(三時計の基礎集中活動=all(c['基礎候補'] for c in group.values()),条件別=group)
    equal(clocks,decision['入口時計比較'],'時計')

    randoms = {}
    for field in ('bad_seed','good_seed'):
        selected = sorted([s for s in specs.values() if s.get(field) is not None],key=lambda s:s[field])
        assert len(selected) == 64 and [s[field] for s in selected] == list(range(64))
        confirmations = {s['id']:pair(s['id'],specs,books,accounts,names,False)['全対応元組数'] for s in selected}
        periods = {}
        for period in PERIODS:
            periods[period] = {}
            used = names if period == 'all_symbols' else names[6:]
            for symbol in SYMBOLS:
                rows = []
                for spec in selected:
                    measured = [accounts[spec['id']][(n,symbol)] for n in used]
                    rows.append(dict(id=spec['id'],seed=spec[field],元組R=sum(r['net_r'] for r in measured),
                        収支円=sum(r['net_yen'] for r in measured),最大下落円=cells[spec['id']][period][symbol]['時価最大下落円'],
                        減量回数=sum(r['reductions'] for r in measured),復元回数=sum(r['restorations'] for r in measured)))
                main = cells[PRIMARY][period][symbol]
                main_r = sum(accounts[PRIMARY][(n,symbol)]['net_r'] for n in used)
                mid = median(r['元組R'] for r in rows)
                periods[period][symbol] = dict(主案元組R=main_r,乱数元組R中央値=mid,
                    乱数収支中央値円=median(r['収支円'] for r in rows),乱数下落中央値円=median(r['最大下落円'] for r in rows),
                    元組R中央値差=main_r-mid,主以上元組Rの本数=sum(r['元組R']>=main_r-EPS for r in rows),
                    主以上収支円の本数=sum(r['収支円']>=main['収支円']-EPS for r in rows),
                    主以下下落円の本数=sum(r['最大下落円']<=main['時価最大下落円']+EPS for r in rows),全64=rows)
        later = all(r['元組R中央値差']>EPS for r in periods['symbols'].values())
        full = all(r['元組R中央値差']>=-EPS for r in periods['all_symbols'].values())
        randoms[field] = dict(変更情報=field,後七両市場中央値超過=later,全十三両市場中央値非劣=full,
            構造保存対照の利益超過=later and full,共通影確認組数=confirmations,期間別=periods,
            最良seed採用=False,正式p値=False,ゲート全体の無情報対照=False)
    equal(randoms,decision['乱数対照'],'乱数全128')
    direction = {}
    for variant in ('INV','AV_ALL'):
        identifier = 'G150_F50_N1__'+variant
        data = pairs[identifier]['期間別']
        later = all(c['差R']['合計']>EPS for c in data['symbols'].values())
        full = all(c['差R']['合計']>=-EPS for c in data['all_symbols'].values())
        direction[variant] = dict(id=identifier,後七両市場差R正=later,全十三両市場差R非負=full,
            利益超過=later and full,収益DD関係=relationship(cells,identifier))
    equal(direction,decision['方向除去反転対照'],'INV/AV_ALL')
    active = all(c['減量約定回数']>0 and c['復元約定回数']>0 for p in cells[PRIMARY].values() for c in p.values())
    economic = checks[PRIMARY]['基礎候補'] and central[CONTROL]['中央収益追加改善'] and active
    robust = all(v['全変形の後七基礎'] for v in sensitivities.values())
    bad = active and randoms['bad_seed']['構造保存対照の利益超過'] and all(v['利益超過'] for v in direction.values())
    good = active and randoms['good_seed']['構造保存対照の利益超過']
    flags = dict(監査完了=True,経済目安合格=economic,既知比較の研究候補=economic,
        中央の基礎候補=checks[PRIMARY]['基礎候補'],中央の収益追加改善=central[CONTROL]['中央収益追加改善'],
        全期間両銘柄で減量復元実約定=active,指定八波=checks[PRIMARY]['指定八波'],
        波通過数=checks[PRIMARY]['波通過数'],十二感度の後七基礎=robust,
        入口三時計の集中活動耐性=clocks['主案']['三時計の基礎集中活動'],
        耐性付き研究候補=economic and robust and clocks['主案']['三時計の基礎集中活動'],
        悪化情報の利益付加価値支持=bad,回復情報の構造保存対照超過=good,
        情報対照を通過した研究候補=economic and bad and good,
        主案の事後差替=False,全体目標達成=False,未知での有効性確認=False,
        全十三と後七は既知=True,損失組と未調整組の除外=False,
        主案中央は既知の探索副案=True,既知中央再確認を新たな独立証拠に数える=False)
    for key,value in flags.items():
        equal(value,decision[key],key)
    assert decision['主案ID'] == PRIMARY and decision['元C01ID'] == CONTROL and decision['元A0ID'] == BASELINE
    assert decision['直前25パーセントID'] == PREVIOUS_PRIMARY and decision['同50パーセント無ゲートID'] == SAME_FRACTION
    for key,value in dict(全条件数=153,主条件数=25,補助条件数=128,全入力数=3978,
        既知引継ぎ条件数=11,新反証条件数=142,既知引継ぎ入力数=286,新反証入力数=3692).items():
        equal(value,decision[key],key)
    assert row_count == 3978 and len(cells) == 153
    assert known_count == 11 and len(origins) == 153
    for relative,sha in REFERENCES.items():
        assert relative not in bound or bound[relative] == sha,relative
    for relative,sha in {**bound,**REFERENCES}.items():
        assert digest(ROOT/relative) == sha,relative
    REFERENCES[Path(__file__).relative_to(ROOT).as_posix()] = digest(Path(__file__))
    REFERENCES[(HERE/'post_audit_selftest.py').relative_to(ROOT).as_posix()] = digest(HERE/'post_audit_selftest.py')
    output = dict(全合格=True,全条件数=153,主条件数=25,補助条件数=128,全入力数=row_count,
        既知引継ぎ条件数=11,新反証条件数=142,既知引継ぎ入力数=286,新反証入力数=3692,
        全条件の由来=origins,既知十一の六成果と経済要約一致=True,
        既知中央優位は新しい独立証拠ではない=True,
        由来欄補完の独立検算=repair_check,
        全返済脚数=leg_count,全元組数=group_count,金額枚数元組比率活動除外一致=True,
        同じ影全組差一致=True,全十二感度と時計比較一致=True,全乱数128と反転方向除去一致=True,
        固定採否と数値差一致=True,旧採否関数呼出=False,追加売買再生=False,
        DD='完備した独立時価会計の値を使用。条件間差と採否は別計算し、時価曲線は再生しない。',
        主案の独立判定=flags,中央比較=central,完備元SHA256=digest(HERE/'完備監査.json'),
        完備参照全数=len(bound),参照資料SHA256=REFERENCES,現在API取得数=0,保存ライブ使用=False)
    (HERE/'post_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k not in ('参照資料SHA256','中央比較','主案の独立判定')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
