"""119v7保存注文だけを会計し、既所有気配の共同snapshotと独立照合する。"""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import math
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
V7 = HERE.parent
BASE = V7.parent
ROOT = BASE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / "audit_result119"))
import saved_accounting as audit

READS = dict(結果=0, 組cache=0, 脚cache=0, 既所有prepared=0, 原市場=0, 原cache追加=0, 金融再実行=0)
ORDER = ['parent', 'leg', 'kind', 'side', 'quantity', 'decision_time', 'fill_time', 'raw_row', 'price', 'fee', 'reason', 'reference_price', 'reference_quote_time', 'wait_seconds']
PARENT = ['parent', 'complete', 'side_nk', 'decision_time', 'exit_decision_time', 'reason', 'beta', 'center', 'sigma', 'entry_delta', 'cash_loss_budget', 'estimated_roundtrip_cost', 'target_quantity_nk', 'target_quantity_top', 'entry_nk', 'entry_top', 'exit_nk', 'exit_top', 'entry_time_nk', 'entry_time_top', 'exit_time_nk', 'exit_time_top', 'gross_nk', 'gross_top', 'fees_nk', 'fees_top', 'net_nk', 'net_top', 'net', 'filled_legs', 'single_leg_seconds', 'maximum_single_leg_notional', 'maximum_held_quote_age', 'entry_hedge_error', 'actual_entry_hedge_error', 'mfe_liquidation_net', 'mae_liquidation_net']
CURVE = ['time', 'realized', 'unrealized_after_close_fees', 'equity', 'quantity_nk', 'quantity_top', 'quote_age_nk', 'quote_age_top', 'active_parent', 'armed', 'drawdown', 'unclosed_legs']
MODEL = ['time', 'known', 'beta', 'center', 'sigma', 'delta', 'quantity_nk', 'quantity_top', 'hedge_error', 'qualification_move_gross', 'estimated_roundtrip_cost', 'candidate_side_nk', 'accepted', 'quote_age_nk', 'quote_age_top', 'armed', 'busy']
SYMBOLS = ('NK225', 'TOPIX')
MULTIPLIERS = np.asarray([10., 1000.])
FEES = np.asarray([11., 41.8])
CAPS = np.asarray([20, 10])


# ----------------------------------------


