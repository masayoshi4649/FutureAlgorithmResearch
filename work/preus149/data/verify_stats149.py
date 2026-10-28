"""記述統計の時刻参照と分母を独立した読取処理で点検する。"""

from __future__ import annotations

import importlib.util
import json
import pickle
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def main() -> None:
    """指標構築だけを既存148と比較し、到達事象を直接再計数する。

    引数: なし。
    返り値: None。検算結果JSONを保存する。売買再生は行わない。
    """
    spec = importlib.util.spec_from_file_location('engine148_readonly',ROOT/'work/preus148/engine.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stats = json.loads((OUT/'市場特性149.json').read_text('utf-8'))
    events_checked, slope_checked, missing_total = 0, 0, 0
    for session in stats['sessions']:
        source = pickle.loads((ROOT/f'work/preus148/inputs/{session["session"]}.pkl').read_bytes())['data']
        prepared = module.prepare(source)
        valid = prepared['valid']
        t,bid,ask = (prepared[key][valid] for key in ('times','bid','ask'))
        for window in session['windows'].values():
            events=window['events']
            missing_total += len(window['missing'])
            assert len(events)%6==0 and len(events)//6+len(window['missing'])==10
            for event in events:
                index = int(np.searchsorted(t,event['anchor'],side='left'))
                assert t[index]==event['anchor']
                future = (t >= event['anchor']) & (t <= event['anchor']+1800)
                ids=np.flatnonzero(future)
                ids=ids[ids>index]
                values = bid[ids]-ask[index] if event['side']==1 else bid[index]-ask[ids]
                assert bool(np.any(values>=event['barrier']))==event['favorable_reached']
                assert bool(np.any(values<=-event['barrier']))==event['adverse_reached']
                assert event['favorable_first']+event['adverse_first']+event['neither']==1
                raw_index=int(np.searchsorted(prepared['times'],event['anchor'],side='left'))
                bar_index=prepared['bar_index'][raw_index]
                exact_signal=0
                if event['slot']>0 and bar_index>=0:
                    fast,slow=prepared['bars'][bar_index,1:3]
                    if fast>=4 and slow>=1: exact_signal=1
                    elif fast<=-4 and slow<=-1: exact_signal=-1
                assert event['signal_side']==exact_signal,(session['session'],event['slot'],event['signal_side'],exact_signal)
                for key,column in [('slope5',1),('slope10',2)]:
                    expected=prepared['bars'][bar_index,column] if bar_index>=0 else np.nan
                    actual=event[key]
                    if actual is None:
                        assert not np.isfinite(expected)
                    else:
                        assert np.isclose(actual,expected,atol=1e-8)
                    slope_checked+=1
                events_checked+=1
    receipt=dict(financial_replays=0,sessions=25,barrier_events_checked=events_checked,
                 slope_values_match_148_prepare=slope_checked,missing_anchors=missing_total,
                 all_checks_passed=True,
                 note='148.prepareだけを呼び、売買・約定関数を一切呼ばない。')
    (OUT/'記述統計検算149.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(receipt,ensure_ascii=True))


if __name__=='__main__':
    main()
