"""正式121条件を再生せず、全8448新台帳と採用判定を独立会計から監査する。"""

import argparse
from copy import deepcopy
from datetime import date, timedelta
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys
import traceback

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WAVE = HERE.parents[1]
ROOT = WAVE.parents[1]
CURRENT = {}
sys.path.insert(0, str(WAVE))


def module(name: str, path: Path) -> object:
    """
    機能: 監査の独立部品と保存cache読取だけを接続する。
    引数: name(str)、path(Path)は固有名とsource。
    返り値: object。金融execute、原本、NPZ、APIは呼ばない。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


COMMON = module('104全数監査の独立入力集計', HERE/'入力と集計の独立部品.py')
LEDGER = module('104全数監査の独立台帳停止線', HERE/'台帳と停止線の独立部品.py')
COUNTS, equal, read, sha = COMMON.COUNTS, COMMON.equal, COMMON.OLD.read, COMMON.OLD.sha


def canonical(value: object) -> str:
    """
    機能: tuple/listの保存差だけを正規化して全configを完全比較する。
    引数: value(object)は確定条件又は掲載条件。
    返り値: strは順序固定JSON。閾値や配分の変更は同一扱いしない。
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def compare_row(actual: dict, expected: dict, label: object) -> None:
    """
    機能: 独立注文会計の全公開行項目を掲載値へ照合する。
    引数: actual/expected(dict)、label(object)は掲載行・独立行・診断。
    返り値: None。源別G/Lを相殺せず比較する。
    """
    for key, value in expected.items():
        if isinstance(value, dict):
            compare_row(actual[key], value, (label, key))
        else:
            equal(actual[key], value, (label, key))


def cohort_sum(values: list[dict]) -> dict:
    """
    機能: 玉会計の相殺前金額と枚数を親集計とは別名で独立合算する。
    引数: values(list[dict])は玉集計。
    返り値: dictは玉の期間会計。
    """
    mapped = []
    pairs = (('cohorts', 'campaigns'), ('winning_cohorts', 'winning_campaigns'),
             ('losing_cohorts', 'losing_campaigns'), ('flat_cohorts', 'flat_campaigns'))
    for value in values:
        row = dict(value)
        for left, right in pairs:
            row[right] = row.pop(left)
        mapped.append(row)
    result = COMMON.sum_rows(mapped)
    for left, right in pairs:
        result[left] = result.pop(right)
    return result


def aggregate_extra(actual: dict, rows: list[dict]) -> None:
    """
    機能: 旧独立期間算式に加え、玉/日/週/最大日除外と最大保有を照合する。
    引数: actual(dict)、rows(list[dict])は掲載期間と独立行。
    返り値: None。最大日と採用の最大セッション除外を混同しない。
    """
    compare_row(actual['cohorts'], cohort_sum([row['cohorts'] for row in rows]), '期間玉')
    for direction in ('買い', '売り'):
        compare_row(actual['cohort_directions'][direction], cohort_sum([row['cohort_directions'][direction] for row in rows]), '方向玉')
    for field in ('order_count', 'entry_order_count', 'adding_order_count'):
        equal(actual[field], sum(row[field] for row in rows), ('期間注文', field))
    for field in actual['maximums']:
        equal(actual['maximums'][field], max((row['maximums'][field] for row in rows), default=0), ('期間最大', field))
    days, weeks = {}, {}
    for row in rows:
        day = date.fromisoformat(row['session'][:10])
        days.setdefault(str(day), []).append(row)
        weeks.setdefault(str(day-timedelta(days=day.weekday())), []).append(row)
    for name, groups in (('days', days), ('weeks', weeks)):
        assert set(actual[name]) == set(groups)
        for key, values in groups.items():
            compare_row(actual[name][key], COMMON.sum_rows(values), (name, key))
            compare_row(actual[name][key]['cohorts'], cohort_sum([row['cohorts'] for row in values]), (name, key, '玉'))
    best = max(days, key=lambda label: COMMON.sum_rows(days[label])['net'], default=None)
    equal(actual['best_day'], best, '期間最大利益日')
    others = [row for row in rows if row['session'][:10] != best]
    compare_row(actual['without_best_day'], COMMON.sum_rows(others), '最大日除外')
    compare_row(actual['without_best_day']['cohorts'], cohort_sum([row['cohorts'] for row in others]), '最大日除外玉')


