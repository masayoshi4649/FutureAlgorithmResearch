"""旧100の基準復帰が位相時計を動かさないことを人工だけで確認する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

os.environ['NUMBA_DISABLE_JIT'] = '1'
sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parents[1]


def digest(path: Path) -> str:
    """
    機能: 旧固定機構を変更せず内容指紋へ結び付ける。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 基準復帰と新位相開始の差を旧100の局所helper及び買売正負で確認する。
    引数: なし。101シミュレータ又は原金融素材を実行しない。
    返り値: None。自担当の新規prefix証跡だけ保存する。
    """
    source = ROOT / 'work/wave_v100/engine.py'
    before = digest(source)
    assert before == 'be34cd52ff6fa0fe625dae79f7a2e3444a12c54768c27ae6b6f55b3434a0e0e2'
    spec = importlib.util.spec_from_file_location('旧100基準復帰だけの人工比較101', source)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    cases = []
    for side in (-1, 1):
        fill = np.array([0, 100, 300, 4000, 4000.5, np.nan, np.nan, np.nan, np.nan, np.nan], float)
        watch = np.full(32, np.nan)
        old.entry_watch_start(watch, 1, side, 0, 100, 300., 4000., 4., 0., 0., 0., 300., 1,
            fill, False, 0)
        anchor = np.array([10, 110, 310, 4000, 4000.5, 20, 220, 307, 70000, 70010], float)
        old.entry_anchor(watch, anchor, True, 10, 2)
        assert watch[16] == 300 and watch[29] == 10
        observed = np.array([11, 111, 311, 4000 + side*.5, 4000.5 + side*.5,
            21, 221, 309, 70000 + side*10, 70010 + side*10], float)
        assert old.entry_pair_valid(observed, True, True)
        assert old.entry_bbo_status(watch, observed, True, .5, 10., 1) == (True, True)
        new_phase = watch.copy(); new_phase[16] = 310.
        assert old.entry_bbo_status(new_phase, observed, True, .5, 10., 1) == (False, False)
        for label in ('復帰同行', '同時計seqだけ更新', 'peer源再利用'):
            negative = observed.copy()
            if label == '復帰同行': negative = anchor.copy()
            elif label == '同時計seqだけ更新': negative[7] = anchor[7]
            elif label == 'peer源再利用': negative[5:8] = anchor[5:8]
            assert old.entry_bbo_status(watch, negative, True, .5, 10., 1) == (False, False)
        cases.append(dict(方向=side, 実fill位相時計=300., 復帰自己時計=310., 復帰相手時計=307.,
            後続自己時計=311., 後続相手時計=309.,
            旧C1基準だけ更新で後続進行可=True, 復帰時刻へ共通位相時計変更だと拒否=True,
            復帰同行及び同時計及びpeer再利用拒否=True))
    assert digest(source) == before
    result = dict(全合格=True, 種類='101未知基準復帰に使う旧C1時計の独立意味確認',
        実行範囲='旧100のentry_watch_start/entry_anchor/entry_bbo_statusだけの私有人工。101simulateは未実行。',
        買売正例=2, 買売負例=6, ケース=cases,
        結論='最後の実fill位相時計を保持し、復帰では各市場のBBO基準だけ更新する現仕様は旧C1と整合。'
              '共通位相時計を復帰rowへ変更するのは新しい追加条件であり、anchorだけという操作とは異なる。',
        限定='源/時計を明示注入した数理境界であり、実保存系列でこの例が出現したこと又は真受信順を認定しない。'
              '101では復帰同行の追加禁止も実シミュレータで別途確認する。',
        SHA256={source.relative_to(ROOT).as_posix(): before,
            Path(__file__).relative_to(ROOT).as_posix(): digest(Path(__file__))},
        旧100編集=0, 既存101pure編集=0, 正式101損益閲覧=0, 正式101売買実行=0,
        新simulate実行=0, API取得=0, 実注文=0)
    target = HERE / '新しい101実装反証_未知基準の位相時計.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('旧C1の基準復帰2正例6負例を確認。101本体と正式PLは未実行。', flush=True)


if __name__ == '__main__':
    main()
