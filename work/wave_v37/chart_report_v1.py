"""固定6方式の全注文・枠操作を確定5分足へ重ね、保存台帳へ全数照合する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import partial_runner as runner
import chart_slot_design as design

HERE = Path(__file__).resolve().parent


def samples(ready: dict, result: dict) -> list:
    """機能: 5分時計以前の最後の原本行から実と影の枚数を標本化する。

    引数: ready/result(dict)。返り値: 時刻・原本行・実枚数・影枚数(list[list])。
    """
    clock = np.arange(ready['start'], ready['limit']+1e-8, 300.)
    if len(clock) == 0 or clock[-1] < ready['limit']: clock = np.r_[clock, ready['limit']]
    refs = np.searchsorted(ready['time_s'], clock, side='right')-1
    return [[float(t), int(i), float(result['curve'][i, 2]+result['curve'][i, 3]) if i >= 0 else 0.,
             float(result['shadow']['curve'][i, 2]+result['shadow']['curve'][i, 3]) if i >= 0 else 0.]
            for t, i in zip(clock, refs)]


def synthetic() -> dict:
    """機能: 同値時刻群・未観測・未来変更に対する数量標本を検査する。

    引数: なし。返り値: 合成監査(dict)。
    """
    ready = dict(start=0., limit=600., time_s=np.array([1., 300., 300., 601.]))
    curve = np.zeros((4, 8)); curve[:, 2] = [5, 3, 4, 0]
    result = dict(curve=curve, shadow=dict(curve=curve.copy()))
    value = samples(ready, result)
    assert value == [[0., -1, 0., 0.], [300., 2, 4., 4.], [600., 2, 4., 4.]]
    result['curve'][3, 2] = 999
    assert value == samples(ready, result)
    return dict(全合格=True, 同時刻最終行=True, 未観測を補完しない=True, 未来変更不変=True)


def html(payload: dict) -> str:
    """機能: 内蔵データだけで動く簡潔な暗色の図ページを作る。

    引数: payload(dict)。返り値: HTML(str)。
    """
    body = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>部分減量と復元・５分足と売買</title>
<style>:root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0a111b;color:#e6edf6}body{max-width:1250px;margin:auto;padding:24px 18px;line-height:1.7}a{color:#88c6ff}h1{font-size:25px}select{max-width:100%;background:#142438;color:#e6edf6;font:inherit;padding:6px;border:1px solid #577390}.controls{display:flex;flex-wrap:wrap;gap:14px}canvas{width:100%;height:590px;background:#0c1522;border:1px solid #2a4057;border-radius:8px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}th,td{padding:8px 10px;border-bottom:1px solid #2a394b;text-align:right}th{background:#172637;color:#bcd0e6}details{background:#101c2a;margin:16px 0;padding:10px}summary{cursor:pointer}</style>
<body><a href="悪化時の部分減量と回復後の数量復元.html">結果へ戻る</a><h1>５分足と売買</h1><p>初回は▲買い／▼売り。橙□で減量、水色◇で復元、黄×で元の返済、赤×で予算返済です。</p>
<!--
[コンポーネント概要]
#method/#symbol/#session は結果前に指定した6方式・銘柄・全13区間を選択します。
#chart は原本確定5分足・全注文・過去asofの保有数量です。
#order-table/#trade-table は省略しない全注文・全返済です。
#adjustment-table は公開根拠と数量操作の予約・取消・約定の対応です。
外部通信と注文送信は行いません。
-->
<div class="controls"><label>方式 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div>
<p id="chart-summary"></p><canvas id="chart" aria-label="確定５分足、全注文、実と元A0の保有枚数"></canvas>
<details><summary>凡例と執行条件</summary><p>下段は水色が実保有、灰色破線が元A0の保有枚数。5分時計以前の最後の原本行を標本化した補助表示です。正確な時刻・価格・枚数は全注文表で確認できます。</p><p>元注文は前行から有効な条件、減量・復元は判断後の次の有効原本行で執行。費用0・指定価格約定。小数量対照も元A0の退出線とRを共有します。全13セッションは既知データです。</p></details>
<details open><summary>全注文</summary><div id="order-table"></div></details><details><summary>全返済と損益</summary><div id="trade-table"></div></details><details><summary>減量・復元の判断根拠</summary><p>根拠行はready配列の公開行番号です。元の管理方向として入口方向を代用していません。</p><div id="adjustment-table"></div></details>
<script id="chart-data" type="application/json">PAYLOAD</script><script>JAVASCRIPT</script></body></html>'''
    return body.replace('PAYLOAD', json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</','<\\/')).replace('JAVASCRIPT',(HERE/'chart.js').read_text(encoding='utf-8'))


def main() -> None:
    """機能: 主保存完了後に6方式だけ再生し、全台帳を照合して156図を作る。

    引数: --prepare(bool)。返り値: なし(None)。対象の成績による選別はしない。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true'); args = parser.parse_args()
    frozen = design.prepare(); runner.save(HERE/'chart_synthetic_audit.json', synthetic())
    if args.prepare: return
    assert runner.read(HERE/'主再生の完了.json')['全条件数'] == 363
    runner.initialize(); specs = {s['id']:s for s in runner.FIXED['conditions']}
    payload = dict(methods=design.METHODS, sessions=sorted({k[0] for k in runner.INPUTS}), candles={},
                   orders={}, trades={}, tracking={}, adjustments={},
                   reason_names=runner.engine.REASONS, adjustment_names=runner.engine.ADJUSTMENT_NAMES)
    hashes = {}; checks = []; detail = []
    for key, ready in runner.INPUTS.items():
        path = runner.ROOT/'candle_5min'/key[1]/(key[0]+'.csv'); hashes[str(path)] = runner.digest(path)
        frame = pd.read_csv(path); times = pd.to_datetime(frame.time).map(lambda t:t.timestamp()).to_numpy()
        mask = (times >= ready['start']) & (times <= ready['limit']) & frame.closed.astype(bool).to_numpy()
        payload['candles']['|'.join(key)] = [[float(t), *map(float, values)] for t, values in zip(times[mask], frame.loc[mask,['open','high','low','close']].to_numpy())]
    for identifier in design.METHODS:
        spec = specs[identifier]
        ledger_path, session_path = (HERE/folder/(identifier+'.json.gz') for folder in ('ledgers','sessions'))
        for path in (ledger_path, session_path): hashes[str(path)] = runner.digest(path)
        ledgers = {(r['session'],r['symbol']):r for r in runner.read(ledger_path)}
        saved = {(r['session'],r['symbol']):r for r in runner.read(session_path)}
        for key, ready in runner.INPUTS.items():
            state,bad,bs,good,gs,valid = runner.columns(spec,key)
            config = runner.base.managers.make_config(runner.FIXED['manager'],key[1],ready)
            result = runner.engine.run(ready,state,config,bad,bs,good,gs,spec['policy'],good_valid=valid)
            assert runner.fingerprints(result) == ledgers[key]['result_fingerprints']
            factor = config['point_value']; time = ready['time_s']; plotkey = identifier+'|'+'|'.join(key)
            orders = [[float(time[int(o[0])]), *o.tolist()] for o in result['orders']]
            trades = [[float(time[int(t[6])]),float(time[int(t[7])]),int(t[2]),int(t[3]),float(t[4]),float(t[5]),float(t[10]*factor),int(t[9]),int(t[6]),int(t[7])] for t in result['trades']]
            adjustments = [[float(time[int(a[0])]),int(a[0]),int(a[1]),int(a[2]),int(a[3]),int(a[4]),int(a[5]),int(a[6]),int(a[7]),float(time[int(a[5])]) if a[5]>=0 else None] for a in result['adjustment_events']]
            sample = samples(ready,result)
            totals = [sum(t[6] for t in trades),sum(max(t[6],0) for t in trades),-sum(min(t[6],0) for t in trades),sum(t[3] for t in trades if t[6]>1e-6),sum(t[3] for t in trades if t[6]<-1e-6),sum(t[3] for t in trades if abs(t[6])<=1e-6)]
            np.testing.assert_allclose(totals,[saved[key][k] for k in ('net_yen','gross_profit_yen','gross_loss_yen','profit_units','loss_units','zero_units')],rtol=0,atol=1e-6)
            for name, value in (('orders',orders),('trades',trades),('tracking',sample),('adjustments',adjustments)): payload[name][plotkey]=value
            checks.append(dict(id=identifier,session=key[0],symbol=key[1],orders=len(orders),trades=len(trades),adjustments=len(adjustments),net_yen=totals[0],全保存値一致=True))
            detail.append(dict(id=identifier,session=key[0],symbol=key[1],asof=sample,全配列SHA256=runner.fingerprints(result)))
        print('固定図照合',identifier,flush=True)
    assert len(checks) == len(payload['orders']) == 156
    design.OUT.mkdir(exist_ok=True); path = design.OUT/'５分足と売買.html'; path.write_text(html(payload),encoding='utf-8')
    for source, sha in hashes.items(): assert runner.digest(Path(source)) == sha
    runner.save(HERE/'chart_details.json.gz',detail)
    runner.save(HERE/'chart_audit.json',dict(全図示数=156,全収支一致=True,全返済一致=True,全注文一致=True,
        全台帳一致=True,全数量asof一致=True,入力方向を数量判断と誤表示しない=True,結果=checks,
        固定SHA256=runner.digest(HERE/'chart_slot_fixed.json'),ソースSHA256=hashes,HTML_SHA256=runner.digest(path),
        API取得数=0,現在保存物使用=False))


if __name__ == '__main__':
    main()
