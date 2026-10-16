"""既存の因果入力を実接頭へ切断し、実増玉と全cohortの未来不変を検査する。"""

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
EXECUTION_PATHS = [Path(__file__), WORK / 'engine.py', WORK / 'strategy.py', WORK / 'catalog.py', WORK / 'data.py',
    *[WORK / 'audit' / (name + '.py') for name in ('common', 'runtime_oracle', 'financial',
        'math_oracle', 'support', 'watch', 'compare_utils')],
    WORK / 'engine_preflight/全20人工の絶対初回数量と実cohort及び旧全量とPythonJIT自己検査.json',
    WORK / 'engine_preflight/追加予約の不利実fillと期限及び未知基準と費用床の少数自己検査.json',
    WORK.parent / 'wave_v97/engine_review/5代表の実待機接頭と原本再生成及び自己相手未来源と同clock未来不変.json']
BEGIN_SHA256 = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in EXECUTION_PATHS}
sys.dont_write_bytecode = True
sys.path.insert(0, str(WORK / 'audit'))
import common

# ----------------------------------------
# 監査補助を読取で利用し、こちらの実行キャッシュは担当可能領域だけに保存する。
CACHE = str(WORK / 'numba_cache')
os.environ['NUMBA_CACHE_DIR'] = CACHE
numba.config.CACHE_DIR = CACHE
import runtime_oracle as independent
import financial
import support as support_oracle


REPRESENTATIVES = ('G0_QFULL_X1', 'G1_Q1_X1', 'G2_Q4_X3')


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
                 'price_source_trace', 'trend_exit_state_trace', 'watch_state_trace', 'entry_policy_state_trace', 'entry_cap_state_trace', 'growth_state_trace'):
        np.testing.assert_array_equal(short[name], longer[name][:cut], err_msg=label + '/' + name)
    for name in ('orders', 'events', 'loss_reentry_events', 'entry_wait_events', 'entry_policy_events', 'growth_events'):
        np.testing.assert_array_equal(short[name], longer[name][longer[name][:, 0] < cut], err_msg=label + '/' + name)
    for name, column in (('trades', 3), ('trend_parent_diagnostics', 2)):
        np.testing.assert_array_equal(short[name], longer[name][longer[name][:, column] < cut], err_msg=label + '/' + name)
    count = len(short['entry_support_state_trace'])
    np.testing.assert_array_equal(short['entry_support_state_trace'], longer['entry_support_state_trace'][:count], err_msg=label+'/公表支持59源')
    parents = longer['entry_parent_diagnostics'][longer['entry_parent_diagnostics'][:, 28] < cut].copy()
    for parent in parents:
        if np.isfinite(parent[37]) and parent[37] >= cut:
            parent[37:42] = np.nan
        if np.isfinite(parent[42]) and parent[42] >= cut:
            parent[42:44] = np.nan
    np.testing.assert_array_equal(short['entry_parent_diagnostics'], parents, err_msg=label + '/公表45親')
    cap_parents = longer['entry_cap_parent_diagnostics'][longer['entry_cap_parent_diagnostics'][:, 10] < cut].copy()
    for parent in cap_parents:
        if np.isfinite(parent[15]) and parent[15] >= cut:
            parent[15:21] = np.nan
    np.testing.assert_array_equal(short['entry_cap_parent_diagnostics'], cap_parents, err_msg=label+'/公表上限21親')
    completed = longer['growth_parent_diagnostics'][longer['growth_parent_diagnostics'][:, 12] < cut]
    np.testing.assert_array_equal(short['growth_parent_diagnostics'], completed, err_msg=label+'/決済済追加親24')
    cohorts = longer['growth_cohorts'][longer['growth_cohorts'][:, 8] < cut].copy()
    for cohort in cohorts:
        if np.isfinite(cohort[14]) and cohort[14] >= cut:
            cohort[14:21] = np.nan
            cohort[24] = np.nan
    np.testing.assert_array_equal(short['growth_cohorts'], cohorts, err_msg=label+'/既存実cohort25')


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
                    & (record['time_s'][rows] < record['limit'] - 3000.)]
        if not len(rows):
            return False
    return True


