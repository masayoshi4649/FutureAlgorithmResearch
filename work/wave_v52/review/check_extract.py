"""市場原理の観測器を、独立した小さな原本と未来変更で監査する。"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'measurement/extract.py'
SPEC = importlib.util.spec_from_file_location('measurement_independent_review', SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
START = datetime(2026, 10, 6, 8, 45, tzinfo=timezone(timedelta(hours=9)))


def raw_row(second: int, volume: float | None = 100., last: float = 100.,
            bid_qty: float = 10., ask_qty: float = 10.) -> dict:
    """機能: 独立監査用の整った10段板を1行生成する。

    引数: second(int)、volume(float|None)、last/bid_qty/ask_qty(float)。
    返り値: 生JSONと同じ項目を持つ板(dict)。
    """
    stamp = (START + timedelta(seconds=second)).isoformat()
    raw = dict(CurrentPriceTime=stamp, TradingVolumeTime=stamp,
               CurrentPrice=last, TradingVolume=volume)
    for level in range(1, 11):
        raw[f'Buy{level}'] = dict(Price=100.-level, Qty=bid_qty if level == 1 else 10.)
        raw[f'Sell{level}'] = dict(Price=100.+level, Qty=ask_qty if level == 1 else 10.)
    return raw


def ready_rows(rows: list[dict]) -> dict:
    """機能: 監査用板の最良価格だけを独立に読み、逐次入力を作る。

    引数: rows(list[dict])。返り値: 原本順の有効入力(dict)。
    本体のsnapshot関数を使わず、参照結果との同語反復を避ける。
    """
    sequences, times, prices = [], [], []
    for seq, row in enumerate(rows):
        if not row.get('CurrentPriceTime'):
            continue
        bid, ask = row['Buy1'], row['Sell1']
        if bid['Price'] <= 0 or ask['Price'] <= bid['Price']:
            continue
        if bid['Qty'] <= 0 or ask['Qty'] <= 0 or row['CurrentPrice'] <= 0:
            continue
        sequences.append(seq)
        times.append(datetime.fromisoformat(row['CurrentPriceTime']).timestamp())
        prices.append(row['CurrentPrice'])
    return dict(start=START.timestamp(), limit=START.timestamp()+3600., tick=1.,
                seq=np.asarray(sequences, dtype=np.int64),
                time_s=np.asarray(times), last=np.asarray(prices),
                atr=np.full(len(sequences), 4.))


def extract_rows(rows: list[dict], name: str, cutoff: int | None = None) -> pd.DataFrame:
    """機能: 小原本を書き、監査対象の抽出器へ渡す。

    引数: rows(list[dict])、name(str)、cutoff(int|None)。
    返り値: 公開済み特徴表(DataFrame)。書込先は独立監査フォルダだけ。
    """
    target = HERE / (name+'.jsonl')
    target.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows), encoding='utf8')
    return MODULE.extract(target, ready_rows(rows), cutoff)[0]


def check_final_features() -> dict:
    """機能: 全数独立監査と最終特徴の品質件数・原本SHA・時計を照合する。

    引数: なし。返り値: 全46口座の照合結果(dict)。
    """
    directory = HERE.parent/'measurement'
    features = pickle.loads((directory/'features.pkl').read_bytes())
    extraction = json.loads((directory/'監査.json').read_text(encoding='utf8'))
    independent = json.loads((HERE/'十段品質の全数監査.json').read_text(encoding='utf8'))
    raw = {(r['セッション'], r['銘柄']): r for r in independent['原本別']}
    recorded = {(r['セッション'], r['銘柄']): r for r in extraction['原本別']}
    assert set(features) == set(raw) == set(recorded)
    for key, frame in features.items():
        assert raw[key]['原本SHA256'] == recorded[key]['原本SHA256']
        assert int(frame.depth_duplicate_events.sum()) == raw[key]['重複価格']
        assert int(frame.depth_disordered_events.sum()) == raw[key]['価格順不正']
        assert int(frame.depth_incomplete_events.sum()) == raw[key]['十段欠測']
        np.testing.assert_array_equal(frame.exec_buy+frame.exec_sell+frame.exec_unknown, frame.source_volume_delta)
        assert (frame.source_last_seq < frame.seq).all()
        assert (frame.source_time_s < frame.time_s).all()
        assert (frame.volume_time_s <= frame.time_s).all()
    result = dict(合格=True, 口座数=len(features), 特徴行数=sum(map(len, features.values())),
                  原本SHAが独立走査と全件一致=True, 十段不備64行が特徴品質件数と一致=True,
                  出来高数量保存=True, 公開より後の情報を参照する特徴行=0,
                  出来高時計が公開時計より未来の特徴行=0,
                  出来高時計が約定時計より未来の原本行=sum(r['出来高時刻が約定時刻より未来'] for r in recorded.values()))
    (HERE/'最終特徴と原本の独立照合.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    return result


def main() -> None:
    """機能: 数量保存、公開順序、欠測、回復上限、未来不変性を監査する。

    引数: なし。返り値: なし(None)。監査JSONへ結果を保存する。
    """
    rows = [raw_row(0), raw_row(0, 105., 101.),
            raw_row(1, 105., 101., bid_qty=8.), raw_row(1, 108., 99., bid_qty=12.),
            raw_row(2, 110., 100., bid_qty=12., ask_qty=7.),
            raw_row(3, 110., 100., bid_qty=12.),
            raw_row(4, None, 100., bid_qty=12., ask_qty=8.),
            raw_row(5, 20., 100., bid_qty=12., ask_qty=8.),
            raw_row(6, 10., 100., bid_qty=12.), raw_row(7, 10.)]
    frame = extract_rows(rows, '合成原本')
    totals = frame.sum(numeric_only=True)
    expected = dict(exec_buy=5., exec_sell=3., exec_unknown=2., source_volume_delta=10.,
                    unavailable_volume_events=2., volume_resets=1.,
                    refill_bid=2., refill_ask=5.,
                    refill_bid_fixed_quote=2., refill_ask_fixed_quote=5.)
    for name, value in expected.items():
        assert totals[name] == value, (name, totals[name], value)
    assert np.array_equal(frame.exec_buy+frame.exec_sell+frame.exec_unknown, frame.source_volume_delta)
    no_volume_row = frame.loc[frame.source_time_s == START.timestamp()+4.].iloc[0]
    assert no_volume_row.noexec_ask_remove == 0., '出来高不明を増分0と誤認'
    reset_row = frame.loc[frame.source_time_s == START.timestamp()+6.].iloc[0]
    assert reset_row.noexec_ask_add == 0., '出来高リセットを増分0と誤認'

    # ----------------------------------------
    # 各切断点で未公開の末尾は捨て、全原本の既公開部分と厳密に比較する。
    prefix_checks = []
    future_checks = []
    for cutoff in range(2, len(rows)):
        partial = extract_rows(rows, '合成原本', cutoff)
        wanted = frame.loc[frame.seq < cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(partial, wanted, check_exact=True, check_dtype=bool(len(partial)))
        prefix_checks.append(dict(切断行=cutoff, 一致行数=len(partial)))
        changed = copy.deepcopy(rows)
        for row in changed[cutoff:]:
            row['CurrentPrice'] += 500.
            for side in ('Buy', 'Sell'):
                for depth in range(1, 11):
                    row[f'{side}{depth}']['Price'] += 500.
                    row[f'{side}{depth}']['Qty'] += 7.
            if row['TradingVolume'] is not None:
                row['TradingVolume'] += 5000.
        after = extract_rows(changed, '未来改変原本')
        pd.testing.assert_frame_equal(after.loc[after.seq < cutoff].reset_index(drop=True), wanted, check_exact=True,
                                      check_dtype=bool(len(wanted)))
        future_checks.append(dict(改変開始行=cutoff, 一致行数=len(wanted)))

    # ----------------------------------------
    # 表示範囲の外へ消えた価格を取消量に数えず、不正板を跨がないことを確認する。
    dropped = [raw_row(0), raw_row(1), raw_row(2)]
    for depth in range(1, 11):
        dropped[1][f'Buy{depth}']['Price'] -= 1.
    dropped_frame = extract_rows(dropped, '段入替原本')
    assert dropped_frame.all_bid_remove.sum() == 0.
    assert dropped_frame.noexec_bid_remove.sum() == 0.
    invalid = [raw_row(0), raw_row(1, 120.), raw_row(2, 130.), raw_row(3, 140.)]
    invalid[1]['Buy1']['Price'] = invalid[1]['Sell1']['Price']
    invalid_frame = extract_rows(invalid, '不正板原本')
    assert invalid_frame.source_volume_delta.sum() == 0., '不正板を跨いで出来高差を作成'

    damaged = [raw_row(0), raw_row(1, bid_qty=8.), raw_row(2, bid_qty=8.),
               raw_row(3), raw_row(4)]
    damaged[2]['Buy2']['Price'] = damaged[2]['Buy3']['Price']
    damaged_frame = extract_rows(damaged, '十段重複原本')
    assert damaged_frame.depth_duplicate_events.sum() == 1.
    assert damaged_frame.depth_disordered_events.sum() == 1.
    assert damaged_frame.all_bid_remove.sum() == 2.
    assert damaged_frame.all_bid_add.sum() == 0.
    assert damaged_frame.refill_bid.sum() == 0., '10段不備の前後を回復として結合'

    # ----------------------------------------
    # 回復は先行した減少残高まで。期限と価格を跨いで重複計上しない。
    history = {}
    assert MODULE.refill(history, 99., -5., 0.) == 0.
    assert MODULE.refill(history, 99., 2., 1.) == 2.
    assert MODULE.refill(history, 99., 9., 2.) == 3.
    assert MODULE.refill(history, 99., 9., 3.) == 0.
    assert MODULE.refill(history, 99., -4., 4.) == 0.
    assert MODULE.refill(history, 98., 4., 5.) == 0.
    assert MODULE.refill(history, 99., 4., 35.) == 0.
    exact = {}
    assert MODULE.refill(exact, 99., -4., 0.) == 0.
    assert MODULE.refill(exact, 99., 4., 30.) == 4.

    # ----------------------------------------
    # 出来高時計が公開時計より未来であれば黙って利用しない。
    invalid_time = [raw_row(0), raw_row(1)]
    invalid_time[0]['TradingVolumeTime'] = (START+timedelta(seconds=10)).isoformat()
    rejected = False
    try:
        extract_rows(invalid_time, '未来出来高時計原本')
    except AssertionError:
        rejected = True
    assert rejected
    no_zone = [raw_row(0), raw_row(1)]
    no_zone[0]['CurrentPriceTime'] = '2026-10-06T08:45:00'
    zone_rejected = False
    try:
        extract_rows(no_zone, 'zone欠損原本')
    except (AssertionError, ValueError):
        zone_rejected = True
    assert zone_rejected
    result = dict(合格=True, 抽出コードSHA256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  数量保存=expected, 出来高欠測は増分ゼロにしない=True,
                  不正板を跨ぐ差分なし=True, 板外消失を取消扱いしない=True,
                  回復上限と期限と価格分離=True, 未来出来高時計は拒否=True,
                  十段重複の品質フラグと前後差分切断=True, timezone欠損は拒否=True,
                  合成原本途中切断=prefix_checks, 合成未来改変=future_checks,
                  限界='合成試験の範囲。実データの全体品質と観測分析は別途点検する。')
    (HERE/'抽出器合成監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))
    if (HERE.parent/'measurement/features.pkl').exists() and (HERE/'十段品質の全数監査.json').exists():
        print(json.dumps(check_final_features(), ensure_ascii=False))


if __name__ == '__main__':
    main()
