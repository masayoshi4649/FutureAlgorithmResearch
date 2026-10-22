"""旧注文器と厳格会計を保持し、価格順行後の減量許可だけを固定比較する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent/'wave_v41'))
import replay_state_fix as reference
audit, old, engine = reference.audit, reference.runner, reference.corrected
sys.path.insert(0, str(HERE.parent/'wave_v38'))
import adaptive_causality_audit as causal


def module(name: str, path: Path) -> object:
    """機能: 同名の旧モジュールを置換せず今回の実装を読む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    assert Path(value.__file__).resolve() == path.resolve()
    return value


design = module('profit_gate_design', HERE/'design.py')
sys.path.insert(0, str(HERE))
import profit_gate as gate
assert Path(gate.__file__).resolve() == HERE/'profit_gate.py'
INPUTS, FIXED = {}, {}
FIELDS, STORED = old.FIELDS, old.STORED
PROOF_FLAGS = reference.PROOF_FLAGS
REPRESENTATIVE = ('2026-09-24_Night', '2026-09-29_Day')


def digest(path: Path) -> str:
    """機能: 巨大入力も逐次読取で指紋化する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return reference.digest(path)


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return reference.read(path)


def save(path: Path, value: object) -> None:
    """機能: 今回の領域内へ有限JSONを原子的に保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)
    temporary.replace(path)


def verify(files: dict) -> None:
    """機能: 全参照資料を固定指紋と照合する。

    引数: files(dict[str,str])。返り値: なし(None)。不一致は停止する。
    """
    def check(item: tuple) -> None:
        """機能: 一つの相対パスとSHAを照合する。

        引数: item(tuple[str,str])。返り値: なし(None)。
        """
        name, expected = item
        path = (ROOT/name).resolve()
        assert path.is_relative_to(ROOT) and digest(path) == expected, name
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(check, files.items()))


def initialize() -> None:
    """機能: 旧凍結入力だけを読み、外部通信を拒否して新しい影生成へ備える。

    引数: なし。返り値: なし(None)。保存済み完成ゲートは読み込まない。
    """
    global INPUTS, FIXED
    audit.initialize()
    INPUTS = old.INPUTS
    FIXED = read(HERE/'探索条件の固定.json')
    assert Path(engine.__file__).resolve() == HERE.parent/'wave_v41/engine_partial_restore_corrected.py'
    assert Path(audit.__file__).resolve() == HERE.parent/'wave_v38/adaptive_accounting_audit.py'
    assert Path(audit.slots.__file__).resolve() == HERE.parent/'wave_v38/adaptive_slot_audit.py'
    assert Path(engine.shadow_engine.__file__).resolve() == HERE.parent/'wave_v38/engine_shadow_plan.py'


def columns_for(spec: dict, key: tuple) -> tuple:
    """機能: 入口・悪化・回復・公開元の旧10列を仕様どおりそのまま取得する。

    引数: spec(dict)、key(tuple[str,str])。返り値: 10入力列(tuple)。
    """
    return old.columns(spec, key)


def quality_for(spec: dict, key: tuple) -> np.ndarray:
    """機能: 回復列とは独立に、悪化窓の公開品質を取得する。

    引数: spec(dict)、key(tuple[str,str])。返り値: 有効公開列(bool ndarray[n])。
    数量調整なしのA0では悪化公開を使用しないので全Falseを返す。
    """
    if spec['policy']['kind'] != 'dynamic':
        return np.zeros(len(INPUTS[key]['last']), np.bool_)
    return old.inputs.publication_valid(spec['policy']['bad_id'], key, spec['bad_scale'])


