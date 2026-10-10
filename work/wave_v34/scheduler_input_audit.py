"""旧12入口と追跡ATRの再利用を、売買損益を読まずに独立照合する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V33 = HERE.parent / 'wave_v33'
OLD = HERE.parent / 'wave_v23'
sys.dont_write_bytecode = True
sys.path.insert(0, str(V33))
import input_audit as source


def save(path: Path, value: dict) -> None:
    """機能: 今回作業領域へ監査記録を日本語JSONで保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    assert path.resolve().is_relative_to(HERE.resolve())
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def independent_delay(times: np.ndarray, values: np.ndarray, seconds: float, initial: float | int) -> tuple[np.ndarray, np.ndarray]:
    """機能: 左から進む二ポインタだけで公開済み列の遅延を独立計算する。

    引数: times/values (ndarray)、seconds (float)、initial (float|int)。
    返り値: 遅延値、元行 (tuple[ndarray,ndarray])。0秒は同時刻末尾へ飛ばない。
    """
    if seconds == 0:
        return values.copy(), np.arange(len(times), dtype=np.int64)
    rows = np.full(len(times), -1, np.int64)
    cursor = -1
    for i, timestamp in enumerate(times):
        while cursor + 1 < i and times[cursor + 1] <= timestamp - seconds:
            cursor += 1
        rows[i] = cursor
    output = np.full(values.shape, initial, dtype=values.dtype)
    valid = rows >= 0
    output[valid] = values[rows[valid]]
    return output, rows


def identical(left: tuple, right: tuple) -> None:
    """機能: 値・欠測位置と元原本行の組を厳密照合する。

    引数: left/right (tuple[ndarray,ndarray])。返り値: なし (None)。
    """
    for actual, expected in zip(left, right, strict=True):
        np.testing.assert_array_equal(actual, expected)


def clipped(ready: dict, count: int) -> dict:
    """機能: 未来の原本行だけを切り落とす。

    引数: ready (dict)、count (int)。返り値: 切断入力 (dict)。
    """
    n = len(ready['last'])
    return {k: v[:count] if isinstance(v, np.ndarray) and len(v) == n else v for k, v in ready.items()}


