"""事前固定の主6方式について、全156入力の売買と選択IDの帯を暗色で表示する。"""

from __future__ import annotations

import argparse
from datetime import datetime
from html import escape
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import episode_audit as episode

runner, HERE = episode.runner, Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00027_順張りと反転の機械的選択'


def freeze() -> dict:
    """機能: 図の対象主6条件と実装・確定5分足の指紋を固定する。

    引数: なし。返り値: 固定記録 (dict)。主成績を読まない。
    """
    rules = runner.read(HERE / 'selection_participation_fixed.json')
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    files = [Path(__file__), HERE / 'episode_audit_fixed.json', HERE / 'selection_participation_fixed.json', HERE.parent / 'wave_v23/chart.js']
    files += [ROOT / 'candle_5min' / symbol / (session + '.csv') for session, symbol in inputs]
    record = {'手法': rules['図示対象'], '全図示数': 156,
              '帯の意味': '要求ID・適用ID・実入口源は1=T/2=R。買い売り方向・保有枚数ではない。',
              '選び方': '結果前固定の主6方式全て。148から成績で絞ったものではない。',
              'SHA256': {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in files}}
    destination = HERE / 'chart_fixed.json'
    if destination.exists():
        assert runner.read(destination) == record
    else:
        runner.save(destination, record)
    return record