def play(spec: dict, ready: dict, columns: tuple, config: dict,
         *, gate_valid: np.ndarray | None = None) -> tuple:
    """機能: 同じ入力から影を先に生成し、当行までの許可列を実口座へ渡す。

    引数: spec/ready/config(dict)、columns(tuple)、gate_valid(bool ndarray又はNone)。
    返り値: 実口座結果・実使用10列・ゲート証拠(tuple[dict,tuple,dict])。
    影を未来の完成結果から切り出さず、変更又は切断のたびに生成し直す。
    """
    shadow = engine.make_shadow(ready, columns[0], config, spec['observed_fill'], spec['min_delay_seconds'])
    bad, source, evidence = gate.gate_bad(ready, shadow, columns[1], columns[2],
        spec['gate_threshold_atr'], mode=spec['gate_mode'], valid=gate_valid)
    effective = (columns[0], bad, source, *columns[3:])
    result = reference.play(engine, spec, ready, effective, config, shadow)
    assert shadow['input_sha256'] == engine.input_digest(ready, columns[0], config,
                                                       spec['observed_fill'], spec['min_delay_seconds'])
    assert result['shadow'] is shadow
    return result, effective, evidence


def gate_prefix(actual: tuple, changed: tuple, count: int) -> None:
    """機能: 全注文状態に加えて実使用入力とゲート証拠の過去を照合する。

    引数: actual/changed(tuple)、count(int)。返り値: なし(None)。
    """
    causal.prefix(actual[0], changed[0], count)
    for index, (left, right) in enumerate(zip(actual[1], changed[1])):
        causal.exact(left[:count], right[:count], '実使用入力'+str(index))
    assert set(actual[2]) == set(changed[2])
    for name in actual[2]:
        causal.exact(actual[2][name][:count], changed[2][name][:count], 'ゲート/'+name)


def causal_check(spec: dict, ready: dict, columns: tuple, config: dict,
                 actual: tuple, gate_valid: np.ndarray) -> dict:
    """機能: 原本切断・未来全入力改変・上下反射ごとに影と許可を再生成する。

    引数: spec/ready/config(dict)、columns/actual(tuple)、gate_valid(bool ndarray)。
    返り値: 対象行と全列一致の証跡(dict)。元の完成済み許可列は流用しない。
    """
    n = len(ready['last']); cut = max(2, int(n*.37))
    short = play(spec, causal.clipped(ready, cut), tuple(v[:cut].copy() for v in columns),
                 config, gate_valid=gate_valid[:cut].copy())
    gate_prefix(actual, short, cut)
    del short
    repeated = np.flatnonzero(np.diff(ready['time_s']) == 0)+1
    change = int(repeated[np.argmin(abs(repeated-int(n*.73)))]) if len(repeated) else int(n*.73)
    future = causal.clipped(ready, n)
    future['last'][change:] += ready['tick']*(37+np.arange(n-change))
    future['atr'][change:] *= 3
    altered = [v.copy() for v in columns]
    for index in (0, 1, 3, 6):
        altered[index][change:] = np.where(altered[index][change:] == 1, -1, 1)
    for index in (2, 4, 7):
        altered[index][change:] = np.arange(change, n)
    for index in (5, 8):
        altered[index][change:] = ~altered[index][change:]
    altered[9][change:] = 1-altered[9][change:]
    changed_valid = gate_valid.copy(); changed_valid[change:] = ~changed_valid[change:]
    result = play(spec, future, tuple(altered), config, gate_valid=changed_valid)
    gate_prefix(actual, result, change)
    del result
    # ----------------------------------------
    # 公開元と許可距離は鏡映で変わらず、売買方向だけ反転する。
    center = float(2*np.ceil(np.max(ready['last'])/ready['tick'])*ready['tick'])
    mirrored = dict(ready, last=center-ready['last'])
    mirror_columns = tuple(-v if i in (0,1,3,6) else v.copy() for i,v in enumerate(columns))
    mirror = play(spec, mirrored, mirror_columns, config, gate_valid=gate_valid.copy())
    causal.reflected_result(actual[0], mirror[0], center, True)
    causal.reflected_result(actual[0]['shadow'], mirror[0]['shadow'], center, False)
    for index in range(10):
        expected = -actual[1][index] if index in (0,1,3,6) else actual[1][index]
        causal.exact(expected, mirror[1][index], '実使用入力反射'+str(index))
    for name in actual[2]:
        if name == 'mfe_atr':
            causal.close(actual[2][name], mirror[2][name], 'ゲート順行反射')
        else:
            causal.exact(actual[2][name], mirror[2][name], 'ゲート反射/'+name)
    return dict(先頭切断一致=True, 未来変更一致=True, 上下反射一致=True,
                切断行=cut, 未来変更行=change, 影と許可の再生成数=3)