def main() -> None:
    """機能: 旧監査のSHAを結合し全入口・ATR列の再利用を結果前に検査する。

    引数: なし。返り値: なし (None)。新損益と売買台帳は読まない。
    """
    socket.socket.connect = source.reject_network
    socket.create_connection = source.reject_network
    urllib.request.OpenerDirector.open = source.reject_network
    prior = source.read(V33 / 'input_causality_before_pnl.json')
    assert prior['構造監査合格'] and prior['全監査完了']
    assert prior['新損益読取'] is False and prior['売買再生'] is False
    refs = dict(prior['参照SHA256'])
    for path in (Path(__file__), V33 / 'input_causality_before_pnl.json', V33 / 'input_audit.json'):
        refs[path.relative_to(ROOT).as_posix()] = source.digest(path)
    assert refs == {name: source.digest(ROOT / name) for name in refs}
    originals = prior['原本78SHA256']
    assert len(originals) == 78
    assert originals == {name: source.digest(ROOT / name) for name in originals}
    tests = source.synthetic()
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    entries = source.load_entries(inputs)
    assert len(inputs) == 26 and list(entries) == source.IDS
    entry_records, atr_records = [], []
    atr_values = {delay: {} for delay in (0, 300)}
    for key, ready in inputs.items():
        times, atr = ready['time_s'], ready['atr']
        assert np.isfinite(times).all() and np.all(np.diff(times) >= 0)
        original_atr = atr.copy()
        for delay in (0, 300):
            actual = source.make_tracking_atr(ready, delay)
            identical(actual, independent_delay(times, atr, delay, np.nan))
            atr_values[delay][key] = actual[0]
            for fraction in (.37, .73):
                count = max(2, int(len(times) * fraction))
                expected = tuple(v[:count] for v in actual)
                identical(source.make_tracking_atr(clipped(ready, count), delay), expected)
                changed = dict(ready, atr=atr.copy())
                changed['atr'][count:] = 50000.
                identical(tuple(v[:count] for v in source.make_tracking_atr(changed, delay)), expected)
        np.testing.assert_array_equal(atr, original_atr)
        atr_records.append(dict(session=key[0], symbol=key[1], 原本行数=len(times), 入口ATR不変=True,
                                独立過去参照一致=True, prefix2点一致=True, 未来ATR2点一致=True))
        # ----------------------------------------
        # 入口は同じ原本時間で参照するが、原本価格・初期ATR・追跡ATRとは別列に保つ。
        for identifier, group in entries.items():
            state = group[key]
            for delay in (0, 15):
                actual = source.make_entry(ready, state, delay)
                identical(actual, independent_delay(times, state, delay, 0))
                for fraction in (.37, .73):
                    count = max(2, int(len(times) * fraction))
                    expected = tuple(v[:count] for v in actual)
                    identical(source.make_entry(clipped(ready, count), state[:count], delay), expected)
                    changed = state.copy()
                    changed[count:] = np.where(changed[count:] == 0, 1, -changed[count:])
                    identical(tuple(v[:count] for v in source.make_entry(ready, changed, delay)), expected)
            entry_records.append(dict(id=identifier, session=key[0], symbol=key[1], v27_v30_v31同一=True,
                                      独立過去参照一致=True, prefix2点一致=True, 未来方向2点一致=True))
    hashes = {identifier: source.array_hash(group) for identifier, group in entries.items()}
    assert hashes == prior['入口']['入口SHA256']
    tracking_hashes = {str(delay): source.array_hash(group) for delay, group in atr_values.items()}
    assert tracking_hashes == prior['ATR']['追跡ATR配列SHA256']
    assert refs == {name: source.digest(ROOT / name) for name in refs}
    assert originals == {name: source.digest(ROOT / name) for name in originals}
    sessions = sorted({key[0] for key in inputs})
    payload = dict(構造監査合格=True, 全監査完了=True, 新損益読取=False, 売買再生=False,
                   現在保存物使用=False, API取得数=0, 対象入口ID=source.IDS, 全セッション=sessions,
                   初期6セッション=sessions[:6], 共通評価7セッション=sessions[6:], 合成=tests,
                   入口=dict(全区間数=312, rows=entry_records, 入口SHA256=hashes,
                            prefix比較数=1248, 未来方向改変比較数=1248),
                   ATR=dict(全区間数=26, 原本行数=sum(len(r['last']) for r in inputs.values()),
                            rows=atr_records, 追跡ATR配列SHA256=tracking_hashes,
                            prefix比較数=104, 未来ATR改変比較数=104),
                   参照SHA256=refs, 原本78SHA256=originals,
                   継承検査='ATR確定5分足の開始+360秒公開・最少3本・下限2呼値、および12入口の再生成因果性はSHA一致したv33全監査を継承。',
                   注意='CurrentPriceTimeによる原本順代理であり受信時刻の完全再現ではない。仮想運転の因果性は別の注文器・会計監査で検査する。')
    save(HERE / 'input_causality_before_pnl.json', payload)
    (HERE / 'input_audit.md').write_text('# 仮想準備制御の入力監査\n\n旧12入口×26区間と追跡ATRはv33と同一。旧監査の元実装・原本78・入口NPZを前後SHAで照合した。入口0/15秒、追跡ATR0/300秒を独立な二ポインタ参照、2点切断、未来列変更で全件検査した。0秒は同時刻の後続行を使わない。\n\n新損益・売買台帳・現在保存物・APIは使用していない。仮想準備の因果性は注文器を含む別監査の対象であり、この入力監査だけで売買全体の正しさを宣言しない。\n', encoding='utf-8')
    print(dict(構造監査合格=True, 入口区間数=312, ATR区間数=26, 入口prefix数=1248, ATRprefix数=104), flush=True)


if __name__ == '__main__':
    main()
