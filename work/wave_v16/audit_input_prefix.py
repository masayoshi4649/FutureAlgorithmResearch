"""生板の先行行数の差を除いて、前回既知区間の入力と全信号が不変であるか確認する。"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def compare_value(left: object, right: object, column: str, offset: int, peer_offset: int) -> None:
    """機能: 非有限値と原本行番号の定数差を扱いながら信号値を再帰的に照合する。

    引数: left/right (object)、column (str)、offset/peer_offset (int)。返り値: なし (None)。
    """
    if isinstance(left, dict):
        assert set(left) == set(right)
        for key in left:
            compare_value(left[key], right[key], key, offset, peer_offset)
    elif isinstance(left, (float, int, np.number)):
        if (column == 'seq' or column.endswith('_seq')) and not column.startswith('peer_') and left >= 0:
            right -= offset
        if column.startswith('peer_') and column.endswith('_seq') and left >= 0:
            right -= peer_offset
        np.testing.assert_allclose(left, right, equal_nan=True, rtol=0, atol=1e-9, err_msg=column)
    else:
        assert left == right, f'信号内容不一致: {column}'


def main() -> None:
    """機能: 03:01 より前の足、全配列、全信号を前回保存入力へ直接照合する。

    引数: なし。返り値: なし (None)。価格・損益を表示せず件数と合否を保存する。
    """
    inventory = json.loads((OUT/'データ棚卸し.json').read_text(encoding='utf-8'))
    with (ROOT/'work/wave_v15/現在入力.pkl').open('rb') as stream:
        old = pickle.load(stream)
    with (OUT/'入力_development.pkl').open('rb') as stream:
        new = pickle.load(stream)
    records = []
    exceptions = []
    cut = pd.Timestamp('2026-09-25T03:01:00+09:00')
    for key, before in old.items():
        session, symbol = key
        after = new[key]
        count = len(before['seq'])
        offset = next(row['先行除外行数'] for row in inventory['前回現在原本の照合'] if row['銘柄'] == symbol)
        peer_offset = next(row['先行除外行数'] for row in inventory['前回現在原本の照合'] if row['銘柄'] != symbol)
        np.testing.assert_array_equal(after['seq'][:count] - offset, before['seq'])
        for column in ['time_s', 'last', 'atr', 'board_side', 'trend_side']:
            np.testing.assert_allclose(after[column][:count], before[column], equal_nan=True, rtol=0, atol=1e-10)
        count_events = 0
        columns = 0
        families = []
        for family, prior in before['families'].items():
            following = after['families'][family]
            keep = following['indices'] < count
            selected = [row for row, ok in zip(following['rows'], keep) if ok]
            old_map = {int(i): row for i, row in zip(prior['indices'], prior['rows'])}
            new_map = {int(i): row for i, row in zip(following['indices'][keep], selected)}
            removed, added = sorted(set(old_map)-set(new_map)), sorted(set(new_map)-set(old_map))
            if removed or added:
                exceptions.append(dict(銘柄=symbol, 系統=family,
                    旧入力のみにある信号=[dict(原本配列位置=i, 公開時刻=pd.Timestamp(old_map[i]['time_s'], unit='s', tz='UTC').tz_convert('Asia/Tokyo').isoformat(), 方向=old_map[i]['side']) for i in removed],
                    今回入力のみにある信号=[dict(原本配列位置=i, 公開時刻=pd.Timestamp(new_map[i]['time_s'], unit='s', tz='UTC').tz_convert('Asia/Tokyo').isoformat(), 方向=new_map[i]['side']) for i in added]))
            for i in sorted(set(old_map) & set(new_map)):
                left, right = old_map[i], new_map[i]
                assert set(left) == set(right), '信号の列が一致しません'
                for column in left:
                    if column == 'event_id':
                        continue
                    compare_value(left[column], right[column], column, offset, peer_offset)
                    columns += 1
            families.append(dict(系統=family, 一致信号数=len(set(old_map)&set(new_map)), 旧のみ=len(removed), 今回のみ=len(added)))
            count_events += len(set(old_map)&set(new_map))
        candle_checks = []
        for interval in [1, 5]:
            left = pd.read_csv(ROOT/f'work/wave_v15/live/candle_{interval}min'/symbol/f'{session}.csv')
            right = pd.read_csv(ROOT/f'candle_{interval}min'/symbol/f'{session}.csv')
            right = right[pd.to_datetime(right.time) + pd.Timedelta(minutes=interval) <= cut].reset_index(drop=True)
            pd.testing.assert_frame_equal(left, right)
            candle_checks.append(dict(分=interval, 一致足数=len(left), 全列一致=True))
        records.append(dict(銘柄=symbol, セッション=session, 先行原本行数=offset, 入力一致行数=count,
                            一致配列数=6, 一致信号数=count_events, 一致信号セル数=columns,
                            系統=families, 足照合=candle_checks))
    result = dict(全系統完全一致=not exceptions, 候補N03とN15一致=not any(row['系統'] in ['N03', 'N15'] for row in exceptions),
                  価格ATR状態配列一致=True, 既知足全列一致=True, API取得数=0, 損益計算=False, 既知境界=cut.isoformat(),
                  説明='場前の先行原本行による seq 系列の定数差を補正。event_id は seq を含む文字列のため比較外。共通信号の根拠値・公開位置も直接照合。',
                  例外=exceptions,
                  例外の説明='N17 の１件は、旧実装の他銘柄１分足の読込上限を他銘柄特徴の最終時刻に置くため、短いprefixで利用可能な足が不足する末尾依存。旧ソースは変更せず、全系統一致とはしない。',
                  照合=records)
    (OUT/'既知03時01分入力不変監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
