"""条件を変更せず、候補２方式の現在セッション全体と追加区間を再生する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import current_check

OUT = Path(__file__).resolve().parent
OLD = OUT.parent / 'wave_v14'
reference = current_check.reference
details = current_check.import_v14('details')
metrics = current_check.import_v14('metrics')


def save(path: Path, value: object) -> None:
    """機能: 日本語の結果を既存の有限値変換器で保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    reference.save(path, value)


def pending_entry(ready: dict, result: dict, cfg: dict) -> dict | None:
    """機能: 最後の全返済以降の未約定新規条件を既存規則どおり再構成する。

    引数: ready/result/cfg (dict)。返り値: 未約定条件 (dict|None)。
    建玉保有中の新規はないため、最後の全返済以降だけを読み、原再生の件数と照合する。
    """
    raw = result['raw']
    if result['summary']['open_count']:
        if result['summary']['pending_entries']:
            raise AssertionError('建玉と未約定新規が同時に残っています')
        return None
    cfg = dict(reference.engine.DEFAULTS, **cfg)
    family = ready['families'].get(cfg['family'], {})
    events = {int(i): (int(s), float(d)) for i, s, d in zip(
        family.get('indices', []), family.get('sides', []), family.get('deadlines', []))}
    last_index = int(raw[:, 6].max()) if len(raw) else -1
    last_exit = float(ready['time_s'][last_index]) if last_index >= 0 else -np.inf
    pending = None
    multiplier = cfg.get('signal_multiplier', cfg['direction_multiplier'])
    for i in range(last_index + 1, len(ready['seq'])):
        now, price = float(ready['time_s'][i]), float(ready['last'][i])
        if not np.isfinite(price) or price <= 0:
            continue
        event = events.get(i)
        blocked = now < ready['start'] + cfg['warmup_min'] * 60 or now >= ready['limit'] - cfg['entry_deadline_min'] * 60
        blocked = blocked or (cfg['us_pause'] and ready['us_open'] - cfg['us_before_min'] * 60 <= now < ready['us_open'] + cfg['us_after_min'] * 60)
        if pending is not None:
            if now > pending['期限秒'] or blocked:
                pending = None
            elif i > pending['条件行位置']:
                direction = pending['方向']
                if cfg['entry_mode'] == 'market' or direction * (price - pending['指定価格']) >= 0:
                    raise AssertionError('未約定新規の再構成に未記録の約定があります')
                if event is not None and event[0] * multiplier == -direction:
                    pending = None
        if event is not None and pending is None and not blocked and now >= last_exit + cfg['cooldown_min'] * 60:
            atr = float(ready['atr'][i])
            if np.isfinite(atr) and atr > 0:
                direction = int(event[0] * multiplier)
                atr = max(atr, ready['tick'] * 2)
                threshold = reference.engine.rounded(price + direction * cfg['entry_atr'] * atr, direction, ready['tick'])
                pending = dict(条件行位置=i, 設定時刻秒=now, 方向=direction,
                    指定価格=None if cfg['entry_mode'] == 'market' else float(threshold),
                    注文種別='次の有効行で成行' if cfg['entry_mode'] == 'market' else '逆指値',
                    固定ATR=atr, 期限秒=min(event[1], now + cfg['max_age_min'] * 60))
    if int(pending is not None) != result['summary']['pending_entries']:
        raise AssertionError('原再生と未約定新規件数が一致しません')
    return pending


def snapshot(ready: dict, result: dict, cfg: dict) -> dict:
    """機能: 評価末尾の建玉・返済条件・未約定入口を数値で出力する。

    引数: ready/result/cfg (dict)。返り値: 現在状態 (dict)。
    """
    _, targets = reference.engine.parameters(cfg)
    positions = []
    for trade in result['trades']:
        if trade['返済済み']:
            continue
        direction, leg = int(trade['方向']), int(trade['脚番号'])
        target = reference.engine.rounded(trade['新規価格'] + direction * targets[leg] * trade['固定ATR'], direction, ready['tick'])
        initial = reference.engine.rounded(trade['新規価格'] - direction * cfg['initial_stop_atr'] * trade['固定ATR'], -direction, ready['tick'])
        positions.append(dict(サイクル番号=int(trade['サイクル番号']), 脚番号=leg, 枚数=1,
            方向='買い' if direction == 1 else '売り', 新規時刻秒=trade['新規時刻'],
            新規価格=trade['新規価格'], 評価価格=trade['返済評価価格'], 含み損益円=trade['収支円'],
            固定ATR=trade['固定ATR'], 初期損切り価格=float(initial), 有効返済ストップ=float(trade['最終ストップ']),
            順行極値=trade['順行極値'], 利確価格=float(target) if np.isfinite(target) else None,
            返済予約中=trade['返済条件行位置'] >= 0))
    valid = np.flatnonzero(np.isfinite(ready['last']) & (ready['last'] > 0))
    last = int(valid[-1])
    return dict(評価時刻秒=float(ready['time_s'][last]), 評価価格=float(ready['last'][last]), 建玉=positions,
        未約定新規=pending_entry(ready, result, cfg), 新規停止時刻秒=ready['limit'] - cfg['entry_deadline_min'] * 60,
        全返済判断時刻秒=ready['limit'], 条件価格の有効時点='表示末尾より後の有効原本行', 実注文=False)


