"""固定追加一場の主だけで、実接頭に必要な待機・初回fill・追加fillの到達範囲を調べる。"""

import argparse
import hashlib
import json
from pathlib import Path

import numba
import numpy as np

import prefix


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
DESTINATION = HERE / '追加固定0930Nightの主の待機と実追加カバー診断.json'
SESSIONS = ('2026-09-30_Night',)


def main() -> None:
    """
    機能: 主の追加固定一場両商品を場末10分前までだけ再生し、売買状態の到達を保存する。
    引数: なし。--root-coverage-readyはrootがカバー診断の実行を明示許可したことを示す。
    返り値: None。収益額、最大順行又は全セッション順位を使って検査場を選ばない。
    """
    parser = argparse.ArgumentParser(description='実接頭に必要な状態のカバー不足だけを調べる。')
    parser.add_argument('--root-coverage-ready', action='store_true')
    args = parser.parse_args()
    if not args.root_coverage_ready:
        raise RuntimeError('カバー診断の再生にもrootの明示許可が必要です。')
    assert not DESTINATION.exists(), '診断結果を上書きしません。'
    assert not (WORK / '事前固定.json').exists()
    for stage in ('front', 'back'):
        assert not list((WORK / stage / 'results').glob('*.json'))
        assert not list((WORK / stage / 'ledgers').glob('*.pkl'))
    paths = [Path(__file__), *prefix.EXECUTION_PATHS]
    beginning = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    data = prefix.common.module('102カバー診断の保存入力', WORK / 'data.py')
    strategy = prefix.common.module('102カバー診断の不変本体', WORK / 'strategy.py')
    catalog = prefix.common.module('102カバー診断の20条件', WORK / 'catalog.py')
    numba.config.CACHE_DIR = prefix.CACHE
    configs = {value['id']: value for value in catalog.catalog()}
    material = data.load_inputs()
    prepared = strategy.prepare(material, configs['G0_QFULL_X1'])
    cases = []
    for session in SESSIONS:
        for symbol in catalog.SYMBOLS:
            key = session, symbol
            value = prepared[key]
            record = value['record']
            horizon = record['limit'] - 600.
            cut = int(np.searchsorted(record['time_s'], horizon, side='right'))
            assert 0 < cut < len(record['time_s']) - 50
            output = strategy.play(configs[prefix.PRIMARY], key,
                                   {key: prefix.shorten(value, cut)}, finish=False)
            watch_rows = np.flatnonzero(output['watch_state_trace'][:, 0] != 0)
            cohorts = output['growth_cohorts']
            initial = cohorts[cohorts[:, 23] == 0]
            additions = cohorts[cohorts[:, 23] == 1]
            gate = output['growth_gate_state_trace']
            case = dict(条件=prefix.PRIMARY, 場=session, 商品=symbol, 原行境界=cut,
                部分再生の最終価格時計=float(record['time_s'][cut - 1]),
                待機原行数=int(len(watch_rows)),
                最初の待機原行=int(watch_rows[0]) if len(watch_rows) else None,
                初回実fill原行=initial[:, 8].astype(int).tolist(),
                追加実fill原行=additions[:, 8].astype(int).tolist(),
                基本追加資格行数=int(np.count_nonzero(gate[:, 13] == 1)),
                基本資格があり新余裕で拒否行数=int(np.count_nonzero((gate[:, 13] == 1) & (gate[:, 10] == 0))),
                新追加予約資格行数=int(np.count_nonzero(gate[:, 14] == 1)))
            cases.append(case)
            print(json.dumps(case, ensure_ascii=False), flush=True)
    ending = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert beginning == ending
    proof = dict(診断終了=True, 検査合格の意味ではない=True, 固定場=list(SESSIONS),
        代表の変更=0, 各例=cases, 完結した102口座=0, 正式102損益実行=0, API取得=0, 実注文=0,
        利益損失集計=0, 将来の利益額による場又は条件の選定=0,
        範囲='追加固定一場と主だけ。場末10分前までの部分再生で、接頭に必要な実状態の到達を確認する。19門番又は未来不変の追加合格に代用しない。',
        開始と終端の全依存SHA一致=True, 開始SHA256=beginning, SHA256=ending)
    DESTINATION.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert json.loads(DESTINATION.read_text(encoding='utf-8')) == proof


if __name__ == '__main__':
    main()
