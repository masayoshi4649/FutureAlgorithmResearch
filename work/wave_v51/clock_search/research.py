"""E01の再参加時計と入口・休止・伸びない保有の扱いを先頭10場で選ぶ。"""
from __future__ import annotations

from copy import deepcopy
import gzip
import importlib.util
import json
import os
from pathlib import Path
import pickle
import socket
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'numba_cache')


def module(name: str, path: Path) -> object:
    """機能: 既存実装を変更せず専用名で読み込む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


prior = module('時計探索の既存E01', ROOT / 'work/wave_v50/update_20261001_day/replay_added_session.py')
overlay = module('時計探索の共通入力', ROOT / 'work/wave_v51/overlay/research.py')
early, integration, source = prior.early, prior.integration, prior.source
ACTIVE_CLOCK = 'normal'
SYMBOLS = ('TOPIX', 'NK225')


def save(name: str, value: object) -> None:
    """機能: 時計探索の領域だけにJSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf8')
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def deny(*args: object, **kwargs: object) -> None:
    """機能: 追加ネットワーク接続を拒否する。

    引数: args/kwargs(object)。返り値: なし(None)、常に例外。
    """
    raise RuntimeError('時計探索では追加API取得を認めません')


def catalog() -> list[dict]:
    """機能: 時計3×休止4×入口2×失敗保護2の48条件を固定する。

    引数: なし。返り値: 条件(list[dict])。
    """
    values = []
    for clock in ('normal', 'risk', 'actual'):
        for cooldown in (5., 15., 30., 60.):
            for entry in (.25, .5):
                for failure in (False, True):
                    values.append(dict(id=f'K{len(values):02}', clock=clock, cooldown=cooldown, entry=entry, failure=failure))
    return values


def make_shadow(ready: dict, state: np.ndarray, base: dict, config: dict) -> dict:
    """機能: 指定した時計で準備を再生し実口座の出口影へ接続する。

    引数: ready/base/config(dict)、state(ndarray)。返り値: 出口影と準備時計(dict)。
    元ファイルは変更しない。過去の負け組を削除せず毎行から注文を作り直す。
    """
    old_engine, shadow_api = early.old_engine, early.shadow_api
    if ACTIVE_CLOCK == 'normal':
        schedule_config = dict(base, tighten_atr=0., tight_width=1.)
    elif ACTIVE_CLOCK == 'risk':
        schedule_config = dict(config, tighten_atr=0., tight_width=1.)
    else:
        schedule_config = dict(config)
    # 旧run窓口は研究当時の固定値だけを許すため、同じsimulate本体へ明示した48条件を渡す。
    schedule_par = np.asarray([schedule_config[name] for name in old_engine.PARAMS], float)
    schedule_values = old_engine.simulate(ready['time_s'], ready['last'], ready['atr'], ready['atr'], state, state,
        ready['tick'], ready['start'], ready['limit'], ready['us_open'], schedule_par, True, int(config['audit_cap']), 0, False,
        np.ones(len(state), bool), 0., float(ready.get('session_close', ready['limit']+600)))
    scheduler = dict(zip(shadow_api.FIELDS, schedule_values))
    allow = np.zeros(len(state), bool)
    allow[scheduler['prepare_events'][:, 1].astype(int)] = True
    par = np.asarray([config[name] for name in old_engine.PARAMS], float)
    values = old_engine.simulate(ready['time_s'], ready['last'], ready['atr'], ready['atr'], state, state,
        ready['tick'], ready['start'], ready['limit'], ready['us_open'], par, True, int(config['audit_cap']), 0, False,
        allow, 0., float(ready.get('session_close', ready['limit']+600)))
    shadow = dict(zip(shadow_api.FIELDS, values))
    shadow.update(scheduler=scheduler, schedule_prepare_allow=allow,
        input_sha256=integration.engine.input_digest(ready, state, config, False, 0.), observed_fill=False, min_delay_seconds=0.)
    for field in ('prepare_events', 'entry_preparations'):
        np.testing.assert_array_equal(shadow[field], scheduler[field])
    for value in (shadow, scheduler):
        assert np.all(value['orders'][:, 0] > value['orders'][:, 1])
    return shadow


