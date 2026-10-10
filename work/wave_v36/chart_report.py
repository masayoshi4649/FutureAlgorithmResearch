"""固定4方式の全26入力を旧注文器で照合し、確定5分足と全売買を描く。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import band_runner as runner
import chart_wave_design as design
import wave_order_audit

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00031_出来高通過と気配維持からの方向判定'
TRACE_COLUMNS=['time','source_row','campaign','direction','A0','At','used_atr','stop','trail']


def freeze() -> dict:
    """機能: 図生成・検算・確定足と事前対象104図を固定する。

    引数: なし。返り値: 固定記録 (dict)。新損益は読まない。
    """
    rules=design.prepare()
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    files=[Path(__file__),HERE/'chart.js',HERE/'chart_data_audit.py',HERE/'chart_wave_fixed.json',
        HERE/'wave_order_audit.py']
    files += [ROOT/'candle_5min'/symbol/(session+'.csv') for session,symbol in inputs]
    value=dict(手法=list(design.METHODS),全図示数=104,TRACE_COLUMNS=TRACE_COLUMNS,
        注文初回準備の帰属=False,価格準備は別参考=True,
        SHA256={p.relative_to(ROOT).as_posix():runner.digest(p) for p in files})
    path=HERE/'chart_fixed.json'
    if path.exists(): assert runner.read(path)==value
    else: runner.save(path,value)
    return value


def trace_samples(ready: dict, result: dict) -> list[list]:
    """機能: 5分時計以下の最後の原本行だけでA0/At/価格注文を標本化する。

    引数: ready/result (dict)。返り値: 有限値又はNoneの図示列 (list[list])。
    将来原本は使わず、同値時刻はその時刻の最終行を採用する。
    """
    columns = {key: index for index, key in enumerate(runner.base.engine.ATR_COLUMNS)}
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
    columns = {key: index for index, key in enumerate(runner.base.engine.ATR_COLUMNS)}
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
    """機能: 主再生完了後に事前固定104図だけを詳細再生し全保存値へ照合する。

    引数: --prepare (bool)。返り値: なし (None)。新しい条件の探索はしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    args=parser.parse_args();wave_order_audit.deny_network()
    frozen=freeze();runner.save(HERE/'chart_synthetic_audit.json',synthetic())
    if args.prepare:
        print('固定4方式104図と原本asofを結果前固定、人工4件合格。',flush=True)
        return
    assert runner.read(HERE/'主再生の完了.json')['全条件数']==364
    runner.initialize();fixed=runner.FIXED;inputs=runner.INPUTS
    specs={s['id']:s for s in fixed['conditions']}
    candles,trades,tracking,episodes,details,checks={},{},{},{},[],[]
    hashes={}
    for (session,symbol),ready in inputs.items():
        path=ROOT/'candle_5min'/symbol/(session+'.csv')
        frame=pd.read_csv(path);times=pd.to_datetime(frame.time).map(lambda t:t.timestamp()).to_numpy()
        valid=(times>=ready['start'])&(times<=ready['limit'])&frame['closed'].astype(bool).to_numpy()
        candles[session+'|'+symbol]=[[float(t),*map(float,v)] for t,v in
            zip(times[valid],frame.loc[valid,['open','high','low','close']].to_numpy())]
        assert candles[session+'|'+symbol]
    for identifier in frozen['手法']:
        spec=specs[identifier]
        lp,sp=(HERE/folder/(identifier+'.json.gz') for folder in ('ledgers','sessions'))
        for p in (lp,sp):hashes[p.relative_to(HERE).as_posix()]=runner.digest(p)
        saved={(r['session'],r['symbol']):r for r in runner.read(lp)}
        expected={(r['session'],r['symbol']):r for r in runner.read(sp)}
        source=HERE/'directions'/(spec['signal_id']+'__C100.npz')
        hashes[source.relative_to(HERE).as_posix()]=runner.digest(source)
        ep_by_key={}
        if spec['signal_id']!='H019':
            ep_path=HERE/'episodes'/(spec['signal_id']+'__C100.json.gz')
            hashes[ep_path.relative_to(HERE).as_posix()]=runner.digest(ep_path)
            ep_by_key={(r['session'],r['symbol']):r['episodes'] for r in runner.read(ep_path)}
        for key,ready in inputs.items():
            state=runner.direction(spec,key)
            config=runner.base.managers.make_config(fixed['manager'],key[1],ready)
            result=runner.base.engine.run(ready,state,config,detail=True,width_mode=0,observed_fill=False)
            assert runner.fingerprints(result)==saved[key]['result_fingerprints']
            for name in runner.STORED:
                np.testing.assert_array_equal(result[name],np.asarray(saved[key][name],float).reshape(result[name].shape))
            records=runner.base.wave_metrics.trade_records(ready,result,config['point_value'])
            rows=[[datetime.fromisoformat(r['新規時刻']).timestamp(),datetime.fromisoformat(r['返済時刻']).timestamp(),
                r['direction'],r['枚数'],r['新規価格'],r['返済価格'],r['損益円'],runner.base.engine.REASONS[r['返済理由番号']],
                '主玉',r['新規行'],r['返済行']] for r in records]
            totals=[sum(r[6] for r in rows),sum(max(r[6],0.) for r in rows),-sum(min(r[6],0.) for r in rows),
                sum(r[3] for r in rows if r[6]>1e-6),sum(r[3] for r in rows if r[6]<-1e-6),sum(r[3] for r in rows if abs(r[6])<=1e-6)]
            np.testing.assert_allclose(totals,[expected[key][k] for k in
                ('net_yen','gross_profit_yen','gross_loss_yen','profit_units','loss_units','zero_units')],atol=1e-6,rtol=0)
            plotkey=identifier+'|'+'|'.join(key);sampled=trace_samples(ready,result)
            trades[plotkey]=rows;tracking[plotkey]=sampled;episodes[plotkey]=ep_by_key.get(key,[])
            details.append(dict(method=identifier,session=key[0],symbol=key[1],全返済=records,
                全注文=result['orders'].tolist(),asof=sampled,価格準備明細=episodes[plotkey],
                注文初回準備の帰属=False,result_fingerprints=runner.fingerprints(result)))
            checks.append(dict(id=identifier,session=key[0],symbol=key[1],返済件数=len(rows),
                新規件数=int(np.count_nonzero(result['orders'][:,7]==1)),収支円=totals[0],保存値一致=True))
        print('図照合 '+identifier,flush=True)
    assert len(checks)==len(trades)==len(tracking)==len(episodes)==104
    payload=dict(methods=design.METHODS,sessions=sorted({key[0] for key in inputs}),candles=candles,
        trades=trades,tracking=tracking,episodes=episodes,trace_columns=TRACE_COLUMNS,
        entry_episode_attribution=False)
    data=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    html='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>価格帯判定・５分足と売買</title>
