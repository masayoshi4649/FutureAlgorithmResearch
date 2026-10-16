"""正式損益を読まず、追従候補と許可の一軸分離を保存入力で独立検算する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
ROOT = STAGE.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
spec = importlib.util.spec_from_file_location('反証95純関数読取', HERE / '38条件の入口と再参加の損益前反証.py')
PURE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PURE)


def inputs() -> dict:
    """
    機能: 正式売買を起動せず、指紋確認付きで旧板と独立LP素材だけを読む。
    引数: なし。
    返り値: dictは62口座の読み取り専用入力。旧領域へ書き込まない。
    """
    spec = importlib.util.spec_from_file_location('反証95価格入力読取', STAGE / 'data.py')
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value.load_inputs()


def permission(price: dict, execution: dict, side: int) -> np.ndarray:
    """
    機能: 正常LP方向比と旧板及び十分な逆OFIを別々に独立判定する。
    引数: price/execution(dict)、side(int)。
    返り値: ndarray[bool]は全5秒格子の許可。未知OFIは方向支持へ転用しない。
    """
    masks, rates = [], []
    for symbol in SYMBOLS:
        market, old = price['markets'][symbol], execution['markets'][symbol]
        value, window = market['current'], market['windows'][300]
        rate = side * window['ret_bp']
        rates.append(rate)
        qualified = (value['valid'] & window['source_valid'] & old['current']['valid']
            & np.isfinite(value['value']) & (value['value'] > 0) & np.isfinite(rate) & (rate > 0))
        flow = old['flow'][15]
        confirmed_reverse = (flow['source_valid'] & flow['valid'] & ~flow['missing_ofi']
            & (flow['nonzero_ofi_count'] >= 3) & np.isfinite(flow['ofi_ratio'])
            & (side * flow['ofi_ratio'] <= -.1))
        masks.append(qualified & ~confirmed_reverse)
    return masks[0] & masks[1] & (np.minimum(*rates) >= .25 * np.maximum(*rates))


def pulse(grid: np.ndarray, states: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """
    機能: 発火後は有効中立の連続区間と600秒間隔の両方を要求する独立発火器。
    引数: grid(ndarray[float])、states(ndarray[int])、valid(ndarray[bool])。
    返り値: ndarray[int8]は15秒候補。欠測と格子欠落は中立連続を壊す。
    """
    result = np.zeros(len(grid), dtype=np.int8)
    armed, neutral, last_fire = True, None, -np.inf
    for i in range(len(grid)):
        if i and grid[i] - grid[i - 1] > 15.0000001:
            neutral = None
        if not valid[i]:
            neutral = None
        elif states[i] == 0:
            if neutral is None:
                neutral = grid[i]
            armed = armed or grid[i] - neutral >= 60.
        else:
            neutral = None
            if armed and grid[i] - last_fire >= 600.:
                result[i] = states[i]
                last_fire, armed = grid[i], False
    return result


def candidate(key: tuple, material: dict, source: str, signal: dict) -> dict:
    """
    機能: LP価格条件と旧15秒両気配支持から候補を独立再構成する。
    引数: key(tuple[str,str])、material(dict)、source(str:P2/P3)、signal(dict)。
    返り値: dictはvalid/states/pulse/candidates。経済結果は計算しない。
    """
    session, symbol = key
    peer = SYMBOLS[1] if symbol == SYMBOLS[0] else SYMBOLS[0]
    prices = material['trend_prices']['I3'][session]
    grid, pos = prices['candidate_grid'], prices['candidate_positions']
    own, other = prices['markets'][symbol], prices['markets'][peer]
    valid = np.ones(len(grid), dtype=bool)
    for market in (own, other):
        current = market['current']
        valid &= current['valid'][pos] & np.isfinite(current['value'][pos])
        for seconds in (15, 300):
            window = market['windows'][seconds]
            valid &= window['source_valid'][pos] & np.isfinite(window['ratio_ret_bp'][pos])
    flow = material['grids'][session]['markets'][symbol]['flow'][15]
    valid &= (flow['source_valid'][pos] & np.isfinite(flow['bid_change_ticks'][pos])
              & np.isfinite(flow['ask_change_ticks'][pos]))
    if source == 'P2':
        valid &= material['legacy'][key]['valid']
    state = np.zeros(len(grid), dtype=np.int8)
    for i, p in enumerate(pos):
        if not valid[i]:
            continue
        for side in (-1, 1):
            if (side * own['windows'][300]['ratio_ret_bp'][p] >= 3.
                    and side * other['windows'][300]['ratio_ret_bp'][p] >= 3.
                    and side * other['windows'][15]['ratio_ret_bp'][p] >= 0
                    and side * flow['bid_change_ticks'][p] >= .99999999
                    and side * flow['ask_change_ticks'][p] >= .99999999):
                state[i] = side
    emitted = pulse(grid, state, valid)
    record, rows = material['prices'][key], []
    for g in np.flatnonzero(emitted):
        row = int(np.searchsorted(record['time_s'], grid[g], side='left'))
        if row == len(record['time_s']):
            continue
        if record['time_s'][row] > grid[g] + 10 or record['time_s'][row] >= record['limit'] - 300:
            continue
        if (not signal['quality'][row] or signal['reset'][row]
                or record['ask'][row] - record['bid'][row] > 2 * record['tick'] + 1e-9):
            continue
        rows.append([g, row, emitted[g], own['current']['index'][pos[g]], other['current']['index'][pos[g]]])
    return dict(valid=valid, states=state, pulse=emitted, candidates=np.asarray(rows, float).reshape(-1, 5))


def fixture(side: int = 1) -> dict:
    """
    機能: LP正常だが旧OFI資格が未知という人工材料を作る。
    引数: side(int)は上下反射方向。
    返り値: dictは300秒開始、5秒許可、15秒候補の最小素材。
    """
    grid = np.arange(300., 960., 5.)
    prices, old = {}, {}
    for j, symbol in enumerate(SYMBOLS):
        size = len(grid)
        prices[symbol] = dict(current=dict(index=np.arange(size) + j * 1000,
            raw_seq=np.arange(size) + j * 10000 + 17, time_s=grid - 2,
            value=np.full(size, 4000. if j == 0 else 68000.), valid=np.ones(size, bool)),
            windows={seconds: dict(source_valid=np.ones(size, bool),
                ratio_ret_bp=np.full(size, side * (4. if seconds == 300 else 1.)),
                ret_bp=np.full(size, side * (4. if seconds == 300 else 1.))) for seconds in (15, 300)})
        old[symbol] = dict(current=dict(index=np.arange(size) + j * 500, valid=np.ones(size, bool),
            q_valid=np.ones(size, bool), bid=np.full(size, 4000. if j == 0 else 68000.),
            ask=np.full(size, 4000.5 if j == 0 else 68010.)), flow={15: dict(source_valid=np.ones(size, bool),
                valid=np.zeros(size, bool), missing_ofi=np.ones(size, bool),
                nonzero_ofi_count=np.zeros(size, int), ofi_ratio=np.full(size, np.nan),
                bid_change_ticks=np.full(size, side), ask_change_ticks=np.full(size, side))})
    positions = np.arange(0, len(grid), 3)
    item = dict(grid=grid, markets=prices, candidate_positions=positions, candidate_grid=grid[positions])
    material = dict(trend_prices={'I3': {'人工': item}}, grids={'人工': dict(grid=grid, markets=old)},
        legacy={('人工', symbol): dict(valid=np.zeros(len(positions), bool)) for symbol in SYMBOLS}, prices={})
    for j, symbol in enumerate(SYMBOLS):
        tick = .5 if j == 0 else 10.
        material['prices'][('人工', symbol)] = dict(time_s=grid.copy(), limit=1800., tick=tick,
            bid=old[symbol]['current']['bid'].copy(), ask=old[symbol]['current']['ask'].copy(),
            seq=np.arange(len(grid)) + j * 10000 + 1)
    return material


def artificial(helper: dict) -> list[dict]:
    """
    機能: 未知OFI、十分逆OFI、旧板不明、比率等号を独立正負例で検査する。
    引数: helper(dict)はASTから抽出した純候補・許可関数。
    返り値: list[dict]は人工事例。新しい取引の損益を生成しない。
    """
    cases = []
    for side in (-1, 1):
        material = fixture(side)
        p = material['trend_prices']['I3']['人工']
        q = material['grids']['人工']
        yes = helper['lp_allowed'](p, q)[side]
        assert yes.all(), '未知OFIは反対支持でなく逆証拠の不存在です'
        for symbol in SYMBOLS:
            key = '人工', symbol
            record = material['prices'][key]
            signal = dict(quality=np.ones(len(record['time_s']), bool), reset=np.zeros(len(record['time_s']), bool))
            two = helper['lp_candidates'](key, material, 'P2', signal)
            three = helper['lp_candidates'](key, material, 'P3', signal)
            assert not two['valid'].any() and len(two['candidates']) == 0
            assert three['valid'].all() and three['pulse'][0] == side and len(three['candidates']) == 1
            for name in ('states', 'valid', 'pulse', 'candidates'):
                np.testing.assert_array_equal(three[name], candidate(key, material, 'P3', signal)[name])
            cases.append({'人工': '旧OFI資格不明を価格へ伝播しない_P2とP3を区別', '方向': side,
                '商品': symbol, 'P2候補': 0, 'P3候補': 1, '未知OFIを支持へ転用': False})
            delayed = deepcopy(material)
            delayed['legacy'][key]['valid'][:] = True
            delayed['legacy'][key]['valid'][0] = False
            d2 = helper['lp_candidates'](key, delayed, 'P2', signal)
            d3 = helper['lp_candidates'](key, delayed, 'P3', signal)
            assert d2['candidates'][0, 0] == 1 and d3['candidates'][0, 0] == 0
            assert d2['pulse'][1] == side and d3['pulse'][1] == 0
            cases.append({'人工': '有効資格を増やすと既存候補も移動_候補集合は部分集合でない',
                '方向': side, '商品': symbol, 'P2最初候補秒': 315, 'P3最初候補秒': 300})
            failed_map = dict(signal, quality=signal['quality'].copy())
            failed_map['quality'][0] = False
            consumed = helper['lp_candidates'](key, material, 'P3', failed_map)
            assert consumed['pulse'][0] == side and len(consumed['candidates']) == 0
            cases.append({'人工': '最初写像の執行資格が不正でも次15秒候補へ返却しない',
                '方向': side, '商品': symbol, '発火': 1, '写像候補': 0})
        reverse = deepcopy(material)
        flow = reverse['grids']['人工']['markets']['TOPIX']['flow'][15]
        flow.update(valid=np.ones(len(p['grid']), bool), missing_ofi=np.zeros(len(p['grid']), bool),
            nonzero_ofi_count=np.full(len(p['grid']), 3), ofi_ratio=np.full(len(p['grid']), -.1 * side))
        assert not helper['lp_allowed'](p, reverse['grids']['人工'])[side].any()
        cases.append({'人工': 'OFI十分逆証拠の3回及び0.1等号を拒否', '方向': side, '受理': False})
        flow['nonzero_ofi_count'][:] = 2
        assert helper['lp_allowed'](p, reverse['grids']['人工'])[side].all()
        cases.append({'人工': 'OFI2回は十分逆証拠としない', '方向': side, '受理': True})
        unknown = deepcopy(material)
        unknown['grids']['人工']['markets']['NK225']['current']['valid'][:] = False
        assert not helper['lp_allowed'](p, unknown['grids']['人工'])[side].any()
        cases.append({'人工': 'LP正常でも相手の旧執行気配不明を救済しない', '方向': side, '受理': False})
        ratio = deepcopy(p)
        ratio['markets']['TOPIX']['windows'][300]['ret_bp'][:] = side
        assert helper['lp_allowed'](ratio, q)[side].all()
        ratio['markets']['TOPIX']['windows'][300]['ret_bp'][:] = side * .999999
        assert not helper['lp_allowed'](ratio, q)[side].any()
        cases.append({'人工': '弱強比0.25等号は受理_直下は拒否', '方向': side, '境界合格': True})
    return cases


def main() -> None:
    """
    機能: 全62の入力・価格窓・純候補と許可を反証し新レビューJSONへ保存する。
    引数: なし。
    返り値: None。正式P/L、選定結果、注文実行は読まない。
    """
    paths = [STAGE / name for name in ('catalog.py', 'data.py', 'prepare_prices.py', 'strategy.py', 'engine.py')]
    paths += [STAGE / 'prepared/metadata.json', STAGE / 'prepared/trend_prices.pkl', Path(__file__), Path(PURE.__file__)]
    before = {str(path.relative_to(ROOT)): PURE.sha(path) for path in paths}
    helper = PURE.functions(STAGE / 'strategy.py', ('event_pulses', 'quote_valid', 'lp_allowed', 'lp_candidates', 'loss_observations'))
    cases = artificial(helper)
    material = inputs()
    rows, windows, permission_rows, states_checked = [], 0, 0, 0
    raw_differences, different_clocks, rescued, blocked = 0, 0, 0, 0
    for session, p in material['trend_prices']['I3'].items():
        q = material['grids'][session]
        np.testing.assert_array_equal(p['grid'][p['candidate_positions']], p['candidate_grid'])
        computed = helper['lp_allowed'](p, q)
        for side in (-1, 1):
            np.testing.assert_array_equal(computed[side], permission(p, q, side))
            permission_rows += len(p['grid'])
        for symbol in SYMBOLS:
            key = session, symbol
            raw, record = material['raw_last_records'][key], material['prices'][key]
            current = p['markets'][symbol]['current']
            now, good = current['index'], current['valid']
            assert np.all(raw['time_s'][now[good]] < p['grid'][good] - 1.)
            np.testing.assert_array_equal(raw['seq'][now[good]], current['raw_seq'][good])
            np.testing.assert_array_equal(raw['last'][now[good]], current['value'][good])
            for window in p['markets'][symbol]['windows'].values():
                valid, index, previous = window['source_valid'], window['now'], window['old']
                expected = np.full(len(valid), np.nan)
                expected[valid] = (raw['last'][index[valid]] / raw['last'][previous[valid]] - 1.) * 10000.
                np.testing.assert_array_equal(expected, window['ratio_ret_bp'])
                assert np.all(index[valid] > previous[valid])
                windows += len(valid)
            mapped = material['execution_lp_index'][key]
            np.testing.assert_array_equal(raw['seq'][mapped], record['seq'])
            np.testing.assert_array_equal(raw['time_s'][mapped], record['time_s'])
            signal = dict(quality=material['features'][key]['quality'], reset=material['features'][key]['reset'])
            own = helper['loss_observations'](key, material)
            own_ok = own[:, 18:].all(axis=1)
            raw_differences += int(np.sum(own_ok & (own[:, 1] != own[:, 11])))
            different_clocks += int(np.sum(own_ok & (own[:, 2] != own[:, 12])))
            candidates = {}
            for source in ('P2', 'P3'):
                actual = helper['lp_candidates'](key, material, source, signal)
                oracle = candidate(key, material, source, signal)
                for name in ('states', 'valid', 'pulse', 'candidates'):
                    np.testing.assert_array_equal(actual[name], oracle[name])
                states_checked += len(actual['states'])
                candidates[source] = actual
            extra = candidates['P3']['valid'] & ~candidates['P2']['valid']
            rescued += int(extra.sum())
            blocked += int(np.sum(extra & (candidates['P3']['states'] == 0)))
            rows.append({'場': session, '商品': symbol, 'LP5秒現在格子': len(now),
                'P2価格候補': len(candidates['P2']['candidates']), 'P3価格候補': len(candidates['P3']['candidates']),
                '旧資格から独立した有効15秒格子': int(extra.sum()),
                '復旧しても方向状態なし': int(np.sum(extra & (candidates['P3']['states'] == 0)))})
        print(f'{session}: 独立候補・許可・別源の損益前反証を確認', flush=True)
    after = {str(path.relative_to(ROOT)): PURE.sha(path) for path in paths}
    assert before == after, '検査中に実装又は入力が変化しました。最新SHAで再実行が必要です。'
    out = dict(段階='95の保存入力による純特徴・純候補検算。新正式損益未参照。',
        全合格=True, 口座数=len(rows), 人工数=len(cases), 人工=cases, 全62入力=rows,
        価格窓演算全格子数=windows, 許可全方向格子数=permission_rows, 候補全状態格子数=states_checked,
        四源正常だが自己BBOとLPの原seq相違格子=raw_differences,
        四源正常だが自己BBOとLPの時計相違格子=different_clocks,
        独立資格で復旧した候補格子=rescued, 復旧しても方向状態なし=blocked,
        結論='価格観測を正常化しても新規方向条件に達しない格子がある。候補数増加は正の期待値の証拠ではない。候補は原seq/LPindexと旧執行indexを別々に保持する。',
        SHA256=before, 正式95損益実行=0, 正式95損益閲覧=0, API取得=0, 実注文=0)
    target = HERE / '全62入力の正常LP追従候補と旧板資格の独立反証.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    assert len(rows) == 62 and json.loads(target.read_text(encoding='utf-8'))['全合格']
    print('全62入力の純候補と許可を独立検算。新正式P/L0。', flush=True)


if __name__ == '__main__':
    main()