def initial_identity(ready: dict, result: dict) -> dict:
    """機能: 実と影の全初回新規、初期ATRと予算が同一であることを検査する。

    引数: ready/result(dict)。返り値: 全組数と一致フラグ(dict)。
    早期予算返済後の同じ組への再参加を許さず、復元新規は初回新規と分ける。
    """
    shadow = result['shadow']
    actual = result['orders'][(result['orders'][:,7] == 1) & (result['orders'][:,6] == 20)]
    original = shadow['orders'][(shadow['orders'][:,7] == 1) & (shadow['orders'][:,6] == 20)]
    causal.exact(actual, original, '全初回新規の8列')
    for field in ('prepare_events', 'entry_preparations'):
        causal.exact(result[field], shadow[field], '影準備/'+field)
    a, b = result['cycles'], shadow['cycles']
    causal.exact(a[:, [0,1,4,5,8]], b[:, [0,1,4,5,8]], '全組開始/初期R/ATR/方向')
    assert np.all(a[:,2] <= b[:,2]), '影終了より後の保有'
    return dict(影全組数=len(b), 全初回新規完全一致=True, 全組初期ATR予算一致=True, 全組影以前返済=True)


def gate_record(spec: dict, ready: dict, columns: tuple, effective: tuple,
                evidence: dict, valid: np.ndarray, result: dict) -> dict:
    """機能: 許可の行数・時間・公開機会・組数と実約定を混同せず記録する。

    引数: spec/ready/evidence/result(dict)、columns/effective(tuple)、valid(bool ndarray)。
    返り値: 指紋、初回到達の疎記録、同じ公開元を一回とする計数(dict)。
    全False行数を取引機会の損失として解釈しない。0閾値は到達計測対象外。
    """
    plans = result['shadow']['plans']; n = len(ready['last'])
    held = plans[:,0] != 0
    durations = np.diff(ready['time_s'], append=ready['time_s'][-1])
    arms = np.flatnonzero(evidence['armed'] & (evidence['arm_row'] == np.arange(n)))
    opposite = held & (effective[1] == -plans[:,0])
    fresh_pairs = np.column_stack((plans[opposite,1].astype(np.int64), effective[2][opposite]))
    orders = result['orders']
    def executions(reason: int) -> tuple:
        """機能: 分割された返済脚を組・原本行単位の一約定判断へまとめる。

        引数: reason(int)。返り値: 判断回数・合計枚数(tuple[int,float])。
        """
        selected = orders[orders[:,6] == reason]
        return len(np.unique(selected[:,[2,0]],axis=0)), float(selected[:,4].sum())
    reduction_count, reduction_units = executions(30)
    restore_count, restore_units = executions(31)
    sparse = [dict(row=int(i), seq=int(ready['seq'][i]), time_s=float(ready['time_s'][i]),
        campaign=int(plans[i,1]), direction=int(plans[i,0]), initial_atr=float(plans[i,2]),
        anchor=float(plans[i,3]), extreme=float(plans[i,10]), mfe_atr=float(evidence['mfe_atr'][i]),
        original_source_row=int(columns[2][i]), plan_source_row=int(plans[i,33])) for i in arms]
    shadow_groups = np.unique(plans[held,1].astype(np.int64))
    armed_groups = np.unique(evidence['campaign'][evidence['armed']])
    bypass = spec['gate_threshold_atr'] == 0
    trace = dict(original_bad=columns[1], original_source=columns[2], effective_bad=effective[1],
                 effective_source=effective[2], bad_valid=valid, **evidence)
    return dict(session=ready['session'], symbol=ready['symbol'], bypass=bypass,
        eligibleの意味='実装上の通過可否。0閾値は非保有中も全Trueで、実減量可能時間ではない。',
        fingerprints=old.fingerprints(trace, tuple(trace)), arm_events=sparse,
        shadow_campaigns=len(shadow_groups), armed_campaigns=None if bypass else len(armed_groups),
        unarmed_campaigns=None if bypass else len(shadow_groups)-len(armed_groups),
        eligible_rows=int(evidence['eligible'].sum()), eligible_seconds=float(durations[evidence['eligible']].sum()),
        opposite_publications=len(np.unique(fresh_pairs, axis=0)),
        adverse_rows=int(opposite.sum()), adverse_seconds=float(durations[opposite].sum()),
        reductions=reduction_count, reduced_units=reduction_units, restorations=restore_count,
        restored_units=restore_units, budget_closed_campaigns=int(np.sum(result['cycles'][:,9] == 32)),
        全源行維持=bool(np.array_equal(columns[2], effective[2])),
        初期準備と建玉一致=initial_identity(ready, result))


