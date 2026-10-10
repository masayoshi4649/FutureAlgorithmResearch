"""既存の確定1分足公開を原板区間と境界prefixから独立に確認する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v63/directional/features.py'


def clipped(account,quote,size):
    """機能: 過去行だけが渡る価格prefixを作る。

    引数: account/quote(dict)、size(int)。返り値: 切断口座と切断価格(tuple)。
    """
    result=dict(account)
    for key in ('seq','time_s'):
        result[key]=account[key][:size]
    return result,{key:value[:size] for key,value in quote.items()}


def main():
    """機能: 全50口座の閉じた足を別集計し、公開直前直後と欠測境界を監査する。

    引数: なし。返り値: なし(None)。板、旧作業、主実装を変更しない。
    """
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location('minute_features_audit66',SOURCE)
    features=importlib.util.module_from_spec(spec);spec.loader.exec_module(features)
    inputs=pickle.loads((ROOT/'work/wave_v60/inputs.pkl').read_bytes())
    quotes=pickle.loads((ROOT/'work/wave_v60/quotes.pkl').read_bytes())
    reports=[];all_bar=all_prefix=all_changed=all_gaps=0
    setting=dict(short=3,long=20)
    for key in sorted(inputs):
        account,quote=inputs[key],quotes[key]
        frame=features.build(account,quote,setting)
        t,seq,mid=account['time_s'],account['seq'],quote['mid']
        minute=np.floor(t/60).astype(np.int64)
        starts=np.r_[0,np.flatnonzero(minute[1:]!=minute[:-1])+1]
        assert frame['i'].tolist()==starts[1:].tolist()
        gaps=0
        for position in range(1,len(starts)):
            i,previous=int(starts[position]),int(starts[position-1])
            observed=minute[i]==minute[i-1]+1
            row=frame.iloc[position-1]
            expected=dict(source_bucket=int(minute[i]-1),i=i,seq=int(seq[i]),time_s=float(t[i]),mid=float(mid[i]),
                spread=float(quote['ask'][i]-quote['bid'][i]),source_last_seq=float(seq[i-1]),source_last_time=float(t[i-1]),
                observed=observed,close=float(mid[i-1]),
                open=float(mid[previous]) if observed else float(mid[i-1]),
                high=float(mid[previous:i].max()) if observed else float(mid[i-1]),
                low=float(mid[previous:i].min()) if observed else float(mid[i-1]))
            for label,value in expected.items():
                assert row[label]==value,(key,i,label,row[label],value)
            assert row['source_last_seq']<row['seq'] and row['source_last_time']<row['time_s']
            assert row['bar_end']<=row['time_s']
            gaps+=int(not observed)
        points={1}
        selected=[int(starts[1]),int(starts[len(starts)//2]),int(starts[-1])]
        for i in selected:
            points.update((i,min(i+1,len(t))))
            if i+1<len(t) and t[i+1]==t[i]:
                points.add(i+2)
        gap_positions=np.flatnonzero(np.diff(minute[starts])>1)+1
        if len(gap_positions):
            i=int(starts[gap_positions[0]])
            points.update((i,i+1))
        for window in (3,5,10):
            available=frame[frame['time_s']>=account['start']+window*60]
            if len(available):
                i=int(available.iloc[0]['i'])
                points.update((i,i+1))
        prefix=changed_count=0
        for size in sorted(points):
            part,qpart=clipped(account,quote,size)
            expected=frame[frame['i']<size].reset_index(drop=True)
            pd.testing.assert_frame_equal(features.build(part,qpart,setting),expected,check_exact=True)
            prefix+=1
            changed={name:value.copy() for name,value in quote.items()}
            for name in ('bid','ask','mid'):
                changed[name][size:]+=997*account['tick']
            changed_frame=features.build(account,changed,setting)
            pd.testing.assert_frame_equal(changed_frame[changed_frame['i']<size].reset_index(drop=True),expected,check_exact=True)
            changed_count+=1
        reports.append(dict(session=key[0],symbol=key[1],公開足数=len(frame),空白直後の公開数=gaps,
            原板別集計一致=True,prefix件数=prefix,未来改変件数=changed_count))
        all_bar+=len(frame);all_prefix+=prefix;all_changed+=changed_count;all_gaps+=gaps
    report=dict(結論='既存確定1分足の公開行とOHLC等は原板別集計と一致。公開境界prefixと未来価格改変も一致。',
        口座数=len(inputs),公開足照合数=all_bar,空白直後の公開数=all_gaps,prefix検査数=all_prefix,未来価格改変検査数=all_changed,
        既存コードSHA256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),口座別=reports,
        新入口の監査方針=['frameは実観測バケットの公開行だけ。N行前がN分前であることを窓全体の連続バケットで確認する。',
        '過去N分の変化はN+1確定終値が必要。ERの分母は同じN差分の絶対値合計。始点価格比で百分率へ換算しN分で割る。',
        '初発は既知の方向stateから定義し、速度だけか全ゲート結合後のstateかを結果前固定する。',
        '連続発火では同じ波が多数標本になるので、検知候補数と実取引数を分け、単純な独立試行としない。',
        '末尾形成中の足は公開しない。新入口prefixでも公開行iの直前・直後、準備3/5/10分境界、欠測、同時計更新を確認する。',
        '既存can_tradeにはSMA20+3分準備がある。今回速度入口へ継承するか、新窓の観測条件で置換するかを明記する。',
        '時刻はCurrentPriceTime基準で実受信時計不明。seqにおける同一銘柄の過去性を確認しており、別銘柄厳密同時性は証明しない。'])
    (HERE/'確定1分公開の独立準備監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','口座数','公開足照合数','空白直後の公開数','prefix検査数','未来価格改変検査数')},ensure_ascii=False))


if __name__=='__main__':
    main()
