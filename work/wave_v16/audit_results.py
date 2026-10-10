"""保存された全取引からサイクルと銘柄別の損小利大を独立に再集計する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent
MULTIPLIERS = {'NK225': 1000., 'TOPIX': 10000.}


def read_json(name: str) -> object:
    """機能: この作業の保存済みJSONだけを読み込む。

    引数: name (str)。返り値: JSON値 (object)。通信は行わない。
    """
    return json.loads((WORK/name).read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """機能: 入力と検査対象の内容を識別する。

    引数: path (Path)。返り値: SHA256 (str)。ファイルは変更しない。
    """
    answer = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024*1024):
            answer.update(chunk)
    return answer.hexdigest()


def close(actual: float | None, expected: float | None, label: str) -> None:
    """機能: 欠損と有限数を区別して、独立計算と保存値を照合する。

    引数: actual/expected (float|None)、label (str)。返り値: なし (None)。
    """
    if expected is None:
        if actual is not None and not pd.isna(actual):
            raise AssertionError(f'{label}: 欠損のはずが {actual}')
    elif actual is None or pd.isna(actual) or not np.isclose(actual,expected,rtol=1e-9,atol=1e-5):
        raise AssertionError(f'{label}: 保存 {actual} / 独立 {expected}')


def distribution(values: list[float]) -> dict:
    """機能: 完了サイクルの勝敗を、既存の指標コードを呼ばず集計する。

    引数: values (list[float])。返り値: 平均勝敗・PF等 (dict)。
    """
    wins = [x for x in values if x>0]
    losses = [-x for x in values if x<0]
    mean_win = sum(wins)/len(wins) if wins else None
    mean_loss = sum(losses)/len(losses) if losses else None
    return dict(count=len(values), complete_cycles=len(values), wins=len(wins), losses=len(losses),
        flats=sum(x==0 for x in values), net=sum(values), complete_net=sum(values),
        gross_profit=sum(wins),gross_loss=sum(losses),avg_win=mean_win,avg_loss=mean_loss,
        payoff_ratio=mean_win/mean_loss if wins and losses else None,
        profit_factor=sum(wins)/sum(losses) if losses else None,
        win_rate=len(wins)/len(values) if values else None,
        worst_cycle=min(values) if values else None,best_cycle=max(values) if values else None)


def sensitivity(cycles: list[dict], sessions: list[str]) -> dict:
    """機能: 同銘柄１方式の全期間・昼夜・最高区間除外を独立に求める。

    引数: cycles (list[dict])、sessions (list[str])。返り値: 感度診断 (dict)。
    """
    complete = [c for c in cycles if c['complete']]
    values = [c['net_yen'] for c in complete]
    result = distribution(values)
    session_values = {s:sum(c['net_yen'] for c in cycles if c['session']==s) for s in sessions}
    sorted_sessions = sorted(session_values.items(),key=lambda item:(item[1],item[0]),reverse=True)
    total = sum(session_values.values())
    result.update(all_net=total,session_count=len(sessions),
        positive_sessions=sum(v>0 for v in session_values.values()),
        negative_sessions=sum(v<0 for v in session_values.values()),
        flat_sessions=sum(v==0 for v in session_values.values()),
        session_worst=min(session_values.values()) if sessions else None,
        session_best=max(session_values.values()) if sessions else None,
        without_best_one=total-sum(v for _,v in sorted_sessions[:1]),
        without_best_two=total-sum(v for _,v in sorted_sessions[:2]),
        omitted_best_two=[s for s,_ in sorted_sessions[:2]],
        sessions=session_values)
    durations = [(c['exit_time_s']-c['entry_time_s'])/60 for c in complete if 'entry_time_s' in c]
    result['median_holding_min'] = float(np.median(durations)) if durations else None
    for kind in ['Day','Night']:
        part = [c['net_yen'] for c in complete if c['session'].endswith(kind)]
        result[kind] = distribution(part)
    return result


def audit_prefix(prefix: str) -> dict:
    """機能: 全脚の原価計算・サイクル会計・保存集計を直接比較する。

    引数: prefix (str)。返り値: 検査数と独立指標 (dict)。
    """
    trades = read_json(prefix+'_全取引.json')
    cycles = read_json(prefix+'_サイクル.json')
    frame = pd.read_csv(WORK/(prefix+'_セッション集計.csv'))
    catalog = WORK/'全条件一覧.json'
    if not catalog.exists(): catalog=WORK.parent/'wave_v14'/'全条件一覧.json'
    configs = {c['id']:c for c in json.loads(catalog.read_text(encoding='utf-8'))}
    grouped = defaultdict(list)
    leg_checks = 0
    for trade in trades:
        method,symbol = trade['方式'],trade['銘柄']
        cycle_symbol = 'NT' if configs[method].get('engine')=='pair' else symbol
        key = (method,cycle_symbol,trade['セッション'],int(trade['サイクル番号']))
        value = (trade['返済評価価格']-trade['新規価格'])*trade['方向']*trade.get('枚数',1)*trade.get('倍率',MULTIPLIERS[symbol])
        close(trade['収支円'],value,str(key)+' 脚円収支')
        assert trade['返済評価時刻']>=trade['新規時刻'],(key,'新規以前の返済')
        grouped[key].append((trade,value))
        leg_checks += 1
    cycle_checks = 0
    for cycle in cycles:
        key = (cycle['method'],cycle['symbol'],cycle['session'],int(cycle['cycle_id']))
        legs = grouped.pop(key)
        closed = [value for t,value in legs if t['返済済み']]
        opened = [value for t,value in legs if not t['返済済み']]
        for field,expected in [('net_yen',sum(closed)+sum(opened)),('closed_yen',sum(closed)),('open_yen',sum(opened)),
            ('legs',len(legs)),('closed_legs',len(closed)),('open_legs',len(opened))]:
            close(cycle[field],expected,str(key)+' '+field)
            cycle_checks += 1
        if cycle['complete']:
            assert not opened,(key,'未返済を完了サイクルに計上')
    assert not grouped,('サイクルへまとめていない脚',list(grouped)[:3])
    saved_checks = 0
    for row in frame.to_dict('records'):
        part = [c for c in cycles if c['method']==row['方式'] and c['symbol']==row['銘柄'] and c['session']==row['セッション']]
        completed = [c for c in part if c['complete']]
        expected = distribution([c['net_yen'] for c in completed])
        expected.update(incomplete_cycles=len(part)-len(completed),all_net=sum(c['net_yen'] for c in part),
            all_closed_net=sum(c['closed_yen'] for c in part),all_open_net=sum(c['open_yen'] for c in part))
        for field,value in expected.items():
            if 'cycle_'+field in row:
                close(row['cycle_'+field],value,str((row['方式'],row['銘柄'],row['セッション']))+' '+field)
                saved_checks += 1
        for field,metric in [('net_yen','all_net'),('closed_net_yen','all_closed_net'),('open_yen','all_open_net')]:
            if field in row:
                close(row[field],expected[metric],str((row['方式'],row['銘柄'],row['セッション']))+' '+field)
                saved_checks += 1
    sensitivities = {}
    for method,symbol in frame[['方式','銘柄']].drop_duplicates().itertuples(index=False,name=None):
        sessions = list(frame.loc[(frame['方式']==method)&(frame['銘柄']==symbol),'セッション'])
        part = [c for c in cycles if c['method']==method and c['symbol']==symbol]
        sensitivities[method+'|'+symbol] = sensitivity(part,sessions)
    return dict(全脚数=leg_checks,サイクル数=len(cycles),サイクル検査数=cycle_checks,保存指標検査数=saved_checks,
        表示セル数=len(frame),独立感度=sensitivities,
        入力ハッシュ={name:digest(WORK/name) for name in [prefix+'_全取引.json',prefix+'_サイクル.json',prefix+'_セッション集計.csv']})


def main() -> None:
    """機能: 指定された結果接頭辞を独立に集計し監査資料を保存する。

    引数: --prefix (list[str])。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix',nargs='+',required=True)
    args = parser.parse_args()
    answer = {prefix:audit_prefix(prefix) for prefix in args.prefix}
    path = WORK/'全取引とサイクルの独立監査.json'
    path.write_text(json.dumps(answer,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({key:{k:v for k,v in result.items() if k not in ['独立感度','入力ハッシュ']} for key,result in answer.items()},ensure_ascii=False))


if __name__=='__main__':
    main()
