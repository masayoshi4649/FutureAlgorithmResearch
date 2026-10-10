"""三反復の探索全体を含め、同じ開始日の損益符号を共通に反転する参考対照。"""

from __future__ import annotations

from datetime import datetime
import argparse
import itertools
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'wave_v25'))
import discovery_runner as runner

PHASES = ['wave_v25', 'wave_v26', 'wave_v27']
SYMBOLS = ['TOPIX', 'NK225']


def freeze() -> dict:
    """機能: 探索全体を含む対照の統計量と限界を、第三反復の結果前に固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    rule = {'対象': PHASES, '単位': '各セッションのnet_rを開始日ごとに加算。両銘柄は合算しない。',
            '統計量': '銘柄ごとに日別Rの合計÷日別R二乗和の平方根。二銘柄の小さい方をその手法の値とする。全日ゼロは0。',
            '対照': '全開始日について±1の全組合せ。ある開始日の符号は、全手法と両銘柄の損益に共通に掛ける。',
            '探索効果': '各符号組合せで、全探索手法中の最大値を求める。上位だけや合格だけへ母集団を絞らない。',
            '選抜禁止': 'この診断の首位へ主候補を変更しない。判定基準の緩和・再最適化に用いない。',
            '解釈': '少ない開始日と多数探索に対する参考の反例。収益ベクトルの日ごとの独立・符号対称性は実証されていない。実価格の再生でも正式な有意確率でもない。',
            '限界': '第１・第２反復を読んで第３反復を設計した事実は消えない。過去の別作業まで全探索を含むものではなく、今回３反復の範囲だけ。'}
    original_path = HERE / '探索全体対照の固定.json'
    original = runner.read(original_path)
    assert original['規則'] == rule
    assert original['コードSHA256'] == runner.digest(HERE / 'search_selection_control_original.py')
    path = HERE / '探索全体対照の実装修正固定.json'
    if path.exists():
        fixed = runner.read(path)
        assert fixed['規則'] == rule and fixed['コードSHA256'] == runner.digest(Path(__file__))
        return fixed
    fixed = {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '規則': rule,
             'コードSHA256': runner.digest(Path(__file__)), '初期固定SHA256': runner.digest(original_path),
             '実装修正': '結果計算前にID集合・26入力キー・R有限性の拒否検査を追加。固定比較の所在をv25へ解決し、未所在も記録する。数式・符号組合せ・候補選抜をしない規則は変更しない。'}
    runner.save(path, fixed)
    return fixed


def collect() -> tuple[list[str], np.ndarray, list[str]]:
    """機能: 全条件の保存済みセッションRを、手法×銘柄×開始日の行列へ集約する。

    引数: なし。返り値: 手法ID・R行列・開始日 (tuple[list[str],ndarray,list[str]])。
    """
    input_keys = set(pickle.loads((HERE.parent / 'wave_v23' / 'inputs.pkl').read_bytes()))
    dates = sorted({key[0][:10] for key in input_keys})
    identifiers, values = [], []
    for phase in PHASES:
        directory = HERE.parent / phase
        fixed = runner.read(directory / '探索条件の固定.json')
        completed = runner.read(directory / '反証前の候補固定.json')
        assert completed['全条件数'] == fixed['全組合せ数']
        for signal in fixed['signals']:
            results = runner.read(directory / 'sessions' / f"{signal['id']}.json.gz")
            assert len(results) == len(fixed['managers'])
            expected_ids = {signal['id'] + '__' + manager['id'] for manager in fixed['managers']}
            assert {entry['id'] for entry in results} == expected_ids
            for result in results:
                rows = result['rows']
                observed = sorted({row['session'][:10] for row in rows})
                assert dates == observed and len(rows) == len(input_keys)
                assert {(row['session'], row['symbol']) for row in rows} == input_keys
                assert all(np.isfinite(row['net_r']) for row in rows), '非有限Rの入力を拒否'
                matrix = np.zeros((2, len(dates)), dtype=float)
                for row in rows:
                    matrix[SYMBOLS.index(row['symbol']), dates.index(row['session'][:10])] += row['net_r']
                identifiers.append(phase + '/' + result['id'])
                values.append(matrix)
        print(phase + 'の全条件を読込み', flush=True)
    return identifiers, np.asarray(values), dates


def evaluate() -> dict:
    """機能: 全共通符号反転で探索最大値を算出し、元の最大値や固定候補と比較する。

    引数: なし。返り値: 全符号組合せの分布と参考診断 (dict)。
    """
    fixed = freeze()
    names, values, dates = collect()
    assert len(names) == len(set(names)) and np.isfinite(values).all()
    scale = np.sqrt(np.sum(values ** 2, axis=2, keepdims=True))
    normalized = np.divide(values, scale, out=np.zeros_like(values), where=scale > 0)
    original = normalized.sum(axis=2).min(axis=1)
    cases = []
    for signs in itertools.product((-1, 1), repeat=len(dates)):
        score = np.einsum('ijk,k->ij', normalized, np.asarray(signs, float)).min(axis=1)
        winner = int(np.argmax(score))
        cases.append({'符号': list(signs), '全探索最大値': float(score[winner]), '最大値の手法': names[winner]})
    original_max = float(original.max())
    real_winner = int(np.argmax(original))
    observed = np.array([case['全探索最大値'] for case in cases])
    selected, missing = {}, []
    for phase in ['wave_v26', 'wave_v27']:
        path = HERE.parent / phase / '現在照合候補の固定.json'
        if path.exists():
            for candidate in runner.read(path)['候補']:
                name = phase + '/' + candidate['id']
                if name not in names and 'wave_v25/' + candidate['id'] in names:
                    name = 'wave_v25/' + candidate['id']
                if name in names:
                    score = float(original[names.index(name)])
                    selected[name] = {'元の統計量': score, '探索最大値がこれ以上の符号組合せ数': int(np.sum(observed >= score - 1e-12))}
                else:
                    missing.append({'選択元': phase, '手法ID': candidate['id'],
                                    '理由': '全組合せ探索の母集団に存在しない補助対照。統計量を捏造せず除外。'})
    output = {'固定': fixed, '全条件数': len(names), '開始日': dates, '符号組合せ数': len(cases),
              '元データ最大値': original_max, '元データ最大値の手法': names[real_winner],
              '探索最大値が元最大値以上の組合せ数': int(np.sum(observed >= original_max - 1e-12)),
              '探索最大値の百分位': np.percentile(observed, [0, 5, 50, 95, 100]).tolist(),
              '固定候補': selected, '母集団にない固定比較': missing,
              '全符号対照': cases, '正式な有意確率ではない': True}
    runner.save(HERE / '探索全体対照の結果.json', output)
    return output


def main() -> None:
    """機能: 固定だけ、または全探索完了後の集約対照を行う。

    引数: --prepare (bool)。返り値: なし (None)。価格取得や売買再生は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    freeze()
    if args.prepare:
        print('第三反復の損益計算前に、探索全体の参考対照を固定。')
    else:
        output = evaluate()
        print({key: value for key, value in output.items() if key not in ['固定', '全符号対照']})


if __name__ == '__main__':
    main()