def legacy_id(spec: dict) -> str | None:
    """機能: 元A0・無ゲートC01の中央と入口時計感度だけを旧厳密対照へ対応する。

    引数: spec(dict)。返り値: 旧ID又は該当なし(str|None)。
    """
    prefix, variant = spec['id'].split('__')
    if prefix not in ('A0', 'G000_F25_N1') or variant not in ('V000','E080','E120'):
        return None
    manager = 'A0' if prefix == 'A0' else 'B00_RB00_F25_N1'
    return f'H019__{manager}__R1__{variant}'


def evaluate(spec: dict) -> dict:
    """機能: 一条件の26入力を全行会計へ通し、期間集計と元単一窓同値を保存する。

    引数: spec(dict)。返り値: 条件完了記録(dict)。
    """
    identifier, started = spec['id'], time.perf_counter()
    destination = HERE/'supplementary' if spec['role'] == 'supplementary' else HERE
    rows, series, ledgers, proofs, waves, causality = [], {}, [], [], [], []
    prior_id = legacy_id(spec)
    prior = {(r['session'],r['symbol']):r for r in read(HERE.parent/'wave_v38/ledgers'/(prior_id+'.json.gz'))} if prior_id else {}
    gate_use = []
    for key, ready in sorted(INPUTS.items()):
        columns = columns_for(spec, key)
        config = old.base.managers.make_config(old.FIXED['manager'], key[1], ready)
        valid = quality_for(spec, key)
        result, effective, evidence = play(spec, ready, columns, config, gate_valid=valid)
        row, curves, proof, basic = audit.inspect(spec, ready, result, config, effective)
        for flag in PROOF_FLAGS:
            assert proof[flag] is True, (identifier, key, flag)
        assert proof['原本行数'] == len(ready['last'])
        other_row = old.session_row(identifier, ready, result, config, effective[1], basic, curves)
        audit.statistics.equal(other_row, row, '別経路の全統計')
        fingerprints = old.fingerprints(result)
        if prior_id:
            assert fingerprints == prior[key]['result_fingerprints'], (identifier, key, '旧単一窓全15指紋')
        rows.append(row)
        series[key] = curves['equity']
        usage = gate_record(spec, ready, columns, effective, evidence, valid, result)
        assert usage['全源行維持']
        gate_use.append(usage)
        ledgers.append(dict(session=key[0], symbol=key[1], config=config,
            **{field:result[field].tolist() for field in STORED}, result_fingerprints=fingerprints,
            shadow_fingerprints=old.fingerprints(result['shadow'], reference.EXPECTED_SHADOW_FIELDS),
            shadow_cycles=result['shadow']['cycles'].tolist(), shadow_orders=result['shadow']['orders'].tolist(),
            gate_fingerprints=usage['fingerprints'], arm_events=usage['arm_events']))
        proofs.append(dict(session=key[0], symbol=key[1], **proof, 全統計一致=True,
            時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest(), 旧単一窓一致=prior_id is not None))
        if key[0] in REPRESENTATIVE:
            causality.append(dict(session=key[0], symbol=key[1], **causal_check(spec, ready, columns, config, (result,effective,evidence), valid)))
        for wave in old.FIXED['指定波']:
            if wave['session'] == key[0]:
                records = old.base.wave_metrics.order_records(ready, columns[0], result, engine.REASONS)
                waves.append(old.base.wave_metrics.episode_metrics(dict(id=identifier, manager=old.FIXED['manager']),
                    wave, ready, columns[0], result, records, config['point_value']))
    assert len(rows) == len(ledgers) == len(proofs) == 26 and len(waves) == 8 and len(causality) == 4
    periods = {}
    for period, names in (('all_symbols', old.FIXED['全セッション']), ('symbols', old.FIXED['後半7セッション'])):
        periods[period] = {s:audit.statistics.period(rows, series, names, s, old.base.research.MULT[s]) for s in old.SYMBOLS}
        audit.statistics.equal(old.period(rows, names), periods[period], '期間全統計')
    value = dict(id=identifier, spec=spec, **periods, wave_passes=sum(r['正方向ネット20分目安達成'] for r in waves),
        全26全行独立会計一致=True, 探索固定SHA256=digest(HERE/'探索条件の固定.json'),
        全原本行会計数=sum(len(r['last']) for r in INPUTS.values()), 旧単一窓一致入力数=26 if prior_id else 0)
    paths = []
    for folder, payload, suffix in (('sessions', rows, '.json.gz'), ('ledgers', ledgers, '.json.gz'),
        ('audits', proofs, '.json.gz'), ('waves', waves, '.json.gz'), ('causality', causality, '.json'),
        ('gate_use', gate_use, '.json'), ('summaries', value, '.json')):
        path = destination/folder/(identifier+suffix)
        save(path, payload)
        paths.append(path)
    done = dict(id=identifier, 全合格=True, 全入力数=26, 因果入力数=4,
        全原本行会計数=value['全原本行会計数'], 旧単一窓一致入力数=value['旧単一窓一致入力数'],
        探索固定SHA256=digest(HERE/'探索条件の固定.json'),
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in paths}, 経過秒=time.perf_counter()-started)
    save(destination/'completed'/(identifier+'.json'), done)
    return done


