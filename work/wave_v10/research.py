"""事前固定した9,600条件を保存データで比較し、過去だけから主条件を選択する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

import catalog
import engine
import signals

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SESSIONS = signals.SESSIONS
SYMBOLS = signals.SYMBOLS
FIXED_IDS = ['S09_E07_X00_Z00', 'S09_E02_X04_Z00', 'S09_E02_X07_Z00',
             'S05_E02_X05_Z00', 'S03_E02_X04_Z02']
save = engine.save


def drawdown(values: np.ndarray) -> float:
    """機能: ０から始まる確定損益累積曲線の最大下落を計算する。

    引数: values (ndarray)。返り値: 最大下落の非負値 (float)。
    """
    curve = np.r_[0., np.cumsum(values)]
    return float(np.max(np.maximum.accumulate(curve) - curve))


def summarize(prepared: dict, config: dict, raw: np.ndarray | None = None,
              delay: str = '次行') -> dict:
    """機能: 費用後損益と損小利大の指標を、未返済を分けて集計する。

    引数: prepared/config (dict)、raw (ndarray|None)、delay (str)。
    返り値: セッション銘柄条件別の日本語集計 (dict)。
    """
    if raw is None:
        raw = engine.simulate_array(prepared, config, delay)
    result = engine.summary(prepared, config, delay, raw)
    closed = raw[raw[:, 13] == 1]
    net = closed[:, 14] * engine.MULTIPLIERS[prepared['symbol']]
    result.update(信号ID=config['signal'], 入口ID=config['entry_id'], 出口ID=config['exit_id'],
                  時間ID=config['time_id'], 負け数=int((net < 0).sum()), 引分数=int((net == 0).sum()),
                  ATR収支=float((closed[:, 14] / closed[:, 6]).sum()),
                  確定最大下落ATR=drawdown(closed[:, 15] / closed[:, 6]),
                  確定最大下落円=drawdown(net),
                  検知から約定平均秒=float(np.mean([
                      prepared['time_s'][int(r[4])] - prepared['families'][config['family']]['times'][int(r[0])]
                      for r in closed])) if len(closed) else None)
    return result


def choose(frame: pd.DataFrame, conditions: list[dict], train: list[str], group: str | None = None) -> dict:
    """機能: 過去期間だけの費用・下落・頻度・入口近傍から条件を一つ選ぶ。

    引数: frame (DataFrame)、conditions (list[dict])、train (list[str])、group (str|None)。
    返り値: 採用条件と全順位を持つ記録 (dict)。
    """
    candidates = [c for c in conditions if group is None or c['group'] == group]
    ids = [c['id'] for c in candidates]
    part = frame[frame.セッション.isin(train) & frame.方式.isin(ids)]
    columns = ['取引数', '費用倍ATR収支', '確定最大下落ATR']
    sums = part.groupby(['方式', '銘柄'])[columns].sum().unstack('銘柄').reindex(ids).fillna(0)
    count = sums['取引数'].reindex(columns=SYMBOLS, fill_value=0)
    eligible = (count >= len(train)).all(axis=1)
    points = (sums['費用倍ATR収支'] - .25 * sums['確定最大下落ATR']
              - .25 * (count - 6 * len(train)).clip(lower=0)) / len(train)
    raw = points.min(axis=1)
    total = points.sum(axis=1)
    rankings = []
    for config in candidates:
        key = config['id']
        if not eligible.loc[key]:
            continue
        neighbors = [n for n in catalog.entry_neighbors(config) if n in eligible and bool(eligible.loc[n])]
        neighbor_median = float(raw.loc[neighbors].median()) if len(neighbors) >= 2 else None
        rankings.append(dict(方式=key, 基本得点=float(raw.loc[key]), 合計得点=float(total.loc[key]),
                             近傍得点中央値=neighbor_median, 適格近傍数=len(neighbors),
                             主得点=.5 * (float(raw.loc[key]) + neighbor_median) if neighbor_median is not None else None,
                             銘柄別取引数={s: int(count.loc[key, s]) for s in SYMBOLS}))
    robust = [r for r in rankings if r['主得点'] is not None]
    fallback = not robust
    pool = robust if robust else rankings
    pool.sort(key=lambda r: (-(r['基本得点'] if fallback else r['主得点']),
                             -r['基本得点'], -r['合計得点'], r['方式']))
    return dict(群=group or '主選択', 学習=train, 採用=pool[0] if pool else None,
                近傍不足の基本得点への切替=fallback, 全順位=pool,
                不採用理由=None if pool else '両銘柄の最低取引数を満たす候補がない')


def prepared_inputs(inputs: dict) -> dict:
    """機能: 信号と全生板の因果的状態から全セッションの実行入力を作る。

    引数: inputs (dict)。返り値: 同じキーの準備済み実行入力 (dict)。
    """
    return {key: engine.prepare(value['tape'], value['events'], key[0], key[1], value['state'])
            for key, value in inputs.items()}


def chart_data(inputs: dict, trades: list[dict], methods: list[dict]) -> dict:
    """機能: 確定５分足と同じ計算の移動平均、選択候補売買を図解へ渡す。

    引数: inputs (dict)、trades (list[dict])、methods (list[dict])。
    返り値: HTML用資料 (dict)。
    """
    candles, averages = {}, {}
    for (session, symbol), item in inputs.items():
        key = f'{symbol}|{session}'
        frame = pd.read_csv(signals.candle_root(session)/'candle_5min'/symbol/f'{session}.csv')
        frame = frame[frame.closed.astype(str).str.lower().eq('true')]
        rows = []
        for row in frame.to_dict('records'):
            rows.append([pd.Timestamp(row['time']).timestamp(), row['open'], row['high'], row['low'], row['close']])
        candles[key] = rows
        price = item['price_frame']
        averages[key] = [[float(r['available_time_s']), r.get('ema3'), r.get('ema8'), r.get('ema21')]
                         for r in price.to_dict('records')]
    return dict(candles=candles, averages=averages, trades=trades, methods=methods,
                sessions=SESSIONS, symbols=SYMBOLS,
                us_open={s: catalog.us_open_time(s) for s in SESSIONS if s.endswith('Night')})


def diagnostics(prepared: dict, conditions: dict[str, dict], main_id: str) -> None:
    """機能: 主条件と前回固定条件の一変数近傍と方向無作為化を、採否と分けて調べる。

    引数: prepared (dict)、conditions (dict[str, dict])、main_id (str)。返り値: なし (None)。
    """
    targets = list(dict.fromkeys([main_id, FIXED_IDS[0]]))
    jitter = []
    for key in targets:
        original = conditions[key]
        combined = dict(engine.DEFAULTS, **original)
        for field in ['entry_offset', 'initial_stop_atr', 'trail_atr', 'tighten_trigger_atr',
                      'breakeven_trigger_atr', 'protect_trigger_atr']:
            value = combined[field]
            if not np.isfinite(value) or value <= 0:
                continue
            for ratio in [.75, 1.25]:
                changed = dict(original, **{field: value * ratio})
                for (session, symbol), ready in prepared.items():
                    if session == SESSIONS[-1]:
                        continue
                    jitter.append(dict(**summarize(ready, changed), 元方式=key, 変更項目=field,
                                       倍率=ratio, 元値=value, 変更値=value*ratio))
    pd.DataFrame(jitter).to_csv(OUT/'一変数近傍感度.csv', index=False, encoding='utf-8-sig')

    # ----------------------------------------
    # 同じ候補時刻で方向だけを二択に変える。選択後の診断であり未見の有意性証明ではない。
    random_rows = []
    for key in targets:
        config = conditions[key]
        for seed in range(128):
            rng = np.random.default_rng(seed)
            total_atr = 0.
            for (session, symbol), ready in prepared.items():
                if session == SESSIONS[-1] or config['family'] not in ready['families']:
                    continue
                family = ready['families'][config['family']]
                shuffled = dict(family, sides=rng.choice(np.array([-1, 1], dtype=np.int64), size=len(family['sides'])))
                fake = dict(ready, families=dict(ready['families'], **{config['family']: shuffled}))
                result = summarize(fake, config)
                total_atr += result['費用倍ATR収支']
                random_rows.append(dict(**result, 乱数種=seed))
    pd.DataFrame(random_rows).to_csv(OUT/'同時刻コイントス比較.csv', index=False, encoding='utf-8-sig')


def main() -> None:
    """機能: 事前記録、全条件再生、過去だけの選択、候補明細と感度を保存する。

    引数: なし。返り値: なし (None)。現在セッションの追加通信を行わない。
    """
    started = time.monotonic()
    conditions = catalog.configs({p['id']: p for p in signals.profiles()})
    assert len(conditions) == 9600 and len({c['id'] for c in conditions}) == 9600
    mapping = {c['id']: c for c in conditions}
    tracked = [OUT/name for name in ['catalog.py', 'signals.py', 'engine.py', 'research.py', '検証計画.md', '入口信号の定義.md']]
    save(OUT/'条件一覧.json', conditions)
    save(OUT/'実行前記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')), 条件数=len(conditions),
         現在セッション取得数=0, 固定比較=FIXED_IDS,
         SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}))
    inputs = signals.load_inputs()
    prepared = prepared_inputs(inputs)
    cells, raw_blocks = [], []
    for cell_i, ((session, symbol), ready) in enumerate(prepared.items()):
        cache = {}
        for config_i, config in enumerate(conditions):
            cache_key = (config['signal'], config['entry_id'], config['exit_id'])
            if session.endswith('Day') and cache_key in cache:
                raw = cache[cache_key]
            else:
                raw = engine.simulate_array(ready, config)
                if session.endswith('Day'):
                    cache[cache_key] = raw
            cells.append(summarize(ready, config, raw))
            if len(raw):
                raw_blocks.append(np.column_stack([np.full(len(raw), config_i), np.full(len(raw), cell_i), raw]))
            if session != SESSIONS[-1] and len(raw):
                assert np.all(raw[:, 13] == 1), (session, symbol, config['id'])
        print(f'{session} {symbol}: 9,600条件終了、累計{time.monotonic()-started:.1f}秒', flush=True)
    frame = pd.DataFrame(cells)
    frame.to_csv(OUT/'全条件セッション集計.csv', index=False, encoding='utf-8-sig')
    array = np.vstack(raw_blocks) if raw_blocks else np.empty((0, 23))
    np.savez_compressed(OUT/'全売買数値.npz', rows=array)
    save(OUT/'数値売買形式.json', dict(条件順=[c['id'] for c in conditions],
         セル順=[dict(セッション=s, 銘柄=y) for s, y in prepared],
         先頭２列=['条件の０始まり番号', 'セルの０始まり番号'],
         後続21列=['イベント番号','方向','条件行添字','成立行添字','新規約定行添字','返済または評価行添字',
                   '設定ATR','建値','返済または評価価格','最終ストップ','最高最安追跡価格','最大順行','返済理由番号',
                   '返済済みフラグ','費用２呼値ポイント収支','費用４呼値ポイント収支','保有分',
                   '返済成立行添字','未返済の待機返済理由','初期幅ATR','最終観測行添字']))
    del raw_blocks, array

    # ----------------------------------------
    # 主結果の条件選択は次セッションを見る前の資料だけに限定する。
    selections, forward, targets = [], [], set(FIXED_IDS)
    for index in [2, 3, 4]:
        selected = choose(frame, conditions, SESSIONS[:index])
        selected['評価セッション'] = SESSIONS[index]
        selections.append(selected)
        if selected['採用']:
            method = selected['採用']['方式']
            targets.add(method)
            forward.extend(frame[frame.方式.eq(method) & frame.セッション.eq(SESSIONS[index])].to_dict('records'))
    final = choose(frame, conditions, SESSIONS[:5])
    if final['採用']:
        targets.add(final['採用']['方式'])
    final.update(固定比較=FIXED_IDS, 固定条件=[mapping[key] for key in sorted(targets)],
                 現在照合条件=[mapping[key] for key in dict.fromkeys(
                     ([final['採用']['方式']] if final['採用'] else []) + FIXED_IDS)])
    save(OUT/'時間順選択.json', selections)
    save(OUT/'最終選択.json', final)
    pd.DataFrame(forward).to_csv(OUT/'時間順セッション集計.csv', index=False, encoding='utf-8-sig')

    # ----------------------------------------
    # 詳細な注文明細と図解は主条件・比較条件に絞り、全条件の数値売買は別途保存する。
    trades, sensitivity = [], []
    for (session, symbol), ready in prepared.items():
        for key in sorted(targets):
            config = mapping[key]
            for trade in engine.simulate(ready, config):
                assert trade['source_last_seq'] < trade['signal_seq'] <= trade['condition_seq'] < trade['trigger_seq'] < trade['entry_seq']
                if trade['closed']:
                    assert trade['entry_seq'] < trade['exit_trigger_seq'] < trade['exit_seq'] and trade['exit_in_session']
                trades.append(dict(方式=key, 群=config['group'], セッション=session, 銘柄=symbol, **trade))
            for delay in ['２行後', '次時刻']:
                sensitivity.append(summarize(ready, config, delay=delay))
    save(OUT/'候補全取引.json', trades)
    pd.DataFrame(trades).to_csv(OUT/'候補全取引.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(sensitivity).to_csv(OUT/'約定遅延感度.csv', index=False, encoding='utf-8-sig')
    save(OUT/'図解資料.json', chart_data(inputs, trades, [mapping[key] for key in sorted(targets)]))
    if final['採用']:
        diagnostics(prepared, mapping, final['採用']['方式'])
    for p in tracked:
        expected = json.loads((OUT/'実行前記録.json').read_text(encoding='utf-8'))['SHA256'][p.name]
        assert hashlib.sha256(p.read_bytes()).hexdigest() == expected, p.name
    save(OUT/'完了記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')), 経過秒=time.monotonic()-started,
         条件数=len(conditions), 集計セル数=len(frame), 候補明細取引数=len(trades), 図解条件数=len(targets),
         現在セッション取得数=0, 事前コード変更なし=True))
    print('全条件・時間順評価・候補図解資料・感度の保存完了', flush=True)


if __name__ == '__main__':
    main()
