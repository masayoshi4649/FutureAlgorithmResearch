"""保存公開だけを入口に使い、次原行の市場約定と実返済を一回ずつ測る。"""

import gzip
import hashlib
from io import BytesIO
import json
from pathlib import Path
import pickle

import numpy as np

import catalog
import engine
import input_contract
from metrics import metrics
import plan


OUT = plan.HERE / 'finance'

# ----------------------------------------


def primitive(value: object) -> object:
    """
    機能: JSONへ保存する有限の集計をPythonの型へ変換する。
    引数: value(object) は集計。非有限値は未知としてNoneへ移す。
    返り値: object。注文配列のNaN欄を隠して金額を修正する処理ではない。
    """
    if isinstance(value, dict):
        return {str(k): primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [primitive(v) for v in value]
    if isinstance(value, np.ndarray):
        return primitive(value.tolist())
    if isinstance(value, np.generic):
        return primitive(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def curve_pack(curve: np.ndarray) -> dict:
    """
    機能: 清算曲線を同値連続区間へ可逆圧縮する。
    引数: curve(ndarray[float]) は原行ごとの全欄。NaN同士だけを同値とする。
    返り値: dict は開始行・値・元形状。計算行や時点を省いて再計算しない。
    """
    assert curve.ndim == 2
    if len(curve) == 0:
        return dict(shape=curve.shape, starts=np.zeros(0, dtype=np.int64), values=curve.copy())
    equal = (curve[1:] == curve[:-1]) | (np.isnan(curve[1:]) & np.isnan(curve[:-1]))
    starts = np.r_[0, np.flatnonzero(~equal.all(axis=1)) + 1].astype(np.int64)
    return dict(shape=curve.shape, starts=starts, values=curve[starts].copy())


def curve_unpack(packed: dict) -> np.ndarray:
    """
    機能: 可逆圧縮した清算曲線を元の全原行へ戻す。
    引数: packed(dict) はcurve_packの出力。
    返り値: ndarray は全欄・全行。人工検査と独立会計で用いる。
    """
    starts, values = packed['starts'], packed['values']
    if len(starts) == 0:
        return values.copy().reshape(packed['shape'])
    lengths = np.diff(np.r_[starts, packed['shape'][0]])
    return np.repeat(values, lengths, axis=0)


def load_once(info: dict, counter: dict, label: str, only: tuple | None = None) -> dict:
    """
    機能: 一入力を一回読んだ同じbytesで指紋とNPZを検査する。
    引数: info(dict)、counter(dict)、label(str)、only(tuple|None) は目録と用途。
    返り値: dict[str,ndarray]。114の未来結果を読む用途には使わない。
    """
    path = plan.ROOT / info['path']
    before = path.stat()
    assert before.st_size == info['bytes']
    if 'mtime_ns' in info:
        assert before.st_mtime_ns == info['mtime_ns']
    counter[label] += 1
    raw = path.read_bytes()
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    assert hashlib.sha256(raw).hexdigest() == info['SHA256']
    with np.load(BytesIO(raw), allow_pickle=False) as archive:
        keys = tuple(archive.files) if only is None else only
        assert set(keys).issubset(archive.files)
        result = {key: archive[key] for key in keys}
    for array in result.values():
        array.flags.writeable = False
    return result


def guard() -> tuple[dict, dict]:
    """
    機能: 正式固定・登録・人工証跡・全66系譜が同じ実装へ接続することを検査する。
    引数: なし。
    返り値: tuple[dict,dict] は入力固定と正式固定。不一致時は原入力を読まない。
    """
    assert not OUT.exists(), '金融出力があるため再計算しない'
    frozen = plan.read(plan.HERE / '金融前の正式固定.json')
    proposal = plan.read(plan.HERE / '試行計画.json')
    audit = plan.read(plan.HERE / '金融初読前の人工と独立監査.json')
    assert frozen['全合格'] and audit['全合格'] and audit['新金融'] == 0
    assert frozen['source_SHA256'] == audit['source_SHA256'] == plan.sources()
    assert frozen['source_configs'] == catalog.configs() == proposal['spec']['entry']['conditions']
    for filename, key in (('入力と保存公開の固定.json', 'input_SHA256'),
                          ('試行計画.json', 'proposal_SHA256'),
                          ('金融初読前の人工と独立監査.json', 'audit_SHA256')):
        assert plan.digest(plan.HERE / filename) == frozen[key]
    for item in audit['evidence']:
        assert plan.digest(plan.ROOT / item['path']) == item['SHA256']
    checked = plan.read(plan.HERE / '正式照合の全出力.json')
    registered = plan.read(plan.HERE / '正式登録の全出力.json')
    assert checked['終了コード'] == registered['終了コード'] == 0
    assert json.loads(checked['stdout'])['proposal_complete'] is True
    registry_path = plan.ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json'
    registry = plan.read(registry_path)
    trials = registry['trials']
    matches = [row for row in trials if row['id'] == catalog.TRIAL_ID]
    assert len(matches) == 1 and matches[0]['spec'] == proposal['spec']
    fixed = plan.read(plan.HERE / '入力と保存公開の固定.json')
    assert fixed['全合格'] and len(fixed['inputs']) == 66
    assert len(fixed['sessions']) == len(set(fixed['sessions'])) == 33
    actual = [(row['raw']['session'], row['raw']['symbol']) for row in fixed['inputs']]
    assert len(set(actual)) == 66 and set(actual) == {(s, y) for s in fixed['sessions'] for y in catalog.CAP}
    assert proposal['spec']['data']['inputs'] == plan.registration_inputs(fixed)
    assert proposal['spec']['data']['sessions'] == fixed['sessions']
    assert proposal['spec']['implementation'] == plan.sources()
    assert frozen['実行予定'] == dict(原NPZ=66, 保存eventNPZ=66, 新金融口座=792, 原板=0, API=0)
    return fixed, frozen

# ----------------------------------------


def save_ledger(daily: dict, path: Path) -> dict:
    """
    機能: 実注文・親・脚・途中状態の全欄を可逆曲線だけ圧縮して保存する。
    引数: daily(dict)、path(Path) は実再生結果と新規保存位置。
    返り値: dict は出力目録。未知欄をゼロへ置き換えない。
    """
    assert not path.exists() and path.resolve().is_relative_to(OUT)
    kept = {k: v for k, v in daily.items() if k not in ('curve', 'price_valid_mask', 'execution_normal_mask')}
    kept['curve_rle'] = curve_pack(daily['curve'])
    raw = gzip.compress(pickle.dumps(kept, protocol=5), compresslevel=5, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return dict(path=path.relative_to(plan.ROOT).as_posix(), SHA256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def diagnose(daily: dict, arrays: dict, symbol: str) -> dict:
    """
    機能: 同時刻中値差・気配差負担・手数料の恒等式を実脚から検算する。
    引数: daily/arrays(dict)、symbol(str) は同口座と原列。
    返り値: dict は金額分解。公開後の値動きを別途二重控除しない。
    """
    mid = (arrays['bid'] + arrays['ask']) / 2
    spread = arrays['ask'] - arrays['bid']
    midpoint_gross, spread_paid = 0., 0.
    snapshots, breakdown = [], {}
    for leg in daily['actual_legs']:
        a, b, q, side = int(leg['entry_row']), int(leg['exit_row']), int(leg['q']), int(leg['side'])
        gain = side * q * catalog.VALUE[symbol] * (mid[b] - mid[a])
        burden = q * catalog.VALUE[symbol] * (spread[a] + spread[b]) / 2
        midpoint_gross += gain
        spread_paid += burden
        key = int(leg['parent'])
        if key not in breakdown:
            breakdown[key] = dict(parent=key, uid=int(leg['uid']), 中値差粗損益=0., 気配差負担=0., 手数料=0., 収支=0., legs=[])
        value = breakdown[key]
        value['中値差粗損益'] += gain
        value['気配差負担'] += burden
        value['手数料'] += leg['entry_fee_allocated'] + leg['exit_fee']
        value['収支'] += leg['net_yen']
        endpoints = dict(q=q, side=side, entry_row=a, exit_row=b)
        for label, index in (('新規', a), ('返済', b)):
            endpoints[label] = {name: primitive(arrays[name][index]) for name in (
                'raw_seq', 'price_time_s', 'bid', 'ask', 'bid_qty', 'ask_qty')}
        value['legs'].append(endpoints)
    assert abs(midpoint_gross - spread_paid - daily['summary']['費用'] - daily['summary']['収支']) < 1e-6
    for value in breakdown.values():
        assert abs(value['中値差粗損益'] - value['気配差負担'] - value['手数料'] - value['収支']) < 1e-6
    for parent in daily['parent']:
        entry = int(parent['entry_row'])
        scene = dict(parent=int(parent['parent']), uid=int(parent['uid']))
        for label, index in (('公開', int(parent['publication_row'])), ('新規', entry), ('最終返済', int(parent['exit_row']))):
            scene[label] = {name: primitive(arrays[name][index]) for name in (
                'raw_seq', 'price_time_s', 'bid', 'ask', 'bid_qty', 'ask_qty')}
        snapshots.append(scene)
    return dict(中値差粗損益=midpoint_gross, 気配差負担=spread_paid,
                手数料=daily['summary']['費用'], 収支=daily['summary']['収支'],
                snapshots=snapshots, parent_breakdown=list(breakdown.values()))


def main() -> None:
    """
    機能: 正式登録した66入力を各一回読み、十二条件792口座を再生する。
    引数: なし。
    返り値: None。失敗時はFalseを保存して停止し、自動再試行しない。
    """
    fixed, frozen = guard()
    OUT.mkdir()
    counts = dict(原NPZ=0, 保存eventNPZ=0, 新金融口座=0, 原板=0, API=0)
    configs = catalog.configs()
    rows, parents, legs, ledgers, diagnostics = [], [], [], [], []
    try:
        for number, item in enumerate(fixed['inputs'], 1):
            raw_info = item['raw']
            session, symbol = raw_info['session'], raw_info['symbol']
            arrays = load_once(raw_info, counts, '原NPZ')
            input_contract.validate(arrays, fixed['schema'])
            assert len(arrays['raw_seq']) == item['raw_rows']
            saved = load_once(item['events'], counts, '保存eventNPZ', ('events',))
            assert len(saved['events']) == item['events']['n']
            start, end = raw_info['bounds']
            signal = input_contract.signal(arrays, saved['events'], item['fields'], start, end)
            policy = {key: item['time_policy'][key] for key in (
                'entry_start_s', 'entry_end_s', 'force_start_s', 'quiet_windows')}
            policy['quiet_windows'] = np.asarray(policy['quiet_windows'], dtype=np.float64).reshape(-1, 2)
            for config in configs:
                counts['新金融口座'] += 1
                daily = engine.simulate(arrays, signal, symbol, start, end, fixed['観測T'][symbol], policy, config, finish=True)
                assert daily['completed'], dict(session=session, symbol=symbol, case=config['id'], final=daily['final_state'])
                row = metrics.account(symbol, session, daily)
                row.update(case=config['id'], counts=daily['counts'])
                rows.append(row)
                for parent in daily['parent']:
                    parents.append(dict(parent, session=session, symbol=symbol, case=config['id']))
                for leg in daily['actual_legs']:
                    legs.append(dict(leg, session=session, symbol=symbol, case=config['id']))
                ledger_path = OUT / 'ledgers' / config['id'] / (session + '_' + symbol + '.pkl.gz')
                ledgers.append(dict(session=session, symbol=symbol, case=config['id'], **save_ledger(daily, ledger_path)))
                diagnostics.append(dict(session=session, symbol=symbol, case=config['id'], **diagnose(daily, arrays, symbol)))
                del daily
            del arrays, saved, signal
            print(json.dumps(dict(進捗=number, session=session, symbol=symbol, **counts), ensure_ascii=False), flush=True)
        assert counts == frozen['実行予定'] and plan.sources() == frozen['source_SHA256']
        aggregate = {}
        for config in configs:
            name = config['id']
            rr = [r for r in rows if r['case'] == name]
            pp = [p for p in parents if p['case'] == name]
            ll = [v for v in legs if v['case'] == name]
            aggregate[name] = {symbol: metrics.periods(rr, pp, fixed['sessions'], symbol, ll) for symbol in catalog.CAP}
        result = dict(全合格=True, 金融=True, 試行=catalog.TRIAL_ID, source_SHA256=plan.sources(),
            sessions=fixed['sessions'], configs=configs, 主候補='QREVERSE_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1',
            counts=counts, rows=rows, parents=parents, actual_legs=legs, ledgers=ledgers,
            diagnostics=diagnostics, aggregate=aggregate, 時刻模型='自身rawseqとCurrentPriceTime。真受信順と実注文遅延は未証明。',
            未測定='ミニ/マイクロ実板・板列待ち・実遅延・5秒最悪条件・追加二場')
        plan.write(OUT / '結果.json', primitive(result))
        print(json.dumps(dict(全合格=True, **counts), ensure_ascii=False), flush=True)
    except BaseException as exc:
        plan.write(OUT / 'False.json', dict(全合格=False, counts=counts, 例外型=type(exc).__name__, 例外=str(exc), 自動再試行=False))
        raise


if __name__ == '__main__':
    main()
