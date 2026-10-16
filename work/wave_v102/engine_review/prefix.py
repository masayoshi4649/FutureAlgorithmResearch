"""初回幅余裕と据置の代表を部分接頭で再生し、19門番と実増玉の未来不変を検査する。"""

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
EXECUTION_PATHS = [Path(__file__), WORK / 'engine.py', WORK / 'strategy.py', WORK / 'catalog.py', WORK / 'data.py',
    *[WORK / 'audit' / (name + '.py') for name in ('common', 'runtime_oracle', 'financial',
        'math_oracle', 'support', 'watch', 'compare_utils')],
    WORK / 'engine_preflight/全20人工の初期幅余裕と据置及び旧8対照とPythonJIT自己検査.json',
    WORK / 'engine_preflight/余裕と据置の拒否及び不利実fillと通常追尾と未知期限場末の少数自己検査.json',
    WORK / '結果前の設計案.json', WORK / '実装前の仕様明確化.json',
    WORK / '正式新損益前の主変更理由.json', WORK.parent / 'wave_v101/事前固定.json',
    WORK.parent / 'wave_v97/engine_review/5代表の実待機接頭と原本再生成及び自己相手未来源と同clock未来不変.json']
BEGIN_SHA256 = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in EXECUTION_PATHS}
sys.dont_write_bytecode = True
sys.path.insert(0, str(WORK / 'audit'))
import common

# ----------------------------------------
# 監査補助を読取で利用し、こちらの実行キャッシュは担当可能領域だけに保存する。
CACHE = str(HERE / 'jit')
os.environ['NUMBA_CACHE_DIR'] = CACHE
numba.config.CACHE_DIR = CACHE
import runtime_oracle as independent
import financial
import support as support_oracle