def join_check(ledger: dict, c: dict, r: dict) -> None:
    """
    機能: 実量腿を再読せず、配分台帳のnamespaceと全玉時価の完全連結を照合する。
    引数: ledger/c/r(dict)は配分と既監査のC/R実量腿。
    返り値: None。全利益と損失、含み損、料金の片方省略を拒否する。
    """
    for field, columns_field in (('orders', 'order_columns'), ('trades', 'trade_columns'),
                                  ('growth_cohorts', 'growth_cohort_columns'), ('events', 'event_columns')):
        assert ledger[columns_field] == c[columns_field] == r[columns_field]
        columns = ledger[columns_field]
        parts = []
        for src, value in enumerate((c, r)):
            result = value[field].copy()
            for name in ('parent_id', 'cohort_id', 'uid', 'order_uid'):
                if name in columns:
                    index = columns.index(name)
                    mask = result[:, index] > 0
                    result[mask, index] = 2*result[mask, index]+src
            if 'source' in columns:
                result[:, columns.index('source')] = src
            parts.append(result)
        expected = np.concatenate(parts)
        key = 'exit_row' if field == 'trades' else 'entry_row' if field == 'growth_cohorts' else 'row'
        if len(expected):
            expected = expected[np.argsort(expected[:, columns.index(key)], kind='stable')]
        np.testing.assert_array_equal(ledger[field], expected)
    np.testing.assert_array_equal(ledger['source_curve'][:, 0], c['curve'])
    np.testing.assert_array_equal(ledger['source_curve'][:, 1], r['curve'])
    np.testing.assert_array_equal(ledger['curve'], c['curve']+r['curve'])
    np.testing.assert_array_equal(ledger['target_trace'], c['trace']+r['trace'])
    expected_diag = []
    for src, (family, value) in enumerate((('C', c), ('R', r))):
        for diagnostic in value['raw_entry_diagnostics']:
            item = deepcopy(diagnostic)
            item.update(parent_id=2*item['parent_id']+src, order_uid=2*item['order_uid']+src, source=src, family=family)
            expected_diag.append(item)
    COMMON.deep(ledger['raw_entry_diagnostics'], expected_diag, '配分原行完全連結')
    COUNTS['実量腿と配分完全連結'] += 1


def load_ledger(item: dict, folder: Path, hashes: dict) -> dict:
    """
    機能: 新台帳bytesを一回だけ読み、同bytesのSHAからpickleへ接続する。
    引数: item(dict)、folder(Path)、hashes(dict)は固定位置、許可領域、読取済み記録。
    返り値: dictは台帳。二重読取又は領域外は拒否する。
    """
    path = ROOT/item['path']
    assert path.resolve().is_relative_to(folder.resolve()) and item['path'] not in hashes
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == item['SHA256']
    hashes[item['path']] = digest
    return pickle.loads(gzip.decompress(data))


