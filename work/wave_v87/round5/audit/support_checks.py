"""強度換算の境界・非変更・未来切断を売買成績を使わず独立検査する。"""

import hashlib
import json
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[2]
sys.path.insert(0, str(WORK))
import strategy
import catalog


def digest(values):
    """
    機能: 支持特徴の全配列を指紋化する。
    引数: values (dict[str,ndarray]) は特徴。
    返り値: dict[str,str] のSHA256。
    """
    return {key: hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()
            for key, value in values.items()}


def decision(short, config, side):
    """
    機能: 旧判定器とは別式で、変更後の強度条件を全行評価する。
    引数: short/config (dict)、side (int) は買い又は売り方向。
    返り値: ndarray[bool] の許可状態。
    """
    own = short['self_valid'] & (side*short['self_value'] > config['threshold_atr'])
    if config['support_mode'] == 3:
        own &= short['peer_valid'] & (side*short['peer_value'] > config['threshold_atr'])
    return own


def artificial():
    """
    機能: 閾値の等号・直前直後浮動小数点・反対方向・欠測を独立式へ照合する。
    引数: なし。
    返り値: int の合格した境界条件数。
    """
    total = 0
    for config in catalog.catalog():
        threshold = config['threshold_atr']
        values = np.array([-.8, -threshold, np.nextafter(-threshold, -np.inf),
                           np.nextafter(-threshold, np.inf), 0.,
                           np.nextafter(threshold, -np.inf), threshold,
                           np.nextafter(threshold, np.inf), .8, np.nan])
        n = len(values)
        for peer_values in (values, values[::-1].copy()):
            for own_available in (False, True):
                for peer_available in (False, True):
                    original = dict(self_value=values.copy(), peer_value=peer_values.copy(),
                                    self_valid=np.isfinite(values)&own_available,
                                    peer_valid=np.isfinite(peer_values)&peer_available,
                                    self_source_seq=np.arange(n, dtype=np.int64),
                                    peer_source_time=np.arange(n, dtype=float))
                    before = digest(original)
                    converted = strategy.scaled_features(config, dict(short=original))['short']
                    for name in original:
                        if name not in ('self_value', 'peer_value'):
                            assert converted[name] is original[name]
                    for side in (-1, 1):
                        expected = decision(original, config, side)
                        for row in range(n):
                            actual = strategy.core.supported.py_func(config['support_mode'], side, -1, row,
                                np.arange(n, dtype=np.int64), np.arange(n, dtype=float),
                                converted['self_value'], converted['self_valid'], converted['self_source_seq'],
                                converted['peer_value'], converted['peer_valid'], converted['peer_source_time'])
                            assert actual == expected[row], (config['id'], side, row, actual, expected[row])
                            total += 1
                    assert digest(original) == before
    return total


def main():
    """
    機能: 全60口座の変換結果を直接閾値式と比較し、未来を切っても過去値が不変と確かめる。
    引数: なし。
    返り値: None。新旧いずれの売買損益も生成せず検査JSONだけ保存する。
    """
    boundary_count = artificial()
    expanded, proof = strategy.prepare.load(verify=True)
    rows = []
    for key, short in sorted(expanded.items()):
        original_hash = digest(short)
        n = len(short['self_value'])
        checks = 0
        for config in catalog.catalog():
            converted = strategy.scaled_features(config, dict(short=short))['short']
            if config['threshold_atr'] == .05:
                for name in ('self_value', 'peer_value'):
                    np.testing.assert_array_equal(converted[name], short[name])
            for side in (-1, 1):
                equivalent = dict(config, threshold_atr=.05)
                np.testing.assert_array_equal(decision(short, config, side), decision(converted, equivalent, side))
                checks += 1
            for count in sorted({max(2, int(n*x)) for x in (.25, .5, .75)}):
                prefix = {name: value[:count].copy() for name, value in short.items()}
                shortened = strategy.scaled_features(config, dict(short=prefix))['short']
                for name in short:
                    np.testing.assert_array_equal(converted[name][:count], shortened[name])
                checks += 1
            assert digest(short) == original_hash
        rows.append(dict(セッション=key[0], 銘柄=key[1], 行数=n, 強度比較と未来切断=checks,
                         共有列全て不変=True, H005元値完全一致=True))
    output = dict(全合格=True, 人工境界件数=boundary_count, 原本口座数=len(rows),
                  検査比較数=sum(r['強度比較と未来切断'] for r in rows),
                  全12条件=True, 売買損益生成=False, prepared_SHA256=proof['出力SHA256'],
                  実装SHA256={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in (WORK/'catalog.py', WORK/'strategy.py', HERE/'support_checks.py')},
                  検査=rows, 限界='公開特徴自体の因果抽出はround3の監査に依拠。今回の検査は換算と条件付加の非未来参照・共有列不変を独立確認する。')
    (HERE/'支持強度の人工境界と全口座特徴未来切断.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('人工境界', boundary_count, '全口座', len(rows), '全条件比較', output['検査比較数'], '合格', flush=True)


if __name__ == '__main__':
    main()
