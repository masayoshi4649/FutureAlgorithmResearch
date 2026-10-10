"""一度取得した未使用セッションを元足から打ち切り、９固定方式の確定取引を照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
LIVE = OUT / 'live'
sys.dont_write_bytecode = True
sys.path.insert(0, str(OUT))
import research as research
from signals import build_features, get_signals


PREDICT_CODE = r'''
import sys,json
from pathlib import Path
import numpy as np
sys.dont_write_bytecode=True
sys.path.insert(0,'work/wave_v7')
import ml_models
data={key:np.asarray(value) for key,value in json.load(sys.stdin).items()}
predictions=ml_models.predict_arrays(data,Path('work/wave_v7/models'),scope='final')
print(json.dumps({key:predictions[key].tolist() for key in ('logistic_60','lstm_60')}))
'''


def digest(path: Path) -> str:
    """機能: 監査対象ファイルのSHA256を読む。

    引数: path (Path) は対象。
    返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_frozen(frozen: dict) -> int:
    """機能: 取得前の75ファイルが変更されていないことを確認する。

    引数: frozen (dict) は取得前の凍結記録。
    返り値: 一致したファイル数 (int)。
    """
    for name, expected in frozen['files_sha256'].items():
        assert digest(ROOT / name) == expected, name
    return len(frozen['files_sha256'])


def prefix_input(frames: dict, session: str, cutoff: pd.Timestamp) -> tuple:
    """機能: 確定時刻に基づいて元足を削除し、価格特徴を新規生成する。

    引数: frames (dict) は元足、session (str) はセッション名、cutoff (Timestamp) は観測締切。
    返り値: 銘柄別売買入力と教師列のないML入力 (tuple[dict,dict])。
    ９固定方式の機械09・14は価格のみであり、生板特徴を入力しない。
    """
    data = {}
    parts = {key: [] for key in ('X', 'time_ns', 'session_idx', 'symbol_idx', 'valid')}
    for symbol_id, symbol in enumerate(research.SYMBOLS):
        one, five = frames[symbol]
        one = one.loc[one.index + pd.Timedelta(minutes=1) <= cutoff].copy()
        five = five.loc[five.index + pd.Timedelta(minutes=5) <= cutoff].copy()
        feature = build_features(one, five, None, research.TICKS[symbol], cutoff - pd.Timedelta(minutes=1))
        item = research.prepare(one, feature, symbol, session)
        data[(session, symbol)] = item
        times = feature.index + pd.Timedelta(minutes=2)
        valid = feature.atr.notna() & feature.age.ge(43) & feature.stale_minutes.le(10)
        valid &= times < item['limit'] - pd.Timedelta(minutes=30)
        parts['X'].append(feature[research.FEATURES].to_numpy(float))
        parts['time_ns'].append(times.as_unit('ns').asi8)
        parts['session_idx'].append(np.zeros(len(feature), dtype=int))
        parts['symbol_idx'].append(np.full(len(feature), symbol_id))
        parts['valid'].append(valid.to_numpy(bool))
    dataset = {key: np.concatenate(value) for key, value in parts.items()}
    dataset['feature_names'] = np.asarray(research.FEATURES)
    return data, dataset


def model_signals(dataset: dict) -> dict:
    """機能: 保存モデルだけの推論をGPU環境で実行する。

    引数: dataset (dict) はラベルなしの過去特徴。
    返り値: モデル別確率配列 (dict[str,ndarray])。
    中間ファイルを作らず標準入出力で受け渡し、学習関数を呼ばない。
    """
    process = subprocess.run([str(OUT / 'ml_gpu_env' / 'Scripts' / 'python.exe'), '-X', 'utf8', '-c', PREDICT_CODE],
                             input=json.dumps({key: value.tolist() for key, value in dataset.items()}),
                             capture_output=True, text=True, encoding='utf-8', cwd=ROOT, check=True)
    return {key: np.asarray(value, dtype=float) for key, value in json.loads(process.stdout).items()}


