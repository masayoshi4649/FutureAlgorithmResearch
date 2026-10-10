"""二つの固定候補の全玉会計、過去不変性、未返済条件を独立に監査する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
PREVIOUS = OUT.parent/'wave_v14'
sys.path.insert(0,str(PREVIOUS))
from audit_guard import independent_account
import reference
sys.path.pop(0)

TARGETS = {'NK225':'N03_R-1_L3_U1','TOPIX':'N15_R-1_A4_U0'}


def read_json(path: Path):
    """機能: 保存済みJSONを読み込む。

    引数: path (Path)。返り値: object: 内容。通信は行わない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """機能: 保存ファイルのSHA256を計算する。

    引数: path (Path)。返り値: str: ハッシュ。対象を変更しない。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024*1024):
            value.update(chunk)
    return value.hexdigest()


def compare_prefix(ready: dict, previous: dict, result: dict, config: dict) -> dict:
    """機能: 既読範囲の入力、対象信号、完了脚を前回保存結果と直接比較する。

    引数: ready/previous/result/config (dict)。返り値: dict: 検査数。
    """
    count = len(previous['seq'])
    for key in ['seq','time_s','last','atr','board_side','trend_side']:
        np.testing.assert_allclose(ready[key][:count],previous[key],equal_nan=True,atol=1e-10,rtol=0)
    family = config['family']
    old_event,new_event = previous['families'][family],ready['families'][family]
    keep = new_event['indices'] < count
    for key in ['indices','sides','deadlines']:
        np.testing.assert_allclose(new_event[key][keep],old_event[key],equal_nan=True,atol=1e-9,rtol=0)
    old_saved = read_json(PREVIOUS/'現在全体_全取引.json')
    old_trades = [t for t in old_saved if t['方式']==config['id'] and t['銘柄']==ready['symbol']]
    old_raw = np.array([[t[k] for k in reference.engine.RAW_COLUMNS] for t in old_trades],dtype=float).reshape((-1,22))
    assert np.all(old_raw[:,14]==1),'前回境界に未返済玉がある場合は別途比較が必要'
    raw = result['raw']
    closed_before = raw[(raw[:,14]==1)&(raw[:,6]<count)]
    np.testing.assert_allclose(closed_before,old_raw,equal_nan=True,atol=1e-8,rtol=0)
    truncated = dict(ready)
    for key in ['seq','time_s','last','atr','board_side','trend_side']:
        truncated[key] = ready[key][:count]
    prefix_result = reference.engine.simulate(truncated,family,config,detail=True)
    np.testing.assert_allclose(prefix_result['raw'],old_raw,equal_nan=True,atol=1e-8,rtol=0)
    return dict(入力原本行数=count,不変信号数=len(old_event['indices']),不変返済脚数=len(old_raw))


def independent_open_conditions(ready: dict, raw: np.ndarray, config: dict) -> list[dict]:
    """機能: 未返済脚の初期ストップ・追跡極値・現在ストップ・利確価格を原本から再算出する。

    引数: ready/config (dict)、raw (ndarray): 22列約定。返り値: list[dict]: 未返済条件。
    初期値は約定価格。約定行そのものの飛び越え価格を追跡極値へ遡及しない。
    """
    answer = []
    tick = ready['tick']
    for row in raw[raw[:,14]==0]:
        side,entry,atr,leg = int(row[2]),row[8],row[7],int(row[1])
        start,end = int(row[5]),int(row[6])
        initial_unrounded = entry-side*config['initial_stop_atr']*atr
        initial = (np.floor(initial_unrounded/tick) if side==1 else np.ceil(initial_unrounded/tick))*tick
        extreme = entry
        stop = initial
        for price in ready['last'][start+1:end+1]:
            if not np.isfinite(price) or price<=0:
                continue
            assert side*(price-stop)>0,'未返済脚が既存ストップへ到達している'
            extreme = max(extreme,price) if side==1 else min(extreme,price)
            favorable = max(0.,side*(extreme-entry))
            if favorable>=config['trail_start_atr']*atr:
                candidate = extreme-side*config['trail_atr']*atr
                candidate = (np.floor(candidate/tick) if side==1 else np.ceil(candidate/tick))*tick
                stop = max(stop,candidate) if side==1 else min(stop,candidate)
        np.testing.assert_allclose(stop,row[10],atol=1e-8)
        np.testing.assert_allclose(extreme,row[11],atol=1e-8)
        target_width = config.get('leg_targets',[None]*config['max_legs'])[leg]
        target = None
        if target_width is not None:
            value = entry+side*target_width*atr
            target = (np.ceil(value/tick) if side==1 else np.floor(value/tick))*tick
            observed = ready['last'][start+1:end+1]
            observed = observed[np.isfinite(observed)&(observed>0)]
            assert np.all(side*(observed-target)<0),'未返済脚が利確幅へ到達している'
        answer.append(dict(銘柄=ready['symbol'],方式=config['id'],サイクル番号=int(row[0]),脚番号=leg,
                           方向=side,新規価格=float(entry),固定ATR=float(atr),初期ストップ=float(initial),
                           順行極値=float(extreme),現在ストップ=float(stop),利確価格=target,
                           評価価格=float(row[9]),含み損益円=float(row[15]*reference.engine.MULTIPLIERS[ready['symbol']]),
                           強制返済条件時刻=float(ready['limit'])))
    return answer


def audit_cell(ready: dict, previous: dict, result: dict, config: dict, boundary: float) -> dict:
    """機能: 一銘柄の全原本会計・既知差分・過去不変性・未返済条件を照合する。

    引数: ready/previous/result/config (dict)、boundary (float)。返り値: dict: 独立結果。
    """
    raw = result['raw']; multiplier = reference.engine.MULTIPLIERS[ready['symbol']]
    values = independent_account(raw,ready['last'])
    summary = result['summary']
    net,closed,opened,dd = values[0][-1]*multiplier,values[3][-1]*multiplier,(values[0][-1]-values[3][-1])*multiplier,values[5]*multiplier
    for key,expected in [('net_yen',net),('closed_net_yen',closed),('open_yen',opened),('max_drawdown_yen',dd)]:
        np.testing.assert_allclose(summary[key],expected,atol=1e-5)
    first = np.searchsorted(ready['time_s'],boundary,side='left')
    baseline = values[0][first-1]*multiplier
    difference = values[0][first:]*multiplier-baseline
    peak = np.maximum.accumulate(np.r_[0.,difference])[1:]
    curve = np.array(result['equity'])
    positions = np.searchsorted(ready['seq'],curve[:,1].astype(int))
    np.testing.assert_allclose(curve[:,2],values[0][positions]*multiplier,atol=1e-5)
    np.testing.assert_allclose(curve[:,4],values[2][positions],atol=1e-5)
    np.testing.assert_allclose(curve[:,5],values[3][positions]*multiplier,atol=1e-5)
    np.testing.assert_allclose(curve[:,6],values[4][positions]*multiplier,atol=1e-5)
    assert values[2].max()<=config['max_legs']
    assert int(values[2][-1])==sum(raw[:,14]==0)
    return dict(方式=config['id'],銘柄=ready['symbol'],原本行数=len(ready['seq']),
                全体収支円=float(net),全体確定円=float(closed),含み円=float(opened),全体最大下落円=float(dd),
                境界直前資産円=float(baseline),新たな区間収支円=float(difference[-1]),
                新たな区間最大下落円=float((peak-difference).max()),
                過去不変性=compare_prefix(ready,previous,result,config),
                未返済条件=independent_open_conditions(ready,raw,config))


def check_cycle_statistics(cycles: list[dict], summary: dict) -> int:
    """機能: 完了組の勝敗と全玉損益を保存サイクルから独立集計する。

    引数: cycles (list[dict])、summary (dict)。返り値: int: 確認指標数。
    """
    completed = [c for c in cycles if c['complete']]
    values = np.array([c['net_yen'] for c in completed])
    wins,losses = values[values>0],-values[values<0]
    expected = dict(complete_cycles=len(completed),incomplete_cycles=len(cycles)-len(completed),
                    wins=len(wins),losses=len(losses),all_net=sum(c['net_yen'] for c in cycles),
                    all_closed_net=sum(c['closed_yen'] for c in cycles),
                    all_open_net=sum(c['open_yen'] for c in cycles),
                    profit_factor=float(wins.sum()/losses.sum()) if len(losses) else None,
                    payoff_ratio=float(wins.mean()/losses.mean()) if len(wins) and len(losses) else None)
    for key,value in expected.items():
        if value is None:
            assert summary[key] is None
        else:
            np.testing.assert_allclose(summary[key],value,atol=1e-5)
    return len(expected)


def check_state(ready: dict, result: dict, saved: dict, cfg: dict, independent: list[dict]) -> None:
    """機能: 表示された未返済条件・未約定新規の向き、幅、時刻を確認する。

    引数: ready/result/saved/cfg (dict)、independent (list[dict])。返り値: None。
    """
    fields = {'初期損切り価格':'初期ストップ','有効返済ストップ':'現在ストップ',
              '利確価格':'利確価格','順行極値':'順行極値','固定ATR':'固定ATR',
              '新規価格':'新規価格','含み損益円':'含み損益円'}
    assert len(saved['建玉'])==len(independent)
    for position,wanted in zip(saved['建玉'],independent):
        assert position['方向']==('買い' if wanted['方向']==1 else '売り')
        assert position['脚番号']==wanted['脚番号'] and position['サイクル番号']==wanted['サイクル番号']
        for output,expected in fields.items():
            if wanted[expected] is None:
                assert position[output] is None
            else:
                np.testing.assert_allclose(position[output],wanted[expected],atol=1e-8)
    np.testing.assert_allclose(saved['全返済判断時刻秒'],ready['limit'])
    np.testing.assert_allclose(saved['新規停止時刻秒'],ready['limit']-cfg['entry_deadline_min']*60)
    pending = saved['未約定新規']
    assert int(pending is not None)==result['summary']['pending_entries']
    if pending is not None:
        assert not independent
        index = pending['条件行位置']
        events = ready['families'][cfg['family']]
        event = int(np.flatnonzero(events['indices']==index)[0])
        side = int(events['sides'][event]*cfg['signal_multiplier'])
        atr = max(ready['atr'][index],2*ready['tick'])
        assert pending['方向']==side
        np.testing.assert_allclose(pending['固定ATR'],atr)
        deadline = min(events['deadlines'][event],ready['time_s'][index]+cfg['max_age_min']*60)
        np.testing.assert_allclose(pending['期限秒'],deadline)
        assert saved['評価時刻秒']<=deadline
        if cfg['entry_mode']=='market':
            assert pending['指定価格'] is None
            assert not np.any(np.isfinite(ready['last'][index+1:])&(ready['last'][index+1:]>0))
        else:
            value = ready['last'][index]+side*cfg['entry_atr']*atr
            threshold = (np.ceil(value/ready['tick']) if side==1 else np.floor(value/ready['tick']))*ready['tick']
            np.testing.assert_allclose(pending['指定価格'],threshold)
            prices = ready['last'][index+1:]
            prices = prices[np.isfinite(prices)&(prices>0)]
            assert np.all(side*(prices-threshold)<0)


def main() -> None:
    """機能: 一回取得後の保存結果だけを独立照合し、監査結果JSONを出力する。

    引数: なし。返り値: None: 監査結果.jsonを保存。取引・取得・条件変更は行わない。
    """
    root = OUT.parents[1]
    frozen = read_json(OUT/'現在照合_凍結記録.json')
    receipt = read_json(OUT/'live/取得記録.json')
    assert datetime.fromisoformat(frozen['fixed_at'])<datetime.fromisoformat(receipt['started_at'])
    assert frozen['selected_by_symbol']==TARGETS and len(frozen['selected_ids'])==2
    assert len(receipt['requests'])==6 and all(r['attempts']==1 and r['ok'] for r in receipt['requests'])
    assert receipt['manifest_sha256']==digest(OUT/'現在照合_凍結記録.json')
    for relative,expected in frozen['files_sha256'].items():
        assert digest(root/relative)==expected,relative
    for request in receipt['requests']:
        path = root/request['path']
        assert digest(path)==request['sha256'] and path.stat().st_size==request['bytes']
    old_configs = {c['id']:c for c in read_json(PREVIOUS/'全条件一覧.json')}
    configs = {c['id']:c for c in frozen['selected_configs']}
    for identifier,cfg in configs.items():
        assert cfg==old_configs[identifier]
    # ----------------------------------------
    for symbol,book in frozen['known_books'].items():
        old_path = root/book['path']
        new_path = OUT/'live/book'/symbol/(frozen['session']+'.jsonl')
        assert digest(old_path)==book['sha256']
        with old_path.open('rb') as previous, new_path.open('rb') as current:
            while chunk := previous.read(1024*1024):
                assert current.read(len(chunk))==chunk
    with (OUT/'現在入力.pkl').open('rb') as stream:
        inputs = pickle.load(stream)
    with (PREVIOUS/'現在入力.pkl').open('rb') as stream:
        prior = pickle.load(stream)
    saved_full = {r['銘柄']:r for r in read_json(OUT/'結果_全体.json')}
    saved_extra = {r['銘柄']:r for r in read_json(OUT/'結果_追加区間.json')}
    raw_arrays = np.load(OUT/'全脚数値.npz')
    boundary = pd.Timestamp(frozen['known_cutoff']).timestamp()
    checks,records = 0,[]
    for symbol,method in TARGETS.items():
        full,extra = saved_full[symbol],saved_extra[symbol]
        ready,old_ready = inputs[(frozen['session'],symbol)],prior[(frozen['session'],symbol)]
        cfg = configs[method]
        result = dict(summary=full['summary'],raw=raw_arrays[symbol],equity=full['equity'])
        for trade,row in zip(full['trades'],result['raw']):
            np.testing.assert_allclose(np.array([trade[k] for k in reference.engine.RAW_COLUMNS],dtype=float),row,
                                       equal_nan=True,atol=1e-8)
        assert len(full['trades'])==len(result['raw'])
        record = audit_cell(ready,old_ready,result,cfg,boundary)
        check_state(ready,result,full['state'],cfg,record['未返済条件'])
        np.testing.assert_allclose(extra['summary']['net_yen'],record['新たな区間収支円'],atol=1e-5)
        np.testing.assert_allclose(extra['summary']['max_drawdown_yen'],record['新たな区間最大下落円'],atol=1e-5)
        np.testing.assert_allclose(extra['boundary']['baseline_equity_yen'],record['境界直前資産円'],atol=1e-5)
        assert not any(c['carried'] for c in extra['cycles']),'前回境界に未返済組はなかった'
        for saved in [full,extra]:
            checks += check_cycle_statistics(saved['cycles'],saved['cycle_summary'])
            np.testing.assert_allclose(sum(t['収支円'] for t in saved['trades']),saved['summary']['net_yen'],atol=1e-5)
            np.testing.assert_allclose(sum(t['収支円'] for t in saved['trades'] if t['返済済み']),
                                       saved['summary']['closed_net_yen'],atol=1e-5)
        checks += check_cycle_statistics(extra['cycles'],extra['fresh_summary'])
        records.append(record)
    for relative,expected in frozen['files_sha256'].items():
        assert digest(root/relative)==expected,relative
    answer = dict(成功=True,条件変更=False,取得要求数=6,各要求回数=1,監査のAPI取得数=0,
                  凍結ファイル数=len(frozen['files_sha256']),サイクル指標確認数=checks,
                  未読開始=frozen['known_cutoff'],取得締切未満=receipt['cutoff'],対象=records)
    (OUT/'監査結果.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(answer,ensure_ascii=False))


if __name__=='__main__':
    main()
