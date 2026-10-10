"""無予測の方向指定に対する注文管理の対照実験。主探索の候補順位へは混ぜない。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np

import engine
import managers
from research import summarize, aggregate

OUT = Path(__file__).resolve().parent
MANAGER_IDS = ('G00', 'G18', 'G07', 'G17')
SEEDS = tuple(range(16))


def random_state(ready: dict, seed: int) -> np.ndarray:
    """機能: 価格を参照せず、３０分ごとに固定する独立の買い売り方向を作る。

    引数: ready (dict)、seed (int)。返り値: 原本行ごとの -1/+1 (ndarray[int8])。
    セッション・銘柄を SHA256 で乱数列に織り込み、切断しても過去方向は変えない。
    """
    identity = f"{seed}|{ready['session']}|{ready['symbol']}".encode('utf-8')
    words = np.frombuffer(hashlib.sha256(identity).digest(), dtype='<u4')
    generator = np.random.default_rng(np.random.SeedSequence(words))
    blocks = np.maximum(0, np.floor((ready['time_s']-ready['start'])/1800).astype(np.int64))
    signs = (generator.integers(0,2,size=int(blocks.max())+1,dtype=np.int64)*2-1).astype(np.int8)
    return signs[blocks]


def distribution(values: list[float | None]) -> dict:
    """機能: 有限値だけの最小・中央値・最大を求める。

    引数: values (list[float|None])。返り値: 分布の要約 (dict)。
    """
    finite = np.array([v for v in values if v is not None and np.isfinite(v)],dtype=float)
    return {'最小':float(finite.min()) if len(finite) else None,
            '中央値':float(np.median(finite)) if len(finite) else None,
            '最大':float(finite.max()) if len(finite) else None,
            '有限件数':len(finite)}


def main() -> None:
    """機能: 固定１６乱数と買い固定・売り固定を、４注文管理で逐次比較する。

    引数: なし。返り値: なし (None)。control_results.json と短い説明を保存する。
    """
    started = time.monotonic()
    additional = '--additional' in sys.argv
    manager_ids = ('G08', 'G12') if additional else MANAGER_IDS
    suffix = '_additional' if additional else ''
    inputs = pickle.loads((OUT/'inputs.pkl').read_bytes())
    selected = {spec['id']:spec for spec in managers.manager_catalog() if spec['id'] in manager_ids}
    rows, random_periods, fixed_periods = [], [], []
    scenarios = [(f'乱数{seed:02d}',seed,None) for seed in SEEDS]+[('常時買い',None,1),('常時売り',None,-1)]
    completed, prefix_cases = 0, 0
    for name, seed, fixed_side in scenarios:
        directions = {}
        for key, ready in inputs.items():
            state = random_state(ready,seed) if seed is not None else np.full(len(ready['time_s']),fixed_side,dtype=np.int8)
            directions[key] = state
            if seed is not None:
                for fraction in (.33,.67):
                    short = dict(ready)
                    cut = int(len(ready['time_s'])*fraction)
                    short['time_s'] = ready['time_s'][:cut]
                    np.testing.assert_array_equal(state[:cut],random_state(short,seed))
                    prefix_cases += 1
        for manager_id in manager_ids:
            manager = selected[manager_id]
            subset = []
            identifier = f'{name}_{manager_id}'
            for key, ready in inputs.items():
                session,symbol = key
                cfg = managers.make_config(manager,symbol,ready)
                result = engine.run(ready,directions[key],cfg,detail=False)
                summary = summarize(result,cfg,symbol,session,identifier)
                summary.update(manager_id=manager_id,対照=name,seed=seed)
                rows.append(summary)
                subset.append(summary)
            for symbol in ('TOPIX','NK225'):
                period = dict(manager_id=manager_id,symbol=symbol,対照=name,seed=seed,
                              **aggregate([r for r in subset if r['symbol']==symbol]))
                (random_periods if seed is not None else fixed_periods).append(period)
            completed += 1
            if completed % len(manager_ids) == 0:
                print(f'対照再生 {completed}/{len(scenarios)*len(manager_ids)} 条件完了、経過 {time.monotonic()-started:.1f} 秒',flush=True)
    summaries = []
    for manager_id in manager_ids:
        for symbol in ('TOPIX','NK225'):
            seeds = [r for r in random_periods if r['manager_id']==manager_id and r['symbol']==symbol]
            summaries.append(dict(manager_id=manager_id,管理名=selected[manager_id]['name'],symbol=symbol,
                seed数=len(seeds),seed黒字数=sum(r['net_yen']>0 for r in seeds),
                seed黒字割合=sum(r['net_yen']>0 for r in seeds)/len(seeds),
                利益円=distribution([r['gross_profit_yen'] for r in seeds]),
                損失円=distribution([r['gross_loss_yen'] for r in seeds]),
                収支円=distribution([r['net_yen'] for r in seeds]),
                金額PF=distribution([r['money_ratio'] for r in seeds]),
                組PF=distribution([r['cycle_ratio'] for r in seeds]),
                時価最大下落円=distribution([r['drawdown_yen'] for r in seeds]),
                seed別=seeds))
    both = []
    for manager_id in manager_ids:
        count = sum(all(next(r for r in random_periods if r['manager_id']==manager_id and r['symbol']==symbol and r['seed']==seed)['net_yen']>0
                        for symbol in ('TOPIX','NK225')) for seed in SEEDS)
        both.append(dict(manager_id=manager_id,両銘柄黒字seed数=count,seed数=len(SEEDS),両銘柄黒字割合=count/len(SEEDS)))
    output = {'対照の目的':'価格予測なしで注文管理だけを使った場合の、この既知期間における成績分布を確認する。',
              '条件':{'セッション数':len({k[0] for k in inputs}),'銘柄区間数':len(inputs),'乱数種':list(SEEDS),
                      '方向更新分':30,'銘柄とセッションの乱数独立':True,'管理ID':list(manager_ids),
                      '費用円':0,'指定価格約定':True,'プロセス数':1,'主探索候補へ混入':False},
              '監査':{'乱数方向prefix一致件数':prefix_cases,'全玉会計と保有上限と場内返済':True,
                      '約定は注文より後の観測':True},
              'ランダム方向集計':summaries,'両銘柄黒字割合':both,'固定方向集計':fixed_periods,
              '区間別結果':rows,'経過秒':round(time.monotonic()-started,2),
              '解釈':'１６個の乱数は同じ１３セッション上の対照であり、１６個の独立した市場期間ではない。将来の確実利益や統計的優位性を保証しない。'}
    if additional:
        output['追加診断の位置づけ'] = '主探索の有望候補に採用された管理 G08/G12 に揃えた事後診断。初回と全く同じ全１６乱数と常時買売を使用し、結果に応じた乱数選択はしていない。'
    (OUT/f'control_results{suffix}.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    text = '''# 無予測の方向を使う対照実験

`control_results.json` を参照。既知の１３セッションで、３０分ごとのランダム方向（固定乱数０〜１５）・常時買い・常時売りを、G00・G18・G07・G17で比較した。

乱数方向は価格を参照せず、銘柄・セッションごとに独立。実際の注文は通常の次行執行・損切り・追跡・場内返済であり、方向が変わるたびに自動決済するとは限らない。管理条件ごとの性質に従う。

銘柄ごとに利益・損失・収支・PFと乱数別の中央値・最小・最大・黒字割合を保存した。金額を銘柄間で合算していない。G17だけは固定１枚ではなく、１回２万円以下の予定損失から枚数を決めるため、他管理と円額だけでは比較しない。

全乱数は同じ期間を共有する。この対照は注文管理だけで将来も確実に利益を得られる証明ではなく、主探索の候補順位にも含めない。
'''
    if additional:
        text = '''# 有望候補と同じ注文管理による追加対照

`control_results_additional.json` を参照。主探索終了後、有望候補に使われた G08・G12 を追加した事後診断であり、事前に選んだ独立の評価ではない。

初回の対照と全く同じ固定乱数０〜１５、同じ銘柄・セッション別の独立生成、同じ３０分方向更新、常時買い・常時売りを用いた。結果に応じた乱数の採用・除外は行っていない。

G08は１枚、G12はTOPIX５枚・NK１０枚で開始して半分利確する。円額の単純比較ではなく、同一管理・同一銘柄のPFや収支分布との比較に使う。方向指定は無予測でも、新規の値幅確認や返済の価格条件は維持する。

同じ１３セッションで得た１６乱数の結果であり、独立１６期間の成績や将来の確実利益を示すものではない。
'''
    (OUT/f'control_README{suffix}.md').write_text(text,encoding='utf-8')
    print(json.dumps({'完了':True,'経過秒':output['経過秒'],'乱数集計件数':len(summaries),'固定方向集計件数':len(fixed_periods)},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
