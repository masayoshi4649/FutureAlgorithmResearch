"""正式登録された旧CS源の同値検証。新しい条件を探索しない。"""

import json
from pathlib import Path
import pickle
import sys
import time
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'work/research145_engine'))
import source145 as source


def main():
    """
    機能: 手数料385指定の旧S01/L00を再現し、保存全行と比較する。
    引数: なし。
    返り値: None。受領済みの独立互換検証であり、新しい有効性の証拠に数えない。
    """
    receipt_path = ROOT / 'work/research145_report/登録受領145.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
    assert receipt['returncode'] == 0
    inventory = json.loads((ROOT/'work/research145_data/全保存資料の再照合145.json').read_text(encoding='utf-8'))
    output = HERE / '別入口S01_L00全場同値監査145.json'
    assert not output.exists(), '同じ互換再生を黙って再実行しない'
    checks = []
    for scene in inventory['known_sessions']:
        cache = ROOT / 'work/research145_engine/cache' / (scene+'.pkl')
        deadline = time.monotonic()+3600
        while not cache.exists():
            assert time.monotonic() < deadline
            time.sleep(1)
        with cache.open('rb') as stream:
            _, data, _, _, _ = pickle.load(stream)
        if scene.endswith('_Day'):
            config = dict(source.episode.configurations()[0], maximum=2, initial=2)
            history = source.active.history(data['ready']['time_s'], data['features'][:, 10], data['ready']['start'], 20)
            orders = source.replay_episode(data, history, config, fee10=385)
            path, name = source.OLD / 'round1/measurement' / ('NK225_'+scene+'.npz'), 'S01'
        else:
            config = dict(source.shared.previous.first.original.configurations()[33], initial=1, maximum=2)
            orders = source.replay_active(data, config, fee10=385, original=True)
            path, name = source.OLD / 'round2/measurement' / ('NK225_'+scene+'.npz'), 'L00'
        with np.load(path) as archive:
            np.testing.assert_array_equal(orders, archive[name], err_msg=scene+' '+name)
        checks.append(dict(session=scene, source=name, orders=len(orders), exact=True))
        (HERE/'別入口同値監査の進捗.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
        print(scene+' '+name+' 旧全行と完全一致', flush=True)
    report = dict(registration=str(receipt_path.relative_to(ROOT)), comparisons=len(checks),
                  all_exact=True, source_only=True, new_strategies=0, checks=checks)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
