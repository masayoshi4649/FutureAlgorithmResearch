"""完備判定が欠落・未来混入・偽集計・準備接続の破壊を拒否する人工検査。"""
from copy import deepcopy
import hashlib
import numpy as np
import completion_guard as guard
import conditional_assessment_test as fixtures
import conditional_engine_audit as engine_audit
import supplementary_diagnostics


def main() -> None:
    """機能: 人工資料を一箇所ずつ破損させ、全件完備の誤表示を防ぐ。

    引数: なし。返り値: なし (None)。実相場損益・現在保存物を読まない。
    """
    cases = []
    def rejected(label: str, function) -> None:
        """機能: 人工破損がAssertionError又はKeyErrorで拒否されることを確認する。

        引数: label (str)、function (callable)。返り値: なし (None)。
        """
        try:
            function()
        except (AssertionError, KeyError):
            cases.append({'検査': label, '一致': True})
            return
        raise AssertionError('破損を受理: ' + label)
    rejected('全明細の重複拒否', lambda: guard.unique([{'id': 'x'}, {'id': 'x'}], ('id',)))
    rejected('必須保存項目欠落拒否', lambda: guard.subset({'a': 1}, {'a': 1, 'b': 2}, '人工'))
    rejected('非有限数値拒否', lambda: guard.close(float('nan'), 1., '人工'))
    # ----------------------------------------
    # 速度改訂によって旧版や別規則の明細を完成品へ混在させない。
    version = {'id': '人工', '値': [1., 2.], '監査版': 2, '監査固定SHA256': 'a' * 64, '旧版実体同値': True}
    assert guard.versioned_body(version, 'a' * 64) == {'id': '人工', '値': [1., 2.]}
    cases.append({'検査': '新版メタデータだけ除き旧実体と比較する', '一致': True})
    corrupted = deepcopy(version); corrupted.pop('監査版')
    rejected('旧版明細の混在拒否', lambda: guard.versioned_body(corrupted, 'a' * 64))
    corrupted = deepcopy(version); corrupted['監査版'] = 1
    rejected('監査版の偽装拒否', lambda: guard.versioned_body(corrupted, 'a' * 64))
    rejected('別固定SHAの明細拒否', lambda: guard.versioned_body(version, 'b' * 64))
    corrupted = deepcopy(version); corrupted['旧版実体同値'] = False
    rejected('旧版不一致の明細拒否', lambda: guard.versioned_body(corrupted, 'a' * 64))
    summaries, details, _, training = fixtures.synthetic()
    name = 'H019__B00__V000'; rows = details[name]
    inputs = {(r['session'], r['symbol']): {'last': np.ones(2), 'time_s': np.array([r['completed_at'] - 1, r['completed_at']]), 'limit': r['completed_at'] - .1} for r in rows}
    import conditional_accounting_audit as independent
    for value in training.values():
        for r in value:
            for field in independent.SESSION_FIELDS:
                r.setdefault(field, 0)
    for r in rows:
        for field in independent.SESSION_FIELDS:
            r.setdefault(field, 0)
    initial = {k for k in inputs if k[0] in guard.design.SESSIONS[:6]}
    guard.stage_rows(training[name], name, initial, inputs)
    cases.append({'検査': '人工初期6の正確な12行を受理', '一致': True})
    bad = deepcopy(training[name]); bad[0].pop('first_entry_min')
    rejected('主側の必須保存字段欠落拒否', lambda: guard.stage_rows(bad, name, initial, inputs))
    rejected('初期6への後半混入拒否', lambda: guard.stage_rows(rows, name, initial, inputs))
    rejected('初期区間欠落拒否', lambda: guard.stage_rows(training[name][:-1], name, initial, inputs))
    bad = deepcopy(training[name]); bad[0]['complete'] = False
    rejected('未完了区間拒否', lambda: guard.stage_rows(bad, name, initial, inputs))
    bad = deepcopy(training[name]); bad[0]['completed_at'] += 100.
    rejected('完了時刻偽装拒否', lambda: guard.stage_rows(bad, name, initial, inputs))
    for mode in ('A0', 'MIN', 'B00', 'B11'):
        views = guard.chart_views(mode, inputs)
        assert len(views) == 104 and len(set(views.values())) == (78 if mode.startswith('B') else 52)
        assert all(v.startswith('H019__A0__') for k, v in views.items() if k.split('|')[0] == 'POLICY' and k.split('|')[1] in guard.design.SESSIONS[:6])
    cases.append({'検査': '104表示と固有52又は78、初期A0参照を区別', '一致': True})
    # ----------------------------------------
    # 人工注文を実際の保存形式へ変換し、準備と全組対応の破損を検査する。
    ready, entry, config, tracking = engine_audit.base.fixture([100., 101., 120., 110., 110.], tracking=[4., 4., 4., 2., 2.])
    bad_direction = np.zeros(len(entry), np.int8); bad_direction[3] = -1
    shadow, actual, allow = engine_audit.paired(ready, entry, config, tracking, bad_direction, 2)
    shadow_record = {**guard.runner.stored_result(shadow), 'result_fingerprints': guard.runner.fingerprints(shadow)}
    record = {**guard.runner.stored_result(actual), 'shadow': shadow_record, 'config': config,
        'result_fingerprints': guard.runner.fingerprints(actual), 'prepare_allow_SHA256': hashlib.sha256(allow.tobytes()).hexdigest()}
    control, pairs = guard.runner.control_metrics(actual, shadow_record, config, ready['time_s'])
    row = {'control': control, 'exit_pairs': pairs, 'cycles': len(actual['cycles']), 'opening_orders': len(actual['entry_preparations'])}
    guard.preparation_and_pairs(record, row, ready, {'width_mode': 2})
    assert any(v is None for e in record['trail_events'] for v in e)
    cases.append({'検査': '人工約定とnull保存の指紋、影と実全新規一致を受理', '一致': True})
    corrupted = deepcopy(record); corrupted['prepare_allow_SHA256'] = '0' * 64
    rejected('影許可指紋破壊拒否', lambda: guard.preparation_and_pairs(corrupted, row, ready, {'width_mode': 2}))
    corrupted = deepcopy(row); corrupted['exit_pairs'][0]['actual_exit_row'] += 1
    rejected('全組退出対応偽装拒否', lambda: guard.preparation_and_pairs(record, corrupted, ready, {'width_mode': 2}))
    corrupted = deepcopy(row); corrupted['control']['additional_advance_events'] += 1
    rejected('短縮進行件数偽装拒否', lambda: guard.preparation_and_pairs(record, corrupted, ready, {'width_mode': 2}))
    corrupted = deepcopy(record); corrupted['trail_events'][0][6] = None
    rejected('許可以外の追跡価格欠測拒否', lambda: guard.preparation_and_pairs(corrupted, row, ready, {'width_mode': 2}))
    corrupted = deepcopy(record); corrupted['entry_preparations'][0][3] += 1
    rejected('新規準備起点破壊拒否', lambda: guard.preparation_and_pairs(corrupted, row, ready, {'width_mode': 2}))
    # ----------------------------------------
    # 補助64はseed全件を維持し、偽の最良値や欠落を受理しない。
    index = guard.unique(summaries, ('id',)); specs = supplementary_diagnostics.catalog('B00')
    extras = { (s['id'],): {**deepcopy(index['H019__B00__V000',]), 'id': s['id'], 'spec': s} for s in specs }
    randoms = [index['H019__B00__R000',]] + [extras[s['id'],] for s in specs if s['random_seed'] is not None]
    reverse = extras['H019__B00__REV0',]
    expected = {}
    for period in ('all_symbols', 'symbols'):
        expected[period] = {}
        for symbol in guard.assessment.SYMBOLS:
            source = index['H019__B00__V000',][period][symbol]; values = [r[period][symbol]['net_yen'] for r in randoms]
            expected[period][symbol] = {'元条件': source, '乱数64収支中央値円': float(np.median(values)),
                '乱数64収支最小円': min(values), '乱数64収支最大円': max(values),
                '元条件より黒字額が大きい本数': 0, '元条件と同じ収支本数': 64,
                '反転条件': reverse[period][symbol], '乱数全64': [{'id': r['id'], '成績': r[period][symbol]} for r in randoms]}
    supplemental = {'適用': True, '条件数': 64, '全入力数': 1664, '全波数': 512,
        '条件IDs': [s['id'] for s in specs], '採用変更': False, '正式p値': False,
        '基準seed0 ID': 'H019__B00__R000', '集計': expected}
    guard.supplementary_summary(supplemental, specs, index, extras, 'B00')
    cases.append({'検査': '乱数seed0と補助63、反転1を分離して受理', '一致': True})
    corrupted = deepcopy(supplemental); corrupted['集計']['symbols']['TOPIX']['乱数64収支中央値円'] += 1
    rejected('乱数分布偽要約拒否', lambda: guard.supplementary_summary(corrupted, specs, index, extras, 'B00'))
    corrupted = deepcopy(specs); corrupted[0]['random_seed'] = 2
    rejected('seed重複と欠落拒否', lambda: guard.supplementary_summary(supplemental, corrupted, index, extras, 'B00'))
    corrupted = deepcopy(supplemental); corrupted['条件IDs'].pop()
    rejected('補助条件不足拒否', lambda: guard.supplementary_summary(corrupted, specs, index, extras, 'B00'))
    empty = {'適用': False, '条件数': 0, '全入力数': 0, '全波数': 0, '条件IDs': [],
        '採用変更': False, '正式p値': False, '基準seed0 ID': None, '集計': {}}
    guard.supplementary_summary(empty, [], index, {}, 'A0')
    cases.append({'検査': '条件不使用時の補助不適用を明示', '一致': True})
    result = {'全検査合格': True, '検査数': len(cases), '検査': cases, '採否条件変更': False,
        '実相場売買再生': False, '現在保存物使用': False, 'API取得数': 0,
        'ガード実装SHA256': guard.design.digest(guard.HERE / 'completion_guard.py')}
    guard.runner.save(guard.HERE / 'completion_guard_test.json', result)
    print('完備ガード人工検査', len(cases), '件合格。')


if __name__ == '__main__':
    main()
