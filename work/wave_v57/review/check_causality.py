"""原本から補充観測と入口までの接頭辞・倍率不変を独立検査する。"""

from pathlib import Path
import hashlib
import json
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE))
from features import extract_one
from signals import candidates, decisions, flow_windows, methods


def same(actual: dict, expected: dict) -> None:
    """機能: 三つの入口候補を順序を含めて照合する。

    引数: actual/expected(dict)。返り値: なし(None)。
    """
    for family in actual:
        np.testing.assert_array_equal(actual[family], expected[family])


def main() -> None:
    """機能: 全46口座の途中切断と一部の原本再抽出・変換不変を検査する。

    引数: なし。返り値: なし(None)。損益結果は読み込まない。
    """
    frames = pickle.loads((BASE/'features.pkl').read_bytes())
    events = pickle.loads((BASE/'events.pkl').read_bytes())
    saved = pickle.loads((BASE/'入口候補.pkl').read_bytes())
    inputs = pickle.loads((BASE.parent/'wave_v55/clean_inputs.pkl').read_bytes())
    signals = pickle.loads((BASE/'判断.pkl').read_bytes())
    counts = dict(口座=0, 特徴原本接頭辞=0, 入口接頭辞=0, 倍率変換=0, 幅丸め=0, 圧力窓直接照合=0)
    for number, key in enumerate(sorted(frames)):
        data, ev, ready = frames[key], events[key], inputs[key]
        n=len(data['seq'])
        np.testing.assert_array_equal(data['seq'],ready['seq'])
        np.testing.assert_array_equal(data['time_s'],ready['time_s'])
        assert np.all(np.diff(data['time_s'])>=0) and np.all(np.diff(data['seq'])>0)
        assert np.all(np.diff(ev['i'])>=0)
        assert np.all(ev['qty']<=ev['decline']) and np.all(ev['qty']>=.8*ev['decline']) and np.all(ev['qty']>=.25*ev['bestqty'])
        assert np.all(ev['seq']==data['seq'][ev['i']]) and np.all(ev['time']==data['time_s'][ev['i']])
        assert np.all(ev['seq']-ev['start_seq']<=500) and np.all(ev['time']-ev['start_time']<=30.)
        reset_indices=np.flatnonzero(data['reset'])
        for seconds in (10.,30.):
            buy,sell=flow_windows(data,seconds)
            for i in np.linspace(0,n-1,21,dtype=int):
                reset=int(reset_indices[np.searchsorted(reset_indices,i,side='right')-1]) if len(reset_indices) and reset_indices[0]<=i else 0
                valid=np.arange(reset,i+1)[data['time_s'][reset:i+1]>=data['time_s'][i]-seconds]
                assert buy[i]==data['exec_buy_qty'][valid].sum() and sell[i]==data['exec_sell_qty'][valid].sum()
                counts['圧力窓直接照合']+=1
        # ----------------------------------------
        # 将来行を取り除いてから状態機械を作り直す。
        for count in (2,3):
            full=saved[key,count]
            for ratio in (.35,.70):
                cut=int(n*ratio)
                out=candidates({k:v[:cut] for k,v in data.items()},ev[ev['i']<cut],count,ready['tick'],ready['start'])
                same(out,{k:v[v[:,0]<cut] for k,v in full.items()})
                counts['入口接頭辞']+=1
            if number in (0,1,22,23,44,45):
                scaled={k:v.copy() for k,v in data.items()}
                for col in ('bid','ask','mid','last','bid_far','ask_far','exec_mean_price'):
                    scaled[col]*=2.
                sev=ev.copy();sev['price']*=2.
                changed=candidates(scaled,sev,count,ready['tick']*2,ready['start'])
                expected={}
                for family,rows in full.items():
                    expected[family]=rows.copy();expected[family][:,2:]*=2.
                same(changed,expected)
                counts['倍率変換']+=1
        for config in methods():
            original=saved[key,config['count']][config['family']]
            expected=decisions(original,config['fraction'],ready['last'][0],ready['tick'])
            np.testing.assert_array_equal(expected,signals[key,config['id']])
            width=max(2*ready['tick'],np.ceil(ready['last'][0]*config['fraction']/ready['tick']-1e-10)*ready['tick'])
            assert np.all(expected[:,2]==width)
            counts['幅丸め']+=1
        counts['口座']+=1
        print(key,'因果合格',flush=True)
    # ----------------------------------------
    # 特徴担当と異なる原本・切断位置を用い、原本パーサから同じ観測になることを再確認する。
    for number in (0,1,44,45):
        key=sorted(frames)[number];cut=min(15000,len(inputs[key]['seq'])//3)
        shorter,short_events,_=extract_one(key,inputs[key],max_valid_rows=cut)
        for col in shorter:
            np.testing.assert_array_equal(shorter[col],frames[key][col][:cut])
        np.testing.assert_array_equal(short_events,events[key][events[key]['i']<cut])
        counts['特徴原本接頭辞']+=1
    report=dict(合格=True,件数=counts,時刻逆行原本数=0,
                限定='保存全原本は非減少時計。新たな時計逆行入力は特徴でresetされるがsignalsは拒否する。未知期間の勝率や真のaggressorは検証していない。',
                コードSHA256={name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in ('features.py','signals.py')}, 損益参照=False)
    (HERE/'原本と入口の独立因果監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
