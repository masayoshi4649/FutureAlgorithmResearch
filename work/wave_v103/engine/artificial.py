"""raw入口と旧固定1枚出口の接続を、人工だけで検査する。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

import adapter


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def fixture(symbol: str, side: int) -> tuple[dict, dict, float]:
    """
    機能: 正常なflat人工板と旧入口に不利な偽支持を作る。
    引数: symbol(str)、side(int)。
    返り値: tuple[dict,dict,float]。正式raw、旧損益又は現在APIを開かない。
    """
    base, tick = (4000., .5) if symbol == 'TOPIX' else (50000., 10.)
    size = 2301
    times = np.arange(size, dtype=float)
    bid, ask = np.full(size, base), np.full(size, base + tick)
    record = dict(symbol=symbol, time_s=times, seq=np.arange(size, dtype=np.int64) + 1000,
        price=.5 * (bid + ask), bid=bid, ask=ask, price_valid=np.ones(size, bool),
        quote_valid=np.ones(size, bool), tick=tick, start=0., limit=2300., end=2400., 人工素材=True)
    grid = np.arange(300., 2305., 5.)
    mapped = np.full(size, -1, np.int32)
    mapped[grid[grid < size].astype(int)] = np.arange(len(grid[grid < size]), dtype=np.int32)
    signal = dict(grid=grid, mapped=mapped, quality=np.ones(size, bool), reset=np.zeros(size, bool),
        event=np.zeros(size, np.int8), mode=np.full(len(grid), -side, np.int8),
        trend_width=max(2, math.ceil(base * .004 / tick - 1e-10)) * tick,
        entry_j2_long=np.zeros(len(grid), bool), entry_j2_short=np.zeros(len(grid), bool),
        wait_opposite_long=np.ones(len(grid), bool), wait_opposite_short=np.ones(len(grid), bool))
    return record, signal, base


def run(record: dict, signal: dict, opening: float, config: dict, row: int, side: int,
        quality: np.ndarray | None = None, reset: np.ndarray | None = None) -> dict:
    """
    機能: 一つの人工判断pulseを当時の行へ接続し、旧Python出口で再生する。
    引数: record/signal/config(dict)、opening(float)、row/side(int)、quality/reset(ndarray[bool]|None)。
    返り値: dict。raw予測の正答率又は収益性を評価する検査ではない。
    """
    size = len(record['time_s'])
    event = np.zeros(size, np.int8)
    event[row] = side
    q = np.ones(size, bool) if quality is None else quality
    r = np.zeros(size, bool) if reset is None else reset
    connected = adapter.signal_for_raw(record, signal, event, q, r, opening, config)
    return adapter.play_artificial(record, connected, config)


def main() -> None:
    """
    機能: 両商品買売で旧入口の二重filter、次正常約定、遅れた準備と期限を検査する。
    引数: なし。
    返り値: None。人工接続だけ。正式金融、全raw又は現在APIは実行しない。
    """
    refs = [Path(__file__), HERE / 'adapter.py', ROOT / 'work/wave_v102/engine.py', ROOT / 'work/wave_v102/catalog.py']
    beginning = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    previous = adapter.reference_config()
    config = adapter.raw_config(previous)
    changed = {key for key in set(previous) | set(config) if previous.get(key) != config.get(key)}
    assert changed == {'entry_wait_kind', 'entry_clock_policy', 'entry_price_cap_multiple', 'entry_bbo_confirm', 'entry_support_lane', 'entry_source'}
    counts = dict(旧支持が逆でも新pulseで予約=0, 次正常quoteだけで実約定=0,
        予約後の資格悪化で取消しない=0, 遅い準備は遅い行で判断=0,
        quote不明pulseは予約されない=0, 不明後の正常行で新判断なら予約=0,
        入口cutの取消は実fillより先=0, 旧即時quantity診断の差を確認=0,
        同1枚同S同D同30分同料金=0)
    examples = []
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            record, signal, opening = fixture(symbol, side)
            direct = run(record, signal, opening, config, 330, side)
            assert direct['orders'][0, 1] == 330 and direct['orders'][0, 0] == 331
            assert direct['orders'][0, 5] == direct['trades'][0, 5] == 1
            assert direct['orders'][0, 6] == record['ask' if side == 1 else 'bid'][331]
            counts['旧支持が逆でも新pulseで予約'] += 1
            value, unit = (1000., 41.8) if symbol == 'TOPIX' else (10., 11.)
            width = max(2, math.ceil(opening * .001 / record['tick'] - 1e-10)) * record['tick']
            parent = direct['trend_parent_diagnostics'][0]
            assert parent[6] == width and parent[7] == signal['trend_width']
            assert direct['orders'][1, 1] == 2131 and direct['orders'][1, 0] == 2132
            assert direct['trades'][0, 13] == 3
            assert direct['orders'][0, 9] == direct['orders'][1, 9] == math.floor(unit + 1e-8)
            counts['同1枚同S同D同30分同料金'] += 1
            assert direct['entry_parent_diagnostics'][0, 8] == (8 if symbol == 'TOPIX' else 16)
            counts['旧即時quantity診断の差を確認'] += 1

            # ----------------------------------------
            # 予約後は次正常quoteまで待ち、支持や品質の事後悪化だけでは巻戻さない。
            gap = deepcopy(record)
            gap['quote_valid'][331:340] = False
            bad_quality, bad_reset = np.ones(len(gap['time_s']), bool), np.zeros(len(gap['time_s']), bool)
            bad_quality[331:] = False
            bad_reset[331:] = True
            delayed = run(gap, signal, opening, config, 330, side, bad_quality, bad_reset)
            assert delayed['orders'][0, 0] == 340 and delayed['orders'][0, 1] == 330
            counts['次正常quoteだけで実約定'] += 1
            counts['予約後の資格悪化で取消しない'] += 1
            late = run(record, signal, opening, config, 350, side)
            assert late['orders'][0, 1] == 350 and late['orders'][0, 0] == 351
            counts['遅い準備は遅い行で判断'] += 1

            # ----------------------------------------
            # quote不明の一回pulseは将来へ移さず、正常行の新判断と区別する。
            invalid = deepcopy(record)
            invalid['quote_valid'][330:340] = False
            rejected = run(invalid, signal, opening, config, 330, side)
            assert not len(rejected['orders'])
            counts['quote不明pulseは予約されない'] += 1
            rechecked = run(invalid, signal, opening, config, 340, side)
            assert rechecked['orders'][0, 1] == 340 and rechecked['orders'][0, 0] == 341
            counts['不明後の正常行で新判断なら予約'] += 1

            # ----------------------------------------
            # 新規cutで取消を先行させ、場末近くの未来の正常quoteへ予約を繰越さない。
            cutoff = run(record, signal, opening, config, 1999, side)
            assert not len(cutoff['orders'])
            assert np.any(cutoff['events'][:, 3] == 6)
            counts['入口cutの取消は実fillより先'] += 1
            examples.append(dict(商品=symbol, 方向=side, 判断原行=330, 実fill原行=331,
                遅延fill原行=340, 準備遅延判断原行=350, 準備遅延fill原行=351,
                実数量=1, 旧quantity診断=int(direct['entry_parent_diagnostics'][0, 8]),
                初期幅=width, 追尾幅=signal['trend_width'], 初回実fillから期限秒=1800))
    ending = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    assert beginning == ending
    proof = dict(全合格=True, 検査件数=counts, 接続例=examples,
        変更設定=sorted(changed), 旧金融本体変更=0, 全raw読取=0, 正式金融再生=0,
        API取得=0, 実注文=0, 開始終端SHA一致=True, 開始SHA256=beginning, SHA256=ending,
        限界='即時入口のold45親quantity欄は旧8/16枠の診断。実注文/実親は1枚。正式連携では別のraw入口診断で実1枚を照合し、旧欄を正答へ使わない。共通の開始後300秒/返済後30秒/新規cutは保持。')
    target = HERE / '新raw入口と旧固定1枚出口の人工接続.json'
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key not in ('SHA256', '開始SHA256')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
