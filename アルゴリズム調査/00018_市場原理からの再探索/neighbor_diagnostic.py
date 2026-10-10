"""採用候補の注文幅を単独で±２０％変える、選択後の感度診断。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import pickle
import time
import numpy as np

import engine
import managers
from research import summarize, aggregate

OUT = Path(__file__).resolve().parent
FIELDS = ('entry_atr','stop_atr','main_trail')
FACTORS = (.8,1.2)


def extrema(values: list[float]) -> dict:
    """機能: 比較範囲の最小値と最大値を返す。

    引数: values (list[float])。返り値: 範囲 (dict)。
    """
    return {'最小':min(values),'最大':max(values)}


def compare_ledgers(first: str, second: str) -> dict:
    """機能: 二つの設定の全区間返済台帳と取引組を完全一致で比較する。

    引数: first/second (str) は候補 ID。返り値: 配列ごとの一致結果 (dict)。
    """
    with np.load(OUT/'trades'/f'{first}.npz') as left, np.load(OUT/'trades'/f'{second}.npz') as right:
        same_keys = set(left.files)==set(right.files)
        checks = {key:bool(np.array_equal(left[key],right[key])) for key in left.files if key in right.files}
    return {'比較候補':[first,second],'台帳キー一致':same_keys,'配列比較数':len(checks),
            '全配列完全一致':same_keys and all(checks.values()),'配列別':checks,
            '解釈':'今回の期間では追加防御の有無で約定結果が変わらない。F32の黒字をG08の損失制限による効果とは説明できない。'}


def main() -> None:
    """機能: 上位５条件の近傍を同じ原本方向で再生し、再選択せず報告する。

    引数: なし。返り値: なし (None)。neighbor_results.json を保存する。
    """
    started = time.monotonic()
    selection = json.loads((OUT/'選択結果.json').read_text(encoding='utf-8'))
    identifiers = selection['finalists']
    inputs = pickle.loads((OUT/'inputs.pkl').read_bytes())
    directions = pickle.loads((OUT/'directions.pkl').read_bytes())
    manager_specs = {row['id']:row for row in managers.manager_catalog()}
    baseline_ranking = json.loads((OUT/'全条件の期間集計.json').read_text(encoding='utf-8'))
    baseline_lookup = {row['id']:row for row in baseline_ranking}
    candidates, all_rows = [], []
    total_neighbors = 0
    for identifier in identifiers:
        signal_id, manager_id = identifier.split('_')
        manager = manager_specs[manager_id]
        fields = [field for field in FIELDS if not(field=='entry_atr' and manager['changes'].get('entry_mode',0)==2)]
        changes = [('基準',None,1.)]+[(f'{field}_{factor}',field,factor) for field in fields for factor in FACTORS]
        variants = []
        for label, field, factor in changes:
            rows, applied = [], {}
            for key, ready in inputs.items():
                session, symbol = key
                cfg = copy.deepcopy(managers.make_config(manager,symbol,ready))
                if field is not None:
                    cfg[field] *= factor
                applied[symbol] = {name:cfg[name] for name in FIELDS}
                result = engine.run(ready,directions[signal_id][key],cfg,detail=False)
                row = summarize(result,cfg,symbol,session,identifier+'_'+label)
                row.update(base_id=identifier,変更項目=field,倍率=factor)
                rows.append(row)
                all_rows.append(row)
            by_symbol = {symbol:aggregate([row for row in rows if row['symbol']==symbol]) for symbol in ('TOPIX','NK225')}
            if field is None:
                for symbol in ('TOPIX','NK225'):
                    for metric in ('net_yen','gross_profit_yen','gross_loss_yen','drawdown_yen'):
                        assert abs(by_symbol[symbol][metric]-baseline_lookup[identifier]['symbols'][symbol][metric]) < .01
            variants.append({'変更':label,'項目':field,'倍率':factor,'適用幅':applied,'symbols':by_symbol,
                             '両銘柄黒字':all(row['net_yen']>0 for row in by_symbol.values())})
        neighbors = [variant for variant in variants if variant['項目'] is not None]
        summary = {}
        for symbol in ('TOPIX','NK225'):
            summary[symbol] = {'黒字近傍数':sum(v['symbols'][symbol]['net_yen']>0 for v in neighbors),
                               '収支円範囲':extrema([v['symbols'][symbol]['net_yen'] for v in neighbors]),
                               '金額PF範囲':extrema([v['symbols'][symbol]['money_ratio'] for v in neighbors if v['symbols'][symbol]['money_ratio'] is not None]),
                               '時価最大下落円範囲':extrema([v['symbols'][symbol]['drawdown_yen'] for v in neighbors])}
        candidates.append({'id':identifier,'近傍数':len(neighbors),
                           '両銘柄黒字近傍数':sum(v['両銘柄黒字'] for v in neighbors),
                           '近傍の範囲':summary,'variants':variants})
        total_neighbors += len(neighbors)
        print(f"{identifier}: 両銘柄黒字 {candidates[-1]['両銘柄黒字近傍数']}/{len(neighbors)} 近傍",flush=True)
    output = {'位置づけ':'全既知期間を使って選んだ上位５条件に対する事後の感度診断。追加候補の採用・順位の変更は行わない。',
              '条件':{'対象':identifiers,'変数':list(FIELDS),'各単独倍率':list(FACTORS),
                      '成行新規の入口幅を除外':True,'未来入力の再取得':False,'追加最適化による採用変更':False,
                      '近傍総数':total_neighbors,'銘柄区間数':len(inputs),'プロセス数':1},
              '監査':{'元の基準５条件を再実行し既存集計と一致':True,'全注文は次観測以降':True,'上限内・会計一致・場内返済':True},
              '追加防御の同等台帳比較':compare_ledgers('F32_G08','F32_G00'),
              'candidates':candidates,'区間別結果':all_rows,'経過秒':round(time.monotonic()-started,2)}
    (OUT/'neighbor_results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    note = '''# 採用候補の近傍診断

`neighbor_results.json` を参照。主探索後に選んだ５候補について、新規確認幅・損切り幅・追跡幅をそれぞれ単独で０.８倍／１.２倍へ変えた。次観測成行の候補は新規確認幅が無効なため、その２条件を除外した。

基準５条件と近傍２８条件を同じ１３セッションで比較した事後の感度分析であり、独立期間の検証ではない。近傍を新しい主探索候補に追加せず、主候補の順位や設定も変えていない。

各銘柄の利益・損失・収支・PF・時価最大下落と、両銘柄が黒字となる近傍数を保存した。銘柄間の円額は合算していない。
'''
    (OUT/'neighbor_README.md').write_text(note,encoding='utf-8')


if __name__=='__main__':
    main()