def poison_lp(material: dict, key: tuple, value: dict, symbol: str,
              boundary: float, mode: str, strategy: object) -> tuple[dict, int]:
    """
    機能: 独立LPの未来値又は同時計後続値を変更し、固定された源の端点だけ再投影する。
    引数: material/value(dict)、key(tuple)、symbol/mode(str)、boundary(float)、strategy(object)。
    返り値: tuple[dict,int]は試験準備と変更raw点数。旧source抽出の再認定ではない。
    元のraw及びBBOには触れず、端点ret・LP支持・59診断だけを明示して再計算する。
    """
    session = key[0]
    original = material['trend_prices']['I3'][session]
    market = deepcopy(original['markets'][symbol])
    raw = {name: array.copy() if isinstance(array, np.ndarray) else deepcopy(array)
           for name, array in material['raw_last_records'][session, symbol].items()}
    if mode == 'future':
        mask = raw['time_s'] > boundary
    else:
        assert mode == 'sameclock'
        known = np.flatnonzero((original['grid'] <= boundary) & market['current']['valid'])
        assert len(known)
        current = int(market['current']['index'][known[-1]])
        stamp = raw['time_s'][current]
        first = int(np.searchsorted(raw['time_s'], stamp, side='left'))
        after = int(np.searchsorted(raw['time_s'], stamp, side='right'))
        if after - first <= 1:
            differences = np.flatnonzero(np.diff(raw['time_s'][:current + 1]) == 0)
            assert len(differences), '既公開源より前に同clock後続が必要です'
            stamp = raw['time_s'][differences[-1]]
            first = int(np.searchsorted(raw['time_s'], stamp, side='left'))
            after = int(np.searchsorted(raw['time_s'], stamp, side='right'))
        mask = np.zeros(len(raw['time_s']), bool)
        mask[first + 1:after] = True
    raw['last'][mask] += 1000.
    raw['seq'][mask] += 1000000
    current = market['current']
    indexes = current['index']
    good = indexes >= 0
    current['value'][good] = raw['last'][indexes[good]]
    current['raw_seq'][good] = raw['seq'][indexes[good]]
    for window in market['windows'].values():
        old, now = window['old'], window['now']
        old_good, now_good = old >= 0, now >= 0
        window['old_value'][old_good] = raw['last'][old[old_good]]
        window['old_seq'][old_good] = raw['seq'][old[old_good]]
        if 'now_value' in window:
            window['now_value'][now_good] = raw['last'][now[now_good]]
        if 'now_seq' in window:
            window['now_seq'][now_good] = raw['seq'][now[now_good]]
        values_now, values_old = raw['last'][np.maximum(now, 0)], raw['last'][np.maximum(old, 0)]
        window['ret_bp'] = (values_now - values_old) / values_old * 10000.
        window['ret_bp'][~window['source_valid']] = np.nan
        if 'ratio_ret_bp' in window:
            window['ratio_ret_bp'] = (values_now / values_old - 1.) * 10000.
            window['ratio_ret_bp'][~window['source_valid']] = np.nan
    price = dict(original, markets=dict(original['markets'], **{symbol: market}))
    raw_records = dict(material['raw_last_records'])
    raw_records[session, symbol] = raw
    trial_material = dict(material, trend_prices={'I3': {session: price}}, raw_last_records=raw_records)
    trial = deepcopy(value)
    trial['trend_lp_allowed'] = strategy.lp_allowed(price, material['grids'][session])
    trial['entry_support_base'] = strategy.support_basis(key, trial_material, trial)
    support_oracle.verify_material(key, trial_material, trial)
    return trial, int(np.count_nonzero(mask))


def poison_bbo(value: dict, cut: int, own: bool) -> dict:
    """
    機能: 接頭の後にある自己執行気配又は未公開相手気配だけを変更する。
    引数: value(dict)、cut(int)、own(bool)。
    返り値: dictは深いコピー。価格格子の再生成ではなく、執行入力の未来混入検査。
    """
    trial = deepcopy(value)
    if own:
        for name in ('bid', 'ask', 'price'):
            trial['record'][name][cut:] += 1000.
    else:
        boundary = value['record']['time_s'][cut - 1]
        mask = trial['signal']['grid'] > boundary
        trial['signal']['entry_peer_bbo'][mask, 3:5] += 1000.
    return trial


