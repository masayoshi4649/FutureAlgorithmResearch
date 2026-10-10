"""HTMLの全売買と、原本から独立計算した5分asofのATR・価格線を照合する。"""

from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import chart_report as chart


class Extractor(HTMLParser):
    """機能: HTMLの図データとローカルリンクを取り出す。

    引数: feed(str)でHTMLを指定。返り値: data/links属性 (str/list[str])。
    """

    def __init__(self) -> None:
        """機能: 収集先を初期化する。

        引数: なし。返り値: なし (None)。
        """
        super().__init__()
        self.data, self.active, self.links, self.ids = '', False, [], set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """機能: 図データ開始・要素ID・リンクを抽出する。

        引数: tag (str)、attrs (list)。返り値: なし (None)。
        """
        values = dict(attrs)
        if values.get('id'):
            assert values['id'] not in self.ids
            self.ids.add(values['id'])
        if tag == 'script' and values.get('id') == 'chart-data':
            self.active = True
        if tag == 'a' and values.get('href'):
            self.links.append(values['href'])

    def handle_endtag(self, tag: str) -> None:
        """機能: 図データの終端を検出する。

        引数: tag (str)。返り値: なし (None)。
        """
        if tag == 'script':
            self.active = False

    def handle_data(self, value: str) -> None:
        """機能: 図データ内のJSON文字列を保存する。

        引数: value (str)。返り値: なし (None)。
        """
        if self.active:
            self.data += value


def independent_lines(ready: dict, ledger: dict, dynamic: bool) -> dict:
    """機能: 組の建値・全返済・原本価格ATRから固定予算と累積追跡線を別式で計算する。

    引数: ready/ledger (dict)、dynamic (bool)。返り値: 組番号ごとの価格線等 (dict)。
    本番エンジン・atr_curveの値を使用しない。
    """
    prices, atr, tick = ready['last'], ready['atr'], ready['tick']
    trades = np.asarray(ledger['trades'], dtype=float).reshape(-1, 11)
    result = {}
    for cycle in np.asarray(ledger['cycles'], dtype=float).reshape(-1, 10):
        campaign, begin, end = map(int, cycle[:3])
        selected = trades[trades[:, 0] == campaign]
        anchor, direction, a0, risk = selected[0, 4], int(cycle[8]), cycle[5], cycle[4]
        n = end - begin
        history = atr[begin:end]
        pointers = np.maximum.accumulate(np.where(np.isfinite(history) & (history > 0), np.arange(n), -1))
        at = np.full(n, a0)
        valid = pointers >= 0
        at[valid] = np.maximum(history[pointers[valid]], tick * 2)
        extreme = (np.maximum.accumulate(np.r_[anchor, prices[begin:end]]) if direction > 0
                   else np.minimum.accumulate(np.r_[anchor, prices[begin:end]]))[1:]
        width_atr = at if dynamic else np.full(n, a0)
        proposed = extreme - direction * 3 * width_atr
        if direction > 0:
            proposed = np.floor(proposed / tick + 1e-9) * tick
            proposed[direction * (extreme - anchor) < 1.5 * a0] = -np.inf
            trail = np.maximum.accumulate(proposed)
        else:
            proposed = np.ceil(proposed / tick - 1e-9) * tick
            proposed[direction * (extreme - anchor) < 1.5 * a0] = np.inf
            trail = np.minimum.accumulate(proposed)
        gains, closed = np.zeros(n), np.zeros(n)
        for trade in selected:
            index = int(trade[7]) - begin
            if index < n:
                gains[index] += trade[2] * trade[3] * (trade[5] - trade[4])
                closed[index] += trade[3]
        quantities = ledger['config']['initial_qty'] - np.cumsum(closed)
        stop = anchor + direction * (-risk - np.cumsum(gains)) / quantities
        stop = np.floor(stop / tick + 1e-9) * tick if direction > 0 else np.ceil(stop / tick - 1e-9) * tick
        result[campaign] = {'begin': begin, 'end': end, 'direction': direction, 'A0': a0, 'At': at,
                            'used_atr': width_atr, 'stop': stop, 'trail': trail}
    return result


