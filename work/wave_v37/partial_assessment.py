"""元組単位の損小利大と復元情報の価値を、固定主案だけで判定する。"""

from __future__ import annotations

import math
from statistics import median

import partial_design as design


SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('all_symbols', 'symbols')
PRIMARY = design.PRIMARY_ID
VARIANTS = ('E080', 'E120', 'O000', 'D080', 'D120', 'R080', 'R120')
CONTROLS = {
    '元A0': 'H019__A0__V000',
    '減量のみ': 'H019__B06_NONE_F50__V000',
    '固定コア': 'H019__CORE50__V000',
    '通常半分利確型小数量': 'H019__SMALL50__V000',
    '120秒復元': 'H019__B06_T120_F50_N1__V000',
}
SUM_FIELDS = ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units',
    'loss_units', 'zero_units', 'cycles', 'cycle_wins', 'cycle_losses',
    'cycle_profit_yen', 'cycle_loss_yen', 'reductions', 'restorations')
COUNT_FIELDS = ('profit_units', 'loss_units', 'zero_units', 'cycles', 'cycle_wins',
    'cycle_losses', 'reductions', 'restorations')
EPS = 1e-6


def rules() -> dict:
    """機能: 主案の採否と診断の用途を結果前の一つの規則へまとめる。

    引数: なし。返り値: 固定する研究規則 (dict)。
    """
    return dict(主仮説=PRIMARY, 主格子数=309, 診断条件数=54, 全主再生条件数=363,
        別補助条件数=64, 全条件数=427, 主仮説の事後差替=False,
        主期間='全13と共通後7、各TOPIX/NK225の4セル。既知期間の再検証。',
        基礎='4セルで収支正、元組PF>1、平均元組勝敗比>1。最大1勝ち元組と最大1黒字場を各々除外して非負。',
        元組='元A0の開始から終了までを同じ組IDとして合算し、減量・復元を別の勝ち組に分割しない。',
        機構稼働='4セルで減量約定回数>0かつ復元約定回数>0。予約・取消は含めない。',
        感度=dict(対象=list(VARIANTS), 必須='後7の両銘柄で収支正・元組PF>1・平均元組勝敗比>1。',
            表示のみ='感度の最大勝ち除外と全13。最良変形で主案を救済しない。'),
        指定波='旧定義の全8波を表示し8/8を必要とする。コア保有の維持だけで予測精度向上と呼ばない。',
        A0代替目標='4セルの収支非劣位・時価DD非劣位、全体で最低1項目厳密改善。75/80等の割合は追加しない。',
        単純対照='減量のみ・固定コア・通常半分利確型小数量・120秒復元に4セルの収支/DDで厳密に支配されない。',
        対照同値='同値は非支配だが追加価値の証明ではない。各関係と完全同値を別表示する。',
        回復符号対照='64本の各セル中央値に収支/DD非劣位、全体で最低1項目厳密改善。正式p値ではない。',
        乱数の保持情報='元B06非0の有効公開機会を保持し、公開source単位で元方向へ符号を乗算。同source内は保持するが別イベント・銘柄の方向関係を保持するとは限らない。',
        採用目安='監査完了、基礎、機構稼働、7変形基礎、8波、A0代替目標、単純対照非支配、64中央値対照の全て。',
        分離='会計・入力の監査合格と経済条件を分ける。代替改善未達は手法全体無価値の証明ではない。',
        undefined='無損失等でPF/平均勝敗比が未定義の場合は未確認として基礎を通さない。',
        枚数='金額/勝敗決済枚数/同値枚数/一枚平均を表示。両建ての脚別PFを独立の利益源の判定に使わない。',
        未知='既知データの多重探索であり、通過しても未知相場の統計的優位・利益保証ではない。')


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


