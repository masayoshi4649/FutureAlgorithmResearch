"""初回の実追加カバー不足を、固定二場の主の待機・実初回・余裕拒否で補完する。"""

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
PLAN = HERE / '実追加未到達後の固定二場主の補完計画.json'
REACH = HERE / '固定二場の主の部分接頭における待機と実追加のカバー診断.json'
DESTINATION = HERE / '固定二場主の待機初回fillと余裕拒否の独立19列及び未来源補完.json'


def main() -> None:
    """
    機能: 主の固定二場両商品の意味別3接頭を、19列独立算定と6未来改変で比較する。
    引数: なし。--root-supplement-readyはrootの追加計画承認を示す。
    返り値: None。実追加は未到達のまま記録し、存在しない実追加カバーを認定しない。
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
    assert plan['新正式102損益'] == 0 and plan['新検査接頭数'] == 12
    reach = json.loads(REACH.read_text(encoding='utf-8'))
    assert reach['診断終了'] and all(not case['追加実fill原行'] for case in reach['各例'])
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
                  自己BBO未来=0, 相手BBO未公開=0, 待機直後=0, 初回実fill直後=0, 余裕拒否直後=0,
                  実追加を含む接頭=0)
    for case in reach['各例']:
        key = case['場'], case['商品']
        value = prepared[key]
        record = value['record']
        probe = strategy.play(config, key, {key: prefix.shorten(value, case['原行境界'])}, finish=False)
        gate = probe['growth_gate_state_trace']
        reject = np.flatnonzero((gate[:, 13] == 1) & (gate[:, 10] == 0))
        assert len(reject) and not np.any(probe['growth_cohorts'][:, 23] == 1)
        cuts = ((case['最初の待機原行'] + 1, '待機直後'),
                (case['初回実fill原行'][0] + 1, '初回実fill直後'),
                (int(reject[0]) + 1, '余裕拒否直後'))
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
            if reason == '待機直後':
                assert short['watch_state_trace'][-1, 0] != 0
            elif reason == '初回実fill直後':
                assert len(short['growth_cohorts']) == 1 and short['growth_cohorts'][0, 8] == cut - 1
            else:
                assert short['growth_gate_state_trace'][-1, 13] == 1 and short['growth_gate_state_trace'][-1, 10] == 0
            counts[reason] += 1
            counts['接頭'] += 1
            counts['実追加を含む接頭'] += int(np.any(short['growth_cohorts'][:, 23] == 1))
            samples.append(dict(条件=prefix.PRIMARY, 場=key[0], 商品=key[1], 切断理由=reason,
                                原行境界=cut, 最終価格時計=float(piece['record']['time_s'][-1])))
        print(prefix.PRIMARY + '/' + key[0] + '/' + key[1] + ': 意味別3接頭の独立19列と6未来源不変が一致', flush=True)
    assert counts['商品場'] == counts['待機直後'] == counts['初回実fill直後'] == counts['余裕拒否直後'] == 4
    assert counts['接頭'] == counts['独立oracle'] == 12 and counts['実追加を含む接頭'] == 0
    for counter in ('自己LP未来', '相手LP未来', '自己LP同clock後続', '相手LP同clock後続', '自己BBO未来', '相手BBO未公開'):
        assert counts[counter] == 12
    ending = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert beginning == ending
    proof = dict(全合格=True, 検査件数=counts, 検査例=samples,
        範囲='主の固定二場両商品の待機・最初の実初回fill・新1S余裕拒否の意味別12接頭だけ。別19gateは独立Fractionで全行全列比較。旧70/74と実cohort25/完了親24及び旧経済/支持59/入口cap20/21は過去比較。',
        未検証='この固定二場の主には実追加がない。実データで主追加fillの過去接頭は本補完でも未認定。人工の実追加/不利fill検査とは別の限界として残す。',
        初回の記録不足='初回16商品場の一致出力はあるが、失敗JSONに詳細件数と接頭例がないため48接頭を本補完の認定件数へ足さない。',
        真受信順='CurrentPriceTimeと固定I3 source indexの検査。真の両市場受信順は未証明。',
        開始と終端の全依存SHA一致=True, 開始SHA256=beginning, SHA256=ending,
        完結した102口座=0, 正式102損益実行=0, API取得=0, 実注文=0)
    DESTINATION.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert json.loads(DESTINATION.read_text(encoding='utf-8')) == proof


if __name__ == '__main__':
    main()
