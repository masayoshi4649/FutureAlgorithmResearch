"""保存済みv9取得物だけを使い、今回の一回照合を通信禁止で試験する。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import urllib.request

import numpy as np
import pandas as pd

import live_check as live


def forbidden_network(*args, **kwargs):
    """機能: 試験からネットワークへ出る呼出しを必ず失敗させる。

    引数: args (tuple)、kwargs (dict)。返り値: なし。必ずAssertionError。
    """
    raise AssertionError('この試験ではネットワークは禁止です')


def main() -> None:
    """機能: 別試験領域で保存取得物の再生・区分・排他・凍結不変性を確認する。

    引数: なし。返り値: なし (None)。
    """
    urllib.request.urlopen = forbidden_network
    urllib.request.OpenerDirector.open = forbidden_network
    original_out = live.OUT
    fixture = original_out/'live_fixture_saved'
    fixture.mkdir(parents=True, exist_ok=False)
    live.OUT, live.LIVE, live.FROZEN = fixture, fixture/'live', fixture/'現在照合_凍結記録.json'
    live.LIVE.mkdir()
    source = live.ROOT/'work/wave_v9/live'
    original_record = json.loads((source/'取得記録.json').read_text(encoding='utf-8'))
    configs = live.configuration_map()
    ids = ['S09_E07_X00_Z00', 'S09_E02_X04_Z00', 'S09_E02_X07_Z00', 'S05_E02_X05_Z00', 'S03_E02_X04_Z02']
    selection = dict(採用={'方式': ids[0]}, 固定比較=ids, 現在照合条件=[configs[key] for key in ids])
    live.execution.save(fixture/'最終選択.json', selection)
    assert live.selection_ids(selection)[0] == sorted(ids)
    live.TRACKED = [fixture/'最終選択.json' if p.name == '最終選択.json' else p for p in live.TRACKED]
    sentinel = fixture/'凍結変更検出用.txt'
    sentinel.write_text('変更前', encoding='utf-8')
    live.TRACKED.append(sentinel)
    frozen = dict(fixed_at=live.now_jst().isoformat(), session='2026-09-23_Night',
                  starts_at='2026-09-23T17:00:00+09:00', ends_at='2026-09-24T06:00:00+09:00',
                  known_cutoff='2026-09-23T19:14:00+09:00', selected_ids=sorted(ids),
                  selected_configs=[configs[key] for key in sorted(ids)],
                  files_sha256={p.relative_to(live.ROOT).as_posix(): live.sha256(p) for p in live.TRACKED},
                  説明='保存済みv9取得物を使った通信禁止試験。実際の追加照合ではない。')
    live.execution.save(live.FROZEN, frozen)
    assert live.freeze_check() == frozen
    sentinel.write_text('変更後', encoding='utf-8')
    try:
        live.freeze_check()
    except RuntimeError:
        pass
    else:
        raise AssertionError('凍結対象の変更を検出できませんでした')
    sentinel.write_text('変更前', encoding='utf-8')

    # ----------------------------------------
    # 既存取得物を読み取り専用でコピーする。今回は外部要求を一切作らない。
    record = dict(original_record, known_cutoff=frozen['known_cutoff'], fixed_at=frozen['fixed_at'],
                  manifest_sha256=live.sha256(live.FROZEN), selected_ids=sorted(ids), requests=[], candles=[],
                  説明=frozen['説明'], 試験用=True)
    for item in original_record['requests']:
        original = live.ROOT/item['path']
        relative = original.relative_to(source)
        destination = live.LIVE/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        record['requests'].append(dict(item, path=destination.relative_to(live.ROOT).as_posix()))
    helper = live.load_module('v10_fixture_fetch_helper', live.ROOT/'work/wave_v7/fetch_once.py')
    helper.LIVE = live.LIVE/'work/wave_v9/live/work/wave_v7/live'
    for symbol in live.SYMBOLS:
        for minutes in [1, 5]:
            record['candles'].append(helper.convert_candles(
                live.LIVE/'応答'/f'{symbol}_{minutes}min.json', symbol, minutes, frozen['session'],
                datetime.fromisoformat(frozen['starts_at']), datetime.fromisoformat(frozen['ends_at']),
                datetime.fromisoformat(record['cutoff'])))
        live.validate_book(live.LIVE/'book'/symbol/f"{frozen['session']}.jsonl", symbol,
                           datetime.fromisoformat(frozen['starts_at']), datetime.fromisoformat(record['cutoff']))
    live.execution.save(live.LIVE/'取得記録.json', record)
    live.execution.save(live.LIVE/'一回取得開始.json', record)
    try:
        live.fetch()
    except FileExistsError:
        pass
    else:
        raise AssertionError('取得開始記録による再取得禁止が働きませんでした')
    audit = live.evaluate()
    trades = json.loads((fixture/'現在照合_全取引.json').read_text(encoding='utf-8'))
    known = datetime.fromisoformat(frozen['known_cutoff']).timestamp()
    checked = 0
    for filename, section in [('現在照合_セッション集計.csv', '追加区間の新規転換'),
                              ('現在照合_既知起源集計.csv', '既知区間の転換')]:
        cells = pd.read_csv(fixture/filename)
        for cell in cells.to_dict('records'):
            part = [t for t in trades if t['銘柄'] == cell['銘柄'] and t['方式'] == cell['方式'] and t['評価区分'] == section]
            assert all((t['signal_time_s'] >= known) == (section == '追加区間の新規転換') for t in part)
            closed, opened = [t for t in part if t['closed']], [t for t in part if not t['closed']]
            multiplier = live.execution.MULTIPLIERS[cell['銘柄']]
            net = np.array([t['net_points']*multiplier for t in closed])
            assert cell['取引数'] == len(closed) and cell['未返済数'] == len(opened)
            assert cell['収支円'] == net.sum()
            assert cell['利益円'] == net[net > 0].sum() and cell['損失円'] == -net[net < 0].sum()
            assert cell['評価損益円'] == sum(t['net_points']*multiplier for t in opened)
            checked += 1
    result = dict(試験用=True, ネットワーク関数禁止=True, ネットワーク要求数=0,
                  元データ='v9で取得済みの17:00〜23:22未満', 仮の評価境界=frozen['known_cutoff'],
                  本番評価境界ではない=True, 凍結変更検出=True, 二重取得禁止=True,
                  独立再集計セル数=checked, 区分と損益一致=True, 再生監査=audit)
    live.execution.save(original_out/'現在照合_保存再生単体監査.json', result)
    print(json.dumps(dict(通信数=0, 集計一致=checked, 全取引数=len(trades), 二重取得禁止=True, 凍結変更検出=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