def random_comparison(main: dict, randoms: list[dict]) -> dict:
    """機能: 64符号対照の全分布と中央値を固定主案と比較する。

    引数: main (dict)、randoms (list[dict])。返り値: 4セル・全64個別関係 (dict)。
    """
    expected = {r['id'] for r in design.supplementary()}
    assert len(randoms) == 64 and {r['id'] for r in randoms} == expected
    rows = []
    for period in PERIODS:
        for symbol in SYMBOLS:
            origin = main[period][symbol]
            nets = [finite(r[period][symbol]['net_yen']) for r in randoms]
            dds = [finite(r[period][symbol]['drawdown_yen']) for r in randoms]
            assert all(v >= 0 for v in dds)
            net, dd = finite(origin['net_yen']), finite(origin['drawdown_yen'])
            assert dd >= 0
            rows.append(dict(期間=period, 銘柄=symbol, 主収支円=net, 主最大下落円=dd,
                乱数収支中央値円=median(nets), 乱数最大下落中央値円=median(dds),
                収支非劣位=net >= median(nets) - EPS, 下落非劣位=dd <= median(dds) + EPS,
                厳密改善=net > median(nets) + EPS or dd < median(dds) - EPS,
                主以上収支の乱数本数=sum(v >= net - EPS for v in nets),
                主以下下落の乱数本数=sum(v <= dd + EPS for v in dds),
                収支分布円=sorted(nets), 最大下落分布円=sorted(dds)))
    pairs = {r['id']: relation(main, r) for r in sorted(randoms, key=lambda r: r['id'])}
    return dict(完了=True, 合格=all(r['収支非劣位'] and r['下落非劣位'] for r in rows)
        and any(r['厳密改善'] for r in rows), 中央値比較=rows, 全64対応比較=pairs,
        主を厳密支配する乱数本数=sum(p['対照が厳密支配'] for p in pairs.values()),
        解釈=rules()['乱数の保持情報'] + ' 正式p値ではなく、最良seedは採用しない。')


def assess(index: dict, sessions: dict, session_names: list[str], verification: bool = False) -> dict:
    """機能: 全資料の集合を要求し、固定主案の経済条件と監査完了を別判定する。

    引数: index (dict[id,dict])、sessions (dict[id,list[dict]])、session_names (list[str])、verification (bool)。
    返り値: 採否と全比較根拠 (dict)。新しい入口・管理・seedへ差し替えない。
    """
    assert type(verification) is bool
    assert len(session_names) == 13 and session_names == sorted(set(session_names))
    specifications = design.catalog() + design.supplementary()
    expected = {r['id'] for r in specifications}
    assert len(expected) == 427 and set(index) == set(sessions) == expected
    expected_rows = {(session, symbol) for session in session_names for symbol in SYMBOLS}
    for identifier in sorted(expected):
        value, rows = index[identifier], sessions[identifier]
        assert value['id'] == identifier and len(rows) == 26
        assert {(r['session'], r['symbol']) for r in rows} == expected_rows
        assert all(r['id'] == identifier for r in rows)
        assert type(value['wave_passes']) is int and 0 <= value['wave_passes'] <= 8
        for period in PERIODS:
            assert set(value[period]) == set(SYMBOLS)
            for symbol in SYMBOLS:
                ratios(value[period][symbol])
                assert finite(value[period][symbol]['drawdown_yen']) >= 0
    main = index[PRIMARY]
    checks = {}
    for period, names in (('all_symbols', session_names), ('symbols', session_names[6:])):
        checks[period] = {symbol: basic(main[period][symbol],
            [r for r in sessions[PRIMARY] if r['symbol'] == symbol and r['session'] in names], names, True)
            for symbol in SYMBOLS}
    comparisons = {label: relation(main, index[identifier]) for label, identifier in CONTROLS.items()}
    sensitivity = {}
    for variant in VARIANTS:
        identifier = 'H019__' + design.PRIMARY_POLICY + '__' + variant
        sensitivity[variant] = {symbol: basic(index[identifier]['symbols'][symbol],
            [r for r in sessions[identifier] if r['symbol'] == symbol and r['session'] in session_names[6:]],
            session_names[6:], False) for symbol in SYMBOLS}
    randomized = random_comparison(main, [index[r['id']] for r in design.supplementary()])
    gates = dict(元組基礎と大勝ち除外=all(r['合格'] for p in checks.values() for r in p.values()),
        両期間両銘柄で減量と復元約定=all(r['減量約定回数'] > 0 and r['復元約定回数'] > 0
            for p in checks.values() for r in p.values()),
        七変形の後七基礎=all(r['合格'] for p in sensitivity.values() for r in p.values()),
        指定八波=main['wave_passes'] == 8, A0代替の同時改善=comparisons['元A0']['同時改善'],
        単純対照に厳密支配されない=all(not row['対照が厳密支配'] for name, row in comparisons.items() if name != '元A0'),
        回復符号対照=randomized['合格'])
    economic = all(gates.values())
    return dict(主仮説=PRIMARY, 全主再生条件数=363, 補助条件数=64, 監査完了=verification,
        基礎=checks, 対応比較=comparisons, 七変形感度=sensitivity, 指定波=main['wave_passes'],
        回復符号対照=randomized, 経済検査=gates, 経済目安合格=economic,
        既知比較の採用候補=bool(verification and economic), 未知での有効性確認=False,
        単純対照と同値の項目=[name for name, row in comparisons.items() if name != '元A0' and row['完全同値']],
        規則=rules(), 限界='A0代替の改善目標は今回の研究目標。未達は既存A0や他手法の無価値を示さない。既知の多重探索で将来の優位を確証しない。')
