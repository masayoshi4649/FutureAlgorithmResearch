"""独立LP現在値と300秒窓、旧気配資格と15秒OFIから支持だけを再計算する。"""

import math
import hashlib

import numpy as np


def basis(key: tuple[str, str], material: dict, value: dict) -> np.ndarray:
    """
    機能: LP原源と旧BBO原源を別々に読取り、59列の輸送を独立構成する。
    引数: key(tuple[str,str])、material/value(dict)は入力素材と旧信号。
    返り値: ndarray[float64]。対象support_basis、対象許可、実台帳を呼ばない。
    既存I3の窓生成は94/95で検証済みの不変入力で、ここでは新支持への接続を検査する。
    """
    session, own = key
    peer = 'NK225' if own == 'TOPIX' else 'TOPIX'
    price, execution = material['trend_prices']['I3'][session], material['grids'][session]
    signal, grid = value['signal'], value['signal']['grid']
    np.testing.assert_array_equal(grid, price['grid'])
    np.testing.assert_array_equal(grid, execution['grid'])
    allowed = lp_allowed(price, execution)
    output = np.full((len(grid), 59), np.nan)
    output[:, 0], output[:, 1], output[:, 2] = np.arange(len(grid)), grid, 0
    for column, array in ((3, signal['entry_j2_long']), (4, signal['entry_j2_short']),
                          (5, allowed[1]), (6, allowed[-1]),
                          (7, signal['entry_j2_long']), (8, signal['entry_j2_short'])):
        output[:, column] = array
    for offset, symbol in ((11, own), (35, peer)):
        current, window = price['markets'][symbol]['current'], price['markets'][symbol]['windows'][300]
        raw, old_market = material['raw_last_records'][session, symbol], execution['markets'][symbol]
        old, now = window['old'], current['index']
        assert ((old >= -1) & (old < len(raw['last']))).all()
        assert ((now >= -1) & (now < len(raw['last']))).all()
        block = output[:, offset:offset + 24]
        block[:, 0], block[:, 5] = now, old
        block[:, 1], block[:, 6] = -1, -1
        block[:, 4], block[:, 9] = current['valid'], False
        for indexes, columns in ((now, (1, 2, 3)), (old, (6, 7, 8))):
            known = indexes >= 0
            source = indexes[known]
            for column, field in zip(columns, ('seq', 'time_s', 'last')):
                block[known, column] = raw[field][source]
        np.testing.assert_array_equal(block[:, 1], current['raw_seq'])
        np.testing.assert_array_equal(block[:, 2], current['time_s'])
        np.testing.assert_array_equal(block[:, 3], current['value'])
        np.testing.assert_array_equal(block[:, 6], window['old_seq'])
        np.testing.assert_array_equal(block[:, 7], window['old_time_s'])
        np.testing.assert_array_equal(block[:, 8], window['old_value'])
        known = old >= 0
        source = old[known]
        block[known, 9] = raw['valid'][source] & np.isfinite(raw['last'][source]) & (raw['last'][source] > 0) & np.isfinite(raw['time_s'][source])
        for column, field in ((10, 'source_valid'), (11, 'ret_bp'), (12, 'reset_or_invalid_cross'), (13, 'actual_seconds')):
            block[:, column] = window[field]
        block[:, 14], block[:, 15] = old_market['windows'][300]['source_valid'], old_market['windows'][300]['ret_bp']
        if 'prices' in material:
            bbo = old_market['current']
            record = material['prices'][session, symbol]
            indexes = bbo['index']
            block[:, 16], block[:, 17] = indexes, -1
            known = indexes >= 0
            block[known, 17] = record['seq'][indexes[known]]
            block[known, 18] = record['time_s'][indexes[known]]
            block[:, 19], block[:, 20] = bbo['bid'], bbo['ask']
        elif symbol == own:
            # ----------------------------------------
            # 人工相手には独立原時計系列がないため、公開peer原素材の範囲を明示して検査する。
            record = value['record']
            indexes = now
            known = indexes >= 0
            block[:, 16], block[:, 17] = indexes, -1
            block[known, 17] = record['seq'][indexes[known]]
            block[known, 18] = record['time_s'][indexes[known]]
            block[known, 19], block[known, 20] = record['bid'][indexes[known]], record['ask'][indexes[known]]
        else:
            block[:, 16:21] = signal['entry_peer_bbo'][:, :5]
        block[:, 21] = old_market['current']['valid']
        flow = old_market['flow'][15]
        for row in range(len(grid)):
            ratio = float(flow['ofi_ratio'][row])
            block[row, 22] = bool(flow['source_valid'][row] and flow['valid'][row]
                and not flow['missing_ofi'][row] and flow['nonzero_ofi_count'][row] >= 3 and math.isfinite(ratio))
            block[row, 23] = ratio
    output[np.isinf(output)] = np.nan
    return output


def verify_material(key: tuple[str, str], material: dict, value: dict) -> dict:
    """
    機能: 原素材から独立再構成した支持と59列を、準備済み新接続へ公差0照合する。
    引数: key(tuple[str,str])、material/value(dict)。
    返り値: dict。格子・市場源・支持列の検査件数。窓不明を単点正常で救済しない。
    """
    expected = basis(key, material, value)
    np.testing.assert_array_equal(expected, value['entry_support_base'])
    allowed = lp_allowed(material['trend_prices']['I3'][key[0]], material['grids'][key[0]])
    transported = from_basis(expected)
    for side in (-1, 1):
        np.testing.assert_array_equal(allowed[side], value['trend_lp_allowed'][side])
        np.testing.assert_array_equal(transported[side], allowed[side])
    return dict(支持格子=len(expected), 別市場源=2 * len(expected), 支持判定=2 * len(expected))


