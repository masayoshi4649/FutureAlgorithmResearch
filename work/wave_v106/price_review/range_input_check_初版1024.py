"""純価格R候補を独立した六点選択・反発判定・整数料金から検査する。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

from check_highwater import sample_oracle
from range_math import order_fee


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/range_price'


def digest(path: Path) -> str:
    """
    機能: 小sourceの固定を確認する。
    引数: path(Path)は新候補source。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(symbol: str, side: int, trend: bool = False) -> tuple[dict,dict,dict]:
    """
    機能: ネイティブ参照呼値の両市場反発を、同時計の原行で作る。
    引数: symbol(str)、side(int)、trend(bool)は往復又は進行の人工形。
    返り値: tuple[dict,dict,dict]は原価格・正常列・元C候補。実原板を読まない。
    """
    symbols = ('TOPIX','NK225'); other = next(s for s in symbols if s != symbol)
    raws = {}; records = {}; cases = {}
    for s in symbols:
        tick = .5 if s == 'TOPIX' else 10.
        times = np.array([0.,60.,120.,180.,240.,300.,300.,300.,300.,310.])
        if s == other: times[5:9] = 299.
        units = np.array([101.,111.,101.,111.,105.,102.,100.,101.,102.,102.]) if not trend else np.array([101.,103.,105.,107.,109.,111.,110.,111.,112.,112.])
        midpoint = (1000.+units+.5)*tick
        if side < 0: midpoint = 2400*tick-midpoint
        bid = midpoint-tick/2; ask = midpoint+tick/2; seq = np.arange(200,210,dtype=np.int64); mapping = np.arange(10,dtype=np.int64)
        raws[s] = dict(raw_seq=seq,price_time_s=times.copy(),bid=bid.copy(),ask=ask.copy(),execution_to_raw_index=mapping)
        records[s] = dict(symbol=s,seq=seq,time_s=times.copy(),bid=bid.copy(),ask=ask.copy(),price=midpoint,
            quote_valid=np.ones(10,bool),price_valid=np.ones(10,bool),tick=tick,start=0.,end=1000.,limit=900.)
        cases[s] = dict(event=np.zeros(10,np.int8),support_price=np.full(10,np.nan),entry_quality=np.zeros(10,bool),
            entry_reset=np.ones(10,bool),execution_to_raw_index=mapping,decisions=[])
    return raws,records,cases


def reference(raws: dict, records: dict, symbol: str, row: int) -> dict:
    """
    機能: ownerの共有tableを使わず二市場六点状態と現在の境界反発を求める。
    引数: raws/records(dict)、symbol(str)、row(int)は自己判断正常行。
    返り値: dictは自己/相手の原行・ERと固定二閾値のstate/event。
    """
    other = next(s for s in records if s != symbol); current = records[symbol]; stamp = float(current['time_s'][row])
    result = {}
    for role,s,bound,strict in [('own',symbol,row,False),('peer',other,None,True)]:
        record = records[s]; value = sample_oracle(raws[s],stamp,record['tick'],bound,strict,record['start'],record['limit'])
        if value['known']:
            prices = [.5*(raws[s]['bid'][r]+raws[s]['ask'][r]) for r in value['rows']]
            value.update(low=min(prices),high=max(prices),span=(max(prices)-min(prices))/record['tick'],
                centre=.5*(max(prices)+min(prices)),ret=(prices[-1]-prices[0])/prices[0]*10000.)
        result[role] = value
    bid,ask = float(current['bid'][row]),float(current['ask'][row]); mid = .5*(bid+ask)
    qok = bool(current['quote_valid'][row] and np.isfinite(stamp) and np.isfinite(bid) and np.isfinite(ask) and 0 < bid < ask)
    previous = [r for r in range(row) if current['quote_valid'][r] and np.isfinite(current['time_s'][r]) and
        np.isfinite(current['bid'][r]) and np.isfinite(current['ask'][r]) and 0 < current['bid'][r] < current['ask'][r]]
    prev = previous[-1] if previous else -1
    for er in (.2,.4):
        own,peer = result['own'],result['peer']; state = 0; event = 0
        if own['known'] and peer['known']:
            state = 3
            if all(v['ER'] is not None and v['ER'] <= er and v['span'] >= 4 for v in (own,peer)): state = 1
            elif all(v['ret'] >= 2 for v in (own,peer)): state = 2
            elif all(v['ret'] <= -2 for v in (own,peer)): state = -2
            if state == 1 and qok and prev >= 0:
                up = bid-current['bid'][prev] >= current['tick'] and ask-current['ask'][prev] >= current['tick']
                down = bid-current['bid'][prev] <= -current['tick'] and ask-current['ask'][prev] <= -current['tick']
                if own['low'] <= mid <= own['low']+.25*(own['high']-own['low']) and up: event = 1
                if own['high']-.25*(own['high']-own['low']) <= mid <= own['high'] and down: event = -1
        result[str(er)] = dict(state=state,event=event)
    return result