def compare_trades(actual: list[dict], expected: list[dict]) -> int:
    """機能: 打切り再生と全取得データ再生の確定済み取引を照合する。

    引数: actual/expected (list[dict]) は時刻順の確定取引。
    返り値: 比較属性数 (int)。不一致は例外とする。
    """
    assert len(actual) == len(expected), (len(actual), len(expected))
    count = 0
    for first, second in zip(actual, expected):
        for key in ('symbol', 'session', 'side', 'entry_method', 'closed', 'reason'):
            assert first[key] == second[key], (key, first[key], second[key])
            count += 1
        for key in ('signal_time', 'entry_time', 'exit_time'):
            assert pd.Timestamp(first[key]) == pd.Timestamp(second[key]), (key, first[key], second[key])
            count += 1
        for key in ('entry_price', 'exit_price', 'atr', 'initial_stop', 'gross_points', 'net_points', 'stress_points', 'duration_min'):
            np.testing.assert_allclose(first[key], second[key], rtol=0, atol=1e-10)
            count += 1
    return count


def main() -> None:
    """機能: ３つの時刻で９方式×２銘柄を再生し、監査結果だけを書き出す。

    引数: なし。
    返り値: なし (None)。追加API呼出し、条件変更、再学習は行わない。
    """
    frozen = json.loads((OUT / '凍結記録.json').read_text(encoding='utf-8'))
    frozen_before = check_frozen(frozen)
    full = json.loads((LIVE / '未使用セッション結果.json').read_text(encoding='utf-8'))
    session = full['セッション']
    assert session == '2026-09-23_Night'
    assert len(frozen['live_methods']) == 9
    frames = {symbol: tuple(research.read_candle(LIVE / f'candle_{minutes}min' / symbol / f'{session}.csv')
                            for minutes in (1, 5)) for symbol in research.SYMBOLS}
    with np.load(LIVE / 'dataset.npz', allow_pickle=False) as source:
        full_dataset = {key: source[key] for key in source.files}
    with np.load(LIVE / 'live_predict.npz', allow_pickle=False) as source:
        full_predictions = {key: source[key] for key in source.files}
    cells, prediction_checks, feature_checks = [], [], []
    for clock in ('17:55', '18:30', '18:55'):
        cutoff = pd.Timestamp(f'2026-09-23 {clock}:00+09:00')
        data, dataset = prefix_input(frames, session, cutoff)
        predictions = model_signals(dataset)
        for symbol_id, symbol in enumerate(research.SYMBOLS):
            local = dataset['symbol_idx'] == symbol_id
            reference = (full_dataset['symbol_idx'] == symbol_id) & (full_dataset['time_ns'] <= dataset['time_ns'][local].max())
            np.testing.assert_array_equal(dataset['time_ns'][local], full_dataset['time_ns'][reference])
            np.testing.assert_allclose(dataset['X'][local], full_dataset['X'][reference], rtol=1e-12, atol=1e-12, equal_nan=True)
            feature_checks.append(dict(締切=str(cutoff), 銘柄=symbol, 比較行数=int(local.sum()), 一致=True))
            for name in predictions:
                first, second = predictions[name][local], full_predictions[name][reference]
                np.testing.assert_allclose(first, second, rtol=0, atol=2e-7, equal_nan=True)
                usable = np.isfinite(first)
                np.testing.assert_array_equal(first[usable] >= .5, second[usable] >= .5)
                prediction_checks.append(dict(締切=str(cutoff), 銘柄=symbol, 方式=name, 比較予測数=int(usable.sum()),
                                              最大確率誤差=float(np.max(np.abs(first[usable]-second[usable]))) if usable.any() else 0., 方向完全一致=True))

        # ----------------------------------------
        # 確定済み足を順に再生。締切の未返済は将来の確定取引と比較しない。
        for method in frozen['live_methods']:
            name, exit_name = method.split('/')
            for key, item in data.items():
                symbol = key[1]
                if name.startswith('機械'):
                    family = int(name[2:])
                    peer_symbol = 'TOPIX' if symbol == 'NK225' else 'NK225'
                    signs = get_signals(item['z'], data[(session, peer_symbol)]['z'], family, .75).to_numpy()
                elif name in ('上昇固定', '下降固定'):
                    family = 9
                    signs = np.full(len(item['z']), 1 if name == '上昇固定' else -1)
                else:
                    family = 9
                    mask = dataset['symbol_idx'] == research.SYMBOLS.index(symbol)
                    probability = predictions[name][mask]
                    signs = np.where(np.isfinite(probability), np.where(probability >= .5, 1, -1), 0)
                    signs[~dataset['valid'][mask]] = 0
                trades = research.simulate(item, research.sign_schedule(signs), research.config(family), research.RULES[exit_name])
                actual = [trade for trade in trades if trade['closed']]
                expected = [trade for trade in full['取引'] if trade['方式'] == method and trade['symbol'] == symbol
                            and trade['closed'] and pd.Timestamp(trade['exit_time']) + pd.Timedelta(minutes=1) <= cutoff]
                count = compare_trades(actual, expected)
                cells.append(dict(締切=str(cutoff), 方式=method, 銘柄=symbol, 確定取引数=len(actual), 比較属性数=count,
                                  未返済除外数=sum(not trade['closed'] for trade in trades), 一致=True))
        print(f'{clock}: ９固定方式・２銘柄の確定取引が全取得期間再生と一致', flush=True)
    frozen_after = check_frozen(frozen)
    result = dict(判定='合格', セッション=session, 追加API取得=False, 再学習=False, 条件変更=False,
                  凍結照合件数={'開始前': frozen_before, '終了後': frozen_after},
                  元足打切り='１分は開始+１分、５分は開始+５分が締切以下の確定足だけを使用し、build_featuresを再実行。',
                  ML='事前凍結した全既知５セッション学習済みfinalモデルだけで再推論。教師列を渡さない。',
                  対象方式=frozen['live_methods'], 比較セル数=len(cells), 比較取引延べ数=sum(row['確定取引数'] for row in cells),
                  比較属性総数=sum(row['比較属性数'] for row in cells), 特徴比較=feature_checks, ML予測比較=prediction_checks, 確定取引比較=cells,
                  限界=['同じ取引を複数の締切・類似方式で照合するため、延べ数を独立した取引標本数とは扱わない。',
                        '締切時点で未返済の建玉は確定利益へ含めず、今回の取引照合から除外。',
                        '１分内の高値・安値の秒単位順序は不明。元の保守的な同足損切り優先仮定を維持しており、実市場の約定保証ではない。',
                        '９方式の機械09と14は価格特徴だけを使うため、生板の逐次打切り検証はこの監査の対象外。'],
                  対象SHA256={str(path.relative_to(ROOT)).replace('\\','/'): digest(path) for path in
                              [Path(__file__), LIVE/'未使用セッション結果.json', LIVE/'dataset.npz', LIVE/'live_predict.npz', OUT/'凍結記録.json']})
    (OUT/'live_prefix_review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 未使用ナイトの元足打切りによる逐次売買確認', '',
             '**判定: 合格。** 追加取得せず、１回だけ取得済みの9/23ナイトを17:55・18:30・18:55で打ち切り、各時刻に確定済みの元足から特徴・保存モデルの予測・売買を再計算した。', '',
             f"９固定方式×２銘柄×３締切の{len(cells)}セルすべて一致。確定取引は延べ{result['比較取引延べ数']}件、属性は{result['比較属性総数']}個を照合した。入口/出口時刻・価格、方向、ATR、初期損切り、費用控除後損益、理由等を確認。未返済は比較対象から除外した。", '',
             '| 締切 | 比較セル | 確定取引の延べ照合数 | 結果 |', '|---|---:|---:|---|']
    for clock in ('17:55', '18:30', '18:55'):
        subset = [row for row in cells if clock in row['締切']]
        lines.append(f"| {clock} | {len(subset)} | {sum(row['確定取引数'] for row in subset)} | 全件一致 |")
    lines += ['', '１分足は開始+１分、５分足は開始+５分まで観測したものだけを使う。事前計算済み特徴を切る方法ではなく、元足を切って再生成した。ロジスティック回帰とLSTMは既知５セッションで事前学習したモデルを読み、教師ラベルを渡さず予測。方向は全件一致した。', '',
              f"凍結{frozen_before}ファイルは監査の開始前・終了後とも取得前SHA256に一致した。再学習、条件変更、追加API呼出しは行っていない。", '',
              '延べ件数には締切・方式間の同じ取引の重複がある。１分内の高安の秒単位順序は分からず、元実装の保守的な約定仮定を維持している。この一致は実市場で同じ価格に約定することの保証ではない。９方式で使う機械09・14は価格のみのため、生板特徴の逐次打切りは対象外。', '',
              '再現: `python -X utf8 work/wave_v7/live_prefix_review.py`', '',
              '個別結果は [live_prefix_review.json](live_prefix_review.json)、コードは [live_prefix_review.py](live_prefix_review.py) を参照。']
    (OUT/'live_prefix_review.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