def assessment_check(actual: dict, docs: dict, computed: dict) -> dict:
    """
    機能: 事前基準の資格・両商品3非悪化・80・最大場除外・順位を自前で判定する。
    引数: actual/docs/computed(dict)は掲載判定、正式集計、独立会計。
    返り値: dictは独立候補と順位。evaluation.assessは呼ばない。
    """
    results, keys = {}, {}
    for ident, document in docs.items():
        values = {}
        for symbol in ('TOPIX', 'NK225'):
            aggregate = document['periods']['全32'][symbol]
            stability = document['stability']['全32'][symbol]
            baseline = docs['OLD_G0']['stability']['全32'][symbol]
            loss_free = aggregate['loss'] == 0 and aggregate['profit'] > 1e-5 and aggregate['winning_campaigns'] > 0
            eligible = stability['activity_adequate'] and aggregate['net'] > 1e-5 and (loss_free or (aggregate['payoff'] is not None and aggregate['payoff'] > 1))
            share80 = aggregate['profit_share'] is not None and aggregate['profit_share'] >= .8 and aggregate['profit'] > 1e-5
            metrics = ('losing_active_rate', 'downside_rms_units', 'worst_session_loss_units')
            non_worsening = all(stability[key] is not None and baseline[key] is not None and stability[key] <= baseline[key] for key in metrics)
            best_positive = stability['without_best_session_net'] > 1e-5
            facts = actual['results'][ident]['symbols'][symbol]
            for name, wanted in dict(eligible=eligible, zero_loss_positive=loss_free, profit_share_80=share80,
                stability_non_worsening=non_worsening, without_best_session_positive=best_positive,
                net=aggregate['net'], profit=aggregate['profit'], loss=aggregate['loss'], profit_share=aggregate['profit_share'],
                payoff=aggregate['payoff'], active_sessions=stability['active_sessions'], losing_sessions=stability['losing_sessions'],
                no_trade_sessions=stability['no_trade_sessions'], configured_quantity=stability['configured_quantity']).items():
                equal(facts[name], wanted, ('採用商品', ident, symbol, name))
            for key in metrics:
                equal(facts['metrics'][key], stability[key], ('採用指標', key))
            values[symbol] = dict(eligible=bool(eligible), share80=bool(share80), non_worsening=bool(non_worsening), best_positive=bool(best_positive),
                all32=aggregate['all_sessions_profitable'], metrics=[stability[key] for key in metrics], share=aggregate['profit_share'])
        eligible = all(value['eligible'] for value in values.values())
        flags = dict(eligible=eligible, both_profit_share_80=all(value['share80'] for value in values.values()),
            stability_non_worsening=all(value['non_worsening'] for value in values.values()),
            without_best_session_both_positive=all(value['best_positive'] for value in values.values()),
            all32_profitable=all(value['all32'] for value in values.values()))
        flags['adoption_achieved'] = all(flags[key] for key in ('eligible', 'both_profit_share_80', 'stability_non_worsening', 'without_best_session_both_positive'))
        flags['comparison_only'] = ident == 'OLD_G0' or not flags['adoption_achieved']
        for key, value in flags.items():
            equal(actual['results'][ident][key], value, ('採用条件', ident, key))
        if eligible and ident != 'OLD_G0':
            keys[ident] = [max(value['metrics'][i] for value in values.values()) for i in range(3)]+[-min(value['share'] for value in values.values()), ident]
        results[ident] = dict(symbols=values, **flags)
    ranking = sorted(keys, key=lambda ident: tuple(keys[ident]))
    assert actual['ranking'] == ranking
    for rank, ident in enumerate(ranking, 1):
        equal(actual['results'][ident]['rank'], rank, '独立順位')
        COMMON.deep(actual['results'][ident]['rank_key'], keys[ident], '独立順位key')
    for ident in set(docs)-set(ranking):
        assert actual['results'][ident]['rank'] is None and actual['results'][ident]['rank_key'] is None
    candidates = [ident for ident in ranking if results[ident]['adoption_achieved']]
    assert actual['adoption_candidates'] == candidates
    COUNTS['全121採用と順位'] += len(docs)
    return dict(ranking=ranking, adoption_candidates=candidates, results=results)


def plan() -> None:
    """
    機能: 全数監査のscopeと読取回数だけを新source完成時に登録する。
    引数: なし。
    返り値: None。正式結果・台帳・入力cacheは読まない。
    """
    path = HERE/'全121独立監査の計画.json'
    if path.exists():
        path = HERE/'全121独立監査の計画_最終接続.json'
    assert not path.exists()
    value = dict(状態='正式全32完了通知後に一回だけ起動する。', scope='掲載7744口座=新7680+旧64委譲、追加実腿768、全8448新台帳。',
        読取=dict(base=1, 新104prepared=32, 旧103activity=32, 新台帳=8448, 生原本=0, NPZ=0, API=0),
        検査=['全config完全一致', 'Decimal注文料/次正常quote/親と一玉', '全curve/source/予約6列と末尾flat',
            '全19入口とrawseq/map/実旧state段階/strictpast相手窓', 'B/T全因果判断と当時support',
            '12実腿と6配分namespace全連結', '商品内G/L/normalized3指標/最大場除外/事前資格と順位'],
        SHA256={str(path.relative_to(ROOT)): sha(path) for path in (Path(__file__), HERE/'入力と集計の独立部品.py', HERE/'台帳と停止線の独立部品.py')},
        正式金融再生=0, 正式監査本実行=0, goal操作=0)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(計画保存=True, SHA256=sha(path)), ensure_ascii=False))


