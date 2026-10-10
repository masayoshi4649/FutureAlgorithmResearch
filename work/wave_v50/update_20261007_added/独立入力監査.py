"""保存済み追加四場の原本を読み取り専用で独立検査する。"""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSIONS = ('2026-10-02_Night', '2026-10-05_Day', '2026-10-05_Night', '2026-10-06_Day')
PRIOR = ROOT / 'work/wave_v50/update_20261002_two/独立監査.py'
spec = importlib.util.spec_from_file_location('独立入力監査旧実装', PRIOR)
prior = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prior
spec.loader.exec_module(prior)


def run() -> dict:
    """機能: 六保存系列の一覧、追加原本の品質、旧十九場の指紋を検査する。

    引数: なし。返り値: 統合監査結果(dict)。
    """
    old_paths = [ROOT / name for name in (
        'work/wave_v48/update_20261001/固定.json',
        'work/wave_v50/update_20261001_day/固定.json',
        'work/wave_v50/update_20261002_two/固定.json',
    )]
    old = {}
    for path in old_paths:
        for name, digest in json.loads(path.read_text(encoding='utf-8'))['原本SHA256'].items():
            assert name not in old or old[name] == digest
            old[name] = digest
    old_names = {Path(name).stem for name in old}
    assert len(old_names) == 19
    inventory = {}
    for folder in ('book', 'candle_1min', 'candle_5min'):
        for symbol in ('TOPIX', 'NK225'):
            names = {p.stem for p in (ROOT / folder / symbol).iterdir() if p.is_file()}
            inventory[f'{folder}/{symbol}'] = dict(セッション数=len(names), 全セッション=sorted(names),
                                                   追加=sorted(names-old_names), 不足=sorted(old_names-names))
    assert all(item['追加'] == list(SESSIONS) and not item['不足'] for item in inventory.values())
    originals, candles = [], []
    observation_path = HERE / '独立観測.npz'
    independent = {}
    for session in SESSIONS:
        for symbol in ('TOPIX', 'NK225'):
            result, bars, observations = prior.raw_audit(session, symbol)
            originals.append(result)
            candles.extend(prior.candle_audit(session, symbol, sec, bars[sec]) for sec in (60, 300))
            independent[f'{session}/{symbol}'] = observations
            print(json.dumps(dict(対象=session, 銘柄=symbol, 原本行数=result['原本行数'],
                                  有効板行数=result['有効板行数'], 最後=result['最後の有効板時刻']), ensure_ascii=False), flush=True)
    np.savez_compressed(observation_path, **independent)

    # ----------------------------------------
    # 追加以外の原本が変更されていないか、以前の保存済み指紋と比較する。
    names = list(old)
    with ThreadPoolExecutor(max_workers=2) as pool:
        actual = list(pool.map(prior.sha, (ROOT / name for name in names)))
    fingerprints = [dict(原本=name, 以前SHA256=old[name], 現在SHA256=digest, 一致=digest == old[name])
                    for name, digest in zip(names, actual)]
    checks = dict(
        六保存系列の追加一致=True,
        旧十九場原本全一致=all(item['一致'] for item in fingerprints),
        全追加場に返済期限以降の有効板あり=all(item['最終5分区間の有効板あり'] and item['返済期限以降の有効板あり'] for item in originals),
        追加板の形式価格時刻検査=all(not any(item.get(key, 0) for key in ('JSON不正行数', '時刻不正行数', '時刻逆行数', '対象内価格不正行数')) for item in originals),
        追加足の確定性整合性検査=all(not any(item[key] for key in ('未確定足数', '重複時刻数', '時刻逆行数', '価格不正足数', 'OHLC不整合足数')) and item['最終区間の確定足あり'] for item in candles),
    )
    result = dict(全合格=all(checks.values()), 項目別判定=checks, 対象=list(SESSIONS), 保存一覧=inventory,
                  生原本=originals, 保存足=candles,
                  旧十九場原本照合=dict(参照=[p.relative_to(ROOT).as_posix() for p in old_paths], 件数=len(fingerprints), 全一致=checks['旧十九場原本全一致'], 詳細=fingerprints),
                  独立観測SHA256=prior.sha(observation_path), 監査スクリプトSHA256=prior.sha(Path(__file__)),
                  API追加取得数=0, 原本変更数=0,
                  完了判定='保存足が全足確定し、監視終端の最後の1分・5分枠を覆う。返済期限はデイ15:35、ナイト05:50で、その後の有効板がある。約定のない足は補完しない。全約定の完全収集を意味しない。',
                  時刻の制約='CurrentPriceTimeは約定時刻であり受信時刻ではない。約定時刻の間隔だけではネットワーク中断と断定できない。',
                  因果性の前提='原本物理行順を保持する。約定時刻集計と保存足のOHLC差は開示し、原本を編集しない。')
    (HERE / '入力独立監査.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(全合格=result['全合格'], 項目別判定=checks), ensure_ascii=False), flush=True)
    return result


def align() -> dict:
    """機能: 別系統で作成した再生入力と独立観測の全行を照合する。

    引数: なし。返り値: 完全一致の照合結果(dict)。
    """
    input_path = HERE / 'new_inputs.pkl'
    inputs = pickle.loads(input_path.read_bytes())
    result = []
    with np.load(HERE / '独立観測.npz') as observations:
        for session in SESSIONS:
            for symbol in ('TOPIX', 'NK225'):
                independent, ready = observations[f'{session}/{symbol}'], inputs[session, symbol]
                for index, key in enumerate(('seq', 'time_s', 'last')):
                    np.testing.assert_array_equal(independent[:, index], ready[key])
                result.append(dict(対象=session, 銘柄=symbol, 行数=len(independent), 完全一致=True, 比較列=['seq', 'time_s', 'last']))
    output = dict(全合格=True, 再生入力SHA256=prior.sha(input_path), 照合=result)
    (HERE / '再生入力独立照合.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False), flush=True)
    return output


if __name__ == '__main__':
    if '--align' in sys.argv:
        align()
    else:
        run()
