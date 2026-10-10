"""既存収支だけを使い、日集計と偶然性診断を独立に照合する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
OLD = BASE.parent / 'wave_v61'


def read_json(path: Path) -> dict:
    """機能: UTF-8の既存JSONを読み取る。

    引数: path(Path)。返り値: 内容(dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """機能: 保存済みファイルの同一性を照合する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def independent_indices(seed: int, count: int, days: int, length: int) -> np.ndarray:
    """機能: 固定seedの乱数から定常再抽出の原本日添字を別実装で組む。

    引数: seed/count/days/length(int)。返り値: 再抽出添字(ndarray)。
    原実装と乱数呼出順を合わせるが、継続・再開始は別々に代入する。
    """
    rng = np.random.default_rng(seed)
    batches = []
    for begin in range(0, count, 500):
        size = min(500, count - begin)
        table = np.zeros((size, days), dtype=np.int64)
        table[:, 0] = rng.integers(0, days, size=size)
        for k in range(1, days):
            restart = rng.random(size) < (1.0 / length)
            starts = rng.integers(0, days, size=size)
            table[:, k] = (table[:, k - 1] + 1) % days
            table[restart, k] = starts[restart]
            assert np.all(table[~restart, k] == (table[~restart, k - 1] + 1) % days)
        batches.append(table)
    return np.concatenate(batches)


def independent_diagnostic(matrix: np.ndarray, indices: np.ndarray, columns: list[int]) -> list[dict]:
    """機能: 日の出現回数との行列積で平均・単独p・全系列最大値pを計算する。

    引数: matrix/indices(ndarray)、columns(list[int])。
    返り値: 候補ごとの照合数値(list[dict])。
    元コードの三次元添字抽出を使わず、度数加重した日損益から算出する。
    """
    n = len(matrix)
    mean = matrix.sum(axis=0) / n
    deviation = np.sqrt(np.square(matrix - mean).sum(axis=0) / (n - 1))
    assert np.all(deviation > 1e-10)
    selected_samples = []
    selected_null = []
    maxima = []
    observed = np.sqrt(n) * mean / deviation
    for start in range(0, len(indices), 500):
        ix = indices[start:start + 500]
        counts = np.zeros((len(ix), n), dtype=np.int64)
        np.add.at(counts, (np.repeat(np.arange(len(ix)), n), ix.ravel()), 1)
        assert np.all(counts.sum(axis=1) == n)
        sample = counts @ matrix / n
        null = np.sqrt(n) * (sample - mean) / deviation
        maxima.append(null.max(axis=1))
        selected_samples.append(sample[:, columns])
        selected_null.append(null[:, columns])
    maxima = np.concatenate(maxima)
    sample = np.concatenate(selected_samples)
    null = np.concatenate(selected_null)
    output = []
    for j, column in enumerate(columns):
        low, high = np.quantile(sample[:, j], [.025, .975])
        raw = (1 + np.sum(null[:, j] >= observed[column])) / (len(indices) + 1)
        adjusted = (1 + np.sum(maxima >= observed[column])) / (len(indices) + 1)
        assert 0 < raw <= adjusted <= 1
        output.append(dict(候補列=column, 平均日収支=float(mean[column]),
            平均日収支の基本法95区間=[float(2 * mean[column] - high), float(2 * mean[column] - low)],
            単独片側参考p=float(raw), 全900系列最大値調整参考p=float(adjusted),
            標準化観測値=float(observed[column])))
    return output


def main() -> None:
    """機能: 900系列の元会計・全6再抽出と尺度不変性を検証し証跡を保存する。

    引数: なし。返り値: なし(None)。売買再生・原本・外部APIは使用しない。
    """
    fixed = read_json(BASE / '診断仕様.json')
    results = read_json(BASE / '偶然性の診断.json')
    assert sha(BASE / 'check_chance.py') == fixed['実装SHA']
    loaded = np.load(BASE / '日別損益行列.npz')
    matrix, dates, series = loaded['matrix'], loaded['dates'].tolist(), loaded['series'].tolist()
    assert matrix.shape == (13, 900)
    assert len(set(map(tuple, series))) == 900
    lookup = {tuple(value): i for i, value in enumerate(series)}
    reconstructed = np.zeros_like(matrix)
    used = set()
    sessions_by_column = {}
    for branch in ('directional', 'inventory'):
        path = OLD / branch / '集計結果.json'
        assert sha(path) == fixed['入力SHA'][str(path)]
        source = read_json(path)
        for method in source['methods']:
            identifier = method.get('condition_id', method['id'])
            for account in method['accounts']:
                mode = account.get('price_mode', method.get('price_mode', 'quote'))
                if mode != 'quote':
                    continue
                key = (identifier, account['symbol'])
                column = lookup[key]
                session = account['session']
                assert (column, session) not in used
                used.add((column, session))
                sessions_by_column.setdefault(column, []).append(session)
                net = account['gross_profit'] - account['gross_loss'] - account['fees']
                assert abs(net - account['net']) < 1e-7
                assert abs(account.get('unrealized_end', 0)) < 1e-7
                reconstructed[dates.index(session[:10]), column] += net
    assert len(used) == 22500
    matrix_error = float(np.max(np.abs(matrix - reconstructed)))
    assert matrix_error < 1e-7, matrix_error
    common_sessions = sorted(sessions_by_column[0])
    assert len(common_sessions) == 25
    assert all(sorted(value) == common_sessions for value in sessions_by_column.values())
    complete = [i for i, date in enumerate(dates) if sum(s[:10] == date for s in common_sessions) == 2]
    assert len(complete) == 12 and dates[-1] == '2026-10-07'
    selected = [lookup[tuple(value)] for value in fixed['候補']]
    concentration = []
    for candidate in results['候補']:
        column = candidate['列']
        assert abs(matrix[:, column].sum() - candidate['集計']['net']) < 1e-7
        without = float(matrix[:, column].sum() - max(0, matrix[:, column].max()))
        assert without == candidate['最大黒字日除外']
        concentration.append(dict(条件=series[column], 全期間=float(matrix[:, column].sum()), 最大黒字日除外=without))
    # ----------------------------------------
    # 同じ再抽出を別の加重和実装へ入力して、固定済み6通りを再現する。
    checks = []
    for saved in results['再標本化']:
        sample = matrix if saved['日数'] == 13 else matrix[complete]
        ix = independent_indices(saved['seed'], saved['反復数'], saved['日数'], saved['平均ブロック日数'])
        assert ix.shape == (20000, len(sample)) and ix.min() >= 0 and ix.max() < len(sample)
        calculated = independent_diagnostic(sample, ix, selected)
        for actual, expected in zip(calculated, saved['候補']):
            for key in actual:
                assert np.allclose(actual[key], expected[key], rtol=1e-12, atol=1e-8), (saved['対象'], key, actual, expected)
        checks.append(dict(対象=saved['対象'], 平均ブロック日数=saved['平均ブロック日数'], 一致=True, 候補=calculated))
    # ----------------------------------------
    # 元コードを主処理なしで読み、定常添字と正の銘柄尺度変更を小標本で照合する。
    spec = importlib.util.spec_from_file_location('偶然性原実装', BASE / 'check_chance.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rng = np.random.default_rng(35)
    expected_ix = module.indices(rng, 500, 13, 4)
    assert np.array_equal(expected_ix, independent_indices(35, 500, 13, 4))
    toy = np.array([[-3, -6, 5], [2, 4, -1], [9, 18, 0], [-1, -2, -5], [4, 8, 8]], dtype=float)
    module.REPEATS = 500
    original = module.diagnose(toy, [0, 1], 2, 12)
    scaled = module.diagnose(toy * np.array([8, .25, 16]), [0, 1], 2, 12)
    for a, b in zip(original['候補'], scaled['候補']):
        for key in ('単独片側参考p', '全900系列最大値調整参考p', '標準化観測値'):
            assert abs(a[key] - b[key]) < 1e-12
    assert original['候補'][0]['全900系列最大値調整参考p'] == original['候補'][1]['全900系列最大値調整参考p']
    outcome = dict(合格=True, 元場会計数=len(used), 行列形=list(matrix.shape), 完全日数=len(complete), 会計浮動小数点最大差=matrix_error,
        全6設定再現=True, 再標本化回数=120000, 日内まとめとゼロ取引日保持=True,
        固定尺度と共通日添字と倍率不変=True, 集中度=concentration, 詳細=checks,
        入力SHA={str(path.relative_to(BASE)):sha(path) for path in (BASE/'check_chance.py', BASE/'診断仕様.json', BASE/'偶然性の診断.json', BASE/'日別損益行列.npz')},
        限界='数値実装の一致であり、13日での検定精度・定常性・未記録探索を検証したものではない。')
    (HERE / '独立検算.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in outcome.items() if key not in ('詳細', '入力SHA')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
