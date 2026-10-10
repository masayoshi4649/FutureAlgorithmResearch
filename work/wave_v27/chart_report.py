"""第三反復の固定候補を、確定５分足と全返済で図示する。"""

from __future__ import annotations

import json
import pickle
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

import hierarchy_runner as runner

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査' / '00022_中期方向と板の入口を分離'


def main() -> None:
    """機能: 固定済みの候補と台帳を再現し、通信不要の図解を作る。

    引数: なし。返り値: なし (None)。売買条件を再選択せず、全セッションの収支を保存値と照合する。
    """
    fixed = runner.read(HERE / '探索条件の固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert runner.digest(HERE.parent / relative) == expected
    decision = runner.read(HERE / '現在照合候補の固定.json')
    picked = [c['id'] for c in decision['候補'] if c['id'].startswith('H')]
    accepted = bool(picked)
    if not picked:
        picked = [c['id'] for c in runner.read(HERE / '反証前の候補固定.json')['上位30'][:4]]
    picked = list(dict.fromkeys(picked))
    specifications = {s['id']: s for s in fixed['signals']}
    managements = {m['id']: m for m in fixed['managers']}
    inputs = pickle.loads((HERE.parent / 'wave_v23' / 'inputs.pkl').read_bytes())
    candles, trades, names, checks = {}, {}, {}, []
    for (session, symbol), ready in inputs.items():
        frame = pd.read_csv(ROOT / 'candle_5min' / symbol / f'{session}.csv')
        stamps = pd.to_datetime(frame.time).map(lambda t: t.timestamp()).to_numpy()
        valid = (stamps >= ready['start']) & (stamps <= ready['limit']) & frame['closed'].astype(bool).to_numpy()
        candles[session + '|' + symbol] = [[float(t), *map(float, row)] for t, row in zip(stamps[valid], frame.loc[valid, ['open', 'high', 'low', 'close']].to_numpy())]
        assert candles[session + '|' + symbol]
    for identifier in picked:
        signal_id, manager_id = identifier.split('__')
        spec, management = specifications[signal_id], managements[manager_id]
        names[identifier] = spec['name'] + ' / ' + management['name']
        directions = np.load(HERE / 'directions' / f'{signal_id}.npz')
        stored = next(x['rows'] for x in runner.read(HERE / 'sessions' / f'{signal_id}.json.gz') if x['id'] == identifier)
        for (session, symbol), ready in inputs.items():
            config = runner.managers.make_config(management, symbol, ready)
            replay = runner.engine.run(ready, directions[f'{session}|{symbol}'], config, detail=False)
            expected = next(x for x in stored if x['session'] == session and x['symbol'] == symbol)
            rows = []
            for trade in replay['trades']:
                entry, exit_row = int(trade[6]), int(trade[7])
                rows.append([float(ready['time_s'][entry]), float(ready['time_s'][exit_row]), int(trade[2]), int(trade[3]), float(trade[4]), float(trade[5]), float(trade[10] * config['point_value']), runner.engine.REASONS[int(trade[9])], '主玉' if int(trade[8]) == 0 else 'カバー'])
            net = sum(t[6] for t in rows)
            profit = sum(max(0., t[6]) for t in rows)
            loss = -sum(min(0., t[6]) for t in rows)
            np.testing.assert_allclose([net, profit, loss], [expected['net_yen'], expected['gross_profit_yen'], expected['gross_loss_yen']], atol=1e-7)
            trades[identifier + '|' + session + '|' + symbol] = rows
            checks.append({'手法': identifier, 'session': session, 'symbol': symbol, '返済件数': len(rows), '収支円': net, '保存値一致': True})
    payload = dict(methods=names, sessions=sorted({k[0] for k in inputs}), candles=candles, trades=trades)
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    javascript = (HERE.parent / 'wave_v23' / 'chart.js').read_text(encoding='utf-8').replace('<th>監視手法</th>', '<th>建玉</th>').replace('チャートは実際の約定値を', 'チャートは再生上の約定値を')
    note = '固定した採用候補の売買です。' if accepted else '採用基準を満たす手法がなかったため、探索順位の先頭４件を失敗例も含めて示します。採用推奨ではありません。'
    html = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>中期方向と入口：５分足と売買</title><style>
    :root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0a111b;color:#e6edf6}body{max-width:1250px;margin:auto;padding:28px 18px;line-height:1.7}a{color:#88c6ff}h1{font-size:26px}p{margin:12px 0}.muted{color:#a7b8ca}.good{color:#66d9b1}.bad{color:#ff929e}select{max-width:100%;background:#142438;color:#e6edf6;font:inherit;padding:6px;border:1px solid #577390}.controls{display:flex;flex-wrap:wrap;gap:15px;align-items:center}canvas{width:100%;height:490px;background:#0c1522;border:1px solid #2a4057;border-radius:8px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}th,td{padding:8px 10px;border-bottom:1px solid #2a394b;text-align:right}th{background:#172637;color:#bcd0e6}details{margin:20px 0}summary{cursor:pointer}
    </style><body><p><a href="中期方向と入口の検証.html">検証結果へ戻る</a></p><h1>５分足と、新規・返済の位置</h1><p>NOTE</p>
    <p>緑の▲は買い新規、赤の▼は売り新規、黄色の×は返済。線の色は、その決済の利益／損失です。部分返済は同じ新規点から分かれます。</p><p class="muted">費用０・指定価格約定。TOPIXミニ／NK225マイクロ。５分足は図示用で、判断は確定１分足と解放済み板、執行は生データの行順です。赤字の玉を含む全返済を表示します。</p>
    <!--
    [コンポーネント概要]
    #method・#symbol・#session は保存済みの手法・銘柄・セッションを選択します。
    #chart は暗色の確定５分足と売買位置、#chart-summary は選択範囲の収支です。
    #trade-table は全返済の数量・時刻・価格・理由です。外部通信や注文処理はありません。
    -->
    <div class="controls"><label>手法 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div><p id="chart-summary"></p><canvas id="chart" aria-label="確定５分足と全返済"></canvas><details open><summary>全返済の明細</summary><div id="trade-table"></div></details><script id="chart-data" type="application/json">DATA</script><script>JAVASCRIPT</script></body></html>'''.replace('NOTE', escape(note)).replace('DATA', data).replace('JAVASCRIPT', javascript)
    OUT.mkdir(exist_ok=True)
    (OUT / '５分足と売買.html').write_text(html, encoding='utf-8')
    runner.save(HERE / 'chart_audit.json', {'採用候補の図示': accepted, '手法': picked, '保存済み収支との比較': checks, '外部通信': 0})
    print(f'５分足図解: {len(picked)}手法 × {len(inputs)}入力、全収支一致', flush=True)


if __name__ == '__main__':
    main()