def main() -> None:
    """機能: 凍結済み設定を保存済み現在入力へ適用し、結果と検査を保存する。

    引数: なし。返り値: なし (None)。通信・条件探索・設定変更は行わない。
    """
    frozen = current_check.freeze_check()
    receipt = current_check.receipt_check(frozen)
    with (OUT / '現在入力.pkl').open('rb') as stream:
        prepared = pickle.load(stream)
    with (OLD / '現在入力.pkl').open('rb') as stream:
        prior = pickle.load(stream)
    boundary = pd.Timestamp(frozen['known_cutoff']).timestamp()
    mapping = {c['id']: c for c in frozen['selected_configs']}
    full, extra, records, numeric = [], [], [], {}
    for symbol, method in current_check.EXPECTED.items():
        cfg = mapping[method]
        ready = prepared[(frozen['session'], symbol)]
        result, cycles = details.single_result(ready, cfg)
        suffix, suffix_cycles, boundary_audit = details.split_single(ready, result, cycles, cfg, boundary)
        old_ready = prior[(frozen['session'], symbol)]
        old_result, _ = details.single_result(old_ready, cfg)
        previous_closed = old_result['raw'][old_result['raw'][:, 14] == 1]
        already_closed = result['raw'][(result['raw'][:, 14] == 1) & (ready['time_s'][result['raw'][:, 6].astype(int)] < boundary)]
        np.testing.assert_allclose(previous_closed, already_closed, equal_nan=True, atol=1e-8)
        np.testing.assert_allclose(old_result['summary']['net_yen'], boundary_audit['baseline_equity_yen'], atol=1e-5)
        full.append(dict(方式=method, 銘柄=symbol, セッション=frozen['session'], 設定=cfg,
            summary=result['summary'], cycle_summary=metrics.summarize(cycles, [frozen['session']], 'yen'),
            trades=[dict(方式=method, 枚数=1, **t) for t in result['trades']],
            cycles=cycles, equity=result['equity'], state=snapshot(ready, result, cfg)))
        fresh = [c for c in suffix_cycles if not c['carried']]
        extra.append(dict(方式=method, 銘柄=symbol, セッション=frozen['session'], summary=suffix['summary'],
            cycle_summary=metrics.summarize(suffix_cycles, [frozen['session']], 'yen'),
            fresh_summary=metrics.summarize(fresh, [frozen['session']], 'yen'),
            trades=[dict(方式=method, 枚数=1, **t) for t in suffix['trades']], cycles=suffix_cycles,
            equity=suffix['equity'], boundary=boundary_audit))
        numeric[symbol] = result['raw']
        records.append(dict(銘柄=symbol, 方式=method, 旧返済脚数=len(previous_closed), 旧返済全22列一致=True,
            旧締切評価一致=True, 旧締切評価円=boundary_audit['baseline_equity_yen']))
        print(json.dumps(dict(銘柄=symbol, 全体=result['summary'], 追加区間=suffix['summary'], 現在=full[-1]['state']), ensure_ascii=False), flush=True)
    # ----------------------------------------
    save(OUT / '結果_全体.json', full)
    save(OUT / '結果_追加区間.json', extra)
    np.savez_compressed(OUT / '全脚数値.npz', **numeric)
    save(OUT / '既知部分一致確認.json', records)
    current_check.freeze_check()
    save(OUT / '評価記録.json', dict(評価時刻=current_check.now_jst().isoformat(), セッション=frozen['session'],
        セッション開始=frozen['starts_at'], 未読開始=frozen['known_cutoff'], 取得締切未満=receipt['cutoff'],
        実時間の発注実績=False, 条件変更=False, 追加の条件選択=False, 手数料円=0,
        条件='セッション開始から稼働していた場合の再生。今から開始した未来収益を表すものではない。',
        凍結記録SHA256=current_check.sha256(current_check.FROZEN),
        出力SHA256={name: current_check.sha256(OUT / name) for name in ['結果_全体.json', '結果_追加区間.json', '全脚数値.npz', '既知部分一致確認.json']}))


if __name__ == '__main__':
    main()