def main() -> None:
    """機能: 独立診断と同じ再生の図材料から、全売買図と照合結果を作る。

    引数: --prepare (bool)。返り値: なし (None)。売買の追加再生なし。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    episode.deny_network()
    frozen = freeze()
    if args.prepare:
        print('主6条件×26の図156を結果前の対象どおり固定。図示・売買再生なし。', flush=True)
        return
    fixed = runner.read(HERE / '探索条件の固定.json')
    methods = {row['id']: row['name'] for row in fixed['conditions'] if row['id'] in frozen['手法']}
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    candles, trades, bands, checks, source_hashes = {}, {}, {}, [], {}
    for (session, symbol), ready in inputs.items():
        frame = pd.read_csv(ROOT / 'candle_5min' / symbol / (session + '.csv'))
        times = pd.to_datetime(frame.time).map(lambda value: value.timestamp()).to_numpy()
        valid = (times >= ready['start']) & (times <= ready['limit']) & frame['closed'].astype(bool).to_numpy()
        candles[session + '|' + symbol] = [[float(t), *map(float, row)] for t, row in zip(times[valid], frame.loc[valid, ['open', 'high', 'low', 'close']].to_numpy())]
        assert candles[session + '|' + symbol]
    for identifier in frozen['手法']:
        path = HERE / 'selection_participation_details' / (identifier + '.json.gz')
        source = runner.read(path)
        source_hashes[str(path.relative_to(HERE))] = runner.digest(path)
        assert source['計測固定SHA256'] == runner.digest(HERE / 'episode_audit_fixed.json')
        assert len(source['図示用']) == 26
        expected = {(row['session'], row['symbol']): row for row in runner.read(HERE / 'sessions' / (identifier + '.json.gz'))}
        for chart in source['図示用']:
            key = identifier + '|' + chart['session'] + '|' + chart['symbol']
            rows = []
            for trade in chart['全返済']:
                names = {1: 'T', 2: 'R'}
                rows.append([datetime.fromisoformat(trade['新規時刻']).timestamp(), datetime.fromisoformat(trade['返済時刻']).timestamp(),
                             trade['direction'], trade['枚数'], trade['新規価格'], trade['返済価格'], trade['損益円'],
                             runner.engine_selector.REASONS[trade['返済理由番号']],
                             '所有' + names[trade['所有ID']] + '／入口' + names[trade['実入口源ID']],
                             trade['新規行'], trade['返済行']])
            target = expected[(chart['session'], chart['symbol'])]
            values = [sum(r[6] for r in rows), sum(max(r[6], 0.) for r in rows), -sum(min(r[6], 0.) for r in rows)]
            values += [sum(r[3] for r in rows if r[6] > 1e-6), sum(r[3] for r in rows if r[6] < -1e-6), sum(r[3] for r in rows if abs(r[6]) <= 1e-6)]
            np.testing.assert_allclose(values, [target[field] for field in ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units', 'loss_units', 'zero_units')], atol=1e-6, rtol=0)
            order_rows = np.asarray(chart['全約定']).reshape(-1, 8)
            entry_rows = set(order_rows[order_rows[:, 7] == 1, 0].astype(int))
            assert entry_rows == {r[9] for r in rows}
            assert int(order_rows[order_rows[:, 7] == 0, 4].sum()) == sum(r[3] for r in rows)
            assert len(order_rows[order_rows[:, 7] == 0]) == len(rows)
            assert all(set(row[1:]) <= {1, 2} for row in chart['状態'])
            trades[key], bands[key] = rows, chart['状態']
            checks.append({'id': identifier, 'session': chart['session'], 'symbol': chart['symbol'], '返済件数': len(rows),
                           '新規件数': len(entry_rows), '収支円': values[0], '保存値一致': True})
    assert len(checks) == len(trades) == len(bands) == 156
    payload = dict(methods=methods, sessions=sorted({key[0] for key in inputs}), candles=candles, trades=trades, states=bands)
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    javascript = (HERE.parent / 'wave_v23/chart.js').read_text(encoding='utf-8')
    javascript = javascript.replace('<th>監視手法</th>', '<th>所有／実入口源</th>').replace('チャートは実際の約定値を', 'チャートは再生上の約定値を')
    javascript = javascript.replace('hour12:false', "hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'")
    javascript = javascript.replace('bottom = h - 40', 'bottom = h - 98')
    anchor = '    const net = trades.reduce((sum,t)=>sum+t[6],0);'
    assert javascript.count(anchor) == 1
    javascript = javascript.replace(anchor, '''    // ----------------------------------------
    // ID帯は手法の種類だけを示す。買い売り方向とは別の青・紫を用いる。
    const states=data.states[`${method.value}|${session.value}|${symbol.value}`];
    const palette={'1':'#498ee3','2':'#b07ce3'};
    for(let row=0;row<3;row++){
      const yy=bottom+15+row*15;
      for(let i=0;i<states.length;i++){
        const start=Math.max(first,states[i][0]),end=Math.min(last,i+1<states.length?states[i+1][0]:last);
        if(end>start){g.fillStyle=palette[states[i][row+1]];g.fillRect(x(start),yy,Math.max(1,x(end)-x(start)),10);}
      }
      g.fillStyle='#bbcbdc';g.fillText(['要求ID','適用ID','入口源'][row],5,yy+9);
    }
''' + anchor)
    html = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>手法選択：５分足と売買</title><style>
    :root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0a111b;color:#e6edf6}body{max-width:1250px;margin:auto;padding:28px 18px;line-height:1.7}a{color:#88c6ff}h1{font-size:26px}p{margin:12px 0}.muted{color:#a7b8ca}.good{color:#66d9b1}.bad{color:#ff929e}select{max-width:100%;background:#142438;color:#e6edf6;font:inherit;padding:6px;border:1px solid #577390}.controls{display:flex;flex-wrap:wrap;gap:15px;align-items:center}canvas{width:100%;height:490px;background:#0c1522;border:1px solid #2a4057;border-radius:8px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}th,td{padding:8px 10px;border-bottom:1px solid #2a394b;text-align:right}th{background:#172637;color:#bcd0e6}details{margin:20px 0}summary{cursor:pointer}.controls label{min-width:0;max-width:100%}.controls label:first-child{width:100%}#method{display:block;width:100%;box-sizing:border-box}.t{color:#72aef8}.r{color:#c498f3}
    </style><body><p><a href="順張りと反転の機械的選択.html">検証結果へ戻る</a></p><h1>５分足と、新規・返済の位置</h1>
    <p>事前に固定した主6方式 × 全26入力を図示しています。勝った条件だけの表示ではありません。</p>
    <p>緑▲＝買い新規、赤▼＝売り新規、黄色×＝返済。線は緑が利益、赤が損失。部分返済は同じ新規点から分かれます。</p>
    <p>下の3帯は<span class="t">青＝T（中期方向）</span>、<span class="r">紫＝R（短期価格反転）</span>。要求ID／適用ID／実入口源を示し、売買方向・保有枚数ではありません。保有中の入口源は建玉を作った枝です。S004・S005は要求・適用が変わっても、実入口源を片方に固定した取消対照です。</p>
    <p class="muted">費用0・指定価格約定。TOPIXミニ初回5枚／NK225マイクロ初回10枚。図の5分足は表示用で、執行は原本行順。全返済を表示し、現在データは含みません。</p>
    <!--
    [コンポーネント概要]
    #method・#symbol・#session は保存済み主6方式・銘柄・セッションを選びます。
    #chart は確定5分足と全売買、#chart-summary は図の収支です。
    #trade-table は所有者と実入口源を付けた全返済です。外部通信・注文処理はありません。
    -->
    <div class="controls"><label>手法 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div><p id="chart-summary"></p><canvas id="chart" aria-label="確定５分足と全返済と手法ID"></canvas><details open><summary>全返済の明細</summary><div id="trade-table"></div></details><script id="chart-data" type="application/json">DATA</script><script>JAVASCRIPT</script></body></html>'''.replace('DATA', data).replace('JAVASCRIPT', javascript)
    OUT.mkdir(exist_ok=True)
    (OUT / '５分足と売買.html').write_text(html, encoding='utf-8')
    assert freeze() == frozen
    runner.save(HERE / 'chart_audit.json', {'全図示数': 156, '全収支一致': True, '全返済一致': True, '全新規一致': True,
                '状態帯一致': True, '手法': frozen['手法'], '保存済み収支との比較': checks,
                '固定SHA256': runner.digest(HERE / 'chart_fixed.json'), '台帳元SHA256': source_hashes,
                'API取得数': 0, '現在保存物使用': False})
    print('主6方式の156図、全新規・全返済・収支一致。', flush=True)


if __name__ == '__main__':
    main()