REPRESENTATIVES = ('B1_T0_Q1_X1', 'B1_T1_Q1_X1', 'B2_T1_Q1_X3', 'G0_QFULL_X1')
SESSIONS = ('2026-09-22_Day', '2026-10-08_Night')
PRIMARY = 'B1_T0_Q1_X1'
DESTINATION = HERE / '四代表の初回幅と停止据置gate19及び実増玉接頭と未来源不変.json'


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
                 'price_source_trace', 'trend_exit_state_trace', 'watch_state_trace', 'entry_policy_state_trace', 'entry_cap_state_trace', 'growth_state_trace', 'growth_gate_state_trace'):
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
    for name in ('growth_state_columns', 'growth_event_columns', 'growth_event_codes',
                 'growth_cohort_columns', 'growth_parent_columns', 'growth_gate_state_columns'):
        assert short[name] == longer[name], label + '/' + name


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
    機能: 固定四代表・固定二場で接頭、未來源と別19列の独立oracleを照合する。
    引数: なし。
    返り値: None。明示許可のflagが必要。102完結口座と全期間損益を計算しない。
    """
    parser = argparse.ArgumentParser(description='102の部分接頭だけを因果的に検査する。')
    parser.add_argument('--root-prefix-ready', action='store_true', help='rootが局所反証と保存往復の完成を確認済み。')
    args = parser.parse_args()
    if not args.root_prefix_ready:
        raise RuntimeError('原板の実接頭はrootの明示実行許可後だけ開始できます。')
    assert not DESTINATION.exists(), '一度作った接頭証跡を上書きしません。'
    for name in ('事前固定.json', '前16評価.json', '後15評価.json', '前半選定.json', '全31比較.json'):
        assert not (WORK / name).exists(), '正式損益後の事前接頭合格にすり替えません。'
    for stage in ('front', 'back'):
        assert not list((WORK / stage / 'results').glob('*.json')), '正式新損益がまだ無いことが必要です。'
        assert not list((WORK / stage / 'ledgers').glob('*.pkl')), '正式新損益台帳がまだ無いことが必要です。'
    for name in ('全20人工の初期幅余裕と据置及び旧8対照とPythonJIT自己検査.json',
                 '余裕と据置の拒否及び不利実fillと通常追尾と未知期限場末の少数自己検査.json'):
        assert json.loads((WORK / 'engine_preflight' / name).read_text(encoding='utf-8'))['全合格'] is True
    data = common.module('102実接頭の不変入力', WORK / 'data.py')
    strategy = common.module('102実接頭の数量と停止余裕', WORK / 'strategy.py')
    catalog = common.module('102実接頭の20条件', WORK / 'catalog.py')
    os.environ['NUMBA_CACHE_DIR'] = CACHE
    numba.config.CACHE_DIR = CACHE
    configs = {config['id']: config for config in catalog.catalog()}
    material = data.load_inputs()
    prepared = strategy.prepare(material, configs['G0_QFULL_X1'])
    selected = list(SESSIONS)
    assert set(selected).issubset(material['metadata']['sessions'])
    assert all(available(session, prepared, catalog.SYMBOLS) for session in selected)
    counts = dict(代表=len(REPRESENTATIVES), 商品場=0, 接頭=0, 独立oracle=0, 自己LP未来=0,
                  相手LP未来=0, 自己LP同clock後続=0, 相手LP同clock後続=0,
                  自己BBO未来=0, 相手BBO未公開=0,
                  待機を含む接頭=0, gap休止を含む接頭=0, 実約定を含む接頭=0, 実追加を含む接頭=0, 実追加fill数=0,
                  主の実追加を含む接頭=0, 独立gate列=19, 独立gate行=0, 追加切断を含む商品場=0)
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
                                                for seconds in (900., 2400.)]))
                labels = {first + 1: '初候補直後'}
                for seconds, label in ((900., '15分後'), (2400., '40分後')):
                    labels[int(np.searchsorted(record['time_s'], stamp + seconds, side='right'))] = label
                if ident == PRIMARY:
                    # ----------------------------------------
                    # 最初の実追加は状態カバーだけに用い、利益又は最大順行で切断を選ばない。
                    horizon = min(stamp + 10800., record['limit'] - 600.)
                    probe_cut = int(np.searchsorted(record['time_s'], horizon, side='right'))
                    assert cuts[-1] <= probe_cut < n - 50 and horizon <= record['limit'] - 600.
                    probe = strategy.play(config, key, {key: shorten(value, probe_cut)}, finish=False)
                    filled = probe['growth_events'][probe['growth_events'][:, 1] == 3]
                    if len(filled):
                        addition_cut = int(filled[0, 0]) + 1
                        if not any(cut >= addition_cut for cut in cuts):
                            cuts = sorted(set(cuts + [addition_cut]))
                            labels[addition_cut] = '最初の実追加直後'
                            counts['追加切断を含む商品場'] += 1
                counts['商品場'] += 1
                for cut in cuts:
                    assert 0 < cut < n - 50
                    piece = shorten(value, cut)
                    short = strategy.play(config, key, {key: piece}, finish=False)
                    complete = dict(short, trend_parent_diagnostics=short['trend_parent_diagnostics'][
                        np.isfinite(short['trend_parent_diagnostics'][:, 2])])
                    support_oracle.verify_material(key, material, piece)
                    oracle = independent.compare(piece, config, short)
                    financial.verify_account(piece['record'], config, short, complete=False)
                    counts['独立oracle'] += 1
                    assert oracle['独立追加門番列'] == 19
                    counts['独立gate行'] += oracle['独立追加門番行']
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
                    counts['主の実追加を含む接頭'] += int(ident == PRIMARY and additions > 0)

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
                    samples.append(dict(条件=ident, 場=session, 商品=symbol, 切断理由=labels[cut], 原行境界=cut,
                                        当時価格時計=float(piece['record']['time_s'][-1]), 実追加fill数=additions))
                print(ident + '/' + session + '/' + symbol + ': 部分接頭と独立oracle及び未来不変が一致', flush=True)
    assert counts['接頭'] == counts['独立oracle'] == counts['自己LP未来'] == counts['相手LP未来'] == counts['自己LP同clock後続'] == counts['相手LP同clock後続']
    assert counts['接頭'] == counts['自己BBO未来'] == counts['相手BBO未公開']
    assert counts['待機を含む接頭'] > 0 and counts['主の実追加を含む接頭'] > 0

    end_sha = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in EXECUTION_PATHS}
    assert end_sha == BEGIN_SHA256, '実行中に依存ソースが変更されたため合格として固定しません'
    proof = dict(全合格=True, 代表=list(REPRESENTATIVES), 対象場=selected, 検査件数=counts, 検査例=samples,
        範囲='別19gate全行全列は独立Fraction状態再生と比較。旧経済と支持59及びcap20/21、追加state70/events74/cohort25/parent24の過去接続も比較する。検証済みI3 source indexを保持し、改変rawLP端点の値/原seqを再投影してretとL1支持及び59源を再計算する新接続検査。全特徴を原本から再抽出したとは主張しない。',
        接頭の選び方='結果前固定四代表・固定二場・両商品。初候補直後と15分後と40分後。主の3時間以内かつ場末10分以前の部分probeに実追加があれば、基本接頭が届かない場合だけ最初の実追加直後を追加する。損益又は最大順行による場・代表・切断の選択をしない。',
        同clock範囲='公表LP源の同時計先頭を保存し、その後続raw値を変更。固定I3 indexが同時計末尾へ飛ばないことを検査。真の両市場受信順は未証明。全格子入力SHAは未来を含むため過去不変対象から除く。',
        完結した102口座=0, 正式102損益実行=0, API取得=0, 実注文=0,
        開始と終端の全依存SHA一致=True, 開始SHA256=BEGIN_SHA256, SHA256=end_sha,
        初回記録='新102の本検査はroot明示許可後に一度だけ行う。失敗時はFalse証跡を別名で保存し、旧結果又は既存合格を上書きしない。')
    DESTINATION.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    assert json.loads(DESTINATION.read_text(encoding='utf-8')) == proof
    print(json.dumps({key: value for key, value in proof.items() if key not in ('SHA256', '検査例')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # ----------------------------------------
        # 許可後の実検査失敗だけを、その時点のsourceと共に別名で残す。
        if '--root-prefix-ready' in sys.argv:
            number = 1
            while (HERE / f'実接頭不合格_{number:05d}.json').exists():
                number += 1
            snapshot = HERE / f'実接頭不合格時点のprefix_{number:05d}.py'
            snapshot.write_bytes(Path(__file__).read_bytes())
            present = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in EXECUTION_PATHS if path.exists()}
            failure = dict(全合格=False, 理由=str(error), 例外型=type(error).__name__,
                元の不合格source=str(snapshot.relative_to(ROOT)),
                元の不合格sourceSHA256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                完結した102口座=0, 正式102損益実行=0, API取得=0, 実注文=0,
                開始SHA256=BEGIN_SHA256, 終端SHA256=present,
                trace=traceback.format_exc())
            target = HERE / f'実接頭不合格_{number:05d}.json'
            target.write_text(json.dumps(failure, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        raise
