"""E01の15秒価格感度について、発注判断の起点と条件付き注文の例外を監査する。"""

from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'work/wave_v38'))
import engine_shadow_plan as engine


def read(path: Path) -> object:
    """機能: JSONまたは圧縮JSONを読む。

    引数: path(Path)。返り値: 保存値(object)。
    """
    value = path.read_bytes()
    return json.loads(gzip.decompress(value) if path.suffix == '.gz' else value)


def worst(ready: dict, row: int, side: int) -> tuple[float, int]:
    """機能: 原本行順を保持し、判断行から15秒以内の不利な価格を選ぶ。

    引数: ready(dict)、row/side(int)。返り値: 価格と原本行(tuple[float,int])。
    """
    right = int(np.searchsorted(ready['time_s'], ready['time_s'][row]+15, side='right'))
    prices = ready['last'][row:right]
    selected = row + int(np.argmax(prices) if side > 0 else np.argmin(prices))
    return float(ready['last'][selected]), selected


def reconstruct_shadow(ready: dict, ledger: dict) -> tuple[np.ndarray, dict]:
    """機能: 成功した準備区間だけ元影を再生し、注文一致を確認して有効計画を返す。

    引数: ready/ledger(dict)。返り値: 行前計画と一致証跡(tuple[ndarray,dict])。
    注意: 保存注文を用いる事後監査専用。売買判断を作成する手法ではない。
    """
    n = len(ready['last'])
    state = np.zeros(n, np.int8)
    allow = np.zeros(n, bool)
    opens = {int(row[2]): row for row in ledger['orders'] if row[7] == 1}
    for campaign, fill, _, source in ledger['entry_preparations']:
        start, end = int(source), int(fill)
        state[start:end+1] = int(opens[int(campaign)][3])
        allow[start] = True
    config = ledger['config']
    values = engine.simulate(ready['time_s'], ready['last'], ready['atr'], ready['atr'],
        state, state, ready['tick'], ready['start'], ready['limit'], ready['us_open'],
        np.array([config[name] for name in engine.PARAMS], float), True,
        int(config['audit_cap']), 0, False, allow, 0., float(ready.get('session_close', ready['limit']+600)))
    names = ('trades','cycles','curve','orders','stats','atr_curve','prepare_events',
             'entry_preparations','plans','execution_plans')
    result = dict(zip(names, values))
    proof = {}
    for name in ('orders', 'trades', 'cycles', 'curve', 'stats'):
        actual = hashlib.sha256(result[name].tobytes()).hexdigest()
        expected = ledger['shadow_fingerprints'][name]['SHA256']
        assert actual == expected, (ledger['session'], ledger['symbol'], name, actual, expected)
        proof[name] = True
    return result['execution_plans'], proof


def run() -> None:
    """機能: 全469注文の起点感度と価格条件例外を独立確認する。

    引数: なし。返り値: なし(None)。監査JSONを本作業領域へ保存する。
    """
    inputs = pickle.loads((ROOT/'work/wave_v47/inputs.pkl').read_bytes())
    for folder in ('update_20260930', 'update_20261001'):
        inputs.update(pickle.loads((ROOT/'work/wave_v48'/folder/'new_inputs.pkl').read_bytes()))
    folders = [ROOT/'work/wave_v49/early'] + [ROOT/'work/wave_v50'/name
        for name in read(ROOT/'work/wave_v50/追加結果一覧.json')]
    for folder in folders[1:]:
        inputs.update(pickle.loads((folder/'new_inputs.pkl').read_bytes()))
    ledgers = sum([read(folder/'ledgers/E01.json.gz') for folder in folders], [])
    output, proofs = [], []
    totals = {symbol: dict(理想=0., 全成立行=0., 理由別起点=0., 厳密起点=0.) for symbol in ('TOPIX','NK225')}
    for ledger in ledgers:
        key = ledger['session'], ledger['symbol']
        ready, orders = inputs[key], ledger['orders']
        candidates = []
        for number, order in enumerate(orders):
            fill, source, side, reason = int(order[0]), int(order[1]), int(order[3]), int(order[6])
            if not order[7] and reason in (1, 2, 7):
                left, right = worst(ready, fill, side)[0], worst(ready, source, side)[0]
                if left != right:
                    candidates.append(number)
        # ----------------------------------------
        # 起点の分類によって価格が変わる口座だけ、保存指紋と一致する元影を復元する。
        plans = None
        if candidates:
            plans, proof = reconstruct_shadow(ready, ledger)
            proofs.append(dict(セッション=key[0], 銘柄=key[1], 元影指紋一致=proof))
        counts = Counter()
        for number, order in enumerate(orders):
            fill, source, side, reason = int(order[0]), int(order[1]), int(order[3]), int(order[6])
            main = source if reason in (8, 9, 30, 32) else fill
            strict = main
            category = '裁量返済' if main == source else '価格条件到達'
            if plans is not None and reason in (1, 2, 7):
                plan = plans[fill]
                if int(plan[18]):
                    strict = int(plan[19]); category = '事前に成立済みの返済'
                elif bool(plan[{1:15, 2:16, 7:17}[reason]]):
                    strict = int(plan[33]); category = '設置時に価格条件通過済み'
            pf, rf = worst(ready, fill, side)
            pm, rm = worst(ready, main, side)
            ps, rs = worst(ready, strict, side)
            counts[category] += 1
            mult, qty = ledger['config']['point_value'], order[4]
            for name, price in (('理想',order[5]),('全成立行',pf),('理由別起点',pm),('厳密起点',ps)):
                totals[key[1]][name] -= side * qty * price * mult
            output.append(dict(セッション=key[0], 銘柄=key[1], 注文番号=number, 理由=reason,
                判定=category, 成立行=fill, 元源行=source, 理由別判断行=main, 厳密判断行=strict,
                条件例外監査対象=number in candidates, 判定行変更=main!=strict,
                理想価格=order[5], 成立行窓価格=pf, 理由別窓価格=pm, 厳密窓価格=ps,
                成立行窓最悪行=rf, 理由別窓最悪行=rm, 厳密窓最悪行=rs,
                理由別差額=(pf-pm)*side*qty*mult, 厳密差額=(pf-ps)*side*qty*mult))
        print(key, '元影監査' if candidates else '全対象で起点価格不変', dict(counts), flush=True)
    report = dict(全合格=True, API取得数=0, 元注文変更=False, 対象注文数=len(output),
        起点価格差のある条件付き注文数=sum(row['条件例外監査対象'] for row in output),
        元影復元口座数=len(proofs), 元影監査=proofs,
        監査実施口座の条件例外件数=sum(row['判定行変更'] for row in output),
        厳密起点による価格変化数=sum(row['厳密差額'] != 0 for row in output), 合計=totals, 注文=output,
        注意='元影再生は保存台帳からの事後監査専用。起点で価格が同一の口座は、保存理由による起点分類で会計不変と確認。')
    (HERE/'監査結果.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('注文','元影監査')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    run()
