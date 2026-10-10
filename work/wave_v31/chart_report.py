"""H019の全35固定対照を、同じ診断再生の台帳から暗色チャートへ描く。"""

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
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    javascript = (HERE.parent / 'wave_v23' / 'chart.js').read_text(encoding='utf-8').replace('<th>監視手法</th>', '<th>建玉</th>').replace('チャートは実際の約定値を', 'チャートは再生上の約定値を')
    javascript = javascript.replace("hour12:false", "hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'")
    javascript = javascript.replace('bottom = h - 40', 'bottom = h - 98')
    anchor = "    const net = trades.reduce((sum,t)=>sum+t[6],0);"
    assert javascript.count(anchor) == 1
    bands = '''    // ----------------------------------------
    // 入口の許可と二つの中期方向を別の帯で表示する。帯は保有枚数ではない。
    const states=data.states[`${method.value}|${session.value}|${symbol.value}`];
    const palettes=[{'-1':'#914355','0':'#172637','1':'#318464'},{'-1':'#8964ab','0':'#172637','1':'#427bbe'},{'-1':'#be774c','0':'#172637','1':'#53a9ad'}];
    for(let row=0;row<3;row++){
      const yy=bottom+15+row*15;
      for(let i=0;i<states.length;i++){
        const start=Math.max(first,states[i][0]),end=Math.min(last,i+1<states.length?states[i+1][0]:last);
        if(end>start){g.fillStyle=palettes[row][states[i][row+1]];g.fillRect(x(start),yy,Math.max(1,x(end)-x(start)),10);}
      }
      g.fillStyle='#bbcbdc';g.fillText(['入口','両市場C','自己S'][row],5,yy+9);
    }
'''
    javascript = javascript.replace(anchor, bands + anchor)
    after_summary = "    document.getElementById('trade-table').innerHTML = "
    assert javascript.count(after_summary) == 1
    javascript = javascript.replace(after_summary, "    document.getElementById('chart-summary').textContent += ({'entry':' 退出は価格注文のみ。C/S帯は参考表示。','main':' 保有撤回には両市場Cを使用。','own':' 保有撤回には自己Sを使用。'}[data.contexts_used[method.value]]);\n" + after_summary)
    note = '図示は結果前にH019の全35条件へ固定しました。採用・推奨を意味しません。Vは方向情報を遅延、Wは同じ解放時点まで待って現在情報を使います。両者の初回約定・その後の保有時間は同じとは限りません。'
    html = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>方向情報の鮮度：５分足と売買</title><style>
    :root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0a111b;color:#e6edf6}body{max-width:1250px;margin:auto;padding:28px 18px;line-height:1.7}a{color:#88c6ff}h1{font-size:26px}p{margin:12px 0}.muted{color:#a7b8ca}.good{color:#66d9b1}.bad{color:#ff929e}select{max-width:100%;background:#142438;color:#e6edf6;font:inherit;padding:6px;border:1px solid #577390}.controls{display:flex;flex-wrap:wrap;gap:15px;align-items:center}canvas{width:100%;height:490px;background:#0c1522;border:1px solid #2a4057;border-radius:8px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}th,td{padding:8px 10px;border-bottom:1px solid #2a394b;text-align:right}th{background:#172637;color:#bcd0e6}details{margin:20px 0}summary{cursor:pointer}
    .controls label{min-width:0;max-width:100%}.controls label:first-child{width:100%}#method{display:block;width:100%;box-sizing:border-box}
    </style><body><p><a href="方向情報の鮮度と保有継続.html">検証結果へ戻る</a></p><h1>５分足と、新規・返済の位置</h1><p>NOTE</p>
    <p>緑の▲は買い新規、赤の▼は売り新規、黄色の×は返済。線の色は、その決済の利益／損失です。部分返済は同じ新規点から分かれます。</p><p>下の三帯は、変形後の入口・両市場C・自己S。緑・青・水色は買い向き、赤・紫・茶色は売り向き、暗色は中立です。保有枚数を表す帯ではありません。</p><p class="muted">費用０・指定価格約定。TOPIXミニ／NK225マイクロ。５分足は図示用で、判断は確定１分足と解放済み板、執行は生データの行順です。赤字の玉を含む全返済を表示します。現在一回照合のデータは含みません。</p>
    <!--
    [コンポーネント概要]
    #method・#symbol・#session は保存済みの手法・銘柄・セッションを選択します。
    #chart は暗色の確定５分足と売買位置、#chart-summary は選択範囲の収支です。
    #trade-table は全返済の数量・時刻・価格・理由です。外部通信や注文処理はありません。
    -->
    <div class="controls"><label>手法 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div><p id="chart-summary"></p><canvas id="chart" aria-label="確定５分足と全返済"></canvas><details open><summary>全返済の明細</summary><div id="trade-table"></div></details><script id="chart-data" type="application/json">DATA</script><script>JAVASCRIPT</script></body></html>'''.replace('NOTE', escape(note)).replace('DATA', data).replace('JAVASCRIPT', javascript)
    OUT.mkdir(exist_ok=True)
    (OUT / '５分足と売買.html').write_text(html, encoding='utf-8')
    assert freeze() == frozen
    runner.save(HERE / 'chart_audit.json', {'採用候補の図示': False, '結果前固定の例示': True, '手法': picked, '保存済み収支との比較': checks, '固定SHA256': runner.digest(HERE / 'chart_fixed.json'), '台帳元SHA256': runner.digest(source), '外部通信': 0, '現在保存物使用': False})
    print(f'５分足図解: {len(picked)}手法 × {len(inputs)}入力、全収支一致', flush=True)


if __name__ == '__main__':
    main()