def main() -> None:
    """
    機能: 全人工行の六点cache・尾部と24条件の料金RRを独立計算する。
    引数: なし。実原板・実金融結果を使わない。
    返り値: Noneは独立source結合と旧範囲外Falseの参照を保存する。
    """
    sys.path.insert(0,str(SOURCE)); import features; import selection; import catalog
    paths = [SOURCE/name for name in ('features.py','selection.py','catalog.py','common.py')] + [ROOT/'work/wave_v106/regime_price/features.py']
    before = {str(path.relative_to(ROOT)):digest(path) for path in paths}; checks = {}; bad_outside = 0
    def counted(name: str) -> None:
        """
        機能: 用途別の検査数を記録する。
        引数: name(str)は検査名。
        返り値: Noneは私有件数を増やす。
        """
        checks[name] = checks.get(name,0)+1
    for symbol in ('TOPIX','NK225'):
        for side in (-1,1):
            for variant in ('基準','同時計後半seq断裂','欠測跨ぎ時計逆行','範囲外反発','未来変更'):
                raws,records,cases = fixture(symbol,side)
                tick = records[symbol]['tick']
                if variant == '同時計後半seq断裂': raws[symbol]['raw_seq'][7:] += 1
                if variant == '欠測跨ぎ時計逆行':
                    raws[symbol]['price_time_s'][6] = np.nan; raws[symbol]['price_time_s'][7] = 299.
                if variant == '範囲外反発':
                    for row,units in [(6,99.),(7,100.)]:
                        mid = (1000.+units+.5)*tick
                        if side < 0: mid = 2400*tick-mid
                        raws[symbol]['bid'][row] = mid-tick/2; raws[symbol]['ask'][row] = mid+tick/2
                if variant == '未来変更':
                    raws[symbol]['bid'][8:] = 1.; raws[symbol]['ask'][8:] = 2.
                    raws[symbol]['price_time_s'][9] = 10000.
                records[symbol].update(seq=raws[symbol]['raw_seq'].copy(),time_s=raws[symbol]['price_time_s'].copy(),
                    bid=raws[symbol]['bid'].copy(),ask=raws[symbol]['ask'].copy())
                observed = features.build(raws,records,symbol)
                for row in range(8):
                    expected = reference(raws,records,symbol,row)
                    index = int(observed['normal_sample_index'][row])
                    own = features.at_row(observed['sample_tables']['own'],index,bool(observed['own_known'][row]),int(observed['own_reason'][row]))
                    peer = features.at_row(observed['sample_tables']['peer'],index)
                    for role,actual in [('own',own),('peer',peer)]:
                        assert actual['known'] == expected[role]['known'] and actual['rows'] == expected[role]['rows'], (symbol,side,variant,row,role)
                        if actual['known'] and actual['ER'] is not None: assert abs(actual['ER']-expected[role]['ER']) <= 1e-12
                        counted('六点逐次選点と各候補尾部')
                    for er in (.2,.4):
                        assert observed['states'][str(er)][row] == expected[str(er)]['state']
                        assert observed['boundary_events'][str(er)][row] == expected[str(er)]['event'], (symbol,side,variant,row)
                        counted('両市場stateと範囲内反発')
                if variant == '範囲外反発':
                    assert observed['boundary_events']['0.2'][7] == 0; bad_outside += 1
                prepared = {'record':records[symbol]}
                for config in catalog.catalog():
                    result = selection.range_arrays(prepared,observed,config)
                    for row in np.flatnonzero(result['event']):
                        s = int(result['event'][row]); index = int(observed['normal_sample_index'][row]); own = observed['sample_tables']['own']
                        target = (math.floor(own['centre'][index]/tick+1e-10) if s > 0 else math.ceil(own['centre'][index]/tick-1e-10))*tick
                        stop = (math.floor((own['low'][index]-config['margin_ticks']*tick)/tick+1e-10) if s > 0 else math.ceil((own['high'][index]+config['margin_ticks']*tick)/tick-1e-10))*tick
                        entry = records[symbol]['ask' if s > 0 else 'bid'][row] if config['range_entry']=='MARKET' else records[symbol]['bid' if s > 0 else 'ask'][row]
                        qty = config['quantity'][symbol]; m = 1000 if symbol == 'TOPIX' else 10
                        fees = 2*order_fee(qty,'41.8' if symbol == 'TOPIX' else '11')
                        profit = s*(target-entry)*qty*m-fees; loss = s*(entry-stop)*qty*m+fees; clearance = s*(entry-stop)/tick
                        reason = 2 if clearance < 2.-1e-10 else 3 if s*(target-entry) <= 0 else 4 if loss <= 0 else 5 if profit < 1.25*loss else 0
                        assert target == result['target'][row] and stop == result['stop'][row] and fees == result['roundtrip_fees']
                        assert profit == result['planned_net_profit'][row] and loss == result['planned_net_loss'][row]
                        assert result['rejection'][row] == reason and bool(result['allowed'][row]) == (reason == 0)
                        counted('24条件の丸め料金RR独立算術')
    assert bad_outside == 4
    after = {str(path.relative_to(ROOT)):digest(path) for path in paths}; assert before == after
    output = dict(全合格=True,scope='R_PRICE入力の人工独立測定のみ',検査件数=checks,検査合計=sum(checks.values()),
        source_SHA256=before,開始終端source一致=True,範囲外反発の拒否=bad_outside,
        金融結果読取=0,金融再生=0,原本NPZAPI=0,
        設計限界=['純価格六点ERは全tick経路でない','予定RRは判定後nextqの実RR保証でない',
            '元C_OWN根拠は量を含む不変別仮説、R_PRICEに補充や板episodeがあるとは呼ばない'],
        レビューsource_SHA256=digest(Path(__file__)))
    (HERE/'range_修正後の入力と料込RRの独立人工.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('新R入力独立',sum(checks.values()),'合格',flush=True)


if __name__ == '__main__':
    main()
