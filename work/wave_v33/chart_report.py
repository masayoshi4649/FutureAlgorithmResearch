"""固定H019と動的ATRの52入力を同じ5分足上に描き、全台帳とasofを照合する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import atr_runner as runner
import chart_wave_design as design
import wave_order_audit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00028_保有中ATRによる追跡幅更新'
TRACE_COLUMNS = ['time', 'source_row', 'campaign', 'direction', 'A0', 'At', 'used_atr', 'stop', 'trail']


def freeze() -> dict:
    """機能: 固定2条件52図と、元5分足・描画実装の指紋を保存する。

    引数: なし。返り値: 固定記録 (dict)。成績で図示対象を変更しない。
    """
    rules = design.prepare()
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    files = [Path(__file__), HERE / 'chart_wave_fixed.json', HERE.parent / 'wave_v23/chart.js']
    files += [ROOT / 'candle_5min' / symbol / (session + '.csv') for session, symbol in inputs]
    record = {'手法': rules['図示対象'], '全図示数': 52, 'TRACE_COLUMNS': TRACE_COLUMNS,
              'SHA256': {path.relative_to(ROOT).as_posix(): runner.digest(path) for path in files}}
    path = HERE / 'chart_fixed.json'
    if path.exists():
        assert runner.read(path) == record
    else:
        runner.save(path, record)
    return record


def trace_samples(ready: dict, result: dict) -> list[list]:
    """機能: 5分時計以下の最後の原本行だけでA0/At/価格注文を標本化する。

    引数: ready/result (dict)。返り値: 有限値又はNoneの図示列 (list[list])。
    将来原本は使わず、同値時刻はその時刻の最終行を採用する。
    """
    columns = {key: index for index, key in enumerate(runner.engine.ATR_COLUMNS)}
    clock = np.arange(ready['start'], ready['limit'] + 1e-6, 300.)
    if len(clock) == 0 or clock[-1] < ready['limit']:
        clock = np.r_[clock, ready['limit']]
    references = np.searchsorted(ready['time_s'], clock, side='right') - 1
    rows = []
    for stamp, reference in zip(clock, references):
        if reference < 0:
            rows.append([float(stamp), -1, -1, 0, None, None, None, None, None])
            continue
        assert ready['time_s'][reference] <= stamp
        if reference + 1 < len(ready['time_s']):
            assert ready['time_s'][reference + 1] > stamp
        trace = result['atr_curve'][reference]
        side = int(trace[columns['direction']])
        values = [trace[columns[name]] for name in ('initial_atr', 'current_atr', 'used_width_atr', 'stop_level', 'trail_level')]
        rows.append([float(stamp), int(reference), int(result['curve'][reference, 7]), side,
                     *[float(value) if side and np.isfinite(value) else None for value in values]])
    return rows


def synthetic() -> dict:
    """機能: 同値時刻・未観測・フラット・未来値改変でasof標本化を検算する。

    引数: なし。返り値: 合成検査の成功記録 (dict)。実価格再生なし。
    """
    columns = {key: index for index, key in enumerate(runner.engine.ATR_COLUMNS)}
    ready = {'start': 0., 'limit': 600., 'time_s': np.array([1., 300., 300., 599., 601.])}
    trace = np.full((5, len(columns)), np.nan)
    trace[:, columns['direction']] = [1, 1, 1, 0, 1]
    for key in ('initial_atr', 'current_atr', 'used_width_atr', 'stop_level', 'trail_level'):
        trace[:, columns[key]] = np.arange(5) + 10
    curve = np.zeros((5, 8));curve[:, 7] = [0, 0, 0, 0, 1]
    result = {'atr_curve': trace, 'curve': curve}
    rows = trace_samples(ready, result)
    assert [r[1] for r in rows] == [-1, 2, 3]
    assert rows[1][4] == 12 and rows[2][4:] == [None] * 5
    changed = dict(result, atr_curve=trace.copy())
    changed['atr_curve'][4] = 900
    assert rows == trace_samples(ready, changed)
    return {'全合格': True, '検査': ['同時刻の最後の原本行', '未観測に未来値を補完しない', 'フラット時は線を切る', '未来値改変不変']}


def main() -> None:
    """機能: 主再生後に固定52入力だけを照合再生し、原本asof線と全売買を表示する。

    引数: --prepare (bool)。返り値: なし (None)。格子の追加や現在データ使用なし。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    wave_order_audit.deny_network()
    frozen = freeze()
    runner.save(HERE / 'chart_synthetic_audit.json', synthetic())
    if args.prepare:
        print('H019固定/動的の52図と原本asof仕様を固定、合成4件一致。実相場再生なし。', flush=True)
        return
    runner.worker_init()
    fixed = runner.read(HERE / '探索条件の固定.json')
    methods = {row['id']: row for row in fixed['conditions'] if row['id'] in frozen['手法']}
    inputs = runner.INPUTS
    candles, trades, tracking, names, details, checks = {}, {}, {}, {}, [], []
    source_hashes = {}
    for (session, symbol), ready in inputs.items():
        frame = pd.read_csv(ROOT / 'candle_5min' / symbol / (session + '.csv'))
        times = pd.to_datetime(frame.time).map(lambda stamp: stamp.timestamp()).to_numpy()
        valid = (times >= ready['start']) & (times <= ready['limit']) & frame['closed'].astype(bool).to_numpy()
        candles[session + '|' + symbol] = [[float(t), *map(float, values)] for t, values in zip(times[valid], frame.loc[valid, ['open', 'high', 'low', 'close']].to_numpy())]
        assert candles[session + '|' + symbol]
    for identifier in frozen['手法']:
        specification = methods[identifier]
        names[identifier] = '初回ATRで幅固定' if specification['dynamic_trail_atr'] == 0 else '保有中ATRで追跡幅更新'
        lp, sp = HERE / 'ledgers' / (identifier + '.json.gz'), HERE / 'sessions' / (identifier + '.json.gz')
        source_hashes[str(lp.relative_to(HERE))], source_hashes[str(sp.relative_to(HERE))] = runner.digest(lp), runner.digest(sp)
        saved = {(row['session'], row['symbol']): row for row in runner.read(lp)}
        expected = {(row['session'], row['symbol']): row for row in runner.read(sp)}
        for key, ready in inputs.items():
            config = runner.managers.make_config(fixed['manager'], key[1], ready)
            state, at = runner.columns(specification, key, ready)
            result = runner.engine.run(ready, state, config, detail=True, width_mode=specification['dynamic_trail_atr'],
                                       observed_fill=specification['observed_fill'], trail_atr=at)
            for field, width in (('trades', 11), ('orders', 8), ('cycles', 10)):
                np.testing.assert_array_equal(result[field], np.asarray(saved[key][field], dtype=float).reshape(-1, width))
            np.testing.assert_array_equal(result['stats'], saved[key]['stats'])
            assert hashlib.sha256(result['curve'].tobytes()).hexdigest() == saved[key]['curve_SHA256']
            records = runner.wave_metrics.trade_records(ready, result, config['point_value'])
            rows = [[datetime.fromisoformat(row['新規時刻']).timestamp(), datetime.fromisoformat(row['返済時刻']).timestamp(), row['direction'],
                     row['枚数'], row['新規価格'], row['返済価格'], row['損益円'], runner.engine.REASONS[row['返済理由番号']],
                     '主玉', row['新規行'], row['返済行']] for row in records]
            target = expected[key]
            totals = [sum(r[6] for r in rows), sum(max(r[6], 0.) for r in rows), -sum(min(r[6], 0.) for r in rows),
                      sum(r[3] for r in rows if r[6] > 1e-6), sum(r[3] for r in rows if r[6] < -1e-6), sum(r[3] for r in rows if abs(r[6]) <= 1e-6)]
            np.testing.assert_allclose(totals, [target[name] for name in ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units', 'loss_units', 'zero_units')], atol=1e-6, rtol=0)
            sampled = trace_samples(ready, result)
            plot_key = identifier + '|' + key[0] + '|' + key[1]
            trades[plot_key], tracking[plot_key] = rows, sampled
            details.append({'method': identifier, 'session': key[0], 'symbol': key[1], '全返済': records,
                            '全注文': result['orders'].tolist(), 'asof': sampled,
                            '原本atr_curve_SHA256': hashlib.sha256(result['atr_curve'].tobytes()).hexdigest()})
            checks.append({'id': identifier, 'session': key[0], 'symbol': key[1], '返済件数': len(rows),
                           '新規件数': int(np.count_nonzero(result['orders'][:, 7] == 1)), '収支円': totals[0], '保存値一致': True})
    assert len(checks) == len(trades) == len(tracking) == 52
    payload = {'methods': names, 'sessions': sorted({key[0] for key in inputs}), 'candles': candles,
               'trades': trades, 'tracking': tracking, 'trace_columns': TRACE_COLUMNS}
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    script = (HERE.parent / 'wave_v23/chart.js').read_text(encoding='utf-8')
    script = script.replace('<th>監視手法</th>', '<th>建玉</th>').replace('チャートは実際の約定値を', 'チャートは再生上の約定値を')
    script = script.replace('hour12:false', "hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'")
    script = script.replace('bottom = h - 40', 'bottom = h - 155')
    source = '    const prices = bars.flatMap(b=>[b[2], b[3]]).concat(trades.flatMap(t=>[t[4], t[5]]));'
    assert script.count(source) == 1
    script = script.replace(source, '''    const tracking=data.tracking[`${method.value}|${session.value}|${symbol.value}`];
    const prices = bars.flatMap(b=>[b[2], b[3]]).concat(trades.flatMap(t=>[t[4], t[5]])).concat(tracking.flatMap(t=>[t[7],t[8]]).filter(Number.isFinite));''')
    anchor = '    const net = trades.reduce((sum,t)=>sum+t[6],0);'
    assert script.count(anchor) == 1
    script = script.replace(anchor, '''    // ----------------------------------------
    // 5分時計の原本asof標本だけを描く。組が異なる区間とフラットは接続しない。
    /**
     * 保存された標本列を同一組の範囲だけ補助線として描く。
     * @param {number} column - 値の列番号。
     * @param {string} color - 暗色背景用の描画色。
     * @param {Function} vertical - 値を縦座標へ変える関数。
     * @returns {undefined} 描画のみ。
     */
    function drawSamples(column,color,vertical){
      g.strokeStyle=color;g.fillStyle=color;g.lineWidth=1.2;g.setLineDash([4,3]);
      for(let i=0;i<tracking.length;i++){
        const current=tracking[i];
        if(!current[3]||!Number.isFinite(current[column])) continue;
        g.beginPath();g.arc(x(current[0]),vertical(current[column]),1.7,0,Math.PI*2);g.fill();
        if(i+1<tracking.length){
          const next=tracking[i+1];
          if(next[3]&&next[2]===current[2]&&Number.isFinite(next[column])){
            g.beginPath();g.moveTo(x(current[0]),vertical(current[column]));g.lineTo(x(next[0]),vertical(next[column]));g.stroke();
          }
        }
      }
      g.setLineDash([]);g.lineWidth=1;
    }
    drawSamples(7,'#e895b0',y);drawSamples(8,'#e9be55',y);
    const panelTop=bottom+37,panelBottom=h-35;
    const atrValues=tracking.flatMap(t=>[t[4],t[5]]).filter(Number.isFinite);
    const maxAtr=Math.max(1,...atrValues)*1.1;
    const ay=v=>panelBottom-v/maxAtr*(panelBottom-panelTop);
    g.strokeStyle='#283c53';g.strokeRect(left,panelTop,right-left,panelBottom-panelTop);
    g.fillStyle='#bbcbdc';g.fillText('ATR',5,panelTop+11);g.fillText(maxAtr.toFixed(1),7,panelTop+26);
    drawSamples(4,'#61c7e2',ay);drawSamples(5,'#b492f1',ay);
''' + anchor)
    html = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>保有中ATR：５分足と売買</title><style>
    :root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0a111b;color:#e6edf6}body{max-width:1250px;margin:auto;padding:28px 18px;line-height:1.7}a{color:#88c6ff}h1{font-size:26px}p{margin:12px 0}.muted{color:#a7b8ca}.good{color:#66d9b1}.bad{color:#ff929e}select{max-width:100%;background:#142438;color:#e6edf6;font:inherit;padding:6px;border:1px solid #577390}.controls{display:flex;flex-wrap:wrap;gap:15px;align-items:center}canvas{width:100%;height:590px;background:#0c1522;border:1px solid #2a4057;border-radius:8px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}th,td{padding:8px 10px;border-bottom:1px solid #2a394b;text-align:right}th{background:#172637;color:#bcd0e6}details{margin:20px 0}summary{cursor:pointer}.controls label{min-width:0;max-width:100%}
    </style><body><p><a href="保有中ATRによる追跡幅更新.html">検証結果へ戻る</a></p><h1>同じH019入口で、追跡幅だけを比較</h1>
    <p>事前固定の2方式 × 全26入力です。緑▲＝買い新規、赤▼＝売り新規、黄×＝全返済。部分返済は同じ新規点から分かれます。</p>
    <p><span style="color:#e895b0">桃色＝損切り線</span>、<span style="color:#e9be55">金色＝主玉の追跡線</span>。下段は<span style="color:#61c7e2">水色＝固定A0</span>、<span style="color:#b492f1">紫＝保持At</span>。固定方式はA0、更新方式はAtの3倍を追跡幅へ使います。</p>
    <p class="muted">線の点は5分時計以前の最後の原本行です。判断後の価格線は次の原本行から有効。点を結ぶ破線は表示補助で、5分内の更新や約定を補間したものではありません。異なる組やフラットを線で結びません。正確な新規・返済は全マーカーと明細で確認できます。</p>
    <p class="muted">費用0・指定価格約定。TOPIXミニ初回5枚／NK225マイクロ初回10枚。新規・初期損失基準・始動・部分利確はA0固定です。現在データは含みません。</p>
    <!--
    [コンポーネント概要]
    #method・#symbol・#session は固定2方式・銘柄・セッションを選びます。
    #chart は保存確定5分足、全売買、原本asofのATRと価格線です。
    #trade-table は全返済、#chart-summary は同じ範囲の収支です。外部通信や注文処理はありません。
    -->
    <div class="controls"><label>追跡幅 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div><p id="chart-summary"></p><canvas id="chart" aria-label="確定５分足と全返済と公開済みATR"></canvas><details open><summary>全返済の明細</summary><div id="trade-table"></div></details><script id="chart-data" type="application/json">DATA</script><script>JAVASCRIPT</script></body></html>'''.replace('DATA', data).replace('JAVASCRIPT', script)
    OUT.mkdir(exist_ok=True)
    (OUT / '５分足と売買.html').write_text(html, encoding='utf-8')
    runner.save(HERE / 'chart_details.json.gz', {'対象': frozen['手法'], '図': details, '固定SHA256': runner.digest(HERE / 'chart_fixed.json')})
    for name, fingerprint in source_hashes.items():
        assert runner.digest(HERE / name) == fingerprint
    assert freeze() == frozen
    runner.save(HERE / 'chart_audit.json', {'全図示数': 52, '全収支一致': True, '全返済一致': True, '全台帳一致': True,
        '全原本asof一致': True, '保存済み収支との比較': checks, '固定SHA256': runner.digest(HERE / 'chart_fixed.json'),
        '台帳元SHA256': source_hashes, 'API取得数': 0, '現在保存物使用': False})
    print('固定/動的H019の52図、全台帳・全収支・原本asof一致。', flush=True)


if __name__ == '__main__':
    main()
