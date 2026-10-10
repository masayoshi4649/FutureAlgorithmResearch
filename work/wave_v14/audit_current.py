"""一回取得後の凍結不変性と、全建玉・未知境界の最終会計を独立に監査する。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

from audit_extensions import pair_full_account
from audit_guard import independent_account
from audit_selection import independent_statistics, assert_metrics
import details
import pair_engine
import reference

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def read_json(name: str):
    """機能: 今回の保存済みJSONを読む。

    引数: name (str)。返り値: object: JSON内容。
    """
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """機能: 原本を変更せずSHA256を計算する。

    引数: path (Path)。返り値: str: ハッシュ。
    """
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(1024*1024):
            hasher.update(data)
    return hasher.hexdigest()


def compare_values(saved: dict, net: float, dd: float, closed: float, opened: float) -> None:
    """機能: 保存要約を全脚の独立損益・全行最大下落と照合する。

    引数: saved (dict)、net/dd/closed/opened (float)。返り値: None。
    """
    expected = dict(net_yen=net,max_drawdown_yen=dd,closed_net_yen=closed,open_yen=opened)
    for key,value in expected.items():
        np.testing.assert_allclose(saved[key],value,atol=1e-5,rtol=1e-8,err_msg=str((saved['方式'],saved['銘柄'],key)))


def main() -> None:
    """機能: 保存された現在再生だけを使い、凍結・集計・全行資産・増分を検査する。

    引数: なし。返り値: None: 現在照合の独立監査.jsonを保存。追加通信なし。
    """
    frozen,receipt = read_json('現在照合_凍結記録.json'),read_json('現在照合_取得記録.json')
    assert datetime.fromisoformat(frozen['fixed_at']) < datetime.fromisoformat(receipt['started_at'])
    assert len(receipt['requests'])==6 and len({r['url'] for r in receipt['requests']})==6
    assert receipt['各要求回数']==1 and not receipt['再試行'] and not receipt['リダイレクト']
    assert receipt['manifest_sha256']==digest(OUT/'現在照合_凍結記録.json')
    for relative,expected in frozen['files_sha256'].items():
        assert digest(ROOT/relative)==expected,relative
    for request in receipt['requests']:
        assert request['attempts']==1 and request['http_status']==200 and request['ok']
        path = ROOT/request['path']
        assert path.stat().st_size==request['bytes'] and digest(path)==request['sha256']
    final = read_json('最終選択.json')
    assert final['照合ID']==frozen['selected_ids']
    assert {k:r['採用']['method'] for k,r in final['主候補'].items()}==frozen['selected_by_symbol']
    # ----------------------------------------
    full_frame = pd.read_csv(OUT/'現在全体_セッション集計.csv')
    after_frame = pd.read_csv(OUT/'現在後半_セッション集計.csv')
    frames = [full_frame,after_frame]
    cycle_groups = []
    ledger_legs,cycle_checks = 0,0
    for prefix,frame in zip(['現在全体','現在後半'],frames):
        trades,cycles = read_json(prefix+'_全取引.json'),read_json(prefix+'_サイクル.json')
        grouped_trades,grouped_cycles = defaultdict(list),defaultdict(list)
        for trade in trades:
            symbol = 'NT' if str(trade['方式']).startswith('NT_') else trade['銘柄']
            grouped_trades[(trade['方式'],symbol)].append(trade)
            multiplier = trade.get('倍率',reference.engine.MULTIPLIERS[trade['銘柄']])
            expected = trade['方向']*trade['枚数']*multiplier*(trade['返済評価価格']-trade['新規価格'])
            np.testing.assert_allclose(trade['収支円'],expected,atol=1e-5)
            ledger_legs += 1
        for cycle in cycles:
            grouped_cycles[(cycle['method'],cycle['symbol'])].append(cycle)
        cycle_groups.append(grouped_cycles)
        for saved in frame.to_dict('records'):
            key = (saved['方式'],saved['銘柄']); cs = grouped_cycles[key]; legs = grouped_trades[key]
            expected = independent_statistics(cs,[saved['セッション']],saved['銘柄'])
            for field in ['complete_cycles','wins','losses','avg_win','avg_loss','payoff_ratio','profit_factor','win_rate','all_net']:
                assert_metrics({field:expected[field]},{field:saved['cycle_'+field]})
                cycle_checks += 1
            np.testing.assert_allclose(sum(t['収支円'] for t in legs),saved['net_yen'],atol=1e-5)
            np.testing.assert_allclose(sum(c['net_yen'] for c in cs),saved['net_yen'],atol=1e-5)
            open_count = saved['open_count'] if pd.notna(saved['open_count']) else saved['cycle_open_legs']
            assert sum(c['open_legs'] for c in cs)==open_count
            if prefix=='現在後半':
                fresh = [c for c in cs if not c['carried']]
                stat = independent_statistics(fresh,[saved['セッション']],saved['銘柄'])
                for field in ['complete_cycles','wins','losses','payoff_ratio','profit_factor','all_net']:
                    assert_metrics({field:stat[field]},{field:saved['fresh_'+field]})
                    cycle_checks += 1
    # ----------------------------------------
    with (OUT/'現在入力.pkl').open('rb') as stream:
        prepared = pickle.load(stream)
    configs = {c['id']:c for c in frozen['selected_configs']}
    boundary = pd.Timestamp(frozen['known_cutoff']).timestamp()
    session = frozen['session']
    pair_ready = pair_engine.prepare_session(session,tapes=[prepared[(session,s)] for s in reference.SYMBOLS])
    all_rows,all_cells,boundaries = 0,0,0
    for saved in full_frame.to_dict('records'):
        method,symbol = saved['方式'],saved['銘柄']; cfg = configs[method]
        after = after_frame[after_frame['方式'].eq(method)&after_frame['銘柄'].eq(symbol)].iloc[0].to_dict()
        if cfg['engine']=='pair':
            result = pair_engine.run(pair_ready,cfg,detail=True)
            values = pair_full_account(pair_ready,result)
            curve = result['full_curve']; mask = curve[:,0]>=boundary
            baseline = values[~mask][-1]
            suffix = values[mask]-baseline
            peak = np.maximum.accumulate(np.r_[0.,suffix])[1:]
            split = pair_engine.split_at_boundary(result,pair_ready,boundary)
            closed = sum(x['net_yen'] for x in result['legs'] if x['complete'])
            opened = sum(x['net_yen'] for x in result['legs'] if not x['complete'])
            compare_values(saved,values[-1],float(curve[:,4].max()),closed,opened)
            cs = cycle_groups[1][(method,symbol)]
            compare_values(after,suffix[-1],float((peak-suffix).max()),
                           sum(c['closed_yen'] for c in cs),sum(c['open_yen'] for c in cs))
            np.testing.assert_allclose(after['baseline_equity_yen'],baseline,atol=1e-5)
            np.testing.assert_allclose(split['net_yen'],suffix[-1],atol=1e-5)
            all_rows += len(curve)
        else:
            ready = prepared[(session,symbol)]
            result,cs = details.single_result(ready,cfg)
            actual = independent_account(result['raw'],ready['last'])
            multiplier = reference.engine.MULTIPLIERS[symbol]
            compare_values(saved,actual[0][-1]*multiplier,actual[5]*multiplier,
                           actual[3][-1]*multiplier,(actual[0][-1]-actual[3][-1])*multiplier)
            first = np.searchsorted(ready['time_s'],boundary,side='left')
            baseline = actual[0][first-1]*multiplier
            suffix = actual[0][first:]*multiplier-baseline
            peak = np.maximum.accumulate(np.r_[0.,suffix])[1:]
            split,split_cycles,diagnostic = details.split_single(ready,result,cs,cfg,boundary)
            independently_split = independent_account(split['raw'],ready['last'])
            np.testing.assert_allclose(independently_split[0][first:]*multiplier,suffix,atol=1e-5)
            compare_values(after,suffix[-1],float((peak-suffix).max()),
                           independently_split[3][-1]*multiplier,
                           (independently_split[0][-1]-independently_split[3][-1])*multiplier)
            np.testing.assert_allclose(after['baseline_equity_yen'],baseline,atol=1e-5)
            assert int(actual[2].max())<=cfg['max_legs']
            all_rows += len(ready['last'])
        all_cells += 1; boundaries += 1
    for relative,expected in frozen['files_sha256'].items():
        assert digest(ROOT/relative)==expected,relative
    output = dict(成功=True,固定ファイル数=len(frozen['files_sha256']),固定ID数=len(configs),
                  原本応答数=6,各応答取得回数=1,追加API取得数=0,明細脚比較数=ledger_legs,
                  完了未完了指標比較数=cycle_checks,全行会計セル数=all_cells,
                  原本行と時計行の延べ数=all_rows,未知境界比較数=boundaries,
                  既知境界=frozen['known_cutoff'],取得締切=receipt['cutoff'],
                  主候補不変=True,全凍結ソース不変=True,
                  注記='未知増分の全脚・継続玉・新規サイクルを区別。未返済損益込み。')
    (OUT/'現在照合の独立監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False))


if __name__ == '__main__':
    main()
