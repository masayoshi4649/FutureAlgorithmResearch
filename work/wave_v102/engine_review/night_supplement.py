"""追加固定一場の主の最初の実追加直後を、独立19列と未来不変で補完する。"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numba
import numpy as np

import prefix


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PLAN = HERE / '追加固定0930Nightの最初の実追加接頭計画.json'
REACH = HERE / '追加固定0930Nightの主の待機と実追加カバー診断.json'
DESTINATION = HERE / '追加固定0930Nightの主の実追加接頭と独立19列及び未来源不変.json'


def main() -> None:
    """
    機能: 追加固定一場の主の最初の実追加直後だけを、19列独立算定と6未来改変で比較する。
    引数: なし。--root-supplement-readyはrootの追加計画承認を示す。
    返り値: None。主の両商品の実追加接頭2件を検査し、その他の追加実fillを認定しない。
    """
    parser = argparse.ArgumentParser(description='固定二場の主の意味別接頭を補完する。')
    parser.add_argument('--root-supplement-ready', action='store_true')
    args = parser.parse_args()
    if not args.root_supplement_ready:
        raise RuntimeError('補完接頭もrootが追加計画を明示承認した後だけ実行できます。')
    assert not DESTINATION.exists() and not (WORK / '事前固定.json').exists()
    for stage in ('front', 'back'):
        assert not list((WORK / stage / 'results').glob('*.json'))
        assert not list((WORK / stage / 'ledgers').glob('*.pkl'))
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    assert plan['新正式102損益'] == 0 and plan['新検査接頭数'] == 2
    reach = json.loads(REACH.read_text(encoding='utf-8'))
    assert reach['診断終了'] and all(case['追加実fill原行'] for case in reach['各例'])
    for name, expected in plan['SHA256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    paths = [Path(__file__), PLAN, REACH, *prefix.EXECUTION_PATHS]
    beginning = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    data = prefix.common.module('102固定補完の保存入力', WORK / 'data.py')
    strategy = prefix.common.module('102固定補完の不変本体', WORK / 'strategy.py')
    catalog = prefix.common.module('102固定補完の20条件', WORK / 'catalog.py')
    numba.config.CACHE_DIR = prefix.CACHE
    configs = {value['id']: value for value in catalog.catalog()}
    config = configs[prefix.PRIMARY]
    material = data.load_inputs()
    prepared = strategy.prepare(material, configs['G0_QFULL_X1'])
    samples = []
    counts = dict(商品場=0, 接頭=0, 独立oracle=0, 独立gate行=0, 独立gate列=19,
                  自己LP未来=0, 相手LP未来=0, 自己LP同clock後続=0, 相手LP同clock後続=0,
                  自己BBO未来=0, 相手BBO未公開=0, 最初実追加直後=0,
                  実追加を含む接頭=0)
    for case in reach['各例']:
        key = case['場'], case['商品']
        value = prepared[key]
        record = value['record']
        probe = strategy.play(config, key, {key: prefix.shorten(value, case['原行境界'])}, finish=False)
        filled = probe['growth_cohorts'][probe['growth_cohorts'][:, 23] == 1]
        assert len(filled) and int(filled[0, 8]) == case['追加実fill原行'][0]
        cuts = ((case['追加実fill原行'][0] + 1, '最初実追加直後'),)
        counts['商品場'] += 1
        for cut, reason in cuts:
            assert 0 < cut < case['原行境界'] and cut + 50 < len(record['time_s'])
            piece = prefix.shorten(value, cut)
            short = strategy.play(config, key, {key: piece}, finish=False)
            prefix.support_oracle.verify_material(key, material, piece)
            oracle = prefix.independent.compare(piece, config, short)
            prefix.financial.verify_account(piece['record'], config, short, complete=False)
            assert oracle['独立追加門番列'] == 19
            counts['独立oracle'] += 1
            counts['独立gate行'] += oracle['独立追加門番行']
            longer_value = prefix.shorten(value, cut + 50)
            longer = strategy.play(config, key, {key: longer_value}, finish=False)
            prefix.compare_past(short, longer, cut, prefix.PRIMARY + '/' + reason)
            for symbol, mode, counter in ((key[1], 'future', '自己LP未来'),
                    ('NK225' if key[1] == 'TOPIX' else 'TOPIX', 'future', '相手LP未来'),
                    (key[1], 'sameclock', '自己LP同clock後続'),
                    ('NK225' if key[1] == 'TOPIX' else 'TOPIX', 'sameclock', '相手LP同clock後続')):
                modified, changed = prefix.poison_lp(material, key, longer_value, symbol,
                    piece['record']['time_s'][-1], mode, strategy)
                assert changed > 0
                output = strategy.play(config, key, {key: modified}, finish=False)
                prefix.compare_past(short, output, cut, reason + '/' + counter)
                counts[counter] += 1
            for own, counter in ((True, '自己BBO未来'), (False, '相手BBO未公開')):
                modified = prefix.poison_bbo(longer_value, cut, own)
                output = strategy.play(config, key, {key: modified}, finish=False)
                prefix.compare_past(short, output, cut, reason + '/' + counter)
                counts[counter] += 1
            fills = short['growth_cohorts'][short['growth_cohorts'][:, 23] == 1]
            assert len(fills) == 1 and fills[0, 8] == cut - 1
            assert short['growth_gate_state_trace'][-1, 15] > 0
            counts[reason] += 1
            counts['接頭'] += 1
            counts['実追加を含む接頭'] += int(np.any(short['growth_cohorts'][:, 23] == 1))
            samples.append(dict(条件=prefix.PRIMARY, 場=key[0], 商品=key[1], 切断理由=reason,
                                原行境界=cut, 最終価格時計=float(piece['record']['time_s'][-1])))
        print(prefix.PRIMARY + '/' + key[0] + '/' + key[1] + ': 最初の実追加接頭の独立19列と6未来源不変が一致', flush=True)
    assert counts['商品場'] == counts['最初実追加直後'] == 2
    assert counts['接頭'] == counts['独立oracle'] == 2 and counts['実追加を含む接頭'] == 2
    for counter in ('自己LP未来', '相手LP未来', '自己LP同clock後続', '相手LP同clock後続', '自己BBO未来', '相手BBO未公開'):
        assert counts[counter] == 2
    ending = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert beginning == ending
    proof = dict(全合格=True, 検査件数=counts, 検査例=samples,
        範囲='追加固定09/30Nightの主の両商品の最初の実追加直後2接頭だけ。別19gateは独立Fractionで全行全列比較。旧70/74と実cohort25/完了親24及び旧経済/支持59/入口cap20/21は過去比較。',
        未検証='本追加固定一場の主の最初の実追加だけを検査する。全31場全追加fillの未来不変又は真受信順を認定しない。元固定二場の主の実追加は0。',
        初回の記録不足='初回16商品場の一致出力はあるが、失敗JSONに詳細件数と接頭例がないため48接頭を本補完の認定件数へ足さない。',
        真受信順='CurrentPriceTimeと固定I3 source indexの検査。真の両市場受信順は未証明。',
        開始と終端の全依存SHA一致=True, 開始SHA256=beginning, SHA256=ending,
        完結した102口座=0, 正式102損益実行=0, API取得=0, 実注文=0)
    DESTINATION.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert json.loads(DESTINATION.read_text(encoding='utf-8')) == proof


if __name__ == '__main__':
    main()
