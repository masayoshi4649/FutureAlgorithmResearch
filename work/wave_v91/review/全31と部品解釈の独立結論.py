"""追加38の完了許可後だけに、旧30と追加Dayを独立会計で合算する。"""

from datetime import date, timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
spec = importlib.util.spec_from_file_location('旧38独立会計91再利用', HERE/'旧38条件の独立会計と部品差分及び最悪場診断.py')
OLD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(OLD)


def read(path: Path) -> object:
    """
    機能: 正式参考代表固定と追加全38完成を確認した後の資料を読む。
    引数: path(Path)。
    返り値: object。JSON又はpickle。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def check_extra(result: dict, ledgers: dict) -> dict:
    """
    機能: 追加1場2商品の全親・注文・料金と無取引分類を独立検算する。
    引数: result/ledgers(dict)。
    返り値: dict。口座、注文、親の件数。
    """
    assert len(result['rows']) == len(ledgers) == 2
    count_order = count_parent = 0
    for row in result['rows']:
        symbol = row['symbol']
        ledger = ledgers[(row['session'], symbol)]
        orders, trades = ledger['orders'], ledger['trades']
        value, fee, cap = (1000., 41.8, 10) if symbol == 'TOPIX' else (10., 11., 20)
        assert len(orders) == 2*len(trades)
        assert np.all(orders[:, 0] > orders[:, 1])
        assert not np.any(ledger['slots'][:, 0]) and not np.any(ledger['trace_changes'][-1, 1:])
        assert ledger['stats'][2] <= cap and ledger['stats'][3] <= cap
        for order in orders:
            assert order[9] == math.floor(order[5]*fee+1e-8)
        for parent in trades:
            pair = orders[(orders[:, 2] == parent[0]) & (orders[:, 3] == parent[1])]
            assert len(pair) == 2 and pair[0, 7] == 1 and pair[1, 7] == 0
            gross = parent[4]*(parent[7]-parent[6])*parent[5]*value
            assert abs(parent[10]-gross) < 1e-5
            assert abs(parent[11]-(gross-parent[8]-parent[9])) < 1e-5
            assert pair[0, 9] == parent[8] and pair[1, 9] == parent[9]
        totals = OLD.totals(trades)
        for field, actual in totals.items():
            expected = row[field]
            assert actual is None and expected is None or abs(float(actual)-float(expected)) < 1e-4
            aggregate = result['periods']['追加1'][symbol][field]
            assert actual is None and aggregate is None or abs(float(actual)-float(aggregate)) < 1e-4
        metric = result['periods']['追加1'][symbol]
        assert metric['positive_sessions'] == int(row['net'] > 1e-5)
        assert metric['no_trade_sessions'] == int(not len(trades))
        assert metric['active_sessions'] == int(bool(len(trades)))
        if not len(trades):
            assert metric['profit_share'] is None and metric['positive_session_rate'] is None
        count_order += len(orders)
        count_parent += len(trades)
    return dict(口座=2, 注文=count_order, 親=count_parent)


def aggregate(rows: list[dict], ledgers: dict, symbol: str, sessions: list[str]) -> dict:
    """
    機能: 全31又は指定期間の源別親損益と全場時価下落を独立に合算する。
    引数: rows(list[dict])、ledgers(dict)、symbol(str)、sessions(list[str])。
    返り値: dict。親G/L、活動場、方向、最大日除外、週別。
    """
    selected = [next(r for r in rows if r['session'] == s and r['symbol'] == symbol) for s in sessions]
    parents = np.concatenate([ledgers[(s, symbol)]['trades'] for s in sessions])
    result = OLD.totals(parents)
    result.update(positive_sessions=sum(r['net'] > 1e-5 for r in selected),
                  losing_sessions=sum(r['net'] < -1e-5 for r in selected),
                  active_sessions=sum(r['campaigns'] > 0 for r in selected),
                  no_trade_sessions=sum(not r['campaigns'] for r in selected), session_count=len(sessions))
    cash = peak = dd = 0.
    for row in selected:
        dd = max(dd, row['equity_drawdown'], peak-cash-row['equity_trough'])
        peak = max(peak, cash+row['equity_peak'])
        cash += row['net']
    result['equity_drawdown'] = dd
    assert abs(cash-result['net']) < 1e-4
    result['sources'] = {name: OLD.totals(parents[parents[:, 1] == source]) for source, name in enumerate(('J2', 'O06'))}
    result['directions'] = {name: OLD.totals(parents[parents[:, 4] == side]) for side, name in ((1, '買い'), (-1, '売り'))}
    result['positive_session_rate'] = result['positive_sessions']/result['active_sessions'] if result['active_sessions'] else None
    days, weeks = {}, {}
    for row in selected:
        day = row['session'][:10]
        days[day] = days.get(day, 0.)+row['net']
        calendar = date.fromisoformat(day)
        week = str(calendar-timedelta(days=calendar.weekday()))
        weeks[week] = weeks.get(week, 0.)+row['net']
    best = max(days, key=days.get)
    remainder_parts = [ledgers[(s, symbol)]['trades'] for s in sessions if s[:10] != best]
    remainder = np.concatenate(remainder_parts) if remainder_parts else np.empty((0, 16))
    result.update(best_day=best, without_best_day=OLD.totals(remainder), weeks=weeks)
    return result


def main() -> None:
    """
    機能: 旧30選定を保持したまま追加38と全31の金額目標を敵対評価する。
    引数: なし。
    返り値: None。新売買条件を作らずreviewだけへ保存する。
    """
    fixed = read(WORK/'事前固定.json')
    selection = read(WORK/'前16参考代表.json')
    assert selection['追加Day完結損益前選定'] and selection['selected'] == 'O10_F15'
    assert selection['固定SHA256'] == OLD.digest(WORK/'事前固定.json')
    for relative, expected in selection['結果SHA256'].items():
        assert OLD.digest(ROOT/relative) == expected
    assert len(list((WORK/'extra/results').glob('*.json'))) == 38
    OLD.FIXED = fixed
    old_results = {c['id']: read(WORK/'results'/f"{c['id']}.json") for c in fixed['条件']}
    reference = OLD.selected(old_results)
    assert reference['selected'] == selection['selected']
    all_results, all_ledgers, checks, hashes = {}, {}, {}, {}
    for c in fixed['条件']:
        ident = c['id']
        path = WORK/'extra/results'/f'{ident}.json'
        ledger_path = WORK/'extra/ledgers'/f'{ident}.pkl'
        extra = read(path)
        extra_ledger = read(ledger_path)
        assert extra['config'] == c and extra['ledger_SHA256'] == OLD.digest(ledger_path)
        checks[ident] = check_extra(extra, extra_ledger)
        old_ledger = read(WORK/'ledgers'/f'{ident}.pkl')
        old_ledger.update(extra_ledger)
        rows = old_results[ident]['rows']+extra['rows']
        all_results[ident] = dict(config=c, rows=rows, periods={
            period: {s: aggregate(rows, old_ledger, s, sessions) for s in SYMBOLS}
            for period, sessions in [('全31', fixed['全31']), ('旧30', fixed['旧30']),
                                     ('前16', fixed['前16']), ('後14', fixed['後14']), ('追加1', fixed['追加1'])]})
        all_ledgers[ident] = old_ledger
        hashes[str(path.relative_to(ROOT))] = OLD.digest(path)
        hashes[str(ledger_path.relative_to(ROOT))] = OLD.digest(ledger_path)
    targets = [i for i, r in all_results.items() if all((r['periods']['全31'][s]['profit_share'] or 0) >= .8 for s in SYMBOLS)]
    source_targets = [dict(条件=i, 源=source) for i, r in all_results.items() for source in ('J2', 'O06')
                      if all((r['periods']['全31'][s]['sources'][source]['profit_share'] or 0) >= .8 for s in SYMBOLS)]
    # ----------------------------------------
    # 旧38に含まれない同数量G82旧準備対照を、別の既往資料として比較する。
    base = '旧G82_C_QA'
    old_g = read(ROOT/'work/wave_v90/round2/ledgers/G82_C_QA.pkl')
    compare_ledgers = {base: old_g, 'A_G82': {k: v for k, v in all_ledgers['A_G82'].items() if k[0] in fixed['旧30']}}
    arm_difference = OLD.compare(base, 'A_G82', compare_ledgers, {})
    material = OLD.old_material()
    additional = read(WORK/'inputs/material_extra.pkl')
    for field in ('prices', 'grids', 'entries'):
        material[field].update(additional[field])
    states = {name: OLD.diagnostic_state(value, material['entries'][name]) for name, value in material['grids'].items()}
    concrete = {ident: OLD.cases(ident, all_results, all_ledgers, material, states)
                for ident in (fixed['主'], selection['selected'])}
    latest_parents = {}
    for ident in (fixed['主'], selection['selected']):
        latest_parents[ident] = {}
        for symbol in SYMBOLS:
            key = (fixed['追加1'][0], symbol)
            record = material['prices'][key]
            ledger = all_ledgers[ident][key]
            session = material['grids'][key[0]]
            mapping = OLD.row_mapping(record, session['grid'])
            latest_parents[ident][symbol] = [dict(親=int(t[0]), 源='J2' if t[1] == 0 else 'O06',
                方向='買い' if t[4] == 1 else '売り', 枚数=int(t[5]), 純収支円=float(t[11]),
                新規=OLD.point(record, session, states[key[0]], mapping, int(t[2])),
                返済=OLD.point(record, session, states[key[0]], mapping, int(t[3])),
                返済理由=ledger['reasons'][int(t[13])]) for t in ledger['trades']]
    conclusions = [
        '全38・全31で両商品金額利益80%を達成した条件はない。主P_G82_HUNLは日経合計赤字であり、追加Dayの1親黒字を安定改善の証明にしない。',
        '追加Dayの主TOPIXは無取引であり勝ちではない。旧前16参考代表O10_F15はTOPIX黒字・日経赤字だった。参考代表を追加Dayの勝ち条件へ差替えていない。',
        '割合を0.15%に揃えた単純反発は旧前16で選ばれ、全31両黒字でも金額割合は約5割、TOPIX後14は赤字。簡単な共通数式が機械的に使えることと、両商品へ安定した収益機序があることは別。',
        '利益追跡は同一新規の一部負けを勝ちにした。しかし利益3幅を伸ばす元の勝ちを削り、早期返済で基準の再配置が早まり、新固有の経路が大幅赤字になった。利確改善だけでなく次の新規への影響が損失拡大を作った。',
        '時間上限解除は一部大勝ちを伸ばしたが、反対commonが短命又は不成立の間、弱い玉も長く保持した。主の日経で同一新規の勝ち13親が負けへ転じ、既存負けも膨らんだ。',
        '準備保持はほぼ無取引だった往復源を復活させたが、低ERから反発する確率を保証しなかった。古い基準を短期分類0だけで捨てないことは状態管理の修正であり、反発の価格予測力の証明ではない。',
        '高ERを出口から外す構造修正は実行可能だが、双方300秒と双方30秒が同時に逆方向へ続くcommonは依然遅い。短期両気配はもっと早く逆行している具体例がある一方、既往では早い出口が勝ちも削った。現時点で万能な反証出口とは認定しない。'
    ]
    OLD.save('全31の独立会計と部品改修の敵対的結論.json', dict(
        全合格=True, 段階='旧30完了・旧前16選定固定・追加38完了の根担当許可後の閲覧',
        主=fixed['主'], 正式前16参考代表=selection['selected'], 独立選定=reference,
        条件数=38, 追加検算=checks, 追加口座=76,
        追加注文=sum(v['注文'] for v in checks.values()), 追加親=sum(v['親'] for v in checks.values()),
        全31比較={i: r['periods'] for i, r in all_results.items()},
        全31両商品金額80=targets, 全31源単独両商品金額80=source_targets,
        同数量旧準備対照からの保持効果=arm_difference,
        主と参考代表の全31赤字上位3場=concrete, 追加Dayの主と代表全親=latest_parents,
        結論=conclusions, API取得=0, 実注文=0, 凍結変更=0, 参考代表差替え=0,
        全原板時価監査='別担当の全会計監査を参照。ここは独立親会計と既存場別全行時価極値の合算。',
        注意=['最大順行や赤字場の選定は事後診断。注文判断へ逆流させない。',
              '全31は3週と追加Day。単に一週間という名称で範囲を狭めない。',
              '全期間の参考上位を新たな主と呼ばない。旧30の既知探索と追加1場の初回確認を分ける。'],
        固定SHA256=OLD.digest(WORK/'事前固定.json'),
        選定SHA256=OLD.digest(WORK/'前16参考代表.json'),
        計算コードSHA256=OLD.digest(Path(__file__)), 追加成果SHA256=hashes))
    print('追加38の全76口座を独立検算、全31の80%未達と部品反証・具体時刻を保存', flush=True)


if __name__ == '__main__':
    main()
