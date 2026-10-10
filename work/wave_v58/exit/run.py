"""原候補列を固定し、壁とトレールの12対照を中値約定で再生する。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np

from engine import execute, MODES, REASONS


HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]
OLD = WORK / 'wave_v57'
SOURCE_PATHS = {'候補': OLD / '判断.pkl', '特徴': OLD / 'features.pkl',
                '有効原本': WORK / 'wave_v55/clean_inputs.pkl', '前回結果': OLD / '売買結果.json',
                '前回売買器': OLD / 'engine.py', '前回仕様': OLD / '売買仕様固定.json',
                '共通集計': WORK / 'wave_v52/export.py'}
spec = importlib.util.spec_from_file_location('export_exit58', SOURCE_PATHS['共通集計'])
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def clean(value: object) -> object:
    """機能: 非有限数値とNumPy型を公開用JSONへ変換する。

    引数: value(object)。返り値: JSONへ格納可能な値(object)。
    """
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: object) -> None:
    """機能: 日本語の有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def digest(path: Path) -> str:
    """機能: 大きな入力を分割読みしてSHA256を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def configurations() -> list[dict]:
    """機能: 成績に依存しない12の出口部品対照を固定順で列挙する。

    引数: なし。返り値: 条件一覧(list[dict])。
    """
    return [dict(id=f'{family}_{mode}', family=family, mode=mode, name=MODES[mode],
                 source_id=f'{family}_C2_W05', primary=mode == 'A')
            for family in ('R1', 'R2', 'R3') for mode in MODES]


def freeze(configs: list[dict]) -> dict:
    """機能: 実データの新しい損益を見る前に出口と実行コードと入力を固定する。

    引数: configs(list[dict])。返り値: 固定仕様(dict)。既存固定と違う場合は停止する。
    """
    code = {name: digest(HERE / name) for name in ('engine.py', 'run.py', 'check_engine.py')}
    sources = {name: dict(path=str(path), SHA256=digest(path)) for name, path in SOURCE_PATHS.items()}
    target = HERE / '出口仕様固定.json'
    if target.exists():
        frozen = json.loads(target.read_text(encoding='utf8'))
        assert frozen['コードSHA256'] == code and frozen['入力'] == sources, '固定後の変更です'
        return frozen
    frozen = dict(固定時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(), 条件=configs,
                  コードSHA256=code, 入力=sources,
                  目的='赤字が補充壁の早い保護か、即時トレールか、その両方に由来するかを部品対照する。利益順位で条件を増減しない。',
                  入口='00054のR1/R2/R3、補充2回、始値0.05%幅の保存判断列をそのまま用いる。再抽出・候補変更・幅変更なし。',
                  出口A='元と同じ固定壁と約定直後からの幅Wトレール。買いは高い線、売りは低い線。等しければ壁理由。',
                  出口B='固定壁だけ。トレールなし。', 出口C='約定直後からの幅Wトレールだけ。固定壁なし。',
                  出口D='固定壁に加え、新規約定中値から1W以上順行した時から幅Wトレールを有効化。有効化後は解除しない。順行到達前は壁だけ。',
                  観測='高安追跡・出口判定・約定・含み評価をすべて中値で実施。時計が同じでも原本順を維持。次の有効原本行でのみ約定。',
                  共通='費用0。TOPIXmini5枚/NK225micro10枚、片方向上限10/20以内、追加なし。Day15:35/Night翌05:50で返済判断。最後5分新規不可。全返済後60秒休止。',
                  再現='Aの138口座は前回の中値再評価の全注文行・収支・利益損失・枚数と完全一致を必須とする。',
                  分母='原候補数、採用数、保有中/締切/休止見送りを相互排他的に計上し総数を照合する。候補は保有中でも消費する。',
                  解釈='候補列が同じでも出口変更で保有時間と休止期間が変わり、採用入口も変わる。比較は出口変更を含む運用全体の差で、純粋な出口だけの因果効果ではない。',
                  限界='既知の23場を原因分析する比較。未知期間検証でも全損失原因の同定でもない。中値はmini/microの実約定可能価格を保証しない。',
                  現在API取得数=0)
    save(target, frozen)
    return frozen


def summarize(accounts: list[dict]) -> dict:
    """機能: 同じ銘柄の各場成績をまとめ、保有時間と出口理由を併記する。

    引数: accounts(list[dict])。返り値: 集計(dict)。
    """
    out = export.summarize(accounts)
    legs = np.asarray([t for a in accounts for t in a['trades']], float).reshape(-1, 16)
    groups = np.asarray([g for a in accounts for g in a['width_groups']], float).reshape(-1, 9)
    out.update(candidate_count=sum(a['candidate_count'] for a in accounts),
               candidate_audit={name: sum(a['candidate_audit'][name] for a in accounts)
                                for name in ('consumed', 'accepted', 'occupied', 'cutoff', 'cooldown', 'unreached')},
               median_hold_minutes=float(np.median(legs[:, 15])) if len(legs) else None,
               mean_hold_minutes=float(np.mean(legs[:, 15])) if len(legs) else None,
               mean_mfe_width=float(groups[:, 7].mean()) if len(groups) else None,
               w_net=float(groups[:, 2].sum()), w_mean=float(groups[:, 2].mean()) if len(groups) else None,
               reasons={})
    for reason in (1, 2, 3):
        selected = legs[legs[:, 7] == reason]
        pnl = selected[:, 6]
        out['reasons'][REASONS[reason]] = dict(cycles=len(pnl), profit=float(pnl[pnl > 0].sum()),
                                               loss=float(-pnl[pnl < 0].sum()), net=float(pnl.sum()))
    return out


def audit_baseline(account: dict, original: dict, ready: dict, frame: dict, value: float) -> dict:
    """機能: Aの全注文と全決済を前回の同じ原本行の中値へ独立に付け直して照合する。

    引数: account/original/ready/frame(dict)、value(float)。返り値: 再現件数と合否(dict)。
    """
    old_orders = np.asarray(original['orders'], float).reshape(-1, 13)
    new_orders = np.asarray(account['orders'], float).reshape(-1, 13)
    old_legs = np.asarray(original['trades'], float).reshape(-1, 16)
    new_legs = np.asarray(account['trades'], float).reshape(-1, 16)
    expected_orders = old_orders.copy()
    expected_orders[:, 7] = frame['mid'][np.searchsorted(ready['seq'], old_orders[:, 3])]
    expected_legs = old_legs.copy()
    expected_legs[:, 4] = frame['mid'][np.searchsorted(ready['seq'], old_legs[:, 11])]
    expected_legs[:, 5] = frame['mid'][np.searchsorted(ready['seq'], old_legs[:, 12])]
    expected_legs[:, 6] = expected_legs[:, 2] * expected_legs[:, 3] * (expected_legs[:, 5] - expected_legs[:, 4]) * value
    expected_orders[expected_orders[:, 4] == 2, 8] = expected_legs[:, 6]
    np.testing.assert_array_equal(new_orders, expected_orders)
    np.testing.assert_array_equal(new_legs, expected_legs)
    for field in ('profit', 'loss', 'net', 'win_qty', 'loss_qty', 'flat_qty', 'cycles', 'wins', 'losses'):
        assert account[field] == original['sensitivity']['中値'][field], field
    assert account['candidate_count'] == original['candidate_count']
    return dict(session=account['session'], symbol=account['symbol'], orders=len(new_orders),
                cycles=len(new_legs), candidate_count=account['candidate_count'], passed=True)


def entrance_map(account: dict) -> dict:
    """機能: 約定組を入口判断原本行と方向で対応付ける。

    引数: account(dict)。返り値: 入口とその決済収支の対応(dict)。
    """
    entries = {int(o[10]): (int(o[2]), int(o[5])) for o in account['orders'] if o[4] == 1}
    return {entries[int(t[9])]: t[6] for t in account['trades']}


def compare_entries(account: dict, baseline: dict) -> dict:
    """機能: 収支差を共通入口の差と追加・失った入口の寄与へ会計分解する。

    引数: account/baseline(dict)。返り値: 入口集合別の件数と収支差(dict)。
    因果効果の推定ではなく、同じ候補を使う運用全体の会計分解である。
    """
    actual, base = entrance_map(account), entrance_map(baseline)
    common, added, removed = actual.keys() & base.keys(), actual.keys() - base.keys(), base.keys() - actual.keys()
    result = dict(common_entries=len(common), added_entries=len(added), removed_entries=len(removed),
                  common_baseline_net=sum(base[k] for k in common), common_variant_net=sum(actual[k] for k in common),
                  added_variant_net=sum(actual[k] for k in added), removed_baseline_net=sum(base[k] for k in removed))
    result['common_delta'] = result['common_variant_net'] - result['common_baseline_net']
    result['total_delta'] = account['net'] - baseline['net']
    assert result['total_delta'] == result['common_delta'] + result['added_variant_net'] - result['removed_baseline_net']
    return result


def main() -> None:
    """機能: 条件固定後に12条件を再生し、全会計と前回再現を保存する。

    引数: なし。返り値: なし(None)。過去の入力・コード・研究成果を変更しない。
    """
    configs = configurations()
    frozen = freeze(configs)
    signals = pickle.loads(SOURCE_PATHS['候補'].read_bytes())
    features = pickle.loads(SOURCE_PATHS['特徴'].read_bytes())
    inputs = pickle.loads(SOURCE_PATHS['有効原本'].read_bytes())
    old = json.loads(SOURCE_PATHS['前回結果'].read_text(encoding='utf8'))
    originals = {(m['id'], a['session'], a['symbol']): a for m in old['methods'] for a in m['accounts']}
    sessions = sorted({key[0] for key in inputs})
    assert len(sessions) == 23 and len(inputs) == 46 and set(inputs) == set(features)
    output, audits, baselines, source_checks, decompositions = [], [], {}, [], []
    for config in configs:
        accounts = []
        for key in sorted(inputs):
            ready, frame = inputs[key], features[key]
            source = signals[(key, config['source_id'])]
            source_hash = hashlib.sha256(source.tobytes()).hexdigest()
            original = originals[(config['source_id'], *key)]
            assert len(source) == original['candidate_count']
            qty, value = (5, 1000.) if key[1] == 'TOPIX' else (10, 10.)
            a = execute(ready, frame, source, qty, value, config['mode'])
            a['intervals'] = export.intervals(ready, a)
            a['source_signal_sha256'] = source_hash
            assert hashlib.sha256(source.tobytes()).hexdigest() == source_hash
            assert a['win_qty'] + a['loss_qty'] + a['flat_qty'] == a['cycles'] * qty
            assert a['candidate_audit']['accepted'] == a['cycles']
            if config['mode'] == 'A':
                audits.append(dict(method=config['id'], **audit_baseline(a, original, ready, frame, value)))
                baselines[(config['family'], key)] = {k: v for k, v in a.items() if k not in ('curve', 'w_curve')}
            a['entry_comparison'] = compare_entries(a, baselines[(config['family'], key)])
            accounts.append(a)
            source_checks.append(dict(method=config['id'], session=key[0], symbol=key[1],
                                      original_count=len(source), source_signal_sha256=source_hash,
                                      **a['candidate_audit']))
        # ----------------------------------------
        # 金額は銘柄別に集計する。単純合算による銘柄横断の優劣選抜はしない。
        summary, periods = {}, {}
        for symbol in ('TOPIX', 'NK225'):
            selected = [a for a in accounts if a['symbol'] == symbol]
            summary[symbol] = summarize(selected)
            periods[symbol] = {label: summarize([a for a in selected if a['session'] in section])
                               for label, section in [('前10場', sessions[:10]), ('次9場', sessions[10:19]), ('後4場', sessions[19:])]}
            decomposition = {field: sum(a['entry_comparison'][field] for a in selected)
                             for field in selected[0]['entry_comparison']}
            decompositions.append(dict(method=config['id'], symbol=symbol, **decomposition))
        compact = [{k: v for k, v in a.items() if k not in ('curve', 'w_curve')} for a in accounts]
        output.append(dict(**config, accounts=compact, summary=summary, periods=periods))
        print(config['id'], [(s, summary[s]['net'], summary[s]['cycles'], summary[s]['payoff'])
                             for s in ('TOPIX', 'NK225')], flush=True)
    # ----------------------------------------
    # 最後に原入力と旧コードの不変を再確認し、比較全件を残す。
    for name, path in SOURCE_PATHS.items():
        assert digest(path) == frozen['入力'][name]['SHA256'], name
    assert len(audits) == 138 and len(source_checks) == 552
    save(HERE / 'A再現監査.json', dict(passed=True, accounts=len(audits),
                                    orders=sum(a['orders'] for a in audits), cycles=sum(a['cycles'] for a in audits), details=audits))
    save(HERE / '候補列と適用数の照合.json', dict(passed=True, accounts=len(source_checks), details=source_checks))
    save(HERE / '入口集合変化の会計分解.json', dict(
        interpretation='共通入口の決済差と、出口変更で追加・失った入口の会計分解。純粋な出口の因果効果ではない。', details=decompositions))
    save(HERE / '出口対照結果.json', dict(methods=output, sessions=sessions, meta=dict(
        conditions=12, accounts=552, price='判断後の次の有効原本行の中値', fees=0,
        qty='TOPIXmini5枚/NK225micro10枚、追加なし、上限10/20枚', main_ids=['R1_A', 'R2_A', 'R3_A'],
        source_ids=['R1_C2_W05', 'R2_C2_W05', 'R3_C2_W05'], current_api_requests=0, unseen=False,
        baseline_accounts_verified=138, input_sha256_unchanged=True,
        interpretation=frozen['解釈'], limit=frozen['限界'])))
    print('全12条件とAの138口座照合が完了', flush=True)


if __name__ == '__main__':
    main()
