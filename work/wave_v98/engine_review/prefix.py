"""既存の因果入力を実接頭へ切断し、価格時計政策の未来不変を検査する。"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(WORK / 'audit'))
import common

# ----------------------------------------
# 監査補助を読取で利用し、こちらの実行キャッシュは担当可能領域だけに保存する。
CACHE = str(WORK / 'numba_cache')
os.environ['NUMBA_CACHE_DIR'] = CACHE
numba.config.CACHE_DIR = CACHE
import independent


REPRESENTATIVES = ('A0_X3', 'C0_A7_X3', 'C1_A7_X3', 'C2_A7_X3', 'C3_A7_X3',
                   'C1_A3_X3', 'C3_A5_X3')


def shorten(value: dict, cut: int) -> dict:
    """
    機能: 運用末の定義を変えず、原行と原行信号だけを因果境界で切断する。
    引数: value(dict)は共通prepared、cut(int)は保存する原行数。
    返り値: dict。将来公表される格子を保持するが、端点返済は追加しない。
    """
    n = len(value['record']['time_s'])
    result = dict(value)
    result['record'] = {name: array[:cut].copy() if isinstance(array, np.ndarray) and len(array) == n
                        else deepcopy(array) for name, array in value['record'].items()}
    raw = {'event', 'mapped', 'quality', 'reset', 'execution_lp_index'}
    result['signal'] = {name: array[:cut].copy() if name in raw else deepcopy(array)
                        for name, array in value['signal'].items()}
    return result


def compare_past(short: dict, longer: dict, cut: int, label: str) -> None:
    """
    機能: 過去の経済・源・待機・政策状態と、当時公表済みの親だけを厳密比較する。
    引数: short/longer(dict)、cut(int)、label(str)。
    返り値: None。未完親の未来fill/netを当時既知にして比較しない。
    """
    for name in ('curve', 'source_curve', 'target_trace', 'range_state_trace', 'risk_state_trace',
                 'price_source_trace', 'trend_exit_state_trace', 'watch_state_trace', 'entry_policy_state_trace'):
        np.testing.assert_array_equal(short[name], longer[name][:cut], err_msg=label + '/' + name)
    for name in ('orders', 'events', 'loss_reentry_events', 'entry_wait_events', 'entry_policy_events'):
        np.testing.assert_array_equal(short[name], longer[name][longer[name][:, 0] < cut], err_msg=label + '/' + name)
    for name, column in (('trades', 3), ('trend_parent_diagnostics', 2)):
        np.testing.assert_array_equal(short[name], longer[name][longer[name][:, column] < cut], err_msg=label + '/' + name)
    parents = longer['entry_parent_diagnostics'][longer['entry_parent_diagnostics'][:, 28] < cut].copy()
    for parent in parents:
        if np.isfinite(parent[37]) and parent[37] >= cut:
            parent[37:42] = np.nan
        if np.isfinite(parent[42]) and parent[42] >= cut:
            parent[42:44] = np.nan
    np.testing.assert_array_equal(short['entry_parent_diagnostics'], parents, err_msg=label + '/公表45親')


def available(session: str, prepared: dict, symbols: tuple) -> bool:
    """
    機能: 損益を参照せず、両市場の受付窓内に元候補がある場だけを選ぶ。
    引数: session(str)、prepared(dict)、symbols(tuple[str,...])。
    返り値: bool。途中接頭を検査できる候補が両市場にある場合True。
    """
    for symbol in symbols:
        value = prepared[session, symbol]
        record = value['record']
        rows = np.flatnonzero(value['signal']['event'])
        rows = rows[(record['time_s'][rows] >= record['start'] + 300.)
                    & (record['time_s'][rows] < record['limit'] - 600.)]
        if not len(rows):
            return False
    return True


def main() -> None:
    """
    機能: 七代表・前後の少数場で接頭/自己未来/相手未公開源と独立oracleを照合する。
    引数: なし。
    返り値: None。完結した98口座及び全期間損益は一つも計算せず、証跡だけ保存する。
    """
    data = common.module('98実接頭の不変入力', WORK / 'data.py')
    strategy = common.module('98実接頭の時計政策', WORK / 'strategy.py')
    catalog = common.module('98実接頭の34条件', WORK / 'catalog.py')
    os.environ['NUMBA_CACHE_DIR'] = CACHE
    numba.config.CACHE_DIR = CACHE
    configs = {config['id']: config for config in catalog.catalog()}
    material = data.load_inputs()
    prepared = strategy.prepare(material, configs['A0_X3'])
    sessions = material['metadata']['sessions']
    selected = [next(session for session in sessions[:16] if session.endswith('_Day') and available(session, prepared, catalog.SYMBOLS)),
                next(session for session in reversed(sessions[16:]) if session.endswith('_Night') and available(session, prepared, catalog.SYMBOLS))]
    counts = dict(代表=len(REPRESENTATIVES), 商品場=0, 接頭=0, 独立oracle=0, 自己未来=0,
                  相手未公開源=0, 待機を含む接頭=0, gap休止を含む接頭=0, 実約定を含む接頭=0,
                  自己同clock後続を改変した接頭=0)
    samples = []
    for ident in REPRESENTATIVES:
        config = configs[ident]
        for session in selected:
            for symbol in catalog.SYMBOLS:
                key = session, symbol
                value = prepared[key]
                record = value['record']
                rows = np.flatnonzero(value['signal']['event'])
                rows = rows[(record['time_s'][rows] >= record['start'] + 300.)
                            & (record['time_s'][rows] < record['limit'] - 600.)]
                first = int(rows[0])
                stamp = record['time_s'][first]
                n = len(record['time_s'])
                cuts = sorted(set([first + 1] + [int(np.searchsorted(record['time_s'], stamp + seconds, side='right'))
                                                for seconds in (90., 300.)]))
                counts['商品場'] += 1
                for cut in cuts:
                    assert 0 < cut < n - 50
                    piece = shorten(value, cut)
                    short = strategy.play(config, key, {key: piece}, finish=False)
                    complete = dict(short, trend_parent_diagnostics=short['trend_parent_diagnostics'][
                        np.isfinite(short['trend_parent_diagnostics'][:, 2])])
                    independent.compare(piece['record'], piece['signal'], config, value['reference_open'], complete)
                    counts['独立oracle'] += 1
                    longer_value = shorten(value, cut + 50)
                    longer = strategy.play(config, key, {key: longer_value}, finish=False)
                    compare_past(short, longer, cut, ident + '/切断')
                    counts['接頭'] += 1
                    counts['待機を含む接頭'] += int(np.any(short['watch_state_trace'][:, 0] != 0))
                    counts['gap休止を含む接頭'] += int(np.any(short['entry_policy_state_trace'][:, 1] != 0))
                    counts['実約定を含む接頭'] += int(len(short['orders']) > 0)

                    # ----------------------------------------
                    # 行境界後の自己を変え、同時計にある後続行も未来のまま扱う。
                    own = deepcopy(longer_value)
                    for field in ('bid', 'ask', 'price'):
                        own['record'][field][cut:] += 100. * record['tick']
                    own['record']['quote_valid'][cut:] = False
                    own['signal']['event'][cut:] *= -1
                    compare_past(short, strategy.play(config, key, {key: own}, finish=False), cut, ident + '/自己未来')
                    counts['自己未来'] += 1
                    counts['自己同clock後続を改変した接頭'] += int(record['time_s'][cut] == record['time_s'][cut - 1])

                    # ----------------------------------------
                    # 判断境界まで未公表のpeer源/J2/反対を改変し、過去の源を救済しない。
                    peer = deepcopy(longer_value)
                    future = peer['signal']['grid'] > piece['record']['time_s'][-1]
                    for field in ('entry_j2_long', 'entry_j2_short', 'wait_opposite_long', 'wait_opposite_short'):
                        peer['signal'][field][future] = ~peer['signal'][field][future]
                    peer['signal']['entry_peer_bbo'][future] = np.nan
                    compare_past(short, strategy.play(config, key, {key: peer}, finish=False), cut, ident + '/相手未公開')
                    counts['相手未公開源'] += 1
                    samples.append(dict(条件=ident, 場=session, 商品=symbol, 原行境界=cut,
                                        当時価格時計=float(piece['record']['time_s'][-1])))
                print(ident + '/' + session + '/' + symbol + ': 部分接頭と独立oracle及び未来不変が一致', flush=True)
    assert counts['接頭'] == counts['独立oracle'] == counts['自己未来'] == counts['相手未公開源']
    assert counts['待機を含む接頭'] > 0 and counts['gap休止を含む接頭'] > 0
    assert counts['実約定を含む接頭'] > 0 and counts['自己同clock後続を改変した接頭'] > 0
    paths = [Path(__file__), WORK / 'engine.py', WORK / 'strategy.py', WORK / 'catalog.py', WORK / 'data.py',
             WORK / 'audit/common.py', WORK / 'audit/watch.py', WORK / 'audit/independent.py',
             WORK / 'engine_preflight/gap四政策の少数人工と旧18列及びPythonJITの自己検査.json',
             WORK.parent / 'wave_v97/engine_review/5代表の実待機接頭と原本再生成及び自己相手未来源と同clock未来不変.json']
    proof = dict(全合格=True, 代表=list(REPRESENTATIVES), 対象場=selected, 検査件数=counts, 検査例=samples,
        範囲='原本再生成40接頭で確認済みの旧97因果入力を不変読取し、新政策の直接接続を検査。98で原本全特徴を再生成したとは主張しない。',
        同clock範囲='自己境界後の同価格時計行も未受信扱いで改変。peerの同clock先頭参照は旧原本再生成証跡を継承し、共通受信順は保証しない。',
        完結した98口座=0, 正式98損益実行=0, API取得=0, 実注文=0,
        SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    destination = HERE / '七代表の実接頭とgap政策及び自己相手未来の独立不変.json'
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    assert json.loads(destination.read_text(encoding='utf-8')) == proof
    print(json.dumps({key: value for key, value in proof.items() if key not in ('SHA256', '検査例')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
