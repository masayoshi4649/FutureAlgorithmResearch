"""気配維持代理の主仮説を、対応対照と固定の基礎条件から判定する。"""

from __future__ import annotations

import math

SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('all_symbols', 'symbols')
PRIMARY = 'Q034__V000'
CONTROLS = {'純価格': 'Q007__V000', '全出来高': 'Q016__V000', '旧中期方向': 'H019__V000'}


def basic(value: dict, rows: list[dict], later: bool) -> dict:
    """機能: 無取引を除外し、金額と1枚平均の損小利大・大勝ち依存を確認する。

    引数: value (dict)、rows (list[dict])、later (bool)。返り値: 判定と根拠 (dict)。
    """
    assert len(rows) == (7 if later else 13)
    assert len({r['session'] for r in rows}) == len(rows)
    required = ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units', 'loss_units', 'drawdown_yen')
    assert all(math.isfinite(value[k]) for k in required)
    assert value['gross_loss_yen'] >= 0 and value['drawdown_yen'] >= 0
    ratio = value['gross_profit_yen'] / value['gross_loss_yen'] if value['gross_loss_yen'] > 0 else None
    payoff = ((value['gross_profit_yen'] / value['profit_units']) / (value['gross_loss_yen'] / value['loss_units'])
        if value['profit_units'] > 0 and value['loss_units'] > 0 and value['gross_loss_yen'] > 0 else None)
    active = sum(r['cycles'] > 0 for r in rows)
    largest = max([0.] + [v for r in rows for v in r['two_largest_cycle_profits']])
    best_session = max([0.] + [r['net_yen'] for r in rows])
    checks = dict(黒字=value['net_yen'] > 0, 金額利益損失比1超=ratio is not None and ratio > 1,
        一枚平均利益損失比1超=payoff is not None and payoff > 1,
        必要稼働=active >= (4 if later else 7),
        最大勝ち組除外非負=value['net_yen'] - largest >= -1e-6,
        最大黒字場除外非負=value['net_yen'] - best_session >= -1e-6)
    return dict(合格=all(checks.values()), 検査=checks, 金額比=ratio, 一枚平均比=payoff,
        稼働セッション数=active, 最大勝ち組除外円=value['net_yen'] - largest,
        最大黒字場除外円=value['net_yen'] - best_session)


def relation(candidate: dict, reference: dict) -> dict:
    """機能: 同期間・同銘柄の収支と時価下落を対応比較する。

    引数: candidate/reference (dict)。返り値: 関係と4セル差 (dict)。銘柄間の円額は合算しない。
    """
    rows = []
    for period in PERIODS:
        for symbol in SYMBOLS:
            a, b = candidate[period][symbol], reference[period][symbol]
            rows.append(dict(期間=period, 銘柄=symbol,
                収支差円=a['net_yen'] - b['net_yen'], 最大下落差円=a['drawdown_yen'] - b['drawdown_yen']))
    assert all(math.isfinite(r[k]) for r in rows for k in ('収支差円', '最大下落差円'))
    positive = all(r['収支差円'] >= -1e-6 and r['最大下落差円'] <= 1e-6 for r in rows)
    negative = all(r['収支差円'] <= 1e-6 and r['最大下落差円'] >= -1e-6 for r in rows)
    strict = any(abs(r[k]) > 1e-6 for r in rows for k in ('収支差円', '最大下落差円'))
    label = '同値' if not strict else '同時改善' if positive else '対照優位' if negative else '交換又は混在'
    return dict(関係=label, 同時改善=positive and strict, 差=rows)


def random_comparison(main: dict, randoms: list[dict], reverse: dict) -> dict:
    """機能: 固定64乱数方向と反転を、同じ期間・銘柄の収支と下落で比較する。

    引数: main/reverse (dict)、randoms (list[dict])。返り値: 中央値対照の判定 (dict)。正式p値ではない。
    """
    from statistics import median
    assert len(randoms) == 64 and len({r['id'] for r in randoms}) == 64
    rows = []
    for period in PERIODS:
        for symbol in SYMBOLS:
            origin = main[period][symbol]
            nets = [r[period][symbol]['net_yen'] for r in randoms]
            dds = [r[period][symbol]['drawdown_yen'] for r in randoms]
            assert all(math.isfinite(v) for v in nets + dds)
            rows.append(dict(期間=period, 銘柄=symbol,
                元収支円=origin['net_yen'], 乱数収支中央値円=median(nets),
                元最大下落円=origin['drawdown_yen'], 乱数最大下落中央値円=median(dds),
                収支非劣位=origin['net_yen'] >= median(nets) - 1e-6,
                下落非劣位=origin['drawdown_yen'] <= median(dds) + 1e-6,
                収支又は下落改善=origin['net_yen'] > median(nets) + 1e-6 or origin['drawdown_yen'] < median(dds) - 1e-6))
    flipped = relation(main, reverse)
    passed = all(r['収支非劣位'] and r['下落非劣位'] for r in rows) and any(r['収支又は下落改善'] for r in rows)
    passed = passed and flipped['関係'] not in ('同値', '対照優位')
    return dict(完了=True, 合格=passed, 中央値比較=rows, 全方向反転比較=flipped,
        解釈='活動時刻だけを保つ方向対照。実際の新規数・保有時間・約定は揃わず、正式p値ではない。')


def assess(index: dict, sessions: dict, session_names: list[str], verification: bool, random_check: dict) -> dict:
    """機能: 主仮説1件を判定し、成績の良い別IDへの差替を行わない。

    引数: index/sessions (dict)、session_names (list[str])、verification (bool) は独立監査の完了、random_check (dict)。
    返り値: 基礎・対応比較・感度・指定波・主仮説の判定 (dict)。
    """
    assert len(session_names) == 13 and session_names == sorted(set(session_names))
    main = index[PRIMARY]
    checks = {}
    for period, names in (('all_symbols', session_names), ('symbols', session_names[6:])):
        checks[period] = {s: basic(main[period][s],
            [r for r in sessions[PRIMARY] if r['symbol'] == s and r['session'] in names], period == 'symbols') for s in SYMBOLS}
    comparisons = {label: relation(main, index[identifier]) for label, identifier in CONTROLS.items()}
    clocks = {}
    for variant in ('C080', 'C120'):
        identifier = 'Q034__' + variant
        clocks[variant] = {s: basic(index[identifier]['symbols'][s],
            [r for r in sessions[identifier] if r['symbol'] == s and r['session'] in session_names[6:]], True) for s in SYMBOLS}
    core = all(r['合格'] for p in checks.values() for r in p.values())
    robust = all(r['合格'] for p in clocks.values() for r in p.values())
    added = all(comparisons[name]['同時改善'] for name in ('純価格', '全出来高'))
    waves = main['wave_passes'] == 8
    random_pass = random_check.get('完了') is True and random_check.get('合格') is True
    passed = bool(verification and core and robust and added and waves and random_pass)
    return dict(主仮説=PRIMARY, 監査完了=verification, 基礎=checks, 対応比較=comparisons,
        窓感度=clocks, 指定波=main['wave_passes'], 代理の追加価値基準=added,
        方向対照=random_check, 既知比較の採用候補=passed, 未知での有効性確認=False,
        判定条件='主仮説のみ。全13/後7両銘柄基礎、後7時計両側基礎、純価格/全出来高に収支DD同時改善、指定8波、方向対照、全監査。',
        限界='既知データを繰り返し使用した設計。基準通過も独立した将来成績や統計的有意性の証明ではない。')