def main() -> None:
    """機能: 全主・補助を同時に事前固定した後、選択した範囲の全件を再生する。

    引数: コマンドラインworkers(int)、supplementary(bool)。返り値: なし(None)。
    保存完了済みの条件も勝手に間引かず、指定範囲を全て同じ規則で比較する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--supplementary', action='store_true')
    args = parser.parse_args()
    fixed = read(HERE/'探索条件の固定.json')
    assert fixed['conditions'] == design.catalog()
    assert fixed['supplementary'] == design.supplementary()
    verify(fixed['参照資料SHA256'])
    specs = design.supplementary() if args.supplementary else design.catalog()
    assert len(specs) == len({s['id'] for s in specs}) == (128 if args.supplementary else 35)
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, spec):spec['id'] for spec in specs}
        completed = []
        for future in as_completed(futures):
            completed.append(future.result())
            print(f"{len(completed)}/{len(futures)} {futures[future]} 完了", flush=True)
    assert {v['id'] for v in completed} == {s['id'] for s in specs}
    verify(fixed['参照資料SHA256'])
    for record in completed:
        verify(record['出力SHA256'])
    destination = HERE/'supplementary' if args.supplementary else HERE
    save(destination/'主再生の完了.json', dict(全合格=True, 全条件数=len(completed),
        全入力数=sum(r['全入力数'] for r in completed), 因果入力数=sum(r['因果入力数'] for r in completed),
        全原本行会計数=sum(r['全原本行会計数'] for r in completed),
        旧単一窓一致入力数=sum(r['旧単一窓一致入力数'] for r in completed),
        探索固定SHA256=digest(HERE/'探索条件の固定.json'), records=sorted(completed, key=lambda x:x['id']),
        現在API取得数=0, 保存ライブ使用=False, 全体目標達成=False))


if __name__ == '__main__':
    main()
