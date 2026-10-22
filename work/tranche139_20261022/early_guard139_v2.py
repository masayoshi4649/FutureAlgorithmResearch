"""早期候補の確定損失回数、管理幅、指標時刻の静観を独立に比較する。"""

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from common139 import force_parent, product
import engine139_native
from run_early139 import settings as early_settings


def settings():
    """
    機能: 二つの固定入口に五つの損失抑制と夜間静観を組み合わせる。
    引数: なし。
    返り値: list[dict]は計十二条件。入口自体の閾値と候補列は変更しない。
    """
    sources = {c['id']: c for c in early_settings()}
    policies = [
        ('L1', '1敗で早期停止', dict(max_early_losses=1, risk_scale=1., initial_only=False, event_gap=False)),
        ('L2', '2敗で早期停止', dict(max_early_losses=2, risk_scale=1., initial_only=False, event_gap=False)),
        ('W2', '管理幅2倍', dict(max_early_losses=0, risk_scale=2., initial_only=False, event_gap=False)),
        ('W2L2', '管理幅2倍・2敗停止', dict(max_early_losses=2, risk_scale=2., initial_only=False, event_gap=False)),
        ('L2S1', '初回1枚だけ・2敗停止', dict(max_early_losses=2, risk_scale=1., initial_only=True, event_gap=False)),
        ('L2G', '2敗停止・夜の米国指標時計を静観', dict(max_early_losses=2, risk_scale=1., initial_only=False, event_gap=True)),
    ]
    return [dict(id=source + '_' + suffix, source=source, name=source + '／' + name,
                 entry=copy.deepcopy(sources[source]['entry']), management=copy.deepcopy(sources[source]['management']),
                 guard=copy.deepcopy(policy))
            for source in ('E01', 'E15') for suffix, name, policy in policies]


def _gap(ready, enabled):
    """
    機能: 既知の早期終了時計から、夜間だけ米国08:30相当の前後十五分を決める。
    引数: ready(dict)はwindow_start/window_end、enabled(bool)は静観比較の指定。
    返り値: tuple[float,float]は開始・終了UNIX秒。対象外は正の無限大。
    """
    night = datetime.fromtimestamp(float(ready['window_start']), ZoneInfo('Asia/Tokyo')).hour == 17
    if enabled and night:
        end = float(ready['window_end'])
        return end - 3600., end - 1800.
    return np.inf, np.inf


def joined(base, candidates, ready, management, symbol, guard=None):
    """
    機能: 早期親の確定損失を時系列で数え、通常担当を残して早期新規だけを止める。
    引数: base/candidates(ndarray)、ready/management(dict)、symbol(str)、guard(dict/None)。
          max_early_lossesは累積損失親数の上限で0は無制限。risk_scaleは管理Rだけを拡大する。
          initial_onlyは初回一枚だけ、event_gapは夜の指標時計帯を静観する。
    返り値: tuple[ndarray,list[dict]]は十列注文と見送り理由。当時確定済み損失数を記録する。
    """
    policy = dict(max_early_losses=0, risk_scale=1., initial_only=False, event_gap=False)
    if guard:
        policy.update(guard)
    limit = int(policy['max_early_losses'])
    scale = float(policy['risk_scale'])
    assert limit >= 0 and scale > 0. and np.isfinite(scale)
    config = copy.deepcopy(management)
    config.update(product(symbol))
    config['risk_floor'] *= scale
    if policy['initial_only']:
        config.update(initial=1, adaptive=False, target=1, increments=[], steps=[], recycle_rounds=0)
    risk_atr = np.asarray(ready['atr']) * scale
    times = ready['time_s']
    gap_start, gap_end = _gap(ready, bool(policy['event_gap']))
    queue = []
    for pid in np.unique(base[:, 2]) if len(base) else []:
        rows = base[base[:, 2] == pid]
        assert not (20000 <= pid < 1000000), '通常担当と早期担当の親IDを分離してください。'
        queue.append((int(rows[0, 1]), '通常', rows))
    for first in candidates:
        row = first.copy()
        row[2] += 20000
        assert 20000 <= row[2] < 1000000, '早期担当の親IDは専用範囲内へ限定してください。'
        queue.append((int(row[1]), '早期', row.reshape(1, -1)))
    parts = []
    skips = []
    last = -1
    loss_count = 0
    pending_outcome = None
    for decision, kind, rows in sorted(queue, key=lambda x: (x[0], 0 if x[1] == '通常' else 1)):
        metadata = dict(parent=int(rows[0, 2]), kind=kind, decision=decision,
                        active_until=last, early_losses=loss_count,
                        gap_start=None if not np.isfinite(gap_start) else gap_start,
                        gap_end=None if not np.isfinite(gap_end) else gap_end)
        # 保有中は、まだ未来にある親の最終損益を損失回数へ加えない。
        if decision < last:
            skips.append(dict(metadata, reason='保有中'))
            continue
        if pending_outcome is not None:
            assert decision >= pending_outcome['exit']
            if pending_outcome['net'] < 0.:
                loss_count += 1
            pending_outcome = None
        metadata['early_losses'] = loss_count
        if kind == '早期':
            when = float(times[decision])
            if limit > 0 and loss_count >= limit:
                skips.append(dict(metadata, reason='早期損失回数の上限'))
                continue
            if gap_start <= when < gap_end:
                skips.append(dict(metadata, reason='米国指標時計帯の静観'))
                continue
            end = float(ready['window_end'])
            if when < gap_start:
                end = min(end, gap_start)
            # 既知の静観境界へ届いた時点で、まだ約定していない新規予約を取り消す模型。
            if float(times[int(rows[0, 0])]) >= end:
                skips.append(dict(metadata, reason='静観又は終了境界で未約定新規を取消', cancel_time=end))
                continue
            source = force_parent(rows[0], times, ready['quotes'], end)
            orders = engine139_native.replay(times, ready['quotes'], risk_atr, ready['market'], ready['phase'], source, config)
            if len(orders):
                mult = float(config['multiplier'])
                net = float(np.sum(-orders[:, 3] * orders[:, 4] * orders[:, 5] * mult - orders[:, 9]))
                pending_outcome = dict(exit=int(orders[-1, 0]), net=net)
        else:
            orders = rows
        if len(orders):
            last = int(orders[-1, 0])
            parts.append(orders)
    output = np.concatenate(parts) if parts else np.empty((0, 10))
    return (output[np.argsort(output[:, 0], kind='stable')] if len(output) else output), skips
