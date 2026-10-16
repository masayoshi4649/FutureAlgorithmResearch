"""追加旧G0監査を小人工だけで検査する。正式追加場は読まない。"""

from copy import deepcopy
import os
from pathlib import Path
import sys

import numpy as np


os.environ['NUMBA_DISABLE_JIT'] = '1'
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WAVE = HERE.parents[1]
ROOT = WAVE.parents[1]


def load(name: str, path: Path) -> object:
    """
    機能: 人工を渡す監査と旧実装の小sourceだけを読取接続する。
    引数: name(str)、path(Path)は固有名とソース。
    返り値: object。JIT保存と正式素材読取は行わない。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def fixture(symbol: str, side: int, name: str) -> tuple[dict, dict, dict]:
    """
    機能: 候補待機、相手時計、取消、通常返済、forceを持つ小さい正常行を作る。
    引数: symbol(str)、side(int)、name(str)は商品、方向、境界名。
    返り値: tuple[dict,dict,dict]は物理record、元信号、監査用完全prepared。
    """
    tick, reference = (.5, 1000.) if symbol == 'TOPIX' else (10., 10000.)
    times = [300., 301., 302., 303., 304., 305., 400., 700., 940., 941., 1000.]
    # ----------------------------------------
    # 符号座標で支持と反転を作り、買売の境界を同じ形にする。
    offsets = [0., 1., 2., 2., 1., 0., -1., -1., -1., -1., -1.]
    if name == '初期停止':
        offsets = [0., 1., 2., -1., -2., -2., -2., -2., -2., -2., -2.]
    elif name == '追尾返済':
        offsets = [0., 1., 2., 10., 5., 4., 4., 4., 4., 4., 4.]
    elif name in ('候補期限', 'force返済', '候補取消reset', '候補取消quote', '相手未確認'):
        offsets = [0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0.]
        if name == 'force返済':
            offsets[1:] = [1.]*10
    elif name == '保有期限':
        times = [300., 301., 302., 303., 304., 305., 2101., 2102., 2140., 2141., 2200.]
        offsets[1:] = [1.]*10
    n = len(times)
    center = reference+side*np.array(offsets)*tick
    bid, ask = center.copy(), center+tick
    record = dict(symbol=symbol, session='追加旧入口人工', tick=tick, start=0., end=float(times[-1]), limit=float(times[-1]),
        time_s=np.array(times), seq=np.arange(100, 100+n, dtype=np.int64), price=(bid+ask)/2,
        bid=bid, ask=ask, quote_valid=np.ones(n, bool), price_valid=np.ones(n, bool))
    event = np.zeros(n, np.int8)
    event[0] = side
    if name == '受付後取消':
        times[1], record['time_s'][1] = 700., 700.
    signal = dict(grid=np.array(times), mapped=np.arange(n), mode=np.zeros(n, np.int8), event=event,
        quality=np.ones(n, bool), reset=np.zeros(n, bool), trend_width=max(2*tick, reference*.004),
        trend_initial_stop_width=max(2*tick, reference*.001),
        entry_wait_width=max(2*tick, reference*.001), entry_advance_width=0., entry_pullback_width=0., entry_recovery_width=0.,
        entry_j2_long=np.ones(n, bool), entry_j2_short=np.ones(n, bool), wait_opposite_long=np.zeros(n, bool),
        wait_opposite_short=np.zeros(n, bool), peer_tick=tick,
        entry_peer_bbo=np.column_stack((np.arange(n), np.arange(200, 200+n), np.array(times)-.1, bid, ask, np.ones(n))))
    if name == '候補取消reset':
        signal['reset'][1] = True
    if name == '候補取消quote':
        record['quote_valid'][1] = False
    if name == '相手未確認':
        signal['entry_peer_bbo'][:, 5] = 0
    if name == '未知から基準復帰':
        signal['entry_peer_bbo'][0, 5] = 0
    if name == '予約後quote不明':
        record['quote_valid'][2] = False
    prepared = dict(record=record, signal=signal, reference_open=reference,
        trend_lp_allowed={1: signal['entry_j2_long'], -1: signal['entry_j2_short']})
    return record, signal, prepared


def main() -> None:
    """
    機能: 私有人工で旧待機占有・元候補・料金・時価・旧停止の検算を確認する。
    引数: なし。
    返り値: None。人工合格と最終source結合計画を別保存する。
    """
    audit = load('104追加旧入口の人工監査', HERE/'追加Dayの旧入口と全台帳を独立監査する.py')
    engine = load('追加旧入口人工だけの102執行', ROOT/'work/wave_v102/engine.py')
    catalog = load('追加旧入口人工の固定設定', ROOT/'work/wave_v102/catalog.py')
    cfg = next(value for value in catalog.catalog() if value['id'] == 'G0_Q1_X1')
    checked, rejected, cancellations, parents = 0, 0, 0, 0
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            for name in ('初期停止', '追尾返済', '候補期限', 'force返済', '保有期限', '候補取消reset',
                '候補取消quote', '相手未確認', '未知から基準復帰', '予約後quote不明'):
                record, signal, prepared = fixture(symbol, side, name)
                ledger = engine.execute(record, signal, cfg)
                ledger.update(entry_id=None, exit_id='OLD_G0', configured_quantity=1, raw_entry_diagnostics=[])
                qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask']) & (record['bid'] > 0)&(record['ask'] > record['bid'])
                context = dict(symbol=symbol, record=record, prepared=prepared, qok=qok, good=np.flatnonzero(qok),
                    last=np.maximum.accumulate(np.where(qok, np.arange(len(qok)), -1)))
                try:
                    result = audit.legacy_audit(ledger, context)
                except AssertionError:
                    number = 1
                    while (HERE/f'追加旧監査人工False_{number:05d}.json').exists():
                        number += 1
                    audit.save(HERE/f'追加旧監査人工False_{number:05d}.json', dict(全合格=False, 人工専用=True,
                        銘柄=symbol, 方向=side, 人工条件=name, 完了人工口座=checked,
                        注文=ledger['orders'].tolist(), source_SHA256=audit.own_sources(),
                        新packet読取=0, 新正式金融読取=0, 原本読取=0, NPZ読取=0))
                    raise
                assert result['campaigns'] == len(ledger['trades'])
                audit.equal(result['net'], ledger['stats'][15], '人工最終現金')
                checked += 1
                cancellations += int(np.sum(ledger['entry_wait_events'][:, 1] == 3))
                parents += len(ledger['trades'])
                if len(ledger['orders']) and symbol == 'TOPIX' and side == 1 and name == '初期停止':
                    for field in ('fee', 'trace', 'curve', '元候補', '元trigger'):
                        changed = deepcopy(ledger)
                        if field == 'fee':
                            changed['orders'][0, 9] += 1
                        elif field == 'trace':
                            changed['target_trace'][0, 4] += 1
                        elif field == 'curve':
                            changed['curve'][2] += 1
                        elif field == '元候補':
                            changed['entry_parent_diagnostics'][0, 3] += 1
                        else:
                            changed['entry_wait_events'][changed['entry_wait_events'][:, 1] == 8, 53] = 0
                        try:
                            audit.legacy_audit(changed, context)
                        except AssertionError:
                            rejected += 1
                        else:
                            raise AssertionError('人工破損を拒否しませんでした。'+field)
    assert checked == 40 and parents > 0 and cancellations > 0 and rejected == 5
    paths = [Path(__file__), HERE/'追加Dayの旧入口と全台帳を独立監査する.py']
    proof = dict(全合格=True, scope='追加旧G0監査の私有人工だけ。正式追加場未読。',
        検査件数=dict(人工口座=checked, 実親=parents, 候補取消=cancellations, 意図的破損拒否=rejected),
        SHA256={str(path.relative_to(ROOT)): audit.sha(path) for path in paths},
        旧32cache読取=0, 旧64base読取=0, 新packet読取=0, 新正式金融読取=0,
        正式金融再生=0, 原本読取=0, NPZ読取=0, API取得=0, goal操作=0)
    target = HERE/'追加旧G0監査の私有人工.json'
    audit.save(target, proof)
    previous = audit.read(HERE/'追加Day全121独立監査の計画.json')
    previous['SHA256'] = audit.own_sources()
    previous.update(旧初回計画保持=True, 補足='価格代理時計で相手未来を許さない旧pair資格を追加確認。金融未読の人工で接続を確定。',
        旧入口人工SHA256=audit.sha(target))
    audit.save(HERE/'追加Day全121独立監査の計画_人工後最終接続.json', previous)
    print('追加旧G0監査人工40口座・5破損拒否合格。新packetと新金融未読。')


if __name__ == '__main__':
    main()
