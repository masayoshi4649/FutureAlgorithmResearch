"""生板10段の公開行抽出を、売買を実行せず独立に照合する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import released_depth as source

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def write(name: str, value: dict) -> None:
    """機能: 日本語の検査成果を保存する。

    引数: name (str)、value (dict)。返り値: なし (None)。
    """
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def cut_ready(ready: dict, count: int) -> dict:
    """機能: 原本行数で入力を切り、同秒後続を残さない。

    引数: ready (dict)、count (int)。返り値: 切断入力 (dict)。
    """
    n = len(ready['seq'])
    return {key: value[:count].copy() if isinstance(value, np.ndarray) and len(value) == n
            else value for key, value in ready.items()}


def equal(actual: dict, expected: dict, count: int | None = None) -> None:
    """機能: 全列の過去値・形状を完全一致で検査する。

    引数: actual/expected (dict)、count (int|None)。返り値: なし (None)。
    """
    assert set(actual) == set(expected)
    for key in actual:
        target = expected[key] if count is None else expected[key][:count]
        np.testing.assert_array_equal(actual[key], target, err_msg=key)


def reflected(records: dict, frame: pd.DataFrame, anchor: float) -> tuple[dict, pd.DataFrame]:
    """機能: 価格を鏡映し、買い板と売り板を交換する。

    引数: records (dict)、frame (DataFrame)、anchor (float)。
    返り値: 反射した原本行と公開表 (tuple[dict, DataFrame])。
    """
    changed = deepcopy(records)
    for raw in changed.values():
        before = deepcopy(raw)
        for target, old in [('Buy', 'Sell'), ('Sell', 'Buy')]:
            for level in range(1, 11):
                value = deepcopy(before.get(f'{old}{level}'))
                if isinstance(value, dict) and source.number(value.get('Price')) > 0:
                    value['Price'] = anchor-float(value['Price'])
                raw[f'{target}{level}'] = value
    f = frame.copy()
    f['bid'], f['ask'] = anchor-frame.ask, anchor-frame.bid
    f['bid_qty'], f['ask_qty'] = frame.ask_qty, frame.bid_qty
    return changed, f


def fixture() -> tuple[dict, dict, pd.DataFrame]:
    """機能: 同秒後続を含む人工入力を作る。

    引数: なし。返り値: 原本・ready・公開表 (tuple[dict, dict, DataFrame])。
    """
    times = np.array([100., 100., 101., 101., 102., 102., 104., 105.])
    ready = dict(seq=np.arange(8, dtype=np.int64), time_s=times, atr=np.full(8, 2.))
    records = {}
    for seq in range(8):
        raw = {'CurrentPriceTime': datetime.fromtimestamp(times[seq], timezone.utc).isoformat()}
        for level in range(1, 11):
            raw[f'Buy{level}'] = dict(Price=101.-level, Qty=float(10+level+seq))
            raw[f'Sell{level}'] = dict(Price=100.+level, Qty=float(20+level+seq))
        records[seq] = raw
    rows = []
    for seq, old in [(2, 1), (4, 3), (6, 5), (7, 6)]:
        rows.append(dict(seq=seq, time_s=times[seq], source_last_seq=old,
                         source_time_s=times[old], block_delay_seconds=times[seq]-times[old],
                         continuity_reset_count=0., bid=100., ask=101.,
                         bid_qty=11.+seq, ask_qty=21.+seq))
    return records, ready, pd.DataFrame(rows)


def synthetic() -> dict:
    """機能: 品質分離・原本順・未来遮断の反例を検査する。

    引数: なし。返り値: 合格した検査名と件数 (dict)。
    """
    records, ready, frame = fixture()
    base = source.extract_records(records, ready, frame)
    assert base['valid'].tolist() == [False, True, True, True]
    assert base['bid_qty'][0, 9] == records[2]['Buy10']['Qty']
    tests = ['10段目を直接保持', '先頭の未知公開間隔を不適格']
    for kind in ['missing', 'duplicate', 'order', 'negative_qty', 'crossed']:
        rec, f = deepcopy(records), frame.copy()
        if kind == 'missing':
            del rec[4]['Buy10']
        elif kind == 'duplicate':
            rec[4]['Buy10']['Price'] = rec[4]['Buy9']['Price']
        elif kind == 'order':
            rec[4]['Buy8']['Price'], rec[4]['Buy9']['Price'] = rec[4]['Buy9']['Price'], rec[4]['Buy8']['Price']
        elif kind == 'negative_qty':
            rec[4]['Sell7']['Qty'] = -1.
        else:
            rec[4]['Buy1']['Price'] = 102.
            f.loc[f.seq == 4, 'bid'] = 102.
        out = source.extract_records(rec, ready, f)
        assert not out['depth_valid'][1] and not out['valid'][1]
        assert bool(out['price_valid'][1]) == (kind != 'crossed')
        tests.append(f'不正{kind}と価格母集団を区別')
    rec = deepcopy(records)
    rec[5]['Buy1']['Qty'] = 999999.
    equal(source.extract_records(rec, ready, frame), base)
    tests.append('同秒後続原本を先取りしない')
    for col, value in [('continuity_reset_count', 1.), ('source_time_s', 0.)]:
        f = frame.copy()
        f.loc[f.seq == 4, col] = value
        f['block_delay_seconds'] = f.time_s-f.source_time_s
        out = source.extract_records(records, ready, f)
        assert not out['publication_quality'][1]
        tests.append(f'{col}品質不正')
    bad = deepcopy(ready)
    bad['atr'][4] = np.nan
    out = source.extract_records(records, bad, frame)
    assert out['price_valid'][1] and not out['valid'][1]
    tests.append('ATR欠測を価格欠測へ混同しない')
    for count in [3, 4, 5, 6, 7]:
        actual = source.extract_records(records, cut_ready(ready, count), frame)
        equal(actual, base, np.searchsorted(base['seq'], count, side='left'))
    tests.append('同秒前後の5切断')
    for field in ['seq', 'time_s']:
        f = frame.copy()
        f.loc[1, field] += .25 if field == 'time_s' else 1
        try:
            source.extract_records(records, ready, f)
        except AssertionError:
            pass
        else:
            raise AssertionError(f'{field}不一致を拒否しない')
    tests.append('公開seqと時計の対応不正を拒否')
    rec, f = reflected(records, frame, 250.)
    mirror = source.extract_records(rec, ready, f)
    np.testing.assert_array_equal(mirror['bid_prices'], 250.-base['ask_prices'])
    np.testing.assert_array_equal(mirror['bid_qty'], base['ask_qty'])
    np.testing.assert_array_equal(mirror['valid'], base['valid'])
    tests.append('上下反射')
    return dict(全合格=True, 検査数=len(tests), 検査名=tests, 新売買実行=False)


def main() -> None:
    """機能: 既知26原本だけで抽出・因果検査・指紋固定を完了する。

    引数: なし。返り値: なし (None)。API・現在保存物・売買は使用しない。
    """
    specification = dict(対象='既知13セッション26市場入力', 抽出='frame.seqのcurrent公開原本行',
        深さ=10, 可視外='NaN。数量0とは区別', 最良価格品質='数量と深い段に非依存',
        板品質='10段有限価格と非負数量・最良正数量・厳密順序・重複交差なし',
        時計品質='0<素材遅れ<=60・0<前公開gap<=60。先頭gap未知は不適格',
        数量公開品質='時計品質にreset0を加える。価格母集団へreset総数を課さない',
        ATR='同じseqの既存ready公開値を改変せず使用。有限正値だけ適格',
        時刻='CurrentPriceTimeによる近似。受信時刻・真の約定取消は識別不可',
        検査='26全入力×2原本切断・未来改変、26上下反射、全106451前後の原本行対応',
        新売買実行=False, 現在保存物使用=False, API取得数=0)
    write('released_depth_specification.json', specification)
    artificial = synthetic()
    write('released_depth_synthetic.json', artificial)
    old = ROOT/'work/wave_v23'
    inputs = pickle.loads((old/'inputs.pkl').read_bytes())
    frames = pickle.loads((old/'features_depth.pkl').read_bytes())
    hashes = json.loads((old/'入力確認.json').read_text(encoding='utf-8'))['原本SHA256']
    expected = {f'book/{symbol}/{session}.jsonl': hashes[f'book/{symbol}/{session}.jsonl']
                for session, symbol in inputs}
    assert len(inputs) == len(frames) == len(expected) == 26
    before = {path: source.digest(ROOT/path) for path in expected}
    assert before == expected
    outputs, rows = {}, []
    for key, ready in sorted(inputs.items()):
        session, symbol = key
        frame = frames[key]
        path = ROOT/f'book/{symbol}/{session}.jsonl'
        records = source.read_records(path, frame.seq.to_numpy(np.int64))
        value = source.extract_records(records, ready, frame)
        n = len(value['seq'])
        # ----------------------------------------
        # 集計関数を使わず、各公開原本の全20価格数量を直接再照合する。
        independently = {name: np.full((n, 10), np.nan) for name in
                         ['bid_prices', 'ask_prices', 'bid_qty', 'ask_qty']}
        for index, seq in enumerate(value['seq']):
            raw = records[int(seq)]
            for side, pname, qname in [('Buy', 'bid_prices', 'bid_qty'), ('Sell', 'ask_prices', 'ask_qty')]:
                for level in range(1, 11):
                    record = raw.get(f'{side}{level}') or {}
                    price, qty = record.get('Price'), record.get('Qty')
                    ep = float(price) if isinstance(price, (int, float)) and np.isfinite(price) and price > 0 else np.nan
                    eq = float(qty) if np.isfinite(ep) and isinstance(qty, (int, float)) and np.isfinite(qty) and qty >= 0 else np.nan
                    independently[pname][index, level-1] = ep
                    independently[qname][index, level-1] = eq
        for name, expected_array in independently.items():
            np.testing.assert_array_equal(value[name], expected_array)
        for fraction in [.37, .73]:
            count = max(1, int(len(ready['seq'])*fraction))
            prefix = source.extract(path, ready, frame, max_rows=int(ready['seq'][count]))
            m = np.searchsorted(value['seq'], ready['seq'][count], side='left')
            equal(prefix, value, m)
            modified, f = deepcopy(records), frame.copy()
            future_seq = ready['seq'][count]
            for seq in modified:
                if seq >= future_seq:
                    modified[seq]['Buy10']['Qty'] = 123456789.
                    modified[seq]['Sell10']['Qty'] = 987654321.
            r = deepcopy(ready)
            r['atr'][count:] = 87654.
            r['last'][count:] = 123456.
            f.loc[f.seq >= future_seq, 'continuity_reset_count'] = 7.
            future = source.extract_records(modified, r, f)
            equal({k: v[:m] for k, v in future.items()}, value, m)
        anchor = float(4*np.nanmax(value['ask_prices']))
        rec, f = reflected(records, frame, anchor)
        mirror = source.extract_records(rec, ready, f)
        np.testing.assert_allclose(mirror['bid_prices'], anchor-value['ask_prices'], rtol=0, atol=1e-8)
        np.testing.assert_allclose(mirror['ask_prices'], anchor-value['bid_prices'], rtol=0, atol=1e-8)
        for col in ['valid', 'price_valid', 'best_valid', 'depth_valid', 'complete', 'duplicate', 'ordered', 'crossed']:
            np.testing.assert_array_equal(mirror[col], value[col])
        np.testing.assert_array_equal(mirror['bid_qty'], value['ask_qty'])
        np.testing.assert_array_equal(mirror['ask_qty'], value['bid_qty'])
        outputs[key] = value
        rows.append(dict(session=session, symbol=symbol, 公開行数=n,
            構造適格数=int(value['depth_valid'].sum()), 総合適格数=int(value['valid'].sum()),
            価格適格数=int(value['price_valid'].sum()), 十段欠測数=int((~value['complete']).sum()),
            重複数=int(value['duplicate'].sum()), 順序不正数=int((~value['ordered']).sum()),
            交差数=int(value['crossed'].sum()), 公開間隔中央値=float(np.nanmedian(value['previous_release_gap'])),
            全原本行対応一致=True, prefix数=2, future数=2, reflection数=1, 全合格=True))
        print(f'{len(rows)}/26 公開10段・因果検査一致', flush=True)
    (OUT/'released_depth.pkl').write_bytes(pickle.dumps(outputs, protocol=pickle.HIGHEST_PROTOCOL))
    after = {path: source.digest(ROOT/path) for path in expected}
    assert before == after
    refs = [OUT/'released_depth.py', Path(__file__), OUT/'released_depth_specification.json',
            OUT/'released_depth_synthetic.json', old/'inputs.pkl', old/'features_depth.pkl', old/'入力確認.json']
    reference = {str(path.relative_to(ROOT)).replace('\\', '/'): source.digest(path) for path in refs}
    result = dict(全合格=True, 入力数=26, 公開行数=sum(row['公開行数'] for row in rows),
        prefix数=52, future数=52, reflection数=26, 結果=rows, 人工検査=artificial,
        参照SHA256=reference, 原本SHA256=after, 原本不変=True,
        出力SHA256=source.digest(OUT/'released_depth.pkl'), 新売買実行=False, 現在保存物使用=False, API取得数=0)
    write('released_depth_audit.json', result)
    fixed = dict(全合格=True, SHA256={**reference, **after,
        'work/wave_v40/released_depth.pkl': result['出力SHA256'],
        'work/wave_v40/released_depth_audit.json': source.digest(OUT/'released_depth_audit.json')},
        入力数=26, 公開行数=result['公開行数'], 新売買実行=False, 現在保存物使用=False, API取得数=0)
    write('released_depth_fixed.json', fixed)
    print({key: result[key] for key in ['全合格', '入力数', '公開行数']}, flush=True)


if __name__ == '__main__':
    main()