def main() -> None:
    """機能: 全104図の全売買・足・価格線・参考準備・リンクを元資料と照合する。

    引数: なし。返り値: なし (None)。追加の注文器再生は行わない。
    """
    chart.wave_order_audit.deny_network()
    path=chart.OUT/'５分足と売買.html';parser=Extractor();parser.feed(path.read_text(encoding='utf-8'))
    payload=json.loads(parser.data);frozen=chart.freeze();details=chart.runner.read(chart.HERE/'chart_details.json.gz')
    assert payload['methods']==chart.design.METHODS and payload['entry_episode_attribution'] is False
    assert len(details['図'])==len(payload['trades'])==len(payload['tracking'])==len(payload['episodes'])==104
    inputs=pickle.loads((chart.HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    ledgers={method:{(r['session'],r['symbol']):r for r in chart.runner.read(chart.HERE/'ledgers'/(method+'.json.gz'))}
        for method in frozen['手法']}
    source_episodes={}
    for method in frozen['手法']:
        signal_id=method.split('__')[0]
        source_episodes[method]={(r['session'],r['symbol']):r['episodes'] for r in
            chart.runner.read(chart.HERE/'episodes'/(signal_id+'__C100.json.gz'))} if signal_id!='H019' else {}
    count=samples=entries=exits=barcount=0
    for key,ready in inputs.items():
        frame=pd.read_csv(chart.ROOT/'candle_5min'/key[1]/(key[0]+'.csv'))
        expected=[]
        for r in frame.itertuples():
            t=pd.Timestamp(r.time).timestamp()
            if r.closed and ready['start']<=t<=ready['limit']:
                expected.append([float(t),float(r.open),float(r.high),float(r.low),float(r.close)])
        assert payload['candles']['|'.join(key)]==expected
        barcount+=len(expected)
    seen=set()
    for item in details['図']:
        method=item['method'];key=(item['session'],item['symbol']);plotkey=method+'|'+'|'.join(key)
        assert plotkey not in seen;seen.add(plotkey)
        ready=inputs[key];ledger=ledgers[method][key]
        assert item['注文初回準備の帰属'] is False
        assert item['result_fingerprints']==ledger['result_fingerprints']
        np.testing.assert_array_equal(np.asarray(item['全注文'],float).reshape(-1,8),np.asarray(ledger['orders'],float).reshape(-1,8))
        records=payload['trades'][plotkey];rawtrades=np.asarray(ledger['trades'],float).reshape(-1,11)
        assert len(records)==len(rawtrades)==len(item['全返済'])
        point=ledger['config']['point_value']
        for row,t,verbose in zip(records,rawtrades,item['全返済']):
            entry,exitrow=int(t[6]),int(t[7])
            values=[ready['time_s'][entry],ready['time_s'][exitrow],t[2],t[3],t[4],t[5],t[2]*t[3]*(t[5]-t[4])*point]
            np.testing.assert_allclose(row[:7],values,atol=1e-6,rtol=0)
            assert row[7]==chart.runner.base.engine.REASONS[int(t[9])]
            assert row[9:]==[entry,exitrow]
            assert datetime.fromisoformat(verbose['新規時刻']).timestamp()==values[0]
            assert datetime.fromisoformat(verbose['返済時刻']).timestamp()==values[1]
        orders=np.asarray(ledger['orders'],float).reshape(-1,8)
        assert set(orders[orders[:,7]==1,0].astype(int))=={r[9] for r in records}
        assert len(orders[orders[:,7]==0])==len(records)
        assert payload['episodes'][plotkey]==item['価格準備明細']==source_episodes[method].get(key,[])
        for ep in payload['episodes'][plotkey]:
            assert 'order_owner' not in ep and 'entry_row' not in ep
        lines=independent_lines(ready,ledger,False)
        assert payload['tracking'][plotkey]==item['asof']
        pointer=-1
        for sample in item['asof']:
            stamp,reference,campaign,side=sample[:4]
            while pointer+1<len(ready['time_s']) and ready['time_s'][pointer+1]<=stamp:
                pointer+=1
            assert reference==pointer
            if side:
                line=lines[campaign];assert line['begin']<=pointer<line['end'] and side==line['direction']
                offset=pointer-line['begin']
                wanted=[line['A0'],line['At'][offset],line['used_atr'][offset],line['stop'][offset],line['trail'][offset]]
                for observed,target in zip(sample[4:],wanted):
                    if np.isfinite(target):np.testing.assert_allclose(observed,target,atol=1e-7,rtol=0)
                    else:assert observed is None
            else:assert sample[4:]==[None]*5
            samples+=1
        count+=1;entries+=int(np.count_nonzero(orders[:,7]==1));exits+=len(records)
    assert count==104 and seen==set(payload['tracking'])
    for href in parser.links:
        assert not href.startswith(('http:','https:'))
        target=href.split('#',1)[0]
        assert not target or (path.parent/target).exists(),href
    assert chart.freeze()==frozen
    chart.runner.save(chart.HERE/'chart_data_audit.json',dict(全図示数=104,全新規件数=entries,全返済件数=exits,
        原本asof標本数=samples,確定足数=barcount,全返済一致=True,全新規一致=True,全確定足一致=True,
        原本asof列一致=True,ATR価格線の別式計算一致=True,価格準備参考明細一致=True,
        注文初回準備の誤帰属なし=True,ローカルリンク全有効=True,API取得数=0,現在保存物使用=False,
        HTML_SHA256=chart.runner.digest(path),固定SHA256=chart.runner.digest(chart.HERE/'chart_fixed.json'),
        図明細SHA256=chart.runner.digest(chart.HERE/'chart_details.json.gz')))
    print('全104図の注文・返済・確定足・独立価格線・準備参考・リンク一致。',flush=True)


if __name__=='__main__':
    main()