def run() -> None:
    """
    機能: 根の正式完了許可後だけ、全8448新台帳と全121掲載結果を一回監査する。
    引数: なし。CLIの明示完了フラグをmainが要求する。
    返り値: None。独立結果証跡を保存する。正式再生とcounterfactualは0。
    """
    destination = HERE/'全121条件と全32セッションの独立金融監査.json'
    assert not destination.exists()
    final, fixed = read(WAVE/'金融全32の結果.json'), read(WAVE/'金融事前固定.json')
    assert final['全合格'] and fixed['全合格'] and final['sessions'] == fixed['sessions'] and final['source_SHA256'] == fixed['source_SHA256']
    assert len(fixed['catalog']) == 121 and len(fixed['sessions']) == 32
    for name, wanted in fixed['source_SHA256'].items():
        assert sha(ROOT/name) == wanted, name
    docs = {}
    for config in fixed['catalog']:
        item = final['results'][config['id']]
        assert sha(ROOT/item['path']) == item['SHA256']
        docs[config['id']] = read(ROOT/item['path'])
        assert canonical(docs[config['id']]['config']) == canonical(config)
    base = module('104独立監査の不変素材読取', WAVE/'base.py')
    prepared = base.load_prepared()
    COUNTS['base一回読取'] += 1
    fresh = module('104独立監査の新prepared読取', WAVE/'prepared_data.py')
    activity = module('104独立監査の旧state読取', ROOT/'work/wave_v103/activity/data.py')
    old_rows = {(row['session'], row['symbol']): row for row in read(ROOT/'work/wave_v103/finance/results/OLD_G0.json')['rows']}
    assert len(old_rows) == 64
    old_audit = read(ROOT/'work/wave_v103/review/finance_audit/全19条件と全32セッションの独立金融監査.json')
    assert old_audit['全合格'] and old_audit['検査件数']['旧対照委譲口座'] == 64
    refs = {session+'|'+symbol: dict(ref_open=dict(value=value['reference_open'])) for (session, symbol), value in prepared.items()}
    entries = []
    for config in fixed['catalog']:
        if config['kind'] == 'single' and config['exit_id'] == 'O':
            entries.append(dict(id=config['entry_id'], family=config['family'], gate=config['gate']))
    assert len(entries) == 19
    computed, hashes = {config['id']: [] for config in fixed['catalog']}, {}
    for session in fixed['sessions']:
        CURRENT.update(セッション=session)
        packet, original = fresh.load_session(session), activity.load_session(session)
        COUNTS['104prepared一場読取'] += 1
        COUNTS['103activity一場読取'] += 1
        contexts = COMMON.check_prepared(packet, original, prepared, entries, session)
        session_doc = read(WAVE/'finance/session'/(session+'.json'))
        for symbol in ('TOPIX', 'NK225'):
            context, legs = contexts[symbol], {}
            for key, item in final['extra_legs'][session].items():
                market, component, exit_id, qty = key.split('|')
                if market != symbol:
                    continue
                CURRENT.update(銘柄=symbol, 条件=key)
                assert item == session_doc['extra_legs'][key]
                ledger = load_ledger(item, WAVE/'finance/legs', hashes)
                cfg = dict(id=component+'_'+exit_id+'_Q'+qty, kind='single', entry_id=component, exit_id=exit_id, quantity={symbol: int(qty)})
                assert ledger['entry_id'] == component and ledger['configured_quantity'] == int(qty) and ledger['exit_id'] == exit_id
                _, connection = LEDGER.audit(ledger, context, cfg)
                legs[component, exit_id, int(qty)] = connection
                COUNTS['追加実量腿'] += 1
            assert len(legs) == 12
            for config in fixed['catalog']:
                ident = config['id']
                CURRENT.update(銘柄=symbol, 条件=ident)
                listed = [row for row in docs[ident]['rows'] if row['session'] == session and row['symbol'] == symbol]
                assert len(listed) == 1
                listed = listed[0]
                assert listed in session_doc['cases'][ident]['rows']
                if config['kind'] == 'previous':
                    assert listed == old_rows[session, symbol]
                    independent = dict(listed)
                    COUNTS['旧対照委譲口座'] += 1
                else:
                    item = docs[ident]['ledgers'][session+'|'+symbol]
                    assert item == session_doc['cases'][ident]['ledgers'][session+'|'+symbol]
                    ledger = load_ledger(item, WAVE/'finance/ledger', hashes)
                    assert ledger['exit_id'] == config['exit_id']
                    expected_quantity = sum(config['allocations'][symbol]) if config['kind'] == 'portfolio' else config['quantity'][symbol]
                    assert ledger['configured_quantity'] == expected_quantity
                    if config['kind'] == 'portfolio':
                        components, allocation = config['components'], config['allocations'][symbol]
                        join_check(ledger, legs[components[0], config['exit_id'], allocation[0]], legs[components[1], config['exit_id'], allocation[1]])
                        assert ledger['entry_id'] is None
                    else:
                        assert ledger['entry_id'] == config['entry_id']
                    independent, _ = LEDGER.audit(ledger, context, config)
                    compare_row(listed, independent, (session, ident, symbol))
                    independent.update(session=session, symbol=symbol)
                    COUNTS['新掲載口座'] += 1
                computed[ident].append(independent)
            del legs
        print(session+' 全121掲載と24追加腿の独立監査完了', flush=True)
        del packet, original, contexts
    for config in fixed['catalog']:
        document = docs[config['id']]
        for label, sessions in (('前16', fixed['sessions'][:16]), ('後16', fixed['sessions'][16:]), ('全32', fixed['sessions'])):
            for symbol in ('TOPIX', 'NK225'):
                rows = [row for session in sessions for row in computed[config['id']] if row['session'] == session and row['symbol'] == symbol]
                COMMON.aggregate_check(document['periods'][label][symbol], rows, (config['id'], label, symbol))
                aggregate_extra(document['periods'][label][symbol], rows)
                COMMON.stable_check(document['stability'][label][symbol], rows, config, refs, symbol)
    evaluated = read(WAVE/'安定性の全121判定.json')
    independent_evaluation = assessment_check(evaluated, docs, computed)
    assert COUNTS['全新台帳'] == len(hashes) == 8448 and COUNTS['追加実量腿'] == 768 and COUNTS['新掲載口座'] == 7680
    assert COUNTS['旧対照委譲口座'] == 64 and COUNTS['104prepared一場読取'] == COUNTS['103activity一場読取'] == 32 and COUNTS['base一回読取'] == 1
    for name, wanted in fixed['source_SHA256'].items():
        assert sha(ROOT/name) == wanted, name
    result = dict(全合格=True, scope='全121×64掲載会計7744、新7680台帳と追加実腿768を一回ずつ独立監査。旧64は既検算会計へ委譲。',
        検査件数=dict(COUNTS), 独立採用と順位=independent_evaluation, 全8448新台帳SHA256=hashes,
        SHA256={str(path.relative_to(ROOT)): sha(path) for path in (Path(__file__), HERE/'入力と集計の独立部品.py',
            HERE/'台帳と停止線の独立部品.py', WAVE/'金融事前固定.json', WAVE/'金融全32の結果.json', WAVE/'安定性の全121判定.json')},
        事前固定sourceSHA256=fixed['source_SHA256'], 旧対照由来='103全32独立監査及び新O128口座経済nullへ委譲。Oの全物理現金と全時価は新台帳から別に監査。',
        正式金融再実行=0, counterfactual生成=0, 原本読取=0, NPZ読取=0, API取得=0, 実注文=0, goal操作=0,
        限界='全32既知。価格時計は受信時刻ではない。配置予算単位は実リスク等価ではなく、無活動を勝ちにしない。')
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=dict(COUNTS), SHA256=sha(destination)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        choice = parser.add_mutually_exclusive_group(required=True)
        choice.add_argument('--plan', action='store_true')
        choice.add_argument('--root-results-complete', action='store_true')
        options = parser.parse_args()
        plan() if options.plan else run()
    except Exception as error:
        i = 1
        while (HERE/f'独立監査False_{i:05d}.json').exists():
            i += 1
        (HERE/f'独立監査False_{i:05d}.json').write_text(json.dumps(dict(全合格=False, 対象=CURRENT, 例外=str(error),
            traceback=traceback.format_exc(), 完了検査件数=dict(COUNTS), sourceSHA256=sha(Path(__file__)),
            正式金融再生=0, 原本読取=0, NPZ読取=0, API取得=0, goal操作=0), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise
