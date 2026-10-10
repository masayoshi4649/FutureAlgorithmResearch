"""固定対照・自動運用・選択固定診断の104表示枠を固有52又は78再生から作る。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import conditional_runner as runner
import chart_wave_design as design
import wave_order_audit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00030_板と両市場による条件付き追跡短縮'
TRACE_COLUMNS = ['time', 'source_row', 'campaign', 'direction', 'A0', 'At', 'used_atr',
                 'stop', 'trail', 'fixed_candidate', 'deterioration_direction', 'evidence_source_row']
PREPARATION_COLUMNS = ['time', 'row', 'prepare_id', 'side', 'level', 'A0', 'expiry_time', 'qty',
                       'shared', 'shadow_prepare_id', 'fill_row', 'fill_time']


def freeze() -> dict:
    """機能: 図生成・独立データ監査・原本5分足を事前対象へ結び付ける。

    引数: なし。返り値: 指紋付き固定内容 (dict)。選択結果は読まない。
    """
    design.prepare()
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    files = [Path(__file__), HERE / 'chart.js', HERE / 'chart_data_audit.py',
             HERE / 'chart_wave_fixed.json', HERE / 'wave_order_audit.py']
    files += [ROOT / 'candle_5min' / symbol / (session + '.csv') for session, symbol in inputs]
    record = {'図示枠': design.SLOTS, '全図示数': 104, '固有再生数候補': [52, 78],
              'TRACE_COLUMNS': TRACE_COLUMNS, 'PREPARATION_COLUMNS': PREPARATION_COLUMNS,
              'SHA256': {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in files}}
    path = HERE / 'chart_fixed.json'
    if path.exists():
        assert runner.read(path) == record
    else:
        runner.save(path, record)
    return record


def trace_samples(ready: dict, result: dict) -> list[list]:
    """機能: 5分時計以前の最後の原本行だけで価格線・ATR・根拠を図示する。

    引数: ready/result (dict)。返り値: 有限値又はNoneの標本 (list[list])。
    """
    a = {name: i for i, name in enumerate(runner.engine.ATR_COLUMNS)}
    c = {name: i for i, name in enumerate(runner.engine.CONDITIONAL_COLUMNS)}
    clock = np.arange(ready['start'], ready['limit'] + 1e-6, 300.)
    if len(clock) == 0 or clock[-1] < ready['limit']:
        clock = np.r_[clock, ready['limit']]
    references = np.searchsorted(ready['time_s'], clock, side='right') - 1
    output = []
    for stamp, row in zip(clock, references):
        if row < 0:
            output.append([float(stamp), -1, -1, 0] + [None] * 8)
            continue
        side = int(result['atr_curve'][row, a['direction']])
        values = [result['atr_curve'][row, a[name]] for name in
                  ('initial_atr', 'current_atr', 'used_width_atr', 'stop_level', 'trail_level')]
        values += [result['conditional_curve'][row, c[name]] for name in
                   ('fixed_candidate', 'deterioration_direction', 'line_evidence_source_row')]
        output.append([float(stamp), int(row), int(result['curve'][row, 7]), side,
                       *[float(value) if side and np.isfinite(value) else None for value in values]])
    return output


def preparation_records(ready: dict, result: dict, shadow: dict) -> dict:
    """機能: 影と実の全準備を約定と分け、元行・属性・新規起点を表示列へ変換する。

    引数: ready/result/shadow (dict)。返り値: 影と実の準備列 (dict[str,list])。
    """
    output = {}
    for label, value in (('shadow', shadow), ('actual', result)):
        fills = {int(r[2]): int(r[1]) for r in value['entry_preparations']}
        rows = []
        for event in value['prepare_events']:
            identity, row, side = map(int, event[:3]); filled = fills.get(identity, -1)
            rows.append([float(ready['time_s'][row]), row, identity, side, float(event[3]), float(event[4]),
                         float(event[5]), int(event[6]), True, identity, filled,
                         float(ready['time_s'][filled]) if filled >= 0 else None])
        output[label] = rows
    assert output['shadow'] == output['actual']
    return output


def synthetic() -> dict:
    """機能: 同時刻asofと、全候補選択時の表示参照・重複数を合成検査する。

    引数: なし。返り値: 成功記録 (dict)。実相場を再生しない。
    """
    a = {name: i for i, name in enumerate(runner.engine.ATR_COLUMNS)}
    c = {name: i for i, name in enumerate(runner.engine.CONDITIONAL_COLUMNS)}
    ready = {'start': 0., 'limit': 600., 'time_s': np.array([1., 300., 300., 599., 601.])}
    trace = np.full((5, len(a)), np.nan); trace[:, a['direction']] = [1, 1, 1, 0, 1]
    for name in ('initial_atr', 'current_atr', 'used_width_atr', 'stop_level', 'trail_level'):
        trace[:, a[name]] = np.arange(5) + 10
    conditions = np.zeros((5, len(c))); curve = np.zeros((5, 8))
    result = {'atr_curve': trace, 'conditional_curve': conditions, 'curve': curve}
    rows = trace_samples(ready, result)
    assert [r[1] for r in rows] == [-1, 2, 3] and rows[1][4] == 12 and rows[2][4:] == [None] * 8
    trace[4] = 900.; conditions[4] = -900.
    assert rows == trace_samples(ready, result)
    for mode in ('A0', 'MIN', *(f'B{i:02d}' for i in range(12))):
        mapping = {(slot, session, symbol): design.source_method(slot, session, mode)
                   for slot in design.SLOTS for session in design.design.SESSIONS for symbol in runner.SYMBOLS}
        assert len(mapping) == 104
        assert len({(v, k[1], k[2]) for k, v in mapping.items()}) == (78 if mode.startswith('B') else 52)
        assert all(mapping['POLICY', s, 'TOPIX'] == 'H019__A0__V000' for s in design.design.SESSIONS[:6])
    return {'全合格': True, '参照切替14選択': True, '同時刻asofと未来改変': True,
            '表示104と固有52又は78を区別': True}


def main() -> None:
    """機能: 後半再生完了後に固有条件だけを照合再生し、104枠の図と全注文を作る。

    引数: --prepare (bool)。返り値: なし (None)。準備時は新損益を読まない。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args(); wave_order_audit.deny_network()
    frozen = freeze(); runner.save(HERE / 'chart_synthetic_audit.json', synthetic())
    if args.prepare:
        print('104表示枠と固有52/78図を固定。新実相場再生なし。', flush=True)
        return
    complete = runner.read(HERE / '主再生の完了.json')
    assert complete['全条件数'] == 840
    selection_path = HERE / '選択固定.json'; selection_hash = runner.digest(selection_path)
    assert complete['選択固定SHA256'] == selection_hash
    selected = runner.read(selection_path)['選択']['selected_exit_mode_id']
    fixed = runner.read(HERE / '探索条件の固定.json')
    specs = {r['id']: r for r in fixed['conditions']}
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes()); runner.input_api.initialize(inputs)
    views = {slot + '|' + session + '|' + symbol: design.source_method(slot, session, selected) + '|' + session + '|' + symbol
             for slot in design.SLOTS for session, symbol in inputs}
    unique = sorted(set(views.values())); assert len(views) == 104 and len(unique) == (78 if selected.startswith('B') else 52)
    names = sorted({key.split('|')[0] for key in unique})
    ledgers = {name: {(r['session'], r['symbol']): r for r in runner.read(HERE / 'ledgers' / (name + '.json.gz'))} for name in names}
    sessions = {name: {(r['session'], r['symbol']): r for r in runner.read(HERE / 'sessions' / (name + '.json.gz'))} for name in names}
    paths = [HERE / folder / (name + '.json.gz') for name in names for folder in ('ledgers', 'sessions')]
    source_hashes = {p.relative_to(HERE).as_posix(): runner.digest(p) for p in paths}
    candles = {}
    for (session, symbol), ready in inputs.items():
        frame = pd.read_csv(ROOT / 'candle_5min' / symbol / (session + '.csv'))
        times = pd.to_datetime(frame.time).map(lambda value: value.timestamp()).to_numpy()
        valid = (times >= ready['start']) & (times <= ready['limit']) & frame['closed'].astype(bool).to_numpy()
        candles[session + '|' + symbol] = [[float(t), *map(float, values)] for t, values in
            zip(times[valid], frame.loc[valid, ['open', 'high', 'low', 'close']].to_numpy())]
        assert candles[session + '|' + symbol]
    cases, details, checks, shadows = {}, [], [], {}
    for plotkey in unique:
        identifier, session, symbol = plotkey.split('|'); key = session, symbol
        ready, spec = inputs[key], specs[identifier]
        config = runner.managers.make_config(fixed['manager'], symbol, ready)
        state, bad, source = runner.columns(spec, key, ready)
        if key not in shadows:
            shadows[key] = runner.shadow_record(ready, state, config, False)
        shadow = shadows[key]; saved = ledgers[identifier][key]; target = sessions[identifier][key]
        assert shadow['result_fingerprints'] == saved['shadow']['result_fingerprints']
        # 保存時の欠値nullを浮動小数NaNへ戻す。欠値を含む辞書の直接比較はしない。
        for field in runner.STORED_FIELDS:
            np.testing.assert_array_equal(np.asarray(shadow[field], dtype=float),
                                          np.asarray(saved['shadow'][field], dtype=float))
        allow = runner.previous.prepare_mask(shadow, len(state))
        result = runner.engine.run(ready, state, config, True, width_mode=spec['width_mode'],
            deterioration=bad, deterioration_source=source, prepare_allow=allow)
        hashes = runner.fingerprints(result); assert hashes == saved['result_fingerprints']
        for name in runner.STORED_FIELDS:
            actual = np.asarray(saved[name], dtype=float).reshape(result[name].shape)
            np.testing.assert_array_equal(result[name], actual)
        control, pairs = runner.control_metrics(result, shadow, config, ready['time_s'])
        assert control == target['control'] and pairs == target['exit_pairs']
        records = runner.wave_metrics.trade_records(ready, result, config['point_value'])
        trades = [[datetime.fromisoformat(r['新規時刻']).timestamp(), datetime.fromisoformat(r['返済時刻']).timestamp(),
            r['direction'], r['枚数'], r['新規価格'], r['返済価格'], r['損益円'], runner.engine.REASONS[r['返済理由番号']],
            '主玉', r['新規行'], r['返済行']] for r in records]
        totals = [sum(r[6] for r in trades), sum(max(r[6], 0.) for r in trades), -sum(min(r[6], 0.) for r in trades),
                  sum(r[3] for r in trades if r[6] > 1e-6), sum(r[3] for r in trades if r[6] < -1e-6),
                  sum(r[3] for r in trades if abs(r[6]) <= 1e-6)]
        np.testing.assert_allclose(totals, [target[k] for k in ('net_yen', 'gross_profit_yen', 'gross_loss_yen',
                                  'profit_units', 'loss_units', 'zero_units')], atol=1e-6, rtol=0)
        events = [[float(ready['time_s'][int(event[0])]), *[float(v) if np.isfinite(v) else None for v in event]]
                  for event in result['trail_events']]
        value = {'method': identifier, 'session': session, 'symbol': symbol, 'trades': trades,
            'tracking': trace_samples(ready, result), 'preparations': preparation_records(ready, result, shadow),
            'events': events, 'control': control, 'net_yen': totals[0], 'phase': '初期6' if session in fixed['選択用6セッション'] else '後半7'}
        cases[plotkey] = value
        details.append({'key': plotkey, **value, '全注文': result['orders'].tolist(), 'result_fingerprints': hashes})
        checks.append({'key': plotkey, '返済件数': len(trades), '新規件数': len(result['entry_preparations']),
                       '追跡進行件数': len(events), '収支円': totals[0], '保存値一致': True})
    payload = {'methods': design.SLOTS, 'sessions': sorted({key[0] for key in inputs}),
        'selected_mode': selected, 'views': views, 'cases': cases, 'candles': candles,
        'trace_columns': TRACE_COLUMNS, 'preparation_columns': PREPARATION_COLUMNS,
        'event_columns': ['time', *runner.engine.TRAIL_EVENT_COLUMNS]}
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    script = (HERE / 'chart.js').read_text(encoding='utf-8')
    html = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>条件付き追跡短縮・５分足と売買</title>
