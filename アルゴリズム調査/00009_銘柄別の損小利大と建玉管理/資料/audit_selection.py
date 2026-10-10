"""全サイクルから選択指標と順位を、研究コードを呼ばずに再計算する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
SESSIONS = ['2026-09-21_Day','2026-09-21_Night','2026-09-22_Day','2026-09-22_Night',
            '2026-09-23_Day','2026-09-23_Night','2026-09-24_Day']


def independent_statistics(cycles: list[dict], sessions: list[str], symbol: str) -> dict:
    """機能: 全脚をまとめた完了サイクルから、銘柄内比率と１区間除外値を算出する。

    引数: cycles (list[dict])、sessions (list[str])、symbol (str)。
    返り値: dict: 探索表と直接比較する独立指標。
    """
    selected = [c for c in cycles if c['session'] in sessions]
    completed = [c for c in selected if c['complete']]
    values = np.array([c['net_yen'] for c in completed])
    labels = np.array([c['session'] for c in completed])
    wins,losses = values[values>0],-values[values<0]
    payoff = float(wins.mean()/losses.mean()) if len(wins) and len(losses) else None
    pf = float(wins.sum()/losses.sum()) if len(losses) else None
    session_net = [sum(c['net_yen'] for c in selected if c['session']==s) for s in sessions]
    session_aux = [sum(c['net_r'] if symbol=='NT' else c['net_atr']/c['cap']
                       for c in selected if c['session']==s) for s in sessions]
    active = sum(any(c['session']==s for c in completed) for s in sessions)
    positive = sum(v>0 for v in session_net)
    without_best = sum(session_aux)-max(session_aux)
    sample = len(values)>=10 and len(wins)>=3 and len(losses)>=3 and active>=min(4,len(sessions))
    quality = bool(sample and payoff is not None and payoff>1 and pf is not None and pf>1
                   and positive>len(sessions)/2 and without_best>0)
    pfs,payoffs = [],[]
    for omitted in sessions:
        part = values[labels!=omitted]
        wp,lp = part[part>0],-part[part<0]
        pfs.append(float(wp.sum()/lp.sum()) if len(lp) else None)
        payoffs.append(float(wp.mean()/lp.mean()) if len(wp) and len(lp) else None)
    min_pf = None if any(p is None for p in pfs) else min(pfs)
    min_payoff = None if any(p is None for p in payoffs) else min(payoffs)
    score = min(5.,min_pf,min_payoff) if min_pf is not None and min_payoff is not None else 0.
    return dict(complete_cycles=len(values),wins=len(wins),losses=len(losses),
                avg_win=float(wins.mean()) if len(wins) else None,
                avg_loss=float(losses.mean()) if len(losses) else None,
                payoff_ratio=payoff,profit_factor=pf,win_rate=len(wins)/len(values) if len(values) else None,
                all_net=sum(session_net),auxiliary_net=sum(session_aux),
                auxiliary_without_best_session=without_best,positive_sessions=positive,
                complete_traded_sessions=active,sample_ok=sample,qualified=quality,
                loo_min_pf=min_pf,loo_min_payoff=min_payoff,score=score)


def assert_metrics(expected: dict, saved: dict) -> int:
    """機能: 空比率を無限大にしないことも含め、保存した選択指標と比較する。

    引数: expected/saved (dict)。返り値: int: 検査した指標数。
    """
    for field,value in expected.items():
        actual = saved[field]
        if value is None:
            assert actual is None or pd.isna(actual),(saved.get('method'),field,value,actual)
        elif isinstance(value,bool):
            assert bool(actual)==value,(saved.get('method'),field,value,actual)
        else:
            np.testing.assert_allclose(actual,value,atol=1e-7,rtol=1e-8,
                err_msg=str((saved.get('method'),saved.get('symbol'),field)))
    return len(expected)


def choose_independent(frame: pd.DataFrame, symbol: str, philosophy: str | None) -> tuple:
    """機能: 銘柄を先に絞って固定資格、除外最悪比率、全体比率、IDの順で選ぶ。

    引数: frame (DataFrame)、symbol (str)、philosophy (str|None)。
    返り値: tuple: 上位ID一覧、候補数、探索基準充足。
    """
    options = [r for r in frame.to_dict('records') if r['symbol']==symbol and not r['diagnostic_only']
               and (philosophy is None or r['philosophy']==philosophy)]
    strict = [r for r in options if r['qualified']]
    if strict:
        options = strict
    else:
        sampled = [r for r in options if r['sample_ok']]
        options = sampled if sampled else [r for r in options if r['complete_cycles']>0]
    ordered = sorted(options,key=lambda r:(-r['score'],
                     -r['profit_factor'] if pd.notna(r['profit_factor']) else float('inf'),
                     -r['payoff_ratio'] if pd.notna(r['payoff_ratio']) else float('inf'),r['method']))
    return [r['method'] for r in ordered[:12]],len(options),bool(strict)


def check_selection(record: dict, frame: pd.DataFrame) -> None:
    """機能: 主候補・思想別・時間順の保存選択を独立並べ替えと比較する。

    引数: record (dict)、frame (DataFrame)。返り値: None: 不一致時例外。
    """
    top,count,strict = choose_independent(frame,record['銘柄'],record['思想'])
    assert count==record['候補数']
    assert top==[r['method'] for r in record['上位']]
    assert (record['採用']['method'] if record['採用'] else None)==(top[0] if top else None)
    assert strict==('候補なし' not in record['判定'])


def main() -> None:
    """機能: 全思想の全指標と、同銘柄だけの採用・時間順選択を独立監査する。

    引数: なし。返り値: None: 条件選択の独立監査.jsonを作成。通信しない。
    """
    metric_checks,metric_rows = 0,0
    frames,prefixes = [],[]
    pools = {}
    for name in ['単独','格子','NT']:
        with (OUT/f'{name}_サイクル.pkl').open('rb') as stream:
            pool = pickle.load(stream)
        pools.update(pool)
        frame = pd.read_csv(OUT/f'{name}_探索集計.csv')
        prefix = pd.read_csv(OUT/f'{name}_時間順候補.csv')
        frames.append(frame); prefixes.append(prefix)
        for saved in [*frame.to_dict('records'),*prefix.to_dict('records')]:
            count = int(saved['train_count'])
            expected = independent_statistics(pool[(saved['method'],saved['symbol'])],SESSIONS[:count],saved['symbol'])
            metric_checks += assert_metrics(expected,saved)
            metric_rows += 1
        print(f'{name} 全行の選択指標を独立照合済み: {metric_rows}',flush=True)
    frame = pd.concat(frames,ignore_index=True)
    prefix = pd.concat(prefixes,ignore_index=True)
    final = json.loads((OUT/'最終選択.json').read_text(encoding='utf-8'))
    walks = json.loads((OUT/'時間順選択.json').read_text(encoding='utf-8'))
    assert final['選択用セッション']==SESSIONS
    assert not final['円額の銘柄横断比較'] and not final['既知ナイト前半を選択に使う']
    records = [*final['主候補'].values(),*final['思想別代表'].values()]
    for record in records:
        check_selection(record,frame)
    for record in walks:
        count = len(record['学習'])
        assert record['学習']==SESSIONS[:count] and record['評価']==SESSIONS[count]
        check_selection(record,prefix[prefix.train_count.eq(count)])
    walk_metrics = pd.read_csv(OUT/'時間順の実評価.csv').to_dict('records')
    for saved in walk_metrics:
        cycles = [c for c in pools[(saved['方式'],saved['銘柄'])] if c['session']==saved['評価']]
        expected = independent_statistics(cycles,[saved['評価']],saved['銘柄'])
        for key in ['complete_cycles','wins','losses','avg_win','avg_loss','payoff_ratio','profit_factor','win_rate','all_net']:
            metric_checks += assert_metrics({key:expected[key]},{key:saved['cycle_'+key]})
    output = dict(成功=True,全指標行数=metric_rows,独立指標比較数=metric_checks,
                  主思想別選択比較数=len(records),時間順選択比較数=len(walks),
                  次区間実評価比較数=len(walk_metrics),銘柄横断円額順位=False,
                  既知ナイト前半の選択利用=False,損失未観測PF無限大化=False,API取得数=0,
                  主候補={s:r['採用']['method'] for s,r in final['主候補'].items()},
                  SHA256={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest()
                          for name in ['research.py','metrics.py','最終選択.json','時間順選択.json']})
    (OUT/'条件選択の独立監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False))


if __name__ == '__main__':
    main()