def lp_allowed(price: dict, execution: dict) -> dict[int, np.ndarray]:
    """
    機能: 対象実装を呼ばず、一格子ずつ両市場のLP方向・強弱比・逆OFIを判定する。
    引数: price(dict)は独立I3価格格子、execution(dict)は旧気配/OFI格子。
    返り値: dict[int,ndarray[bool]]。方向−1/+1の支持列。旧mid不明を反対へ置換しない。
    """
    np.testing.assert_array_equal(price['grid'], execution['grid'])
    result = {side: np.zeros(len(price['grid']), bool) for side in (-1, 1)}
    for grid_index in range(len(price['grid'])):
        for side in (-1, 1):
            progress, allowed = [], True
            for symbol in ('TOPIX', 'NK225'):
                market, old = price['markets'][symbol], execution['markets'][symbol]
                current, window, flow = market['current'], market['windows'][300], old['flow'][15]
                value, change = float(current['value'][grid_index]), side * float(window['ret_bp'][grid_index])
                qualified = bool(old['current']['valid'][grid_index] and current['valid'][grid_index]
                    and math.isfinite(value) and value > 0 and window['source_valid'][grid_index]
                    and math.isfinite(change) and change > 0)
                if not qualified:
                    allowed = False
                progress.append(change)
                ratio = float(flow['ofi_ratio'][grid_index])
                sufficient = bool(flow['source_valid'][grid_index] and flow['valid'][grid_index]
                    and not flow['missing_ofi'][grid_index] and flow['nonzero_ofi_count'][grid_index] >= 3
                    and math.isfinite(ratio))
                if sufficient and side * ratio <= -.1:
                    allowed = False
            if not (min(progress) >= .25 * max(progress)):
                allowed = False
            result[side][grid_index] = allowed
    return result


def from_basis(basis: np.ndarray) -> dict[int, np.ndarray]:
    """
    機能: 59列の原支持素材部分だけから許可を再計算し、target許可ヘッダを使わない。
    引数: basis(ndarray[float])は格子とLP/BBO/OFIの別原資格。
    返り値: dict[int,ndarray[bool]]。L1支持列。
    """
    assert basis.ndim == 2 and basis.shape[1] == 59
    result = {side: np.zeros(len(basis), bool) for side in (-1, 1)}
    for row in range(len(basis)):
        for side in (-1, 1):
            progresses, yes = [], True
            for start in (11, 35):
                market = basis[row, start:start + 24]
                progress = side * market[11]
                qualifies = (market[21] == 1 and market[4] == 1 and math.isfinite(market[3])
                    and market[3] > 0 and market[10] == 1 and math.isfinite(progress) and progress > 0)
                yes = yes and qualifies
                progresses.append(progress)
                if market[22] == 1 and side * market[23] <= -.1:
                    yes = False
            result[side][row] = bool(yes and min(progresses) >= .25 * max(progresses))
    return result


def selected(value: dict, config: dict) -> tuple[dict, dict[int, np.ndarray]]:
    """
    機能: 旧信号を変更せず、独立再計算したL1支持だけを局所コピーへ接続する。
    引数: value(dict)は共通prepared、config(dict)は支持源条件。
    返り値: tuple[dict,dict]。局所signalと独立LP支持。共有配列を書き換えない。
    """
    signal = dict(value['signal'])
    allowed = from_basis(value['entry_support_base'])
    for side in (-1, 1):
        np.testing.assert_array_equal(allowed[side], value['trend_lp_allowed'][side])
    if config['entry_support_lane'] == 'L1':
        signal['entry_j2_long'], signal['entry_j2_short'] = allowed[1], allowed[-1]
    return signal, allowed


def verify_trace(value: dict, config: dict, signal: dict, allowed: dict, actual: dict) -> None:
    """
    機能: 公表済み格子59列と実支持2列の指紋を、独立支持の選択へ照合する。
    引数: value/config/signal/allowed/actual(dict)。
    返り値: None。未来格子の追加又はLP/BBO源混合は例外で止める。
    """
    mapped = value['signal']['mapped']
    seen = np.unique(mapped[mapped >= 0])
    expected = value['entry_support_base'][seen].copy()
    expected[:, 2] = config['entry_support_lane'] == 'L1'
    expected[:, 3], expected[:, 4] = value['signal']['entry_j2_long'][seen], value['signal']['entry_j2_short'][seen]
    expected[:, 5], expected[:, 6] = allowed[1][seen], allowed[-1][seen]
    expected[:, 7], expected[:, 8] = signal['entry_j2_long'][seen], signal['entry_j2_short'][seen]
    expected[:, 9], expected[:, 10] = config['entry_wait_kind'], int(config['entry_clock_policy'][1])
    np.testing.assert_array_equal(actual['entry_support_state_trace'], expected)
    for name in ('entry_j2_long', 'entry_j2_short'):
        assert actual['entry_support_input_SHA256'][name] == hashlib.sha256(signal[name].tobytes()).hexdigest()