def main() -> None:
    """
    機能: 三代表・前後の少数場で接頭/自己未来/相手未公開源と独立oracleを照合する。
    引数: なし。
    返り値: None。完結した101口座及び全期間損益は一つも計算せず、証跡だけ保存する。
    """
    data = common.module('101実接頭の不変入力', WORK / 'data.py')
    strategy = common.module('101実接頭の数量と予算', WORK / 'strategy.py')
    catalog = common.module('101実接頭の20条件', WORK / 'catalog.py')
    os.environ['NUMBA_CACHE_DIR'] = CACHE
    numba.config.CACHE_DIR = CACHE
    configs = {config['id']: config for config in catalog.catalog()}
    material = data.load_inputs()
    prepared = strategy.prepare(material, configs['G0_QFULL_X1'])
    sessions = material['metadata']['sessions']
    selected = [next(session for session in sessions[:16] if session.endswith('_Day') and available(session, prepared, catalog.SYMBOLS)),
                next(session for session in reversed(sessions[16:]) if session.endswith('_Night') and available(session, prepared, catalog.SYMBOLS))]
    counts = dict(代表=len(REPRESENTATIVES), 商品場=0, 接頭=0, 独立oracle=0, 自己LP未来=0,
                  相手LP未来=0, 自己LP同clock後続=0, 相手LP同clock後続=0,
                  自己BBO未来=0, 相手BBO未公開=0,
                  待機を含む接頭=0, gap休止を含む接頭=0, 実約定を含む接頭=0, 実追加を含む接頭=0, 実追加fill数=0)
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
                            & (record['time_s'][rows] < record['limit'] - 3000.)]
                first = int(rows[0])
                stamp = record['time_s'][first]
                n = len(record['time_s'])
                cuts = sorted(set([first + 1] + [int(np.searchsorted(record['time_s'], stamp + seconds, side='right'))
                                                for seconds in (2400.,)]))
                counts['商品場'] += 1
                for cut in cuts:
                    assert 0 < cut < n - 50
                    piece = shorten(value, cut)
                    short = strategy.play(config, key, {key: piece}, finish=False)
                    complete = dict(short, trend_parent_diagnostics=short['trend_parent_diagnostics'][
                        np.isfinite(short['trend_parent_diagnostics'][:, 2])])
                    support_oracle.verify_material(key, material, piece)
                    independent.compare(piece, config, short)
                    financial.verify_account(piece['record'], config, short, complete=False)
                    counts['独立oracle'] += 1
                    longer_value = shorten(value, cut + 50)
                    longer = strategy.play(config, key, {key: longer_value}, finish=False)
                    compare_past(short, longer, cut, ident + '/切断')
                    counts['接頭'] += 1
                    counts['待機を含む接頭'] += int(np.any(short['watch_state_trace'][:, 0] != 0))
                    counts['gap休止を含む接頭'] += int(np.any(short['entry_policy_state_trace'][:, 1] != 0))
                    counts['実約定を含む接頭'] += int(len(short['orders']) > 0)
                    additions = int(np.count_nonzero(short['growth_events'][:, 1] == 3))
                    counts['実追加を含む接頭'] += int(additions > 0)
                    counts['実追加fill数'] += additions

                    # ----------------------------------------
                    # 公表後のLP値・原seqを変更して端点を再投影し、実支持と59源を再計算する。
                    for market_symbol, mode, counter in ((symbol, 'future', '自己LP未来'),
                            ('NK225' if symbol == 'TOPIX' else 'TOPIX', 'future', '相手LP未来'),
                            (symbol, 'sameclock', '自己LP同clock後続'),
                            ('NK225' if symbol == 'TOPIX' else 'TOPIX', 'sameclock', '相手LP同clock後続')):
                        modified, changed = poison_lp(material, key, longer_value, market_symbol,
                                                      piece['record']['time_s'][-1], mode, strategy)
                        assert changed > 0, (key, cut, mode, market_symbol)
                        compare_past(short, strategy.play(config, key, {key: modified}, finish=False), cut,
                                     ident + '/' + counter)
                        counts[counter] += 1
                    for own, counter in ((True, '自己BBO未来'), (False, '相手BBO未公開')):
                        modified = poison_bbo(longer_value, cut, own)
                        compare_past(short, strategy.play(config, key, {key: modified}, finish=False), cut,
                                     ident+'/'+counter)
                        counts[counter] += 1
                    samples.append(dict(条件=ident, 場=session, 商品=symbol, 原行境界=cut,
                                        当時価格時計=float(piece['record']['time_s'][-1])))
                print(ident + '/' + session + '/' + symbol + ': 部分接頭と独立oracle及び未来不変が一致', flush=True)
    assert counts['接頭'] == counts['独立oracle'] == counts['自己LP未来'] == counts['相手LP未来'] == counts['自己LP同clock後続'] == counts['相手LP同clock後続']
    assert counts['接頭'] == counts['自己BBO未来'] == counts['相手BBO未公開']
    assert counts['待機を含む接頭'] > 0 and counts['実追加を含む接頭'] > 0

    end_sha = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in EXECUTION_PATHS}
    assert end_sha == BEGIN_SHA256, '実行中に依存ソースが変更されたため合格として固定しません'
    proof = dict(全合格=True, 代表=list(REPRESENTATIVES), 対象場=selected, 検査件数=counts, 検査例=samples,
        範囲='金融20と支持59及びcap20/21、追加state70/events74/cohort25/parent24の過去接続を比較。検証済みI3 source indexを保持し、改変rawLP端点の値/原seqを再投影してretとL1支持及び59源を再計算する新接続検査。全特徴を原本から再抽出したとは主張しない。',
        同clock範囲='公表LP源の同時計先頭を保存し、その後続raw値を変更。固定I3 indexが同時計末尾へ飛ばないことを検査。真の両市場受信順は未証明。全格子入力SHAは未来を含むため過去不変対象から除く。',
        完結した101口座=0, 正式101損益実行=0, API取得=0, 実注文=0,
        開始と終端の全依存SHA一致=True, 開始SHA256=BEGIN_SHA256, SHA256=end_sha,
        初回記録='helper停止前の初回証跡を別名で保持。今回だけを現在依存での最終接頭合格とする。')
    destination = HERE / '三代表の実増玉接頭とcohort及び自己相手LPとBBO未来不変.json'
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    assert json.loads(destination.read_text(encoding='utf-8')) == proof
    print(json.dumps({key: value for key, value in proof.items() if key not in ('SHA256', '検査例')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