def configs(spec: dict, ready: dict, variant: dict) -> tuple[dict, dict]:
    """機能: 再参加条件を時計と実口座へ同時に設定する。

    引数: spec/ready/variant(dict)。返り値: 時計基準と実出口設定(tuple[dict,dict])。
    """
    base = integration.config_for(spec, ready)
    base.update(cooldown_min=variant['cooldown'], entry_atr=variant['entry'])
    changed = dict(base, stop_atr=.75)
    if variant['failure']:
        changed.update(failure_min=15., failure_mfe=.5, failure_stop=.5)
    return base, changed


def one(variant: dict, key: tuple, ready: dict, detailed: bool) -> tuple:
    """機能: 一銘柄一場の全注文を再生して会計と因果を確認する。

    引数: variant/ready(dict)、key(tuple)、detailed(bool)。返り値: 集計・曲線・台帳・証跡(tuple)。
    """
    global ACTIVE_CLOCK
    ACTIVE_CLOCK = variant['clock']
    spec = deepcopy(next(s for s in source.followup.catalog('new') if s['id'] == early.BASE_ID))
    spec['id'] = early.BASE_ID + '__' + variant['id']
    columns, valid = source.replay.new_columns(spec, key)
    base, config = configs(spec, ready, variant)
    actual = early.play(spec, ready, columns, valid, base, config)
    row, curve, proof = early.inspect(spec, ready, actual, config)
    proof['指定時計と全初回一致'] = proof.pop('全初回一致')
    proof['指定時計から再生成一致'] = proof.pop('元影時計一致')
    result = actual[0]
    row['initial_entries'] = len(result['entry_preparations'])
    row['active_session'] = bool(row['initial_entries'])
    ledger = None
    if detailed:
        ledger = dict(session=key[0], symbol=key[1], config=config,
            **{field: result[field].tolist() for field in integration.STORED},
            result_fingerprints=integration.reference.old.fingerprints(result),
            shadow_fingerprints=integration.reference.old.fingerprints(result['shadow'], integration.reference.reference.EXPECTED_SHADOW_FIELDS),
            scheduler_fingerprints=integration.reference.old.fingerprints(result['shadow']['scheduler'], integration.reference.reference.EXPECTED_SHADOW_FIELDS),
            scheduler_cycles=result['shadow']['scheduler']['cycles'].tolist(), scheduler_orders=result['shadow']['scheduler']['orders'].tolist())
        proof['因果'] = early.causal(spec, ready, columns, valid, base, config, actual)
        proof['因果']['指定時計から再生成'] = proof['因果'].pop('通常影から再生成')
    return row, curve, ledger, proof


def features_all() -> dict:
    """機能: 全23場の検証済み板特徴を読む。

    引数: なし。返り値: 板特徴辞書(dict)。
    """
    values = pickle.loads((ROOT / 'work/wave_v47/features_depth.pkl').read_bytes())
    folders = [ROOT / 'work/wave_v48' / n for n in ('update_20260930', 'update_20261001')]
    folders += [ROOT / 'work/wave_v50' / n for n in prior.read(ROOT / 'work/wave_v50/追加結果一覧.json')]
    for folder in folders:
        values.update(pickle.loads((folder / 'new_features_depth.pkl').read_bytes()))
    return values


def score(period: dict) -> tuple:
    """機能: 先頭10場だけの成績から最弱銘柄のRを優先評価する。

    引数: period(dict)。返り値: 大きいほど良い順位(tuple)。
    """
    return (min(period[s]['net_r'] for s in SYMBOLS),
        min(period[s]['money_ratio'] for s in SYMBOLS), sum(period[s]['net_r'] for s in SYMBOLS))


def eligible(period: dict) -> bool:
    """機能: 両銘柄の活動場数と件数の下限を確認する。

    引数: period(dict)。返り値: 適格(bool)。
    """
    return all(period[s]['active_sessions'] >= 7 and period[s]['cycles'] >= 20 for s in SYMBOLS)


