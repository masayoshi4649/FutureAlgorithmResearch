"""旧図示の描画部だけを読み取り、鮮度診断用の新しい生成器を作る。"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
original = (HERE.parent / 'wave_v30' / 'chart_report.py').read_text(encoding='utf-8')
tail = original[original.index('    data = json.dumps(payload'):]
tail = tail.replace("成績順で絞らず、全84条件を表示しています。採用・推奨を意味しません。入口は共通でも、早期返済で次のエントリーは変わります。",
                    "図示は結果前にH019の全35条件へ固定しました。採用・推奨を意味しません。Vは方向情報を遅延、Wは同じ解放時点まで待って現在情報を使います。両者の初回約定・その後の保有時間は同じとは限りません。")
tail = tail.replace('相手不一致と保有撤回：５分足と売買', '方向情報の鮮度：５分足と売買')
tail = tail.replace('相手不一致と保有撤回.html', '方向情報の鮮度と保有継続.html')
tail = tail.replace('下の三帯は、入口・両市場C・自己S。', '下の三帯は、変形後の入口・両市場C・自己S。')
tail = tail.replace("    runner.save(HERE / 'chart_audit.json', {'採用候補の図示': accepted, '手法': picked, '保存済み収支との比較': checks, '外部通信': 0})",
                    "    assert freeze() == frozen\n    runner.save(HERE / 'chart_audit.json', {'採用候補の図示': False, '結果前固定の例示': True, '手法': picked, '保存済み収支との比較': checks, '固定SHA256': runner.digest(HERE / 'chart_fixed.json'), '台帳元SHA256': runner.digest(source), '外部通信': 0, '現在保存物使用': False})")
header = '''"""H019の全35固定対照を、同じ診断再生の台帳から暗色チャートへ描く。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import pickle
from html import escape
from pathlib import Path
import socket
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import episode_audit as episode
runner = episode.runner
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査' / '00026_方向情報の鮮度と保有継続'


def freeze() -> dict:
    """機能: 図示35条件と生データ5分足の指紋を結果前に固定する。

    引数: なし。返り値: 固定記録 (dict)。対象は成績によらないH019全条件。
    """
    fixed = runner.read(HERE / '探索条件の固定.json')
    picked = [row['id'] for row in episode.catalog(fixed) if row['signal']['id'] == 'H019']
    assert len(picked) == 35
    inputs = pickle.loads((HERE.parent / 'wave_v23' / 'inputs.pkl').read_bytes())
    paths = [Path(__file__), HERE / 'episode_audit_fixed.json', HERE / '探索条件の固定.json', HERE.parent / 'wave_v23' / 'chart.js']
    paths += [ROOT / 'candle_5min' / symbol / (session + '.csv') for session, symbol in inputs]
    record = {'手法': picked, '全入力図数': 910, '選び方': '成績を読まずH019の全7管理×全5変形に固定。',
              'SHA256': {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in paths}}
    destination = HERE / 'chart_fixed.json'
    if destination.exists():
        old = runner.read(destination)
        assert {k: v for k, v in old.items() if k != '固定日時'} == record
        return old
    record['固定日時'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    runner.save(destination, record)
    return record


def main() -> None:
    """機能: 事前固定の910図を保存台帳から作り、主探索の全返済収支と照合する。

    引数: --prepare (bool)。返り値: なし (None)。エンジンの追加再生は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    episode.deny_network()
    frozen = freeze()
    if args.prepare:
        print('図示をH019全35条件×26入力へ固定', flush=True)
        return
    fixed = runner.read(HERE / '探索条件の固定.json')
    items = [row for row in episode.catalog(fixed) if row['signal']['id'] == 'H019']
    picked = frozen['手法']
    source = HERE / 'episode_participation_details' / 'H019.json.gz'
    saved = runner.read(source)
    assert saved['計測固定SHA256'] == runner.digest(HERE / 'episode_audit_fixed.json')
    stored = {row['id']: {(r['session'], r['symbol']): r for r in row['rows']}
              for row in runner.read(HERE / 'sessions' / 'H019.json.gz')}
    inputs = pickle.loads((HERE.parent / 'wave_v23' / 'inputs.pkl').read_bytes())
    candles, trades, names, checks, states, contexts_used = {}, {}, {}, [], {}, {}
    for (session, symbol), ready in inputs.items():
        frame = pd.read_csv(ROOT / 'candle_5min' / symbol / f'{session}.csv')
        stamps = pd.to_datetime(frame.time).map(lambda t: t.timestamp()).to_numpy()
        valid = (stamps >= ready['start']) & (stamps <= ready['limit']) & frame['closed'].astype(bool).to_numpy()
        candles[session + '|' + symbol] = [[float(t), *map(float, row)] for t, row in zip(stamps[valid], frame.loc[valid, ['open', 'high', 'low', 'close']].to_numpy())]
        assert candles[session + '|' + symbol]
    for method in items:
        names[method['id']] = method['name']
        contexts_used[method['id']] = method['manager']['context_source']
    assert len(saved['図示用']) == 910
    for record in saved['図示用']:
        identifier, session, symbol = record['method'], record['session'], record['symbol']
        rows = []
        for trade in record['全返済']:
            rows.append([datetime.fromisoformat(trade['新規時刻']).timestamp(), datetime.fromisoformat(trade['返済時刻']).timestamp(),
                         trade['direction'], trade['枚数'], trade['新規価格'], trade['返済価格'], trade['損益円'],
                         runner.engine.REASONS[trade['返済理由番号']], '主玉' if trade['役割番号'] == 0 else 'カバー'])
        expected = stored[identifier][(session, symbol)]
        net, profit, loss = sum(t[6] for t in rows), sum(max(0., t[6]) for t in rows), -sum(min(0., t[6]) for t in rows)
        positive, negative, zero = (sum(t[3] for t in rows if (t[6] > 1e-6 if side == 1 else t[6] < -1e-6 if side == -1 else abs(t[6]) <= 1e-6)) for side in (1, -1, 0))
        np.testing.assert_allclose([net, profit, loss, positive, negative, zero],
                                   [expected[k] for k in ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units', 'loss_units', 'zero_units')], atol=1e-7, rtol=0)
        key = identifier + '|' + session + '|' + symbol
        trades[key], states[key] = rows, record['状態']
        checks.append({'手法': identifier, 'session': session, 'symbol': symbol, '返済件数': len(rows), '収支円': net, '保存値一致': True})
    assert len(trades) == len(states) == len(checks) == 910
    payload = dict(methods=names, sessions=sorted({k[0] for k in inputs}), candles=candles, trades=trades, states=states, contexts_used=contexts_used)
'''
(HERE / 'chart_report.py').write_text(header + tail, encoding='utf-8')
print('新しい図示生成器を作成。旧コード変更なし。')