<style>:root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0a111b;color:#e6edf6}body{max-width:1250px;margin:auto;padding:24px 18px;line-height:1.7}a{color:#88c6ff}h1{font-size:25px}.muted{color:#a7b8ca}.good{color:#66d9b1}.bad{color:#ff929e}select{max-width:100%;background:#142438;color:#e6edf6;font:inherit;padding:6px;border:1px solid #577390}.controls{display:flex;flex-wrap:wrap;gap:15px;align-items:center}canvas{width:100%;height:590px;background:#0c1522;border:1px solid #2a4057;border-radius:8px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}th,td{padding:8px 10px;border-bottom:1px solid #2a394b;text-align:right}th{background:#172637;color:#bcd0e6}details{background:#101c2a;margin:18px 0;padding:10px}summary{cursor:pointer}</style>
<body><a href="出来高通過と気配維持からの方向判定.html">結果へ戻る</a><h1>５分足と売買</h1><p>主仮説と3つの対照、全13セッションを同じ返済ルールで比較します。▲買い新規・▼売り新規・×返済です。</p>
<!--
[コンポーネント概要]
#method/#symbol/#session は結果前に固定した4方式・銘柄・セッションを選択します。
#chart は保存確定5分足、全約定、過去asofの価格線です。
#trade-table は全返済、#episode-table は注文へ帰属しない価格準備の参考明細です。
外部通信・注文操作は行いません。
-->
<div class="controls"><label>方式 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div><p id="chart-summary"></p><canvas id="chart" aria-label="確定５分足と全新規返済"></canvas>
<details><summary>凡例と執行条件</summary><p>買い▲は緑、売り▼は赤、返済×は黄。部分返済は同じ新規点から分かれます。桃は損切り線、金は追跡線。下段の水色A0は新規準備時ATR、紫Atは保有中の参考ATRです。全方式の追跡幅には固定A0を使います。</p><p>線の点は5分時計以前の最後の原本行。異なる組やフラットを結ばず、破線で5分内の価格経路を再現していません。判断後の注文は次原本行から有効。費用0・指定価格約定、TOPIX初回5枚/NK初回10枚、セッション内全返済。全13は既知データで、現在データを含みません。</p></details>
<details open><summary>全返済の明細</summary><div id="trade-table"></div></details>
<details><summary>価格準備と方向判定の参考明細</summary><p>ここでの「準備」は価格条件の区間であり、注文の初回準備ではありません。旧台帳の発注元は追跡入口の最終更新行の場合があるため、最新の準備IDを注文所有者として割り当てていません。採用されても保有・休止・価格条件によって約定しない場合があります。</p><div id="episode-table"></div></details>
<script id="chart-data" type="application/json">DATA</script><script>JAVASCRIPT</script></body></html>'''
    html=html.replace('DATA',data).replace('JAVASCRIPT',(HERE/'chart.js').read_text(encoding='utf-8'))
    OUT.mkdir(exist_ok=True);(OUT/'５分足と売買.html').write_text(html,encoding='utf-8')
    runner.save(HERE/'chart_details.json.gz',dict(対象=frozen['手法'],図=details,固定SHA256=runner.digest(HERE/'chart_fixed.json')))
    for name,sha in hashes.items():assert runner.digest(HERE/name)==sha
    assert freeze()==frozen
    runner.save(HERE/'chart_audit.json',dict(全図示数=104,全収支一致=True,全返済一致=True,全台帳一致=True,
        全原本asof一致=True,注文初回準備の誤帰属なし=True,保存済み収支との比較=checks,
        固定SHA256=runner.digest(HERE/'chart_fixed.json'),台帳元SHA256=hashes,API取得数=0,現在保存物使用=False))
    print('4方式104図の全6結果と金額・枚数一致。',flush=True)


if __name__=='__main__':
    main()


