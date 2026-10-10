"""既知の損小利大・感度・復元分岐の付加価値を分離して判定する。"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from statistics import median

import adaptive_design as design

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('all_symbols', 'symbols')
PRIMARY = design.PRIMARY_ID
VARIANTS = ('E080','E120','D080','D120','G080','G120','C080','C120','T96','T144','L001','L005','L015','O000')
SIGNAL = 'H019__B06_RB01_F50_N1__R1__V000'
CLOCK = 'H019__' + design.CLOCK_POLICY + '__R1__V000'
REVERSE = 'H019__' + design.REVERSE_POLICY + '__R1__V000'
PAIRED_IDS = (PRIMARY, SIGNAL, CLOCK, REVERSE)
SUM_FIELDS = ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units',
    'loss_units', 'zero_units', 'cycles', 'cycle_wins', 'cycle_losses',
    'cycle_profit_yen', 'cycle_loss_yen', 'reductions', 'restorations')
COUNT_FIELDS = ('profit_units', 'loss_units', 'zero_units', 'cycles', 'cycle_wins',
    'cycle_losses', 'reductions', 'restorations')
EPS = 1e-6


def finite(value: object) -> float:
    """機能: 真偽値・欠損・非有限値を数値と混同せず拒否する。

    引数: value (object)。返り値: 有限数値 (float)。
    """
    assert type(value) in (int, float) and math.isfinite(value)
    return float(value)


def ratios(value: dict) -> dict:
    """機能: 元組と返済脚・枚数の比率をそれぞれ独立に導出する。

    引数: value (dict) は期間集計。返り値: 比率と平均額 (dict)。
    """
    for key in SUM_FIELDS:
        finite(value[key])
    for key in COUNT_FIELDS:
        assert value[key] >= 0 and int(value[key]) == value[key]
    for key in ('gross_profit_yen', 'gross_loss_yen', 'cycle_profit_yen', 'cycle_loss_yen'):
        assert value[key] >= 0
    assert value['cycle_wins'] + value['cycle_losses'] <= value['cycles']
    wins, losses = value['cycle_wins'], value['cycle_losses']
    win = value['cycle_profit_yen'] / wins if wins else None
    loss = value['cycle_loss_yen'] / losses if losses else None
    pf = value['cycle_profit_yen'] / value['cycle_loss_yen'] if value['cycle_loss_yen'] > 0 else None
    payoff = win / loss if win is not None and loss is not None and loss > 0 else None
    unit_win = value['gross_profit_yen'] / value['profit_units'] if value['profit_units'] else None
    unit_loss = value['gross_loss_yen'] / value['loss_units'] if value['loss_units'] else None
    return dict(元組PF=pf, 平均元組勝敗比=payoff, 平均勝ち元組円=win, 平均負け元組円=loss,
        返済脚金額比=value['gross_profit_yen'] / value['gross_loss_yen'] if value['gross_loss_yen'] > 0 else None,
        一枚平均利益円=unit_win, 一枚平均損失円=unit_loss,
        一枚平均勝敗比=unit_win / unit_loss if unit_win is not None and unit_loss is not None and unit_loss > 0 else None)


def basic(value: dict, rows: list[dict], names: list[str], concentration: bool) -> dict:
    """機能: 元組基礎と最大勝ち除外を、明細と期間の一致を検算して判定する。

    引数: value (dict)、rows (list[dict])、names (list[str])、concentration (bool)。
    返り値: 検査・比率・除外後収支 (dict)。診断では最大勝ち除外は表示のみ。
    """
    assert len(rows) == len(names) and {r['session'] for r in rows} == set(names)
    assert len({r['session'] for r in rows}) == len(rows)
    assert len({r['symbol'] for r in rows}) == 1
    for field in SUM_FIELDS:
        assert abs(finite(value[field]) - sum(finite(r[field]) for r in rows)) <= EPS, field
    assert finite(value['drawdown_yen']) >= 0
    measured = ratios(value)
    maximum = max([0.] + [finite(r['maximum_trade_profit']) for r in rows])
    best_session = max([0.] + [finite(r['net_yen']) for r in rows])
    assert all(r['maximum_trade_profit'] >= 0 for r in rows)
    removed_trade = value['net_yen'] - maximum
    removed_session = value['net_yen'] - best_session
    checks = dict(収支正=value['net_yen'] > 0,
        元組PF1超=measured['元組PF'] is not None and measured['元組PF'] > 1,
        平均元組勝敗比1超=measured['平均元組勝敗比'] is not None and measured['平均元組勝敗比'] > 1)
    exclusion = dict(最大勝ち元組除外非負=removed_trade >= -EPS, 最大黒字場除外非負=removed_session >= -EPS)
    return dict(合格=all(checks.values()) and (all(exclusion.values()) if concentration else True),
        基礎検査=checks, 最大勝ち除外検査=exclusion, 最大勝ち除外を採否へ使用=concentration,
        比率=measured, 最大勝ち元組円=maximum, 最大黒字場円=best_session,
        最大勝ち元組除外収支円=removed_trade, 最大黒字場除外収支円=removed_session,
        稼働セッション数=sum(r['cycles'] > 0 for r in rows),
        減量約定回数=value['reductions'], 復元約定回数=value['restorations'])


def relation(candidate: dict, reference: dict) -> dict:
    """機能: 全13/後7の両市場で収支と時価DDの非劣位・交換を区別する。

    引数: candidate/reference (dict)。返り値: 4セルの差と関係 (dict)。
    """
    rows = []
    for period in PERIODS:
        for symbol in SYMBOLS:
            a, b = candidate[period][symbol], reference[period][symbol]
            net = finite(a['net_yen']) - finite(b['net_yen'])
            dd = finite(a['drawdown_yen']) - finite(b['drawdown_yen'])
            assert a['drawdown_yen'] >= 0 and b['drawdown_yen'] >= 0
            rows.append(dict(期間=period, 銘柄=symbol, 収支差円=net, 最大下落差円=dd))
    positive = all(r['収支差円'] >= -EPS and r['最大下落差円'] <= EPS for r in rows)
    negative = all(r['収支差円'] <= EPS and r['最大下落差円'] >= -EPS for r in rows)
    strict = any(abs(r[k]) > EPS for r in rows for k in ('収支差円', '最大下落差円'))
    label = '同値' if not strict else '同時改善' if positive else '対照優位' if negative else '交換又は混在'
    return dict(関係=label, 同時改善=positive and strict, 対照が厳密支配=negative and strict,
        完全同値=not strict, 差=rows)


def rules() -> dict:
    """機能: 基礎・感度・分岐価値を分け、結果前の主判定を定義する。

    引数: なし。返り値: 機械的な判定規則 (dict)。
    """
    return dict(主仮説=PRIMARY, 主条件数=206, 補助条件数=768, 全条件数=974,
        主案の事後差替=False, 期間='全13／同じ後7の各銘柄。全期間既知。',
        基礎='4セルの収支正・元組PF>1・平均元組勝敗比>1、最大1勝ち組／最大1黒字場を別々に除外して非負、減量／復元実約定あり、指定8波。',
        機会='元A0全開始の一致を独立監査で要求。無取引・全不作動を成功にしない。',
        感度=dict(変形=list(VARIANTS), 判定='後7の両銘柄で収支正・元組PF>1・平均元組勝敗比>1。',
            位置付け='独立の頑健性ラベル。不合格でも基準条件の基礎候補は保持する。'),
        分岐対応=list(PAIRED_IDS),
        分岐層='主の減量約定時の有効逆B01／その他。その他は順・中立・欠測も別件数。N1の同じ元組を比較。',
        分岐価値='後7の各銘柄の両層に経済差があり、各層の選択−非選択の合計差R>0。全13の各層は非負。後7で主が固定両方式・逆分岐・分岐64中央値を合計元組Rで上回る。',
        差R='同じ元組の最終収支差／元q0×初回A0の初期R。未復元で終了した元組・損失組も含む。',
        分岐支持の意味='利益差についての既知内支持。DD改善・将来優位を含意しない。',
        A0対照='全4セルの収支／DDの同時改善・交換・同値・対照優位を表示。全セルParetoは採否の必要条件にしない。',
        採用='監査完了 AND 基礎候補 AND 14感度頑健性 AND 分岐の利益付加価値。3段階の結果もそれぞれ保持。',
        R無効='機構除去の診断専用。運用主案はR有効。',
        乱数='減量512／復元192／分岐64を別系統とし全seedを表示。元公開機会が残る構造保存対照。正式p値なし・最良seed採用なし。',
        未定義='分母なしのPF・平均勝敗比は未確認。非有限値は拒否。',
        限界='8本は旧309からの選抜、後7も既読。今回の事前固定は未知検証ではない。どんな相場にも確実という判定はしない。')


def names_for(period: str, sessions: list[str]) -> list[str]:
    """機能: 全13又は同じ後7のセッション集合を返す。

    引数: period (str)、sessions (list[str])。返り値: 対象セッション (list[str])。
    """
    assert period in PERIODS
    return sessions if period == 'all_symbols' else sessions[6:]


def base_candidate(value: dict, rows: list[dict], sessions: list[str]) -> dict:
    """機能: 無活動を除き、基準条件の損小利大と集中を判定する。

    引数: value (dict)、rows (list[dict])、sessions (list[str])。返り値: 4セルと基礎候補 (dict)。
    """
    checks = {period: {symbol: basic(value[period][symbol],
        [r for r in rows if r['symbol'] == symbol and r['session'] in names_for(period, sessions)],
        names_for(period, sessions), True) for symbol in SYMBOLS} for period in PERIODS}
    active = all(c['減量約定回数'] > 0 and c['復元約定回数'] > 0 for p in checks.values() for c in p.values())
    economic = all(c['合格'] for p in checks.values() for c in p.values())
    wave = value['wave_passes'] == 8
    return dict(基礎候補=bool(economic and active and wave), 基礎=checks,
        両期間両銘柄で減量復元実約定=active, 元組基礎と大勝ち除外=economic,
        指定八波=wave, 波通過数=value['wave_passes'])


def samples(values: list[float]) -> dict:
    """機能: 空集合を成功扱いせず、対応差の規模と一件集中を表示する。

    引数: values (list[float])。返り値: 件数・平均・中央値・合計等 (dict)。
    """
    values = [finite(v) for v in values]
    total = sum(values)
    maximum = max([0.] + values)
    return dict(件数=len(values), 合計=total, 平均=total / len(values) if values else None,
        中央値=median(values) if values else None,
        改善数=sum(v > EPS for v in values), 悪化数=sum(v < -EPS for v in values),
        同値数=sum(abs(v) <= EPS for v in values), 最大正差=maximum, 最大正差除外=total - maximum)


def ledger_rows(ledgers: dict, sessions: list[str]) -> dict:
    """機能: 分岐の対応に使う4条件の26台帳と元組を検査する。

    引数: ledgers (dict[id,list[dict]])、sessions (list[str])。返り値: 条件別台帳 (dict)。
    """
    assert set(ledgers) == set(PAIRED_IDS)
    expected = {(name, symbol) for name in sessions for symbol in SYMBOLS}
    output = {}
    for identifier, rows in ledgers.items():
        assert len(rows) == 26
        keyed = {(r['session'], r['symbol']): r for r in rows}
        assert set(keyed) == expected and len(keyed) == len(rows)
        for key, row in keyed.items():
            cycles = row['cycles']
            assert all(isinstance(c, list) and len(c) == 10 for c in cycles)
            for c in cycles:
                list(map(finite, c))
                assert c[0] >= 0 and int(c[0]) == c[0]
                assert c[1] >= 0 and int(c[1]) == c[1]
                assert c[2] >= c[1] and int(c[2]) == c[2]
                assert c[4] > 0 and c[5] > 0 and c[8] in (-1, 1)
            assert len({int(c[0]) for c in cycles}) == len(cycles)
            assert finite(row['config']['point_value']) == (1000. if key[1] == 'TOPIX' else 10.)
        output[identifier] = keyed
    return output


def branch_pairs(ledgers: dict, sessions: list[str]) -> list[dict]:
    """機能: 分岐時の既知状態で元組を対応させ、選択・非選択の差を導出する。

    引数: ledgers (dict[id,list[dict]])、sessions (list[str])。返り値: 全元組の対応明細 (list[dict])。
    予約・損失・未復元の組を将来の成績で除外しない。無分岐は別に保持する。
    """
    sources = ledger_rows(ledgers, sessions)
    output = []
    for key in sorted(sources[PRIMARY]):
        maps = {identifier: {int(c[0]): c for c in sources[identifier][key]['cycles']} for identifier in PAIRED_IDS}
        expected = set(maps[PRIMARY])
        assert all(set(mapping) == expected for mapping in maps.values()), ('元組集合不一致', key)
        branch = sources[PRIMARY][key]['branch_events']
        assert all(isinstance(b, list) and len(b) == 10 for b in branch)
        assert len({int(b[1]) for b in branch}) == len(branch), 'N1の同組に複数分岐'
        events = {}
        for b in branch:
            list(map(finite, b))
            campaign = int(b[1])
            assert b[1] == campaign and campaign in expected and b[2] == 1
            assert b[3] in (1, 2) and b[4] in (-1, 0, 1) and b[6] in (0, 1)
            assert b[8] == 1 and b[9] == -1
            c = maps[PRIMARY][campaign]
            assert int(b[0]) == b[0] and c[1] < b[0] <= c[2]
            assert int(b[5]) == b[5] and -1 <= b[5] <= b[0]
            assert not b[6] or b[5] >= 0
            classification = 0 if not b[6] else 1 if b[4] == 0 else 2 if b[4] == c[8] else 3
            assert b[7] == classification
            assert b[3] == (1 if classification == 3 else 2)
            events[campaign] = b
        for campaign in sorted(expected):
            original = maps[PRIMARY][campaign]
            risk = original[4]
            for identifier in PAIRED_IDS:
                counterpart = maps[identifier][campaign]
                assert all(abs(original[k] - counterpart[k]) <= EPS for k in (0, 1, 4, 5, 8)), ('初回又はR不一致', key, campaign)
            profit = {identifier: maps[identifier][campaign][3] for identifier in PAIRED_IDS}
            event = events.get(campaign)
            factor = sources[PRIMARY][key]['config']['point_value']
            if event is None:
                assert all(abs(v - profit[PRIMARY]) <= EPS for v in profit.values()), '無分岐組の方式差'
                chosen, opposite, classification = None, None, None
                gap = 0.
            else:
                classification = int(event[7])
                chosen, opposite = (SIGNAL, CLOCK) if event[3] == 1 else (CLOCK, SIGNAL)
                assert abs(profit[PRIMARY] - profit[chosen]) <= EPS, '選択した固定方式と収支不一致'
                assert abs(profit[REVERSE] - profit[opposite]) <= EPS, '逆分岐と非選択方式の収支不一致'
                gap = (profit[chosen] - profit[opposite]) / risk
            output.append(dict(session=key[0], symbol=key[1], campaign=campaign,
                減量分岐あり=event is not None, 分類=classification,
                層=None if event is None else '逆方向' if classification == 3 else 'その他',
                選択方式=chosen, 非選択方式=opposite,
                元予定R円=risk * factor, 選択差R=gap, 選択差円=gap * risk * factor,
                元組R={identifier: profit[identifier] / risk for identifier in PAIRED_IDS},
                元組円={identifier: profit[identifier] * factor for identifier in PAIRED_IDS}))
    return output


def branch_evidence(index: dict, ledgers: dict, sessions: list[str]) -> dict:
    """機能: 固定両方式・逆分岐・64分岐対照と、事前層別の利益差を判定する。

    引数: index (dict)、ledgers (dict)、sessions (list[str])。返り値: 分岐の利益付加価値と全対応 (dict)。
    """
    pairs = branch_pairs(ledgers, sessions)
    random_specs = [s for s in design.supplementary() if s['branch_seed'] is not None]
    assert len(random_specs) == 64 and {s['branch_seed'] for s in random_specs} == set(range(64))
    cells = {}
    for period in PERIODS:
        cells[period] = {}
        for symbol in SYMBOLS:
            rows = [r for r in pairs if r['symbol'] == symbol and r['session'] in names_for(period, sessions)]
            levels = {}
            for layer in ('逆方向', 'その他'):
                part = [r for r in rows if r['層'] == layer]
                levels[layer] = dict(差R=samples([r['選択差R'] for r in part]),
                    差円=samples([r['選択差円'] for r in part]),
                    分類件数={str(kind): sum(r['分類'] == kind for r in part) for kind in range(4)})
            scores = {identifier: sum(r['元組R'][identifier] for r in rows) for identifier in PAIRED_IDS}
            for identifier, score in scores.items():
                assert abs(finite(index[identifier][period][symbol]['net_r']) - score) <= EPS, '元組R期間集計不一致'
            net = scores[PRIMARY]
            randoms = [dict(id=s['id'], seed=s['branch_seed'],
                元組R=finite(index[s['id']][period][symbol]['net_r']),
                収支円=finite(index[s['id']][period][symbol]['net_yen']),
                最大下落円=finite(index[s['id']][period][symbol]['drawdown_yen'])) for s in random_specs]
            random_median = median(r['元組R'] for r in randoms)
            levels_active = all(r['差R']['件数'] > 0 and r['差R']['改善数'] + r['差R']['悪化数'] > 0 for r in levels.values())
            signal_count = sum(r['層'] == '逆方向' for r in rows)
            timer_count = sum(r['層'] == 'その他' for r in rows)
            assert finite(index[PRIMARY][period][symbol]['signal_choices']) == signal_count
            assert finite(index[PRIMARY][period][symbol]['timer_choices']) == timer_count
            row = dict(全元組数=len(rows), 無分岐元組数=sum(not r['減量分岐あり'] for r in rows),
                信号選択数=signal_count, 時計選択数=timer_count, 両分岐が作動し経済差あり=levels_active,
                層別=levels, 元組R=scores, 固定両方式超過=all(net > scores[i] + EPS for i in (SIGNAL, CLOCK)),
                逆分岐超過=net > scores[REVERSE] + EPS,
                乱数中央値超過=net > random_median + EPS, 乱数元組R中央値=random_median,
                主以上元組Rの乱数本数=sum(r['元組R'] >= net - EPS for r in randoms),
                主以上収支円の乱数本数=sum(r['収支円'] >= index[PRIMARY][period][symbol]['net_yen'] - EPS for r in randoms),
                主以下下落円の乱数本数=sum(r['最大下落円'] <= index[PRIMARY][period][symbol]['drawdown_yen'] + EPS for r in randoms),
                収支下落両方の乱数本数=sum(r['収支円'] >= index[PRIMARY][period][symbol]['net_yen'] - EPS
                    and r['最大下落円'] <= index[PRIMARY][period][symbol]['drawdown_yen'] + EPS for r in randoms),
                全64分岐対照=sorted(randoms, key=lambda r: r['seed']))
            cells[period][symbol] = row
    gates = dict(後七の両市場両層が作動=all(r['両分岐が作動し経済差あり'] for r in cells['symbols'].values()),
        後七の両市場各層で正の差R=all(layer['差R']['合計'] > EPS for r in cells['symbols'].values() for layer in r['層別'].values()),
        全十三の両市場各層で非負差R=all(layer['差R']['合計'] >= -EPS for r in cells['all_symbols'].values() for layer in r['層別'].values()),
        後七で固定両方式超過=all(r['固定両方式超過'] for r in cells['symbols'].values()),
        後七で逆分岐超過=all(r['逆分岐超過'] for r in cells['symbols'].values()),
        後七で分岐乱数中央値超過=all(r['乱数中央値超過'] for r in cells['symbols'].values()))
    return dict(利益付加価値支持=all(gates.values()), 検査=gates, 期間別=cells,
        全元組対応=pairs, 正式p値ではない=True, DD改善を含意しない=True)


def random_diagnostics(index: dict) -> list[dict]:
    """機能: 減量と回復の全符号対照を、基準条件ごとに分けて保存する。

    引数: index (dict[id,dict])。返り値: 全基準・全期間・全seedの診断 (list[dict])。
    """
    output = []
    supplementary = design.supplementary()
    for policy in design.SELECTED:
        origin_id = 'H019__' + policy + '__R1__V000'
        for role, field in (('減量', 'bad_seed'), ('回復', 'good_seed')):
            specs = [s for s in supplementary if s['policy']['id'] == policy and s[field] is not None]
            if not specs:
                assert role == '回復'
                continue
            assert len(specs) == 64 and {s[field] for s in specs} == set(range(64))
            cells = []
            for period in PERIODS:
                for symbol in SYMBOLS:
                    reference = index[origin_id][period][symbol]
                    rows = [dict(id=s['id'], seed=s[field],
                        収支円=finite(index[s['id']][period][symbol]['net_yen']),
                        最大下落円=finite(index[s['id']][period][symbol]['drawdown_yen']),
                        元組R=finite(index[s['id']][period][symbol]['net_r'])) for s in specs]
                    net, dd = finite(reference['net_yen']), finite(reference['drawdown_yen'])
                    cells.append(dict(期間=period, 銘柄=symbol, 全64=sorted(rows, key=lambda r: r['seed']),
                        収支中央値円=median(r['収支円'] for r in rows), 下落中央値円=median(r['最大下落円'] for r in rows),
                        元方式以上収支本数=sum(r['収支円'] >= net - EPS for r in rows),
                        元方式以下下落本数=sum(r['最大下落円'] <= dd + EPS for r in rows),
                        両方本数=sum(r['収支円'] >= net - EPS and r['最大下落円'] <= dd + EPS for r in rows)))
            output.append(dict(基準=origin_id, 役割=role, 期間別=cells, 採用基準へ加算しない=True))
    assert len(output) == 11
    return output


def assess(index: dict, sessions: dict, session_names: list[str], ledgers: dict,
           verification: bool = False) -> dict:
    """機能: 全974条件を保持し、固定主案の3段階と監査完了を分けて判定する。

    引数: index (dict)、sessions (dict)、session_names (list[str])、ledgers (dict)、verification (bool)。
    返り値: 主案採否・全対照・8既選抜の基礎・層別対応 (dict)。最良条件へ差し替えない。
    """
    assert type(verification) is bool
    assert len(session_names) == 13 and session_names == sorted(set(session_names))
    main_specs, supplementary = design.catalog(), design.supplementary()
    expected_specs = {s['id']: s for s in main_specs + supplementary}
    assert len(main_specs) == 206 and len(supplementary) == 768 and len(expected_specs) == 974
    assert set(index) == set(sessions) == set(expected_specs)
    keys = {(name, symbol) for name in session_names for symbol in SYMBOLS}
    for identifier in sorted(index):
        value, rows = index[identifier], sessions[identifier]
        assert value['id'] == identifier and value['spec'] == expected_specs[identifier]
        assert len(rows) == 26 and {(r['session'], r['symbol']) for r in rows} == keys
        assert all(r['id'] == identifier for r in rows)
        assert type(value['wave_passes']) is int and 0 <= value['wave_passes'] <= 8
        for period in PERIODS:
            assert set(value[period]) == set(SYMBOLS)
            for symbol in SYMBOLS:
                ratios(value[period][symbol])
                assert finite(value[period][symbol]['drawdown_yen']) >= 0
                finite(value[period][symbol]['net_r'])
    primary = index[PRIMARY]
    basic_result = base_candidate(primary, sessions[PRIMARY], session_names)
    sensitivities = {}
    for variant in VARIANTS:
        identifier = 'H019__' + design.PRIMARY_POLICY + '__R1__' + variant
        sensitivities[variant] = {symbol: basic(index[identifier]['symbols'][symbol],
            [r for r in sessions[identifier] if r['symbol'] == symbol and r['session'] in session_names[6:]],
            session_names[6:], False) for symbol in SYMBOLS}
    robust = all(r['合格'] for cells in sensitivities.values() for r in cells.values())
    branching = branch_evidence(index, ledgers, session_names)
    controls = dict(A0='A0', 減量のみ='B06_NONE_F50', 固定コア='CORE50',
        通常半分利確型小数量='SMALL50', 固定B01='B06_RB01_F50_N1',
        対応固定時計=design.CLOCK_POLICY, 旧B06時計='B06_T120_F50_N1', 逆分岐=design.REVERSE_POLICY,
        旧B06回復='B06_RB06_F50_N1')
    comparisons = {label: relation(primary, index['H019__' + policy + '__R1__V000']) for label, policy in controls.items()}
    eight = {policy: base_candidate(index['H019__' + policy + '__R1__V000'],
        sessions['H019__' + policy + '__R1__V000'], session_names) for policy in design.SELECTED}
    without_budget = {policy['id']: relation(index['H019__' + policy['id'] + '__R1__V000'],
        index['H019__' + policy['id'] + '__R0__V000']) for policy in design.policies()}
    economic = bool(basic_result['基礎候補'] and robust and branching['利益付加価値支持'])
    return dict(主仮説=PRIMARY, 主条件数=206, 補助条件数=768, 全条件数=974, 監査完了=verification,
        基礎候補=basic_result['基礎候補'], 十四感度頑健性=robust,
        分岐の利益付加価値=branching['利益付加価値支持'], 経済目安合格=economic,
        既知比較の採用候補=bool(verification and economic), 基礎=basic_result,
        十四感度=sensitivities, 分岐価値=branching, 対応比較=comparisons,
        既選抜八条件=eight, 実R退出有無=without_budget, 成分符号対照=random_diagnostics(index),
        A0全セル同時改善=comparisons['A0']['同時改善'], 未知での有効性確認=False,
        基準候補と頑健性未達を分ける=True, 規則=rules())


def freeze() -> dict:
    """機能: 合成検査後に採否の規則と実装を固定する。

    引数: なし。返り値: 固定資料 (dict)。新しい損益を読み込まない。
    """
    test_path = HERE / 'adaptive_assessment_test.json'
    test = json.loads(test_path.read_text(encoding='utf-8'))
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert test['全合格'] and not test['新実相場損益']
    assert test['実装SHA256'] == sha(Path(__file__))
    assert test['検査SHA256'] == sha(HERE / 'adaptive_assessment_test.py')
    assert test['設計SHA256'] == sha(HERE / 'adaptive_design.py')
    assert test['実エンジン人工接続数'] == 8
    extra = test['実エンジン参照SHA256']
    for relative, expected in extra.items():
        assert sha(ROOT / relative) == expected, relative
    plan_path = HERE / 'adaptive_assessment_revision_plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    assert not any(plan[k] for k in ('新損益読取','売買方式変更','採否閾値変更','対象変更','現在保存物使用'))
    for original, row in plan['旧資料'].items():
        assert sha(HERE / row['保存先']) == row['SHA256'], original
        extra[(HERE / row['保存先']).relative_to(ROOT).as_posix()] = row['SHA256']
    extra[plan_path.relative_to(ROOT).as_posix()] = sha(plan_path)
    value = dict(規則=rules(), 参照SHA256={p.relative_to(ROOT).as_posix(): sha(p) for p in (Path(__file__),
        HERE / 'adaptive_assessment_test.py', test_path, HERE / 'adaptive_design.py',
        HERE / '採否と分岐価値の独立設計案.md', HERE / '独立検算の設計案.md')},
        新実相場損益=False, 新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False)
    value['参照SHA256'].update(extra)
    value['採否版'] = 2
    value['事前接続補正'] = plan
    target = HERE / 'adaptive_assessment_fixed.json'
    if target.exists():
        previous = json.loads(target.read_text(encoding='utf-8'))
        if previous != value:
            assert target.read_bytes() == (HERE / plan['旧資料'][target.name]['保存先']).read_bytes()
            assert previous['規則'] == value['規則'], '採否の条件を変えない'
            target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    else:
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return value


if __name__ == '__main__':
    freeze()
    print('採否の3段階を人工検査と共に固定しました。新損益なし。')


