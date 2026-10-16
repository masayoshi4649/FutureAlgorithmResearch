"""旧及びLPの許可を買売で非対称にし、正しい側への接続を少数人工で確かめる。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

os.environ['NUMBA_DISABLE_JIT'] = '1'
sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: 正式素材を開かずprivateな人工配線用に定義だけを読む。
    引数: name(str)、path(Path)。
    返り値: object。旧領域と既存証跡を変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 実装と既存証跡の非変更を内容指紋で確かめる。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value: object) -> str:
    """
    機能: private人工の共有配列又は設定に副作用がないことを検査する。
    引数: value(object)。
    返り値: strはpickle内容指紋。
    """
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def main() -> None:
    """
    機能: 買売とlaneの8経路を実行し、発注の正負・入力SHA・診断列を反証する。
    引数: なし。新正式PLを開かず又は再生しない。
    返り値: None。自担当review_preへ別の補足JSONを保存する。
    """
    source_paths = [BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py')]
    fixed_proofs = [HERE / name for name in (
        '34現在支持源の独立仕様反証と局所人工の事前期待値.json',
        '34現在支持の局所配線と非包摂及び未来不変の独立反証.json')]
    before = {str(path.relative_to(ROOT)): digest(path) for path in source_paths + fixed_proofs}
    strategy = module('現在支持99の左右配線補足', BASE / 'strategy.py')
    catalog = module('現在支持99の左右定義補足', BASE / 'catalog.py')
    fixture_path = ROOT / 'work/wave_v97/review_pre/36仕様の局所状態境界と源及び共有入力の独立反証.py'
    fixture = module('旧97短人工だけを左右補足へ読取', fixture_path)
    configs = {value['id']: value for value in catalog.catalog()}
    proofs = []
    for legacy_buy in (False, True):
        independent_buy = not legacy_buy
        for side in (-1, 1):
            for lane in ('L0', 'L1'):
                ident = lane + '_C1_A1_X1'
                config = configs[ident]
                record, signal = fixture.fixture(config, side, [0., 1., 1.5, 2.])
                n = len(signal['grid'])
                signal['entry_j2_long'] = np.full(n, legacy_buy, bool)
                signal['entry_j2_short'] = np.full(n, not legacy_buy, bool)
                lp = {1: np.full(n, independent_buy, bool), -1: np.full(n, not independent_buy, bool)}
                basis = np.full((n, 59), np.nan)
                basis[:, 0] = np.arange(n); basis[:, 1] = signal['grid']
                key = ('2000-01-03_人工', 'TOPIX')
                prepared = {key: dict(record=record, signal=signal, reference_open=4000.,
                    trend_lp_allowed=lp, entry_support_base=basis)}
                original = fingerprint((prepared, config))
                output = strategy.play(config, key, prepared, finish=False)
                assert fingerprint((prepared, config)) == original
                expected_buy = legacy_buy if lane == 'L0' else independent_buy
                expected = expected_buy if side == 1 else not expected_buy
                orders = output['orders'][output['orders'][:, 7] == 1]
                if expected:
                    assert len(orders) == 1 and int(orders[0, 1]) == 1 and int(orders[0, 4]) == side
                    trigger = 1
                else:
                    assert len(orders) == 0
                    trigger = None
                columns = {name: i for i, name in enumerate(output['entry_support_columns'])}
                trace = output['entry_support_state_trace']
                assert len(trace) == n
                assert np.all(trace[:, columns['selected_long_allowed']] == int(expected_buy))
                assert np.all(trace[:, columns['selected_short_allowed']] == int(not expected_buy))
                selected_long = signal['entry_j2_long'] if lane == 'L0' else lp[1]
                selected_short = signal['entry_j2_short'] if lane == 'L0' else lp[-1]
                assert output['entry_support_input_SHA256']['entry_j2_long'] == hashlib.sha256(selected_long.tobytes()).hexdigest()
                assert output['entry_support_input_SHA256']['entry_j2_short'] == hashlib.sha256(selected_short.tobytes()).hexdigest()
                proofs.append(dict(条件=ident, 候補方向=side, 旧買許可=legacy_buy,
                    旧売許可=not legacy_buy, LP買許可=independent_buy, LP売許可=not independent_buy,
                    発注期待=expected, 実発注行=trigger, 注文及び入力SHA及び方向診断一致=True))
    assert len(proofs) == 8
    assert sum(row['発注期待'] for row in proofs) == 4
    assert before == {str(path.relative_to(ROOT)): digest(path) for path in source_paths + fixed_proofs}
    result = dict(全合格=True, 種類='結果前の非対称支持入力による局所配線補足',
        買売lane正負経路=8, 発注正例=4, 拒否負例=4, 経路=proofs,
        共有prepared非変更=True, 旧証跡非変更=True, コード及び既存証跡SHA256=before,
        人工fixtureSHA256=digest(fixture_path), 計算コードSHA256=digest(Path(__file__)),
        scope='買売の許可を異なるboolへ注入した現在支持2列の配線検査。LP価格系列の生成又は59源列の全原本再現は認定しない。',
        新正式損益閲覧=0, 新正式売買実行=0, API取得=0, 実注文=0)
    target = HERE / '現在支持の買売非対称配線の独立補足.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('買売の支持を反対にした8人工経路で正例4/負例4を確認。新正式PL0。', flush=True)


if __name__ == '__main__':
    main()