def main() -> None:
    """機能: 条件を固定して探索・選択・選択後再検証を順に実行する。

    引数: なし。返り値: なし(None)。
    """
    started = time.perf_counter()
    HERE.mkdir(parents=True, exist_ok=True)
    socket.socket.connect = deny
    socket.create_connection = deny
    inputs, baseline = overlay.load()
    names = sorted({key[0] for key in inputs})
    periods = dict(先頭10=names[:10], 次9=names[10:19], 追加4=names[19:], 全23=names)
    fixed = dict(条件=catalog(), 分割=periods,
        選択='先頭10場のみ。両銘柄で7活動場以上かつ20組以上。最弱銘柄の合計Rを最大化、同点は最弱PF、次は合計R。上位3条件。次9・追加4は選択に使わない既知データ再検証。',
        制約='TOPIX初回5上限10、NK初回10上限20。0費用・指定価格約定。出口stop0.75ATR/3ATR順行で幅0.75ATR/360分/場内返済。通常影の準備時刻だけ変更し、後から取引を削除しない。',
        時計定義=dict(normal='従来stop1ATR・短縮なし', risk='stop0.75ATRと失敗保護を実口座に一致・3ATR後の短縮はなし', actual='価格出口条件全てを実口座に一致。途中減量は実口座にのみ存在し時計は単独仮想運転'),
        注意='actualでも数量減量を含む実口座完全フラット時計とは異なる。後半成績は既知であり真の未見検証ではない。', API取得数=0)
    freeze_path = HERE / '事前固定.json'
    if freeze_path.exists():
        assert prior.read(freeze_path) == fixed
    else:
        save('事前固定.json', fixed)
    early.make_shadow = make_shadow
    integration.reference.initialize()
    signals = prior.previous.signals(inputs, features_all(), ROOT)
    prior.activate(inputs, signals)
    training = []
    for variant in catalog():
        target = HERE / 'training' / (variant['id']+'.json')
        if target.exists():
            summary = prior.read(target)
        else:
            rows, series = [], {}
            for key, ready in sorted(inputs.items()):
                if key[0] in periods['先頭10']:
                    row, curve, _, _ = one(variant, key, ready, False)
                    rows.append(row)
                    series[key] = curve
            period = {s: source.period(rows, series, periods['先頭10'], s) for s in SYMBOLS}
            summary = dict(条件=variant, 先頭10=period, 適格=eligible(period), 順位値=score(period), sessions=rows)
            save('training/'+variant['id']+'.json', summary)
        training.append(summary)
        print(variant['id'], '先頭10', {s: round(summary['先頭10'][s]['net_yen']) for s in SYMBOLS}, flush=True)
    ranked = sorted([r for r in training if r['適格']], key=lambda r: tuple(r['順位値']), reverse=True)
    selected = [r['条件'] for r in ranked[:3]]
    save('選択.json', dict(選択条件=selected, 選択対象場=periods['先頭10'], 適格数=len(ranked), 比較条件数=len(training),
        順位=[dict(id=r['条件']['id'], 値=r['順位値']) for r in ranked]))
    print('選択', [v['id'] for v in selected], '経過秒', round(time.perf_counter()-started, 1), flush=True)
    all_summaries, all_proofs = {}, {}
    for variant in [catalog()[0]] + [v for v in selected if v['id'] != 'K00']:
        rows, series, ledgers, proofs = [], {}, [], []
        for key, ready in sorted(inputs.items()):
            row, curve, ledger, proof = one(variant, key, ready, True)
            if variant['id'] == 'K00':
                for name in ('result_fingerprints', 'shadow_fingerprints', 'scheduler_fingerprints'):
                    assert ledger[name] == baseline[key][name], (key, name)
                proof['既存E01完全一致'] = True
            rows.append(row)
            series[key] = curve
            ledgers.append(ledger)
            proofs.append(dict(session=key[0], symbol=key[1], **proof))
            folder = HERE / 'curves'
            folder.mkdir(exist_ok=True)
            np.savez_compressed(folder / (variant['id']+'_'+key[0]+'_'+key[1]+'.npz'), equity=curve)
        result = {label: {s: source.period(rows, series, chosen, s) for s in SYMBOLS} for label, chosen in periods.items()}
        summary = dict(条件=variant, periods=result, 全合格=True)
        save('summaries/'+variant['id']+'.json', summary)
        save('sessions/'+variant['id']+'.json.gz', rows)
        save('ledgers/'+variant['id']+'.json.gz', ledgers)
        save('audits/'+variant['id']+'.json.gz', proofs)
        all_summaries[variant['id']] = summary
        all_proofs[variant['id']] = dict(口座数=len(proofs), 因果監査数=sum('因果' in p for p in proofs), 全合格=True)
        print(variant['id'], '全23完了', {s: result['全23'][s]['net_yen'] for s in SYMBOLS}, flush=True)
    save('結果.json', dict(全合格=True, 条件数=len(training), 選択=selected, 集計=all_summaries, 監査=all_proofs,
        API取得数=0, 経過秒=time.perf_counter()-started, 注意=fixed['注意']))


if __name__ == '__main__':
    main()
