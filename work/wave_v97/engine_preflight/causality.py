"""人工接頭部だけで、将来の板・許可・候補が過去の待機や注文を変えないことを確認する。"""

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from support import HERE, ROOT, WORK, fixture, load


DENSE = ('curve', 'source_curve', 'target_trace', 'range_state_trace', 'risk_state_trace',
         'price_source_trace', 'trend_exit_state_trace', 'watch_state_trace')
ROW_EVENTS = ('orders', 'events', 'loss_reentry_events', 'entry_wait_events')


def truncate(record: dict, signal: dict, count: int) -> tuple[dict, dict]:
    """
    機能: 原行接頭部と当時までの格子だけを残し、既知の場末時刻は保持する。
    引数: record/signal(dict)、count(int)。
    返り値: tuple[dict,dict]は未来価格を持たない人工素材。
    """
    output_record, output_signal = copy.deepcopy(record), copy.deepcopy(signal)
    n, g = len(record['time_s']), len(signal['grid'])
    grid_count = int(np.searchsorted(signal['grid'], record['time_s'][count-1], side='right'))
    for key, value in record.items():
        if isinstance(value, np.ndarray) and value.shape[0] == n:
            output_record[key] = value[:count].copy()
    for key, value in signal.items():
        if isinstance(value, np.ndarray):
            if value.shape[0] == n:
                output_signal[key] = value[:count].copy()
            elif value.shape[0] == g:
                output_signal[key] = value[:grid_count].copy()
    return output_record, output_signal


def poison(record: dict, signal: dict, count: int) -> tuple[dict, dict]:
    """
    機能: 接頭部より後の原板と公開格子だけを極端な別経路へ変更する。
    引数: record/signal(dict)、count(int)。
    返り値: tuple[dict,dict]は未来価格と未来候補が異なる人工素材。
    """
    r, s = copy.deepcopy(record), copy.deepcopy(signal)
    for key in ('price', 'bid', 'ask'):
        r[key][count:] += 100000.
    r['quote_valid'][count:] = False
    s['quality'][count:] = False
    s['reset'][count:] = True
    s['event'][count:] *= -1
    future = s['grid'] > record['time_s'][count-1]
    s['entry_peer_bbo'][future, 2] += 100000.
    s['entry_peer_bbo'][future, 3:5] += 100000.
    s['entry_peer_bbo'][future, 5] = 0.
    for key in ('entry_j2_long', 'entry_j2_short'):
        s[key][future] = False
    for key in ('wait_opposite_long', 'wait_opposite_short'):
        s[key][future] = True
    return r, s


def main() -> None:
    """
    機能: 36条件・両商品・買売の二接頭部を実切断と未来改変で照合する。
    引数: なし。
    返り値: Noneは因果検査証跡。人工を収益成功の根拠にはしない。
    """
    strategy = load('待機入口の人工因果検査97', WORK / 'strategy.py')
    catalog = load('待機36の人工因果条件97', WORK / 'catalog.py')
    comparisons = 0
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            record, signal, opening = fixture(symbol, side, 'complete')
            key = ('2000-01-03_人工', symbol)
            for config in catalog.catalog():
                for count in (351, 376):
                    cut_record, cut_signal = truncate(record, signal, count)
                    prepared = {key: dict(record=cut_record, signal=cut_signal, reference_open=opening)}
                    prefix = strategy.play(config, key, prepared, finish=False)
                    poisoned_record, poisoned_signal = poison(record, signal, count)
                    changed = strategy.play(config, key, {key: dict(record=poisoned_record,
                        signal=poisoned_signal, reference_open=opening)}, finish=False)
                    for name in DENSE:
                        np.testing.assert_array_equal(prefix[name], changed[name][:count])
                    for name in ROW_EVENTS:
                        rows = changed[name][changed[name][:, 0] < count]
                        np.testing.assert_array_equal(prefix[name], rows)
                    trades = changed['trades'][changed['trades'][:, 3] < count]
                    np.testing.assert_array_equal(prefix['trades'], trades)
                    comparisons += 1
    paths = (Path(__file__), HERE / 'support.py', WORK / 'engine.py', WORK / 'strategy.py', WORK / 'catalog.py')
    proof = dict(全合格=True, 人工接頭部切断及び未来改変=comparisons,
        各接頭部密配列照合=len(DENSE), 各接頭部注文及び疎イベント=len(ROW_EVENTS),
        完了決済親照合=True, 接頭部時点=[351, 376], 終端の仮想返済追加=False,
        将来で更新される未完親の完成診断を過去列として照合しない=True,
        正式97損益実行=0, API取得=0, 実注文=0,
        SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    path = HERE / '36入口出口の人工接頭部と未来板及び未来許可改変の因果検査.json'
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key != 'SHA256'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
