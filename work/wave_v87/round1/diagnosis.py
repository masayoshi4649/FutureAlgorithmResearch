"""保存済み利確後再参加の入口を、当時までの情報で分解する。新しい売買は再生しない。"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
import pickle
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v86'
JST = timezone(timedelta(hours=9))


def module(name, path):
    """
    機能: 既存の読取処理を別名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def stamp(value):
    """
    機能: 原本代理時計を日本時間の文字列へ変換する。
    引数: value(float)。
    返り値: str。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def main():
    """
    機能: 追加入口・直前高安・同調の再成立・料金前後を照合する。
    引数: なし。
    返り値: None。既存の台帳は変更せず診断だけを保存する。
    """
    helper = module('v87_old_analysis', OLD / 'analysis/independent.py')
    prepare = module('v87_old_prepare', ROOT / 'work/wave_v85/prepare.py')
    strategy = module('v87_old_strategy', OLD / 'phase2/strategy.py')
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')
    inputs, signals, fingerprints = prepare.load_inputs(verify=True)
    features = strategy.initialize(inputs, signals)
    beforepath = OLD / 'observed/ledgers/T2_S.pkl'
    afterpath = OLD / 'phase2/observed/ledgers/T2_P1.pkl'
    before = pickle.loads(beforepath.read_bytes())
    after = pickle.loads(afterpath.read_bytes())
    bc = helper.extract(before, helper.read(OLD / 'observed/results/T2_S.json'))
    ac = helper.extract(after, helper.read(OLD / 'phase2/observed/results/T2_P1.json'))
    bkeys = {helper.entry_key(c) for c in bc}
    details = []
    for key, account in sorted(after.items()):
        ready, f = inputs[key], features[key]
        price, times = ready['last'], ready['time_s']
        state = np.where(f['gate'], f['columns'][0], 0)
        ema, ownsrc, peersrc, emavalid = f['ema']
        byid = {int(r[0]): r for r in account['cycles']}
        byfill = {int(r[1]): int(r[3]) for r in account['entry_preparations']}
        local = sorted((c for c in ac if (c['session'], c['symbol']) == key), key=lambda c: c['entry'])
        prior = None
        for cycle in local:
            row = byid[cycle['campaign']]
            entry, end, atr, side = int(row[1]), int(row[2]), float(row[5]), cycle['direction']
            prep = byfill[entry]
            entryprice = next(t['建値'] for t in account['net_trades'] if t['組'] == cycle['campaign'])
            path = side * (price[entry:end+1] - entryprice) / atr
            value = dict(cycle, added=helper.entry_key(cycle) not in bkeys, entry_row=entry,
                exit_row=end, prepare_row=prep, prepare_time=stamp(times[prep]),
                entry_jst=stamp(times[entry]), exit_jst=stamp(times[end]),
                entry_price=entryprice, initial_atr=atr, initial_stop_atr=.75,
                activation_atr=.75, trail_width_atr=.5,
                observed_mfe_atr=float(max(path)), observed_mae_atr=float(-min(path)),
                trail_ever_eligible=bool(max(path)>=.75), state_at_prepare=int(state[prep]),
                state_at_entry=int(state[entry]), ema_at_prepare=int(ema[prep]),
                self_ema_source_at_prepare=int(ownsrc[prep]), peer_ema_source_at_prepare=int(peersrc[prep]))
            if prior is not None:
                pcycle, prow = prior
                pe, px = int(prow[1]), int(prow[2])
                extreme = float(np.max(price[pe:px+1]) if side > 0 else np.min(price[pe:px+1]))
                valid_between = emavalid[px:prep+1]
                altered = valid_between & (ema[px:prep+1] != side)
                ceased = emavalid[pe:prep+1] & (ema[pe:prep+1] != side)
                value.update(previous_campaign=pcycle['campaign'], previous_net=pcycle['net'],
                    previous_direction=pcycle['direction'], same_direction=side==pcycle['direction'],
                    previous_exit_time=stamp(times[px]), seconds_from_exit_to_prepare=float(times[prep]-times[px]),
                    previous_extreme=extreme, previous_atr=float(prow[5]),
                    pullback_at_prepare_atr=float(side*(extreme-price[prep])/atr),
                    pullback_at_entry_atr=float(side*(extreme-price[entry])/atr),
                    surpassed_previous_extreme_at_prepare=bool(side*(price[prep]-extreme)>0),
                    surpassed_previous_extreme_at_entry=bool(side*(price[entry]-extreme)>0),
                    ema_valid_non_support_after_exit=bool(np.any(altered)),
                    ema_valid_non_support_since_previous_entry=bool(np.any(ceased)),
                    prior_ema_at_exit=int(ema[px]),
                    both_ema_sources_new_at_prepare=bool(ownsrc[prep]>ownsrc[px] and peersrc[prep]>peersrc[px]),
                    entry_state_ceased_after_exit=bool(np.any(state[px:prep+1]!=side)))
            details.append(value)
            prior = cycle, row
    # ----------------------------------------
    # 高安・支持の区分はその入口時点までの情報、MFE/MAE・収支は事後説明。
    grouped = []
    predicates = {
        '全追加': lambda x: x['added'],
        '直前黒字かつ同方向追加': lambda x: x['added'] and x.get('previous_net',0)>0 and x.get('same_direction',False),
        '直前黒字同方向かつ前高安未突破': lambda x: x['added'] and x.get('previous_net',0)>0 and x.get('same_direction',False) and not x['surpassed_previous_extreme_at_entry'],
        '直前黒字同方向かつ前高安突破': lambda x: x['added'] and x.get('previous_net',0)>0 and x.get('same_direction',False) and x['surpassed_previous_extreme_at_entry'],
        '直前黒字同方向かつ同調が継続': lambda x: x['added'] and x.get('previous_net',0)>0 and x.get('same_direction',False) and not x['ema_valid_non_support_after_exit'],
        '直前黒字同方向かつ同調離脱あり': lambda x: x['added'] and x.get('previous_net',0)>0 and x.get('same_direction',False) and x['ema_valid_non_support_after_exit'],
        '追加でトレール始動まで届かず': lambda x: x['added'] and not x['trail_ever_eligible'],
        '追加でトレール始動幅へ到達': lambda x: x['added'] and x['trail_ever_eligible'],
        '共通入口': lambda x: not x['added'],
    }
    for symbol in ('TOPIX','NK225'):
        for name, predicate in predicates.items():
            selected = [x for x in details if x['symbol']==symbol and predicate(x)]
            grouped.append(dict(symbol=symbol,group=name,**helper.summarize(selected)))
    output = dict(definition='保存済みT2_SとT2_P1を新規原本行・方向で照合。前高安と同調離脱は当時までの情報。MFE/MAEと収支は事後説明で、新規判断へ戻していない。入力時計はCurrentPriceTimeの代理時計。新たな売買再生・条件探索を行っていない。',
        input_SHA256=fingerprints,ledger_SHA256={str(beforepath):helper.sha(beforepath),str(afterpath):helper.sha(afterpath)},
        groups=grouped,details=details,
        worst_added={s:sorted((x for x in details if x['symbol']==s and x['added']),key=lambda x:x['net'])[:5] for s in ('TOPIX','NK225')})
    (HERE/'追加入口の時系列診断.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(grouped,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
