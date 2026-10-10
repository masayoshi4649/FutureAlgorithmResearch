"""HTML全156図の売買と数量標本を、保存注文・原本から別式で検算する。"""

from html.parser import HTMLParser
import json
from pathlib import Path

import numpy as np
import pandas as pd

import chart_report as chart


class Extractor(HTMLParser):
    """機能: 埋込図データとリンクだけを解析する。

    引数: feedへHTML(str)。返り値: data/links属性(str/list)。
    """
    def __init__(self):
        """機能: 収集先を初期化する。

        引数: なし。返り値: なし(None)。
        """
        super().__init__(); self.active=False; self.data=''; self.links=[]; self.ids=set()

    def handle_starttag(self, tag, attrs):
        """機能: 図データ開始と重複ID・リンクを確認する。

        引数: tag(str)、attrs(list)。返り値: なし(None)。
        """
        value=dict(attrs)
        if value.get('id'):
            assert value['id'] not in self.ids; self.ids.add(value['id'])
        if tag=='script' and value.get('id')=='chart-data': self.active=True
        if tag=='a' and value.get('href'): self.links.append(value['href'])

    def handle_endtag(self, tag):
        """機能: データ収集の終端を検出する。

        引数: tag(str)。返り値: なし(None)。
        """
        if tag=='script': self.active=False

    def handle_data(self, value):
        """機能: 図データの文字列を保存する。

        引数: value(str)。返り値: なし(None)。
        """
        if self.active: self.data+=value


def inventory(orders: np.ndarray, count: int) -> np.ndarray:
    """機能: 全注文から買売合計保有枚数を積算する。

    引数: orders(ndarray)、count(int)。返り値: 全行枚数(ndarray)。
    """
    changes=np.zeros(count)
    for row in orders:
        changes[int(row[0])] += row[4] if row[7] else -row[4]
    value=np.cumsum(changes); assert np.min(value)>=0 and value[-1]==0
    return value


def main() -> None:
    """機能: 保存台帳から図の全注文・返済・操作根拠・数量を再構成する。

    引数: なし。返り値: なし(None)。新売買再生なし。
    """
    frozen=chart.design.prepare(); chart.runner.initialize()
    path=chart.design.OUT/'５分足と売買.html'; parser=Extractor(); parser.feed(path.read_text(encoding='utf-8'))
    data=json.loads(parser.data); assert data['methods']==chart.design.METHODS
    basepath=chart.HERE/'ledgers'/(chart.design.BASE+'.json.gz')
    base={(v['session'],v['symbol']):v for v in chart.runner.read(basepath)}
    checks=[]; candles_checked=set(); hashes={str(basepath):chart.runner.digest(basepath)}
    for identifier in frozen['規則']['図対象']:
        source=chart.HERE/'ledgers'/(identifier+'.json.gz'); hashes[str(source)]=chart.runner.digest(source)
        for ledger in chart.runner.read(source):
            key=ledger['session'],ledger['symbol']; ready=chart.runner.INPUTS[key]; time=ready['time_s']; name=identifier+'|'+'|'.join(key)
            orders=np.asarray(ledger['orders'],float).reshape(-1,8); trades=np.asarray(ledger['trades'],float).reshape(-1,11)
            expected_orders=[[float(time[int(o[0])]),*o.tolist()] for o in orders]
            np.testing.assert_array_equal(np.asarray(data['orders'][name],float).reshape(-1,9),np.asarray(expected_orders).reshape(-1,9))
            factor=ledger['config']['point_value']
            expected_trades=[[time[int(v[6])],time[int(v[7])],v[2],v[3],v[4],v[5],v[10]*factor,v[9],v[6],v[7]] for v in trades]
            np.testing.assert_array_equal(np.asarray(data['trades'][name],float).reshape(-1,10),np.asarray(expected_trades).reshape(-1,10))
            operations=np.asarray(ledger['adjustment_events'],float).reshape(-1,11)
            expected_actions=[[float(time[int(v[0])]),*map(int,v[:8]),float(time[int(v[5])]) if v[5]>=0 else None] for v in operations]
            assert data['adjustments'][name]==expected_actions
            branches=np.asarray(ledger['branch_events'],float).reshape(-1,10)
            expected_branches=[[float(time[int(v[0])]),*map(int,v),float(time[int(v[5])]) if v[5]>=0 else None,float(ready['last'][int(v[0])])] for v in branches]
            assert data['branches'][name]==expected_branches
            reference_orders=np.asarray(base[key]['orders'],float).reshape(-1,8)
            actual=inventory(orders,len(time)); reference=inventory(reference_orders,len(time))
            rows=np.asarray(data['tracking'][name],float)
            clocks=np.arange(ready['start'],ready['limit']+1e-8,300.)
            if len(clocks)==0 or clocks[-1]<ready['limit']:clocks=np.r_[clocks,ready['limit']]
            terminal=[float(time[int(o[-1,0])]) for o in (orders,reference_orders) if len(o)]
            if terminal and max(terminal)>clocks[-1]:clocks=np.r_[clocks,max(terminal)]
            np.testing.assert_array_equal(rows[:,0],clocks)
            cursor=-1
            for sample in rows:
                while cursor+1<len(time) and time[cursor+1]<=sample[0]:cursor+=1
                assert sample[1]==cursor
                assert sample[2]==(actual[cursor] if cursor>=0 else 0)
                assert sample[3]==(reference[cursor] if cursor>=0 else 0)
            assert rows[-1,2]==rows[-1,3]==0.,'実と影の最終返済後に残玉なし'
            if key not in candles_checked:
                candle_path=chart.runner.ROOT/'candle_5min'/key[1]/(key[0]+'.csv')
                frame=pd.read_csv(candle_path); stamps=pd.to_datetime(frame.time).map(lambda x:x.timestamp()).to_numpy()
                selected=(stamps>=ready['start'])&(stamps<=ready['limit'])&frame.closed.astype(bool).to_numpy()
                expected=[[float(t),*map(float,v)] for t,v in zip(stamps[selected],frame.loc[selected,['open','high','low','close']].to_numpy())]
                np.testing.assert_array_equal(data['candles']['|'.join(key)],expected); candles_checked.add(key)
                hashes[str(candle_path)]=chart.runner.digest(candle_path)
            checks.append(dict(id=identifier,session=key[0],symbol=key[1],orders=len(orders),trades=len(trades),操作根拠=len(operations),分岐根拠=len(branches),asof=len(rows),一致=True))
    assert len(checks)==156 and len(candles_checked)==26
    pending_links=[]
    for href in parser.links:
        assert not href.startswith(('http:','https:')),href
        if not (path.parent/href.split('#')[0]).exists():
            assert href=='復元方式の自動選択と改善8条件の反証.html',href
            pending_links.append(href)
    for source,sha in hashes.items():assert chart.runner.digest(Path(source))==sha
    chart.runner.save(chart.HERE/'chart_data_audit.json',dict(全図示数=156,全注文一致=True,全返済一致=True,
        全数量独立asof一致=True,全操作根拠一致=True,全分岐根拠一致=True,全原本足一致=True,
        全リンク一致=not pending_links,未完成リンク=pending_links,全終端残玉ゼロ=True,結果=checks,
        HTML_SHA256=chart.runner.digest(path),固定SHA256=chart.runner.digest(chart.HERE/'chart_fixed.json'),
        元資料SHA256=hashes,新売買再生=False,API取得数=0,現在保存物使用=False))


if __name__=='__main__':
    main()