def write(path: Path, value: dict) -> dict:
    """
    機能: 所有領域に新規の有限JSONを保存し指紋を返す。
    引数: path(Path) は保存先、value(dict) は監査資料。
    返り値: dict はpath・bytes・SHA256。既存証跡は上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=len(payload), SHA256=audit.sha(payload))


def load_arrays(info: dict, destination: Path | None = None, owned: bool = False) -> dict:
    """
    機能: 固定した保存cacheを一読し同bytes保全後に配列を展開する。
    引数: info(dict) は指紋と位置、destination(Path|None) は新保全先、owned(bool) は旧所有入力。
    返り値: dict[str,ndarray]。原市場又は売買エンジンを読み込まない。
    """
    path = ROOT / info['owned_path' if owned else 'path']
    expected_area = BASE / 'audit_result119/recovered_owned/prepared' if owned else V7 / 'measurement'
    audit.check(path.resolve().is_relative_to(expected_area), '読取領域拘束')
    before = path.stat()
    payload = path.read_bytes()
    after = path.stat()
    audit.check((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), '読取前後不変')
    audit.check(len(payload) == info['bytes'] and audit.sha(payload) == info['SHA256'], '保存cache同bytes')
    if destination is not None:
        assert not destination.exists()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    with np.load(BytesIO(payload), allow_pickle=False) as saved:
        return {key: saved[key].copy() for key in saved.files}


def independent_pair(arrays: dict, quotes: tuple[dict, dict], saved: dict, close_time: float, exit_mode: int = 0) -> dict:
    """
    機能: 保存注文から二脚の現金・保有・全snapshot資産と親会計を独立復元する。
    引数: arrays(dict) は一条件の注文/親/曲線/モデル、quotes(tuple[dict,dict])、saved(dict)、close_time(float)。
    返り値: dict は独立集計。金融条件の再生及び新たな候補選択は行わない。
    """
    orders, parents, curve, models = (arrays[key] for key in ('orders', 'parents', 'curve', 'models'))
    audit.check(orders.ndim == 2 and orders.shape[1] == 14 and parents.ndim == 2 and parents.shape[1] == 37, '注文14/親37列')
    audit.check(curve.shape == (len(models), 12) and models.shape[1] == 17, '曲線12/モデル17列')
    audit.check(np.isfinite(orders[:, :11]).all() and np.isfinite(orders[:, 13]).all(), '注文必須欄は有限')
    audit.check(np.isin(orders[:, 1], [0, 1]).all() and np.isin(orders[:, 2], [1, 2]).all()
                and np.isin(orders[:, 3], [-1, 1]).all(), '脚・注文種別・売買符号')
    audit.check(np.all(orders[:, 6] > orders[:, 5]) and np.all(np.diff(orders[:, 6]) >= 0), 'strict後時計と注文先後')
    audit.near(orders[:, 13], orders[:, 6] - orders[:, 5], '注文待ち秒数')
    audit.check(np.all(orders[:, 4] > 0) and np.all(orders[:, 4] <= CAPS[orders[:, 1].astype(int)]), '注文数量上限')
    audit.near(orders[:, 4], np.rint(orders[:, 4]), '注文整数枚数')
    audit.near(orders[:, 9], np.floor(orders[:, 4] * FEES[orders[:, 1].astype(int)] + 1e-9), '各注文費用切捨て')
    audit.check(len(np.unique(parents[:, 0])) == len(parents) and set(orders[:, 0]) == set(parents[:, 0]), '注文と親の対象一致')
    grid = np.unique(np.concatenate((quotes[0]['time'], quotes[1]['time'], curve[:, 0])))
    n = len(grid)
    cash_delta, position_delta, basis_delta = (np.zeros((n, 2)) for _ in range(3))
    last_bid, last_ask, ages = (np.full((n, 2), np.nan) for _ in range(3))
    for leg, q in enumerate(quotes):
        qi = np.searchsorted(q['time'], grid, side='right') - 1
        known = qi >= 0
        last_bid[known, leg], last_ask[known, leg] = q['bid'][qi[known]], q['ask'][qi[known]]
        ages[known, leg] = grid[known] - q['time'][qi[known]]
    total_gross, total_fees = np.zeros(2), np.zeros(2)
    parent_expected = []
    for parent in parents:
        pid, complete, direction = int(parent[0]), int(parent[1]), int(parent[2])
        own = orders[orders[:, 0] == pid]
        audit.check(complete in (0, 1) and direction in (-1, 1), '親の完結と方向')
        lineage = models[models[:, 0] == parent[3]]
        audit.check(len(lineage) == 1 and lineage[0, 12] == 1, '親は当時受理された公開モデルに対応')
        m = lineage[0]
        audit.near(parent[6:14], [m[2], m[3], m[4], m[5], m[9] if exit_mode == 0 else m[9] / 2., m[10], m[6], m[7]], '親の固定モデルと当時数量の系譜')
        audit.near(parent[[2, 33]], m[[11, 8]], '親の方向と入口ヘッジ端数の系譜')
        references = [int(np.searchsorted(q['time'], parent[3], side='right')) - 1 for q in quotes]
        audit.check(all(k >= 0 and 0 <= parent[3] - q['time'][k] <= 5. for k, q in zip(references, quotes)), '組受理は両脚とも当時5秒以内')
        ref_last = [q['last'][k] for k, q in zip(references, quotes)]
        ref_width = [q['ask'][k] - q['bid'][k] for k, q in zip(references, quotes)]
        delta = math.log(ref_last[0]) - parent[6] * math.log(ref_last[1]) - parent[7]
        goal = (abs(delta) if exit_mode == 0 else 2. * parent[8]) * parent[12] * 10. * ref_last[0]
        estimated = float(2. * sum(np.floor(parent[12:14] * FEES + 1e-9)) + sum(parent[12:14] * MULTIPLIERS * ref_width))
        a, b = parent[6] * parent[12] * 10. * ref_last[0], parent[13] * 1000. * ref_last[1]
        error = abs(a - b) / ((a + b) / 2.)
        audit.near(parent[[9, 10, 11, 33]], [delta, goal if exit_mode == 0 else goal / 2., estimated, error], '受理時の残差・予定額・予定費用・元本差')
        audit.check(abs(delta) >= 2. * parent[8] - 1e-12 and goal >= 3. * estimated - 1e-7 and error <= .05 + 1e-12, '保存受理の乖離・費用・整数ヘッジ資格')
        gross, fees, closed, entry_prices, exit_prices = np.zeros(2), np.zeros(2), np.zeros(2, int), np.full(2, np.nan), np.full(2, np.nan)
        entry_times, exit_times = np.full(2, np.nan), np.full(2, np.nan)
        actual_count = 0
        for leg, q in enumerate(quotes):
            leg_orders = own[own[:, 1] == leg]
            entries = leg_orders[leg_orders[:, 2] == 1]
            exits = leg_orders[leg_orders[:, 2] == 2]
            audit.check(len(entries) <= 1 and len(exits) <= len(entries), '一親一脚の新規返済各一回')
            fees[leg] = sum(leg_orders[:, 9])
            total_fees[leg] += fees[leg]
            for order in leg_orders:
                qi = int(np.searchsorted(q['row'], int(order[7])))
                audit.check(qi < len(q['row']) and q['row'][qi] == order[7], '注文は当該脚正常原rowに存在')
                audit.near(order[6], q['time'][qi], 'fill時計は実気配時計')
                audit.near(order[8], q['ask'][qi] if order[3] == 1 else q['bid'][qi], '買ask/売bid約定')
                first_after = int(np.searchsorted(q['time'], order[5], side='right'))
                audit.check(qi == first_after, '各脚は判断後の最初のstrict時計気配')
            if not len(entries):
                continue
            actual_count += 1
            first = entries[0]
            entry_prices[leg], entry_times[leg] = first[8], first[6]
            side = direction if leg == 0 else -direction
            audit.near(first[3], side, '親の逆方向二脚')
            audit.near(first[4], parent[12 + leg], '親の当初整数数量を固定')
            audit.near(first[5], parent[3], '新規判断は親予約時刻')
            audit.check(first[6] < parent[3] + 60. and first[6] < close_time, '新規の60秒期限と場末取消')
            reference = int(np.searchsorted(q['time'], parent[3], side='right')) - 1
            audit.check(reference >= 0 and 0 <= parent[3] - q['time'][reference] <= 5., '新規判断の両脚鮮度')
            audit.near(first[11:13], [q['last'][reference], q['time'][reference]], '予約参照は当時までのLastと時計')
            k = int(np.searchsorted(grid, first[6]))
            cash_delta[k, leg] -= first[9]
            position_delta[k, leg] += side * first[4]
            basis_delta[k, leg] += side * first[4] * first[8]
            if len(exits):
                last = exits[0]
                audit.near(last[3:5], [-side, first[4]], '各脚全量を反対方向へ返済')
                audit.near(last[5], parent[4], '返済判断は親固定時計')
                audit.check(last[6] > first[6], '各脚返済の原時刻先後')
                audit.near(last[10], parent[5], '親と返済の理由一致')
                exit_prices[leg], exit_times[leg], closed[leg] = last[8], last[6], int(last[4])
                gross[leg] = side * (last[8] - first[8]) * first[4] * MULTIPLIERS[leg]
                k = int(np.searchsorted(grid, last[6]))
                cash_delta[k, leg] += gross[leg] - last[9]
                position_delta[k, leg] -= side * first[4]
                basis_delta[k, leg] -= side * first[4] * first[8]
        audit.near(parent[14:22], np.concatenate((entry_prices, exit_prices, entry_times, exit_times)), '親の脚別建値返済値と時刻')
        audit.near(parent[22:26], np.concatenate((gross, fees)), '親の脚別grossと実支払費用')
        audit.near(parent[29], actual_count, '親の実約定脚数')
        if actual_count == 2:
            a, b = parent[6] * parent[12] * 10. * entry_prices[0], parent[13] * 1000. * entry_prices[1]
            audit.near(parent[34], abs(a - b) / ((a + b) / 2.), '実非同時建値のヘッジ端数')
        else:
            audit.check(np.isnan(parent[34]), '片脚の実ヘッジ誤差を中立としない')
        if complete:
            audit.check(sum(closed > 0) == actual_count, '完結親は全約定脚を返済済み')
            net = gross - fees
            audit.near(parent[26:29], [net[0], net[1], sum(net)], '完結親の脚別と組純損益')
        total_gross += gross
        parent_expected.append(dict(parent=parent, gross=gross, fees=fees))
    cash = np.cumsum(cash_delta, axis=0)
    position = np.cumsum(position_delta, axis=0)
    basis = np.cumsum(basis_delta, axis=0)
    audit.check(np.all(np.abs(position) <= CAPS), '全共同snapshotの実保有上限')
    liquidation = np.where(position > 0, last_bid, last_ask)
    unrealized = np.where(position != 0, (position * liquidation - basis) * MULTIPLIERS
                          - np.floor(np.abs(position) * FEES + 1e-9), 0.)
    equity = cash.sum(axis=1) + unrealized.sum(axis=1)
    peak = np.maximum.accumulate(np.r_[0., equity])[1:]
    drawdown = peak - equity
    if len(curve):
        k = np.searchsorted(grid, curve[:, 0])
        audit.near(curve[:, 1], cash[k].sum(axis=1), '毎分の全脚実現現金')
        audit.near(curve[:, 2], unrealized[k].sum(axis=1), '毎分の返済費込み含み損益')
        audit.near(curve[:, 3], equity[k], '毎分の清算評価資産')
        audit.near(curve[:, 4:6], position[k], '毎分の整数保有と方向')
        audit.near(curve[:, 6:8], ages[k], '毎分の当時正常気配年齢')
        audit.near(curve[:, 10], drawdown[k], '毎分で観測された全snapshot由来DD')
        audit.near(curve[:, 11], np.count_nonzero(position[k], axis=1), '毎分の未返済脚数')
        audit.near(arrays['positions'], position[k], '公開positionsと実注文保有')
        audit.near(models[:, 0], curve[:, 0], 'モデルと毎分曲線時計一致')
        audit.near(models[:, 13:15], ages[k], 'モデル判断時の気配年齢')
    for info in parent_expected:
        parent = info['parent']
        begin = int(np.searchsorted(grid, parent[3]))
        terminal = np.nanmax(parent[20:22]) if parent[1] else grid[-1]
        end = int(np.searchsorted(grid, terminal, side='right'))
        base_cash = cash[begin].sum()
        parent_net = equity[begin:end] - base_cash
        audit.near(parent[35:37], [max(0., max(parent_net)), min(0., min(parent_net))], '親の共同snapshot MFE/MAE')
        pos = position[begin:end]
        isolated = np.count_nonzero(pos, axis=1) == 1
        clocks = grid[begin:end]
        duration = float(np.sum(np.diff(clocks) * isolated[:-1]))
        nominal = np.abs(pos) * MULTIPLIERS * (last_bid[begin:end] + last_ask[begin:end]) / 2.
        maximum_nominal = float(np.max(np.where(isolated[:, None], nominal, 0.)))
        maximum_age = float(np.max(np.where(pos != 0, ages[begin:end], 0.)))
        audit.near(parent[30:33], [duration, maximum_nominal, maximum_age], '親の孤立実秒・最大元本・保有気配年齢')
    closed_parents = parents[parents[:, 1] == 1.]
    final_cash = cash[-1] if n else np.zeros(2)
    final_unrealized = unrealized[-1] if n else np.zeros(2)
    final_position = position[-1] if n else np.zeros(2)
    nets = closed_parents[:, 28]
    entries = orders[orders[:, 2] == 1]
    exits = orders[orders[:, 2] == 2]
    attempts = int(np.count_nonzero(models[:, 12]))
    pending = int(saved['pending_entries'])
    account = dict(net=float(sum(final_cash + final_unrealized)), realized=float(sum(final_cash)),
        profit=float(sum(np.maximum(nets, 0.))), loss=float(sum(np.maximum(-nets, 0.))), parents=len(nets),
        wins=int(np.count_nonzero(nets > 1e-7)), losses=int(np.count_nonzero(nets < -1e-7)),
        fees=float(sum(total_fees)), unclosed=int(sum(np.abs(final_position))),
        max_drawdown=float(max(drawdown)) if n else 0., fills=len(orders), closed_quantity=int(sum(exits[:, 4])),
        attempts=attempts, no_fill_attempts=attempts - len(parents), canceled=2 * attempts - len(entries) - pending,
        halted=5 if n and grid[-1] >= close_time else 0,
        paired_parents=int(np.count_nonzero(closed_parents[:, 29] == 2)),
        aborted_parents=int(np.count_nonzero(closed_parents[:, 29] == 1)),
        single_leg_seconds=float(sum(parents[:, 30])), max_single_leg_notional=float(max(parents[:, 31])) if len(parents) else 0.,
        expected_close_fees=float(sum(np.floor(np.abs(final_position) * FEES + 1e-9))))
    audit.compare_mapping(saved, account, '組口座の全注文独立会計')
    audit.check(account['unclosed'] == pending == 0 and np.all(parents[:, 1] == 1.), '未清算又は予約待機を成功扱いしない')
    for leg, symbol in enumerate(SYMBOLS):
        own = orders[orders[:, 1] == leg]
        expected = dict(gross=float(total_gross[leg]), fees=float(total_fees[leg]), realized=float(final_cash[leg]),
            unrealized_after_close_fees=float(final_unrealized[leg]), net=float(final_cash[leg] + final_unrealized[leg]),
            fills=len(own), entry_quantity=int(sum(own[own[:, 2] == 1., 4])), closed_quantity=int(sum(own[own[:, 2] == 2., 4])),
            unclosed=int(abs(final_position[leg])))
        audit.compare_mapping(saved['legs'][symbol], expected, '各脚の全注文会計')
    return account


def decomposition(parents: np.ndarray, saved: dict) -> None:
    """
    機能: 完結二脚の相対損益と共通元本差の保存恒等式を独立照合する。
    引数: parents(ndarray[:,37]) は保存親、saved(dict) は保存診断。
    返り値: None。会計分解を原因又は予測成功の証拠にしない。
    """
    audit.check(len(saved['parents']) == len(parents), '診断親数一致')
    totals = dict(paired_parents=0, single_leg_parents=0, unclosed_parents=0,
        relative_gross=0., common_gross=0., paired_gross=0., paired_fees=0., paired_net=0.,
        single_leg_gross=0., single_leg_fees=0., single_leg_net=0.)
    for parent, given in zip(parents, saved['parents']):
        gross, fees, net = sum(parent[22:24]), sum(parent[24:26]), parent[28]
        audit.near(given['parent'], parent[0], '診断親ID')
        for key, amount in (('gross', gross), ('fees', fees), ('net', net)):
            audit.near(given[key], amount, '診断会計:' + key)
        paired = parent[1] == 1 and parent[29] == 2
        if paired:
            a, b = parent[12] * 10. * parent[14], parent[13] * 1000. * parent[15]
            rn, rt = parent[16] / parent[14] - 1., parent[17] / parent[15] - 1.
            relative = parent[2] * a * (rn - parent[6] * rt)
            common = parent[2] * (parent[6] * a - b) * rt
            audit.near([given['relative_gross'], given['common_gross']], [relative, common], '相対と共通元本差分解')
            audit.near(relative + common, gross, '分解grossの恒等式')
            totals['paired_parents'] += 1
            for key, amount in (('relative_gross', relative), ('common_gross', common), ('paired_gross', gross), ('paired_fees', fees), ('paired_net', net)):
                totals[key] += amount
        else:
            audit.check(given['relative_gross'] is given['common_gross'] is None, '単脚又は未清算の二要因を推測しない')
            if parent[1]:
                totals['single_leg_parents'] += 1
                for key, amount in (('single_leg_gross', gross), ('single_leg_fees', fees), ('single_leg_net', net)):
                    totals[key] += amount
            else:
                totals['unclosed_parents'] += 1
    audit.compare_mapping(saved['totals'], totals, '全親の分解合計')


# ----------------------------------------


def main(expected_sha: str) -> None:
    """
    機能: 根の指定SHA後に結果と120cacheを一読保全し、320組全会計を照合する。
    引数: expected_sha(str) は完成後に根が指定した結果指紋。
    返り値: None。原市場・旧原cache追加・金融再生及び候補の再選択は0。
    """
    audit.check(len(expected_sha) == 64, '根の完成SHA必須')
    owned = HERE / 'owned'
    owned.mkdir(exist_ok=False)
    payload = (V7 / 'measurement/相対的な強さの継続と残差追尾の全四十場.json').read_bytes()
    READS['結果'] += 1
    audit.check(audit.sha(payload) == expected_sha, '完成結果同bytes')
    (owned / '完成結果.json').write_bytes(payload)
    result = json.loads(payload.decode('utf-8'))
    fixed = json.loads((V7 / '固定計画.json').read_text(encoding='utf-8'))
    manifest_bytes = (ROOT / fixed['input_manifest']['path']).read_bytes()
    audit.check(audit.sha(manifest_bytes) == fixed['input_manifest']['sha256'], '正式目録一致')
    manifest = json.loads(manifest_bytes.decode('utf-8'))
    (owned / '事前入力目録.json').write_bytes(manifest_bytes)
    audit.check(result['source_SHA256'] == fixed['sources'], '固定源と結果一致')
    for path, sha in fixed['sources'].items():
        audit.check(audit.sha((ROOT / path).read_bytes()) == sha, '経済源不変')
    audit.check(result['columns'] == dict(orders=ORDER, parents=PARENT, curve=CURVE, models=MODEL), '保存列名の固定接口')
    audit.check(result['sessions'] == manifest['sessions'] and len(set(result['sessions'])) == 40
                and result['specs'] == manifest['specs'] and len(result['specs']) == 8, '固定40場8条件')
    audit.check(result['原市場追加読取'] == result['API'] == result['実注文'] == 0, '原市場/API/実注文0')
    lookup = {(r['session'], r['method']): r for r in result['runs']}
    episodes = {(r['session'], r['method']): r for r in result['episodes']}
    diagnostics = {(r['session'], r['method']): r for r in result['diagnostics']}
    audit.check(len(lookup) == len(episodes) == len(diagnostics) == len(result['runs']) == 320, '320組全行重複なし')
    input_lookup = {(r['session'], r['symbol']): r for r in manifest['inputs']}
    leg_lookup = {(r['session'], r['symbol']): r for r in result['leg_cache']}
    audit.check(len(result['cache']) == 40 and len(leg_lookup) == len(result['leg_cache']) == len(result['reads']) == 80, '40組cacheと80脚cache')
    audit.check({r['session'] for r in result['cache']} == set(result['sessions']) and len(input_lookup) == 80,
                '組cache40場と入力80組の欠落なし')
    for read in result['reads']:
        prior = input_lookup[read['session'], read['symbol']]
        audit.check(read['path'] == prior['owned_path'] and read['SHA256'] == prior['SHA256']
                    and read['original_market_reads'] == 0, '元入力を追加読取しない保存由来')
    certificates = []
    for info in result['cache']:
        scene = info['session']
        pair = load_arrays(info, owned / 'PAIR' / (scene + '.npz'))
        READS['組cache'] += 1
        material, legs = {}, {}
        for symbol in SYMBOLS:
            material[symbol] = load_arrays(input_lookup[scene, symbol], owned=True)
            READS['既所有prepared'] += 1
            legs[symbol] = load_arrays(leg_lookup[scene, symbol], owned / symbol / (scene + '.npz'))
            READS['脚cache'] += 1
        quotes = tuple({key[8:]: value for key, value in material[symbol].items() if key.startswith('quotes__')} for symbol in SYMBOLS)
        from datetime import datetime, timedelta, timezone
        day = datetime.fromisoformat(scene[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
        close_time = (day + (timedelta(days=1, hours=5, minutes=40) if scene.endswith('_Night') else timedelta(hours=15, minutes=20))).timestamp()
        for spec in result['specs']:
            ident = spec['id']
            arrays = {key: pair[ident + '__' + key] for key in ('orders', 'parents', 'curve', 'models', 'positions')}
            saved = lookup[scene, ident]
            independent_pair(arrays, quotes, saved, close_time, spec['exit_mode'])
            episode = episodes[scene, ident]
            audit.near(np.asarray([[np.nan if x is None else x for x in row] for row in episode['orders']]).reshape((-1, 14)), arrays['orders'], 'JSONとNPZ全注文同値')
            audit.near(np.asarray([[np.nan if x is None else x for x in row] for row in episode['parents']]).reshape((-1, 37)), arrays['parents'], 'JSONとNPZ全親同値')
            decomposition(arrays['parents'], diagnostics[scene, ident])
            audit.check(episode['diagnostics'] == {k: v for k, v in diagnostics[scene, ident].items() if k not in ('session', 'symbol', 'method')}, '親診断の重複保存同値')
            for leg, symbol in enumerate(SYMBOLS):
                audit.near(legs[symbol][ident + '__orders'], arrays['orders'][arrays['orders'][:, 1] == leg], '各脚cacheは全注文の完全射影')
        certificates.append(dict(session=scene, 八条件会計一致=True, 未清算=0))
        print(json.dumps(dict(場=len(certificates), session=scene, 検査数=audit.CHECKS), ensure_ascii=False), flush=True)
    metrics = [dict(method=spec['id'], periods={name: audit.metrics([lookup[scene, spec['id']] for scene in scenes])
        for name, scenes in result['splits'].items()}) for spec in result['specs']]
    audit.check(READS == dict(結果=1, 組cache=40, 脚cache=80, 既所有prepared=80, 原市場=0, 原cache追加=0, 金融再実行=0), '許可範囲一読のみ')
    metrics_meta = write(HERE / '八条件と全四十場の独立指標.json', dict(結果SHA256=expected_sha, metrics=metrics))
    write(HERE / '二脚全三百二十組の注文親会計と共同snapshotの独立監査.json', dict(全合格=True,
        検査数=audit.CHECKS, counts=READS, 結果SHA256=expected_sha, source_SHA256=fixed['sources'],
        監査源SHA256=audit.sha(Path(__file__).read_bytes()), 未清算=0, 未清算成功扱い=False, outputs=[metrics_meta], 場別確認=certificates,
        曲線終点='毎分curveとEOF実現現金は別。全注文から最終現金を照合し、DDは全共同snapshotから計算。',
        限界='同じ保存会計の独立整合監査。金融再実行0・原市場追加0・新しい有効性標本0。未清算又は予約未消化は成功扱いしない。'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args()
    try:
        main(args.expected_sha)
    except BaseException as exc:
        write(HERE / 'False.json', dict(全合格=False, counts=READS, 検査数=audit.CHECKS, 型=type(exc).__name__, 例外=str(exc)))
        raise
