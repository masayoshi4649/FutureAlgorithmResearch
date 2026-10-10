"""先行価格診断の全評価値を、診断関数を呼ばず保存価格から独立再計算する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=HERE/'forward'


def sha(path: Path) -> str:
    """機能: 監査に使用する保存資料の内容指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(8388608):
            h.update(block)
    return h.hexdigest()


def equal(left: float | None, right: float | None) -> None:
    """機能: 欠測と有限な集計値を区別して比較する。

    引数: left/right (float|None)。返り値: なし (None)。不一致では例外。
    """
    if left is None or right is None:
        assert left is None and right is None,(left,right)
    else:
        assert np.isfinite(left) and np.isfinite(right)
        assert np.isclose(left,right,rtol=1e-10,atol=1e-10),(left,right)


def run() -> None:
    """機能: 全発火・全期間の価格値と全セッション／層別集計を独立照合する。

    引数: なし。返り値: なし (None)。新ナイト・売買損益・診断計算関数は使わない。
    """
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    assert len(inputs)==26 and not any(key[0]=='2026-09-29_Night' for key in inputs)
    events=pd.read_csv(OUT/'全発火と先行価格.csv',encoding='utf-8-sig')
    data=json.loads((OUT/'先行価格診断.json').read_text(encoding='utf-8'))
    protocol=json.loads((OUT/'先行価格診断の事前固定.json').read_text(encoding='utf-8'))
    before={path:sha(ROOT/path) for path in protocol['参照SHA256']}
    assert before==protocol['参照SHA256']
    checked=0
    for (identifier,session,symbol),part in events.groupby(['手法ID','セッション','銘柄'],sort=False):
        ready=inputs[(session,symbol)]
        with np.load(HERE/'component_entries'/(identifier+'.npz')) as archive:
            states=archive[session+'|'+symbol]
        expected=np.flatnonzero((states!=0)&(states!=np.r_[0,states[:-1]]))
        actual=part.loc[part['期間分']==5,'発火行'].to_numpy(int)
        np.testing.assert_array_equal(actual,expected)
        assert len(part)==4*len(expected)
        deadline=min(ready['limit'],ready['time_s'][-1])
        common=set(part.loc[(part['期間分']==60)&(part['状態']=='有効'),'発火行'].astype(int))
        for row in part.to_dict('records'):
            fire=int(row['発火行'])
            entry=fire+1
            assert row['共通60分標本']==(fire in common)
            assert row['方向']==states[fire] and row['発火seq']==ready['seq'][fire]
            if entry>=len(states):
                status='次行なし'
            elif not np.isfinite(ready['atr'][fire]) or ready['atr'][fire]<=0 or not np.isfinite(ready['last'][entry]) or ready['last'][entry]<=0:
                status='価格又はATR無効'
            else:
                target=ready['time_s'][entry]+row['期間分']*60
                endpoint=int(np.searchsorted(ready['time_s'],target))
                if ready['time_s'][entry]>deadline or target>deadline or endpoint>=len(states) or ready['time_s'][endpoint]>deadline:
                    status='期限不足'
                else:
                    path=states[fire]*(ready['last'][entry:endpoint+1]-ready['last'][entry])/ready['atr'][fire]
                    status='有効' if np.all(np.isfinite(path)) and np.all(ready['last'][entry:endpoint+1]>0) else '価格又はATR無効'
            assert row['状態']==status
            if status=='有効':
                assert int(row['基準行'])==entry and int(row['評価行'])==endpoint
                equal(row['基準価格'],ready['last'][entry])
                equal(row['当時ATR'],ready['atr'][fire])
                equal(row['評価価格'],ready['last'][endpoint])
                equal(row['符号付変化ATR'],float(path[-1]))
                equal(row['最大順行ATR'],float(max(0,np.max(path))))
                equal(row['最大逆行ATR'],float(max(0,-np.min(path))))
                equal(row['到達遅れ秒'],float(ready['time_s'][endpoint]-target))
            else:
                assert all(pd.isna(row[column]) for column in ('評価行','評価価格','符号付変化ATR','最大順行ATR','最大逆行ATR','到達遅れ秒'))
            checked+=1
    # ----------------------------------------
    # CSVの全発火からセッションの欠測・方向・算術平均を独立に戻す。
    grouped={(identifier,session,symbol,int(minutes)):part for (identifier,session,symbol,minutes),part
        in events.groupby(['手法ID','セッション','銘柄','期間分'],sort=False)}
    for row in data['セッション別']:
        part=grouped.get((row['手法ID'],row['セッション'],row['銘柄'],row['期間分']),events.iloc[:0])
        if row['方向区分']!='両方向':
            part=part.loc[part['方向']==(1 if row['方向区分']=='買い' else -1)]
        assert len(part)==row['発火数']
        for status,column in (('次行なし','次行なし数'),('価格又はATR無効','無効価格ATR数'),('期限不足','期限不足数')):
            assert int((part['状態']==status).sum())==row[column]
        all_valid=part.loc[part['状態']=='有効']
        assert int((~all_valid['共通60分標本']).sum())==row['共通60分除外数']
        valid=all_valid.loc[all_valid['共通60分標本']] if row['標本']=='共通60分' else all_valid
        assert len(valid)==row['評価数']
        ret=valid['符号付変化ATR']
        assert int((ret>0).sum())==row['順方向数']
        assert int((ret<0).sum())==row['逆方向数']
        assert int((ret==0).sum())==row['同値数']
        for target,column,operation in (('平均変化ATR','符号付変化ATR','mean'),
            ('中央値変化ATR','符号付変化ATR','median'),('平均最大順行ATR','最大順行ATR','mean'),
            ('平均最大逆行ATR','最大逆行ATR','mean'),('平均到達遅れ秒','到達遅れ秒','mean'),
            ('最大到達遅れ秒','到達遅れ秒','max')):
            equal(row[target],float(getattr(valid[column],operation)()) if len(valid) else None)
        equal(row['順方向率'],float((ret>0).mean()) if len(valid) else None)
    for row in data['層別']:
        selected=[value for value in data['セッション別'] if value['手法ID']==row['手法ID']
            and value['銘柄']==row['銘柄'] and value['方向区分']==row['方向区分']
            and value['標本']==row['標本'] and value['期間分']==row['期間分']
            and (row['場']=='全場' or row['場']==value['場'])]
        active=[value for value in selected if value['評価数']]
        assert len(selected)==row['全セッション数'] and len(active)==row['評価セッション数']
        assert len(selected)-len(active)==row['欠測セッション数']
        for column in ('発火数','評価数','次行なし数','無効価格ATR数','期限不足数','共通60分除外数'):
            assert sum(value[column] for value in selected)==row[column]
        for column in ('平均変化ATR','平均最大順行ATR','平均最大逆行ATR','順方向率'):
            equal(row['場等重み'+column],sum(value[column] for value in active)/len(active) if active else None)
        assert sum(value['平均変化ATR']>0 for value in active)==row['正平均セッション数']
        assert sum(value['平均変化ATR']<0 for value in active)==row['負平均セッション数']
    assert checked==len(events)==data['評価行数']
    assert {path:sha(ROOT/path) for path in before}==before
    proof=dict(全合格=True,評価値照合数=checked,セッション照合数=len(data['セッション別']),
        層別照合数=len(data['層別']),価格差順行逆行を元配列から計算=True,発火を元方向列から再作成=True,
        共通60分標本一致=True,欠測をゼロ評価へ混ぜない=True,場等重み一致=True,入力不変=True,
        新ナイト読取=False,売買損益読取=False,API取得数=0,
        出典SHA256={name:sha(OUT/name) for name in ('全発火と先行価格.csv','先行価格診断.json','先行価格診断の事前固定.json')})
    (OUT/'独立照合.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:proof[key] for key in ('全合格','評価値照合数','セッション照合数','層別照合数')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    run()
