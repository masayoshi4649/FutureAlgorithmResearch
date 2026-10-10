"""候補資格・同銘柄順位・時間順区分を独立に検査する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

from audit_results import close,distribution,digest

WORK=Path(__file__).resolve().parent
SESSIONS=[f'2026-09-{day:02d}_{part}' for day in range(21,26) for part in ['Day','Night']]


def load_json(name: str) -> object:
    """機能: 保存済み選択結果を読み込む。

    引数: name (str)。返り値: JSON値 (object)。
    """
    return json.loads((WORK/name).read_text(encoding='utf-8'))


def independent_choice(rows: list[dict], symbol: str, philosophy: str | None) -> tuple:
    """機能: 既存の選択関数を使わず資格と順位を再計算する。

    引数: rows (list[dict])、symbol (str)、philosophy (str|None)。返り値: 候補数・上位ID (tuple)。
    """
    eligible=[r for r in rows if r['symbol']==symbol and not r['diagnostic_only'] and (philosophy is None or r['philosophy']==philosophy)]
    qualified=[r for r in eligible if r['qualified']]
    if qualified: candidates=qualified
    else:
        sampled=[r for r in eligible if r['sample_ok']]
        candidates=sampled or [r for r in eligible if r['complete_cycles']>0]
    def rank(row: dict) -> tuple:
        """機能: 欠損を末尾に送り、規定の比率降順・ID昇順へ揃える。

        引数: row (dict)。返り値: 並替えキー (tuple)。
        """
        return tuple(-row[k] if pd.notna(row[k]) else float('inf') for k in ['score','profit_factor','payoff_ratio'])+(row['method'],)
    ordered=sorted(candidates,key=rank)
    return len(candidates),[r['method'] for r in ordered[:12]]


def audit_gates(frame: pd.DataFrame) -> int:
    """機能: 全候補行の資格・得点を構成要素から直接再計算する。

    引数: frame (DataFrame)。返り値: 検査した行数 (int)。
    """
    sample=(frame.complete_cycles>=10)&(frame.wins>=3)&(frame.losses>=3)&(frame.complete_traded_sessions>=np.minimum(4,frame.train_count))
    qualified=sample&(frame.payoff_ratio>1)&(frame.profit_factor>1)&(frame.positive_sessions>frame.train_count/2)&(frame.auxiliary_without_best_session>0)
    assert np.array_equal(sample,frame.sample_ok.astype(bool)),'試料数資格の不一致'
    assert np.array_equal(qualified,frame.qualified.astype(bool)),'損小利大資格の不一致'
    expected=np.minimum(5,np.minimum(frame.loo_min_pf.clip(lower=0),frame.loo_min_payoff.clip(lower=0))).fillna(0)
    np.testing.assert_allclose(frame.score,expected,atol=1e-9)
    return len(frame)


def audit_metrics(rows: list[dict], samples: set[tuple[str,str]]) -> int:
    """機能: 採用候補と一定間隔の候補を、保存サイクルから独立に再集計する。

    引数: rows (list[dict])、samples (set[tuple[str,str]])。返り値: 比較した指標数 (int)。
    """
    by_key={}
    for name in ['単独','格子','NT']:
        with (WORK/f'{name}_サイクル.pkl').open('rb') as stream: source=pickle.load(stream)
        by_key.update({key:value for key,value in source.items() if key in samples})
    comparisons=0
    for row in rows:
        key=(row['method'],row['symbol'])
        if key not in samples: continue
        sessions=SESSIONS[:int(row['train_count'])]
        cycles=[c for c in by_key[key] if c['session'] in sessions]
        done=[c for c in cycles if c['complete']]
        expected=distribution([c['net_yen'] for c in done])
        session_nets=[sum(c['net_yen'] for c in cycles if c['session']==s) for s in sessions]
        expected.update(all_net=sum(session_nets),positive_sessions=sum(x>0 for x in session_nets),
            session_worst=min(session_nets),session_best=max(session_nets),
            net_without_best_session=sum(session_nets)-max(session_nets))
        for field,value in expected.items():
            if field in row:
                close(row[field],value,str(key)+' '+field);comparisons+=1
        loo=[]
        for omitted in sessions:
            others=[c['net_yen'] for c in done if c['session']!=omitted]
            d=distribution(others);loo.append(d)
        for field,source in [('loo_min_pf','profit_factor'),('loo_min_payoff','payoff_ratio')]:
            value=min(d[source] for d in loo) if all(d[source] is not None for d in loo) else None
            close(row[field],value,str(key)+' '+field);comparisons+=1
    return comparisons


def main() -> None:
    """機能: 選択済みデータだけを監査し、未来区間の読み込みを行わない。

    引数: なし。返り値: なし (None)。
    """
    record=load_json('最終選択.json');walks=load_json('時間順選択.json')
    frames=[]
    for name in ['単独','格子','NT']:
        frames.extend([pd.read_csv(WORK/f'{name}_探索集計.csv'),pd.read_csv(WORK/f'{name}_時間順候補.csv')])
    frame=pd.concat(frames,ignore_index=True)
    frame.loc[frame.family.isin(['N17','N18']),'diagnostic_only']=True
    frame['diagnostic_only']=frame.diagnostic_only.fillna(False).astype(bool)
    assert set(frame.train_count)==set(range(3,10)),'学習区間の過不足'
    assert not frame.duplicated(['method','symbol','train_count']).any(),'候補行重複'
    count=audit_gates(frame)
    rows=frame.to_dict('records')
    selections=[*record['主候補'].values(),*record['思想別代表'].values(),*walks]
    checked=0
    for choice in selections:
        past=choice.get('学習',record['選択用セッション'])
        assert past==SESSIONS[:len(past)] and len(past)<=9,'未来を学習へ含めた'
        if '評価' in choice: assert choice['評価']==SESSIONS[len(past)],'次区間以外を評価'
        candidates,ids=independent_choice([r for r in rows if r['train_count']==len(past)],choice['銘柄'],choice['思想'])
        assert candidates==choice['候補数'],'候補数不一致'
        assert ids==[r['method'] for r in choice['上位']],'上位順不一致'
        assert (ids[0] if ids else None)==(choice['採用']['method'] if choice['採用'] else None),'採用不一致'
        checked+=1
    samples={(r['採用']['method'],r['銘柄']) for r in selections if r['採用']}
    unique=sorted(set(zip(frame.method,frame.symbol)))
    samples.update(unique[::max(1,len(unique)//80)])
    metric_checks=audit_metrics(rows,samples)
    output=dict(全資格得点検査行=count,独立順位検査数=checked,独立指標の対象銘柄条件数=len(samples),
        独立指標検査数=metric_checks,最終保留を学習へ含む=False,因果性除外系統=['N17','N18'],
        入力ハッシュ={name:digest(WORK/name) for name in ['最終選択.json','時間順選択.json']})
    (WORK/'選択と時間順の独立監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False))


if __name__=='__main__': main()
