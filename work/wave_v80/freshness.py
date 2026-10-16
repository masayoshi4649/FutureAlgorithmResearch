"""固定代表のまま、損益を見ず保存した厳格3秒鮮度へ差し替えて確認する。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import numpy as np
import pdca
import study

HERE = Path(__file__).resolve().parent
BASE = HERE / 'quality_strict3'


def materials() -> tuple:
    """機能: 原価格列を維持し、信号だけを保存済み3秒鮮度版に置き換える。

    引数: なし。返り値: 原価格・板・信号・格子対応の組(tuple)。
    """
    ready, books, _, _ = study.material()
    signals = study.load(HERE / 'strict3/prepared/signals.pkl')
    maps = {key: (np.searchsorted(signals[key]['grid'], row['time_s'], side='right') - 1).astype(np.int32)
            for key, row in ready.items()}
    return ready, books, signals, maps


def main() -> None:
    """機能: 既定11代表を全30場・注文遅延5秒で再生し、鮮度感度を保存する。

    引数: なし。返り値: なし(None)。この結果を代表の差替えに用いない。
    """
    study.socket.socket.connect = study.deny
    study.socket.create_connection = study.deny
    fixed = study.load(HERE / '初回事前固定.json')
    repair = study.load(HERE / '改修事前固定.json')
    assert all(study.digest(study.ROOT / name) == value for name, value in fixed['SHA256'].items())
    assert all(study.digest(study.ROOT / name) == value for name, value in repair['SHA256'].items())
    configs = study.load(HERE / '最終前半選定.json')['確認条件']
    for name in ('results', 'ledgers'):
        (BASE / name).mkdir(parents=True, exist_ok=True)
    design = BASE / '確認仕様.json'
    if not design.exists():
        study.save(design, dict(目的='原本の受信時計欠如と観測の疎さに対する品質感度。代表選び直しではない。',
            対象=[c['id'] for c in configs], 注文遅延秒=5,
            差替え='signalのみ初回損益前に保存した現在情報/窓始点とも3秒以内版へ戻す。原価格・約定規則・管理は同一。',
            SHA256={str(p.relative_to(study.ROOT)): study.digest(p) for p in
                (Path(__file__), HERE / 'strict3/prepared/signals.pkl', HERE / '最終前半選定.json')}))
    data = materials()
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks = [pool.submit(pdca.run_one, c, data, fixed['全30'], BASE, 5, fixed) for c in configs]
        for i, task in enumerate(as_completed(tasks), 1):
            print(f'3秒鮮度 {i}/{len(configs)} {task.result()}', flush=True)


if __name__ == '__main__':
    main()
