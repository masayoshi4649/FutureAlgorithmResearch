"""一回保存した現在スナップショットの返済済み玉と未返済玉を図示する。"""

from __future__ import annotations

import json
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd

import current_validation as current
import hierarchy_runner as runner

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'アルゴリズム調査' / '00022_中期方向と板の入口を分離'


def main() -> None:
    """機能: 保存物の指紋を確認し、損益を再最適化せず現在の全建玉を可視化する。

    引数: なし。返り値: なし (None)。API取得・再生・新しい手法比較は行わない。
    """
    current.verify_saved()
    live = HERE / 'live'
    result = runner.read(live / 'current_result.json')
    selected = runner.read(HERE / '現在照合候補の固定.json')
    inputs = pickle.loads((live / 'inputs.pkl').read_bytes())
    replays = pickle.loads((live / 'replay.pkl').read_bytes())
    methods = {m['id']: m['name'] for m in selected['候補'] if m['id'].startswith('H')}
    session = result['セッション']
    payload = dict(methods=methods, sessions=[session], candles={}, trades={}, open={}, totals={})
    checks = []
    for (session, symbol), ready in inputs.items():
        bars = pd.read_csv(live / 'candle_5min' / symbol / (session + '.csv'))
        stamps = pd.to_datetime(bars.time).map(lambda t: t.timestamp()).to_numpy()
        valid = bars.closed.eq(True).to_numpy()
        payload['candles'][session + '|' + symbol] = [[float(t), *map(float, row)] for t, row in zip(stamps[valid], bars.loc[valid, ['open', 'high', 'low', 'close']].to_numpy())]
        for identifier in methods:
            replay = replays[(identifier, symbol)]
            multiplier = replay['config']['point_value']
            key = identifier + '|' + session + '|' + symbol
            trades, open_rows = [], []
            for trade in replay['trades']:
                entry, exit_row = int(trade[6]), int(trade[7])
                trades.append([float(ready['time_s'][entry]), float(ready['time_s'][exit_row]), int(trade[2]), int(trade[3]), float(trade[4]), float(trade[5]), float(trade[10] * multiplier), runner.engine.REASONS[int(trade[9])], '主玉' if int(trade[8]) == 0 else 'カバー'])
            for order in replay['orders']:
                if order[7] != 1:
                    continue
                entry = int(order[0])
                closed = sum(int(t[3]) for t in replay['trades'] if int(t[6]) == entry)
                remaining = int(order[4]) - closed
                assert remaining >= 0
                if remaining:
                    mark = float(ready['last'][-1])
                    floating = remaining * int(order[3]) * (mark - order[5]) * multiplier
                    open_rows.append([float(ready['time_s'][entry]), float(ready['time_s'][-1]), int(order[3]), remaining, float(order[5]), mark, float(floating)])
            saved = next(r for r in result['結果'] if r['手法ID'] == identifier and r['銘柄'] == symbol)
            realized = sum(t[6] for t in trades)
            floating = sum(t[6] for t in open_rows)
            np.testing.assert_allclose([realized, floating], [saved['実現収支円'], saved['含み損益円']], atol=1e-7)
            assert sum(t[3] for t in open_rows if t[2] > 0) == saved['保有買い枚数']
            assert sum(t[3] for t in open_rows if t[2] < 0) == saved['保有売り枚数']
            payload['trades'][key], payload['open'][key] = trades, open_rows
            payload['totals'][key] = [realized, floating, realized + floating]
            checks.append({'手法': identifier, '銘柄': symbol, '実現円': realized, '含み円': floating, '未返済枚数': sum(t[3] for t in open_rows), '保存値一致': True})
    javascript = (HERE.parent / 'wave_v23' / 'chart.js').read_text(encoding='utf-8')
    anchor = "    const box = canvas.getBoundingClientRect();"
    assert javascript.count(anchor) == 1
    javascript = javascript.replace(anchor, "    const keyNow = `${method.value}|${session.value}|${symbol.value}`;\n    const open = data.open[keyNow];\n" + anchor)
    javascript = javascript.replace(".concat(trades.flatMap(t=>[t[4], t[5]]));", ".concat(trades.flatMap(t=>[t[4], t[5]]),open.flatMap(t=>[t[4],t[5]]));")
    anchor = "    const net = trades.reduce((sum,t)=>sum+t[6],0);"
    draw_open = '''    // ----------------------------------------
    // 未返済玉は破線と白い丸で現在値へつなぎ、返済を意味する黄色の×を付けない。
    for (const t of open) {
      g.strokeStyle=t[6]>=0?'#57e0a1':'#ff8496';g.setLineDash([5,4]);
      g.beginPath();g.moveTo(x(t[0]),y(t[4]));g.lineTo(x(t[1]),y(t[5]));g.stroke();g.setLineDash([]);
      g.strokeStyle='#eef4ff';g.beginPath();g.arc(x(t[1]),y(t[5]),5,0,Math.PI*2);g.stroke();
      const key=`${t[0]}|${t[2]}|${t[4]}`;
      if(!seen.has(key)){g.fillStyle=t[2]>0?'#53ffb1':'#ff6687';const xx=x(t[0]),yy=y(t[4]),dir=t[2];g.beginPath();g.moveTo(xx,yy);g.lineTo(xx-5,yy+dir*11);g.lineTo(xx+5,yy+dir*11);g.closePath();g.fill();}
    }
'''
    assert javascript.count(anchor) == 1
    javascript = javascript.replace(anchor, draw_open + anchor)
    javascript = re.sub(r"    document\.getElementById\('chart-summary'\)\.textContent = .*?;\n", "    const totals=data.totals[keyNow];\n    document.getElementById('chart-summary').textContent=`実現 ${totals[0].toLocaleString('ja-JP')}円 ／ 含み ${totals[1].toLocaleString('ja-JP')}円 ／ 合算 ${totals[2].toLocaleString('ja-JP')}円。未返済 ${open.reduce((s,t)=>s+t[3],0)}枚。` ;\n", javascript, count=1)
    anchor = "    document.getElementById('trade-table').innerHTML"
    open_table = '''    document.getElementById('open-table').innerHTML='<div class="scroll"><table><tr><th>未返済の方向</th><th>枚数</th><th>新規時刻</th><th>新規価格</th><th>現在値時刻</th><th>現在値</th><th>含み損益 円</th></tr>'+open.map(t=>`<tr><td>${t[2]>0?'買い':'売り'}</td><td>${t[3]}</td><td>${stamp(t[0])}</td><td>${t[4]}</td><td>${stamp(t[1])}</td><td>${t[5]}</td><td>${t[6].toLocaleString('ja-JP')}</td></tr>`).join('')+'</table></div>';
'''
    javascript = javascript.replace(anchor, open_table + anchor).replace('<th>監視手法</th>', '<th>建玉</th>')
    previous_html = (OUT / '５分足と売買.html').read_text(encoding='utf-8')
    style = re.search(r'<style>(.*?)</style>', previous_html, flags=re.S).group(1)
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    html = '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>現在一回照合の５分足と建玉</title><style>' + style + '</style><body><p><a href="中期方向と入口の検証.html">検証結果へ戻る</a></p><h1>現在一回照合：５分足と建玉</h1><p>2026/09/29 ナイト、21:00締切の保存データ。17:25以降が今回初取得の区間です。自動更新・再取得はしません。</p><p>▲買い・▼売り、黄色の×は返済。破線と白い丸は<strong>未返済玉の現在値評価</strong>で、決済ではありません。線色はその玉の利益／損失です。費用０・指定価格約定。</p><!-- [コンポーネント概要] #method/#symbol/#session は保存範囲の選択。#chart は確定５分足、#open-table は未返済玉、#trade-table は全返済。外部通信なし。 --><div class="controls"><label>手法 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div><p id="chart-summary"></p><canvas id="chart" aria-label="現在一回照合の５分足と建玉"></canvas><h2>未返済玉</h2><div id="open-table"></div><details open><summary>全返済の明細</summary><div id="trade-table"></div></details><script id="chart-data" type="application/json">' + data + '</script><script>' + javascript + '</script></body></html>'
    (OUT / '現在一回照合の５分足.html').write_text(html, encoding='utf-8')
    runner.save(HERE / 'current_chart_audit.json', checks)
    current.verify_saved()
    print('現在図解：４入力の実現・含み・未返済枚数が一致。追加取得なし。', flush=True)


if __name__ == '__main__':
    main()
