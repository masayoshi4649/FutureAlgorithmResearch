"""元影の価格順行だけで、既存悪化入力の利用開始を制限する。"""

from __future__ import annotations

import numpy as np
from numba import njit

THRESHOLDS = (0., 1., 1.2, 1.5, 1.8, 2.)
MODES = ('direction', 'inverse', 'any_valid')
PLAN_COLUMNS = {'direction': 0, 'campaign': 1, 'initial_atr': 2, 'anchor': 3,
                'entry_row': 5, 'extreme': 10, 'plan_source_row': 33}
REASONS = {0: '元値の恒等出力', 1: '影が非保有', 2: '現在価格が無効',
           3: '初回尺度又は価格根拠が無効', 4: '未到達', 5: '到達後の新公開を待つ',
           6: '方向が中立', 7: '有効な自市場公開ではない', 8: '悪化入力を通過'}


@njit(cache=True)
def _walk(price, plans, bad, source, valid, threshold, mode):
    """機能: 過去から一回走査し、組別の初回到達と元公開根拠を記録する。

    引数: price/plans/bad/source/valid (ndarray)、threshold (float)、mode (int)。
    返り値: 出力方向と、組・到達・順行・許可・理由の配列 (tuple)。
    """
    n = len(price)
    output = np.zeros(n, np.int8)
    campaigns = np.full(n, -1, np.int64)
    arm_rows = np.full(n, -1, np.int64)
    mfe = np.full(n, np.nan)
    armed = np.zeros(n, np.bool_)
    eligible = np.zeros(n, np.bool_)
    reason = np.full(n, 1, np.int8)
    group = -1; entry = -1; arm = -1
    for i in range(n):
        direction = int(plans[i, 0])
        if direction == 0:
            group = -1; entry = -1; arm = -1
            continue
        current = int(plans[i, 1]); current_entry = int(plans[i, 5])
        if current != group or current_entry != entry:
            group = current; entry = current_entry; arm = -1
        campaigns[i] = group; arm_rows[i] = arm; armed[i] = arm >= 0
        if not np.isfinite(price[i]) or price[i] <= 0:
            reason[i] = 2
            continue
        initial_atr = plans[i, 2]; anchor = plans[i, 3]; extreme = plans[i, 10]
        if (not np.isfinite(initial_atr) or initial_atr <= 0 or not np.isfinite(anchor)
                or anchor <= 0 or not np.isfinite(extreme) or extreme <= 0):
            reason[i] = 3
            continue
        mfe[i] = direction * (extreme - anchor) / initial_atr
        if arm < 0 and mfe[i] >= threshold:
            arm = i
        arm_rows[i] = arm; armed[i] = arm >= 0
        if arm < 0:
            reason[i] = 4
            continue
        if source[i] <= arm:
            reason[i] = 5
            continue
        if mode == 2:
            if not valid[i]:
                reason[i] = 7
                continue
            output[i] = -direction
        else:
            output[i] = bad[i] if mode == 0 else -bad[i]
        eligible[i] = True
        reason[i] = 8 if output[i] else 6
    return output, campaigns, arm_rows, mfe, armed, eligible, reason


def gate_bad(ready: dict, shadow: dict, bad: np.ndarray, bad_source: np.ndarray,
             threshold_atr: float, *, mode: str = 'direction',
             valid: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    """機能: 初回ATRの順行到達後、新公開の悪化方向だけを旧注文器へ渡す。

    引数: ready/shadow (dict)、bad (整数ndarray[n])、bad_source (整数ndarray[n])、
    threshold_atr (float: 0/1/1.2/1.5/1.8/2)、mode (str: direction/inverse/any_valid)、
    valid (bool ndarray[n]又はNone)。any_validだけvalidが必須。
    返り値: 方向(int8[n])、元公開行(int64[n])、当行までの証拠(dict[str,ndarray])。
    sourceは遮断時も変更しない。0閾値はdirectionだけで両元値を恒等出力する。
    影・実口座・売買規則は変更せず、新しい売買も再生しない。
    """
    if not np.isfinite(threshold_atr) or float(threshold_atr) not in THRESHOLDS:
        raise ValueError('未定義の価格順行閾値です')
    if mode not in MODES or (threshold_atr == 0 and mode != 'direction'):
        raise ValueError('閾値0はdirectionの恒等対照だけです')
    price = np.asarray(ready['last'])
    n = len(price)
    if price.ndim != 1:
        raise ValueError('原本価格は一次元です')
    for name, value in (('bad', bad), ('bad_source', bad_source)):
        if not isinstance(value, np.ndarray) or value.shape != (n,) or value.dtype.kind not in 'iu':
            raise ValueError(name + 'は原本行対応の整数配列が必要です')
    if not np.isin(bad, (-1, 0, 1)).all():
        raise ValueError('悪化方向は-1/0/1だけです')
    if np.any(bad_source < -1) or np.any(bad_source > np.arange(n)) or np.any((bad != 0) & (bad_source < 0)):
        raise ValueError('公開根拠の行が無効又は未来です')
    if valid is not None and (not isinstance(valid, np.ndarray) or valid.shape != (n,) or valid.dtype != np.bool_):
        raise ValueError('公開有効列は原本行対応のbool配列です')
    if mode == 'any_valid' and valid is None:
        raise ValueError('方向を除いた対照にも公開品質列が必要です')
    if valid is None:
        valid = np.zeros(n, np.bool_)
    # ----------------------------------------
    # 旧対照は影の生存や追加品質条件で元方向を削らない。
    if threshold_atr == 0:
        evidence = dict(campaign=np.full(n, -1, np.int64), arm_row=np.full(n, -1, np.int64),
                        mfe_atr=np.full(n, np.nan), armed=np.zeros(n, np.bool_),
                        eligible=np.ones(n, np.bool_), reason=np.zeros(n, np.int8))
        return bad.astype(np.int8, copy=True), bad_source.astype(np.int64, copy=True), evidence
    plans = np.asarray(shadow['plans'])
    if plans.shape != (n, 37) or plans.dtype.kind != 'f':
        raise ValueError('影の全37列計画が原本行に対応していません')
    directions = plans[:, 0]
    if not np.isfinite(directions).all() or not np.isin(directions, (-1., 0., 1.)).all():
        raise ValueError('影方向の定義が不正です')
    held = directions != 0
    for column in (1, 5):
        values = plans[held, column]
        if not np.isfinite(values).all() or np.any(values < 0) or np.any(values != np.floor(values)):
            raise ValueError('生存組の識別子又は開始行が不正です')
    if np.any(plans[held, 5] > np.flatnonzero(held)):
        raise ValueError('影の開始行が未来です')
    active_sources = plans[held, 33]
    if (not np.isfinite(active_sources).all() or np.any(active_sources < 0)
            or np.any(active_sources != np.floor(active_sources))
            or np.any(active_sources > np.flatnonzero(held))):
        raise ValueError('影の情報公開行が未来又は不正です')
    result = _walk(np.asarray(price, dtype=float), plans, bad, bad_source, valid,
                   float(threshold_atr), MODES.index(mode))
    evidence = dict(zip(('campaign', 'arm_row', 'mfe_atr', 'armed', 'eligible', 'reason'), result[1:]))
    return result[0], bad_source.astype(np.int64, copy=True), evidence