<style>body{background:#09111c;color:#dce6ef;font:15px/1.6 system-ui;margin:22px}a{color:#8ecfff}h1{font-size:24px}select{background:#142337;color:#e5edf5;border:1px solid #49647d;padding:7px;max-width:100%}.controls{display:flex;gap:18px;flex-wrap:wrap}canvas{width:100%;height:620px;background:#0c1522;border:1px solid #293d52}details{background:#101e2e;margin:12px 0;padding:10px}.scroll{overflow:auto}table{border-collapse:collapse;white-space:nowrap}th,td{padding:6px 9px;border-bottom:1px solid #2b4055;text-align:right}.muted{color:#9bafc3}.good{color:#70e8b1}.bad{color:#ff8c9e}</style>
<body><a href="板と両市場による条件付き追跡短縮.html">結果へ戻る</a><h1>５分足と売買</h1>
<p>新規位置を揃えて、退出がどこで変わるかを比較します。自動選択運用は前6区間が固定A0、後7区間だけ選択方式です。</p>
<!--
[コンポーネント概要]
#method/#session/#symbol は事前固定した表示枠・セッション・銘柄を選択します。
#chart は確定足と全約定、過去asof価格線を描きます。#chart-summary は実参照方式と収支です。
#trade-table は全返済、#event-table は線が実際に進んだ根拠、#preparation-table は全新設を表示します。
外部通信と注文操作は行わず、policyは凍結された方式への期間別参照だけです。
-->
<div class="controls"><label>方式 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div>
<p id="chart-summary"></p><canvas id="chart" aria-label="５分足と全新規返済と追跡線"></canvas>
<details><summary>凡例と執行条件</summary><p>買い▲は緑、売り▼は赤、返済×は黄。固定追跡候補は青灰、最終追跡線は金、初期予算由来の損切り線は桃。下段はA0水色・At紫。短縮によって線を進めた地点は紫の点です。</p><p>線の点は5分時計以前の最後の原本行。破線は表示補助で、5分内を再現する線ではありません。判断後の新線は次原本行から有効。新規・返済と実線進行イベントは全件を表示します。</p><p>費用0・指定価格約定。TOPIX初回5枚/NK初回10枚。全13は既知データで現在データを含みません。選択方式の全期間固定は診断であり、自動運用の実績ではありません。</p></details>
<details open><summary>全返済の明細</summary><div id="trade-table"></div></details>
<details><summary>実際に追跡線を進めた根拠</summary><div id="event-table"></div></details>
<details><summary>影と一致する全新規準備・約定起点</summary><div id="preparation-table"></div></details>
<script id="chart-data" type="application/json">DATA</script><script>JAVASCRIPT</script></body></html>'''.replace('DATA', data).replace('JAVASCRIPT', script)
    OUT.mkdir(exist_ok=True); (OUT / '５分足と売買.html').write_text(html, encoding='utf-8')
    runner.save(HERE / 'chart_details.json.gz', {'図': details, '表示参照': views,
        '選択固定SHA256': selection_hash, '固定SHA256': runner.digest(HERE / 'chart_fixed.json')})
    assert runner.digest(selection_path) == selection_hash
    assert freeze() == frozen
    for name, expected in source_hashes.items():
        assert runner.digest(HERE / name) == expected
    runner.save(HERE / 'chart_audit.json', {'全図示数': 104, '固有再生数': len(unique),
        '全収支一致': True, '全返済一致': True, '全台帳一致': True, '全原本asof一致': True,
        '全仮想準備一致': True, '全実準備一致': True, '全準備起点一致': True, '全追跡根拠一致': True,
        '保存済み収支との比較': checks, '選択方式': selected, '選択固定SHA256': selection_hash,
        '台帳元SHA256': source_hashes, '固定SHA256': runner.digest(HERE / 'chart_fixed.json'),
        'API取得数': 0, '現在保存物使用': False})
    print('104表示枠、固有', len(unique), '再生の保存値照合完了。', flush=True)


if __name__ == '__main__':
    main()
