"""有利指値の未来切断と、成立した親の返済を変更しない性質を検査する。"""

from pathlib import Path
import hashlib
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checks


def fingerprints():
    """
    機能: 取引・人工監査・本切断器の指紋を取得する。
    引数: なし。
    返り値: dict[str,str]。編集中の研究実行器を含めない。
    """
    result = checks.hashes()
    result[str(Path(__file__).relative_to(checks.ROOT))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def same_execution(full, shorter, count):
    """
    機能: 指値成立・取消・次観測返済と、その時点で確定済みの親を切断照合する。
    引数: full/shorter(dict)、count(int)。
    返り値: intの比較配列数。
    """
    total = 0
    for name, column in (('orders', 0), ('trades', 7), ('execution_events', 0), ('limit_events', 0), ('virtual_feed', 0)):
        original = full[name]
        np.testing.assert_array_equal(original[original[:, column] < count], shorter[name], err_msg=name)
        total += 1
    for name in ('curve', 'execution_states'):
        np.testing.assert_array_equal(full[name][:count], shorter[name], err_msg=name)
        total += 1
    np.testing.assert_array_equal(full['order_uids'][:len(shorter['orders'])], shorter['order_uids'])
    finished = {int(c[0]) for c in shorter['core_result']['cycles']}
    expected = np.asarray([c for c in full['cycles'] if c[0] in finished and c[2] < count]).reshape(-1, 10)
    np.testing.assert_array_equal(expected, shorter['cycles'])
    return total + 2


def cut_points(result, length):
    """
    機能: 予約・成立・取消・元部分返済の前後を損益に関係なく選ぶ。
    引数: result(dict)、length(int)。
    返り値: list[int]の切断地点。
    """
    points = {int(length * .37), int(length * .77)}
    for code in (1, 2, 3, 4):
        events = result['limit_events']
        matches = events[events[:, 1] == code]
        chosen = list(matches[:2])
        if len(matches):
            chosen.append(matches[-1])
        for event in chosen:
            i = int(event[0])
            points.update((i, i + 1, i + 2))
    returns = result['virtual_feed'][result['virtual_feed'][:, 7] == 0]
    for event in returns[:2]:
        i = int(event[0])
        points.update((i, i + 1, i + 2))
    return sorted(c for c in points if 2 < c < length)


def main():
    """
    機能: 固定二場・両商品の八幅と無条件対照で未来切断と独立会計を確認する。
    引数: なし。
    返り値: None。全三十場の成績探索や代表選抜は行わない。
    """
    _, previous, fees, _ = checks.load()
    strategy = checks.module('監査87有利指値戦略', checks.WORK / 'strategy.py')
    catalog = checks.module('監査87有利指値条件', checks.WORK / 'catalog.py')
    before = fingerprints()
    helper = checks.module('監査87指値切断道具', checks.ROOT / 'work/wave_v86/audit/support.py')
    prepare = checks.module('監査87指値切断基礎入力', checks.ROOT / 'work/wave_v85/prepare.py')
    inputs, signals, _ = prepare.load_inputs(verify=False)
    selected = {key: inputs[key] for key in [(s, p) for s in ('2026-09-25_Day', '2026-09-28_Night')
                                           for p in ('TOPIX', 'NK225')]}
    features = strategy.initialize(selected, signals)
    configs = [c for c in catalog.catalog() if c['execution_mode'] != 'IDEAL']
    next_config = next(c for c in configs if c['execution_mode'] == 'NEXT')
    records = []
    for key, ready in selected.items():
        feature = features[key]
        baseline, _ = strategy.play(next_config, ready, feature, True)
        source = baseline['core_result']
        quiet = strategy.old.time_filter.features(ready, 'U')
        for config in configs:
            result, settings = strategy.play(config, ready, feature, True)
            helper.compare_prefix(source, result['core_result'], len(ready['last']))
            tally = previous.account(ready, result, fees, settings['audit_cap'])
            evidence = checks.inspect(ready, result, result['virtual_feed'], config['offset_atr'],
                config['execution_mode'] == 'NEXT', quiet['active'], quiet['force'], ready['limit'], baseline)
            cuts = cut_points(result, len(ready['last']))
            checked = 0
            for count in cuts:
                short_ready = helper.clip(ready, count, len(ready['last']))
                short_feature = helper.clip(feature, count, len(ready['last']))
                short, _ = strategy.play(config, short_ready, short_feature, True)
                checked += same_execution(result, short, count)
                checked += helper.compare_prefix(result['core_result'], short['core_result'], count)
                checked += helper.compare_prefix(result['virtual_result'], short['virtual_result'], count)
            records.append(dict(セッション=key[0], 商品=key[1], 条件=config['id'],
                切断地点=len(cuts), 配列照合数=checked, **evidence, **tally))
            print(key, config['id'], len(cuts), '未来切断・元返済不変・料金一致', flush=True)
    assert before == fingerprints()
    checks.save('有利指値待機と元GU不変の未来切断.json', dict(全合格=True,
        条件口座数=len(records), 切断地点=sum(r['切断地点'] for r in records),
        配列照合数=sum(r['配列照合数'] for r in records), 検査=records, コードSHA256=before,
        未完親組='紙上親が未完なら、実玉が空でも将来の親損益として分類しない。',
        切断方法='自己の価格・時刻・全特徴を切り、予約・成立・初返済取消・予定取消の前後を再生。過去の元GUも実注文も一致。',
        入口改善='成立親は無条件次観測と全返済の行・数量・価格・注文料金が同一。料前差額は初回数量×方向×入口価格差のみ。未成立親は利益に数えない。'))
    print('全36口座の未来切断と成立親の同一返済が合格', flush=True)


if __name__ == '__main__':
    main()
