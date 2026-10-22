"""費用ゼロ・指定価格の条件を探索し、保留データを開かず主候補を選ぶ。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np
import pandas as pd

import catalog
import data
import exact_engine as engine
import new_signals

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
TRAIN = data.TRAIN
SYMBOLS = data.SYMBOLS


def clean(value: object) -> object:
    """機能: 無限値とNumPy値を明示的にJSONへ変換する。

    引数: value (object)。返り値: JSONに保存できる値 (object)。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: object) -> None:
    """機能: 日本語の検証記録をUTF-8で保存する。

    引数: path (Path)、value (object)。返り値: None。
    """
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def clock_events(tape: dict, session: str, symbol: str) -> pd.DataFrame:
    """機能: 価格の将来を使わない定刻・固定乱数の比較信号を生成する。

    引数: tape (dict)、session/symbol (str)。返り値: ４系統の比較信号 (DataFrame)。
    """
    start, end = engine.bounds(session)
    times, seq = tape['time_s'], tape['seq']
    seed = int(session[:10].replace('-', '')) * 4 + int(session.endswith('Night')) * 2 + SYMBOLS.index(symbol)
    rng = np.random.default_rng(seed)
    rows = []
    for number, target in enumerate(np.arange(start+20*60, end-30*60, 30*60)):
        i = int(np.searchsorted(times, target, side='left'))
        coin = 1 if rng.integers(0, 2) else -1
        if i <= 0 or i >= len(times) or not np.isfinite(tape['atr'][i]):
            continue
        for family, side in [('Q01', 1), ('Q02', -1), ('Q03', 1 if number % 2 == 0 else -1), ('Q04', coin)]:
            rows.append(dict(family=family, event_id=f'{session}:{symbol}:{family}:{seq[i]}',
                             seq=int(seq[i]), source_last_seq=int(seq[i-1]), time_s=float(times[i]),
                             side=side, atr=float(tape['atr'][i]), deadline_time_s=float(times[i]+10*60)))
    return pd.DataFrame(rows)


def build_inputs(sessions: list[str], allow_holdout: bool = False, roots: dict | None = None) -> dict:
    """機能: 許可した保存区間だけから旧・新・定刻信号と真の価格入力を準備する。

    引数: sessions (list[str])、allow_holdout (bool)、roots (dict|None) はセッション別の足/特徴保存先。
    返り値: (セッション,銘柄)をキーとする準備済み入力 (dict)。
    """
    if data.HOLDOUT in sessions and not allow_holdout:
        raise ValueError('最終保留は凍結後に明示的に開封してください')
    base = data.signals_module(allow_holdout=allow_holdout)
    for session, pair in (roots or {}).items():
        base.CANDLE_OVERRIDES[session], base.FEATURE_OVERRIDES[session] = map(Path, pair)
    new_signals.configure(base)
    original = base.load_inputs(sessions=sessions)
    prepared, audits = {}, []
    for (session, symbol), item in original.items():
        new, audit = new_signals.build_events(session, symbol, item['features'], item['peer_features'])
        events = pd.concat([item['events'], new, clock_events(item['tape'], session, symbol)], ignore_index=True)
        events = events.sort_values(['seq', 'family']).reset_index(drop=True)
        ready = engine.prepare(item['tape'], events, session, symbol, state=item['state'])
        prepared[(session, symbol)] = ready
        audits.append(dict(セッション=session, 銘柄=symbol, 旧信号=item['event_audit'], 新信号=audit,
                           全信号数=len(events), 原本行数=len(ready['seq']),
                           系統別=events.family.value_counts().sort_index().to_dict()))
    name = '学習信号監査.json' if sessions == TRAIN else '追加照合信号監査_' + sessions[0] + '.json'
    save(OUT/name, audits)
    return prepared


def result_row(ready: dict, config: dict, result: dict) -> dict:
    """機能: 英語の数値出力へ日本語の条件・対象メタ情報を付ける。

    引数: ready/config/result (dict)。返り値: CSVの１行 (dict)。
    """
    return dict(方式=config['id'], 系統=config['family'], 思想=config['philosophy'], 群=config['group'],
                新旧=config['origin'], セッション=ready['session'], 銘柄=ready['symbol'],
                設定最大枚数=config['max_legs'], **result['summary'])


def choose(frame: pd.DataFrame, sessions: list[str], symbol: str, philosophy: str | None = None,
           origin: str | None = None, family: str | None = None) -> dict:
    """機能: 過去区間だけの中央値・平均収支・下落額から１条件を選ぶ。

    引数: frame (DataFrame)、sessions (list[str])、symbol (str)、philosophy/origin/family (str|None)。
    返り値: 採用条件と順位を含む選択記録 (dict)。
    """
    part = frame[frame['セッション'].isin(sessions) & frame['銘柄'].eq(symbol)].copy()
    for column, value in [('思想', philosophy), ('新旧', origin), ('系統', family)]:
        if value is not None:
            part = part[part[column].eq(value)]
    part['換算下落'] = part['max_drawdown_yen'] / part['設定最大枚数']
    part['有取引'] = part['closed_count'] > 0
    ranked = part.groupby('方式').agg(中央値=('cap_net_yen', 'median'), 平均=('cap_net_yen', 'mean'),
                平均下落=('換算下落', 'mean'), 返済数=('closed_count', 'sum'), 有取引数=('有取引', 'sum'),
                学習収支円=('closed_net_yen', 'sum'), 利益円=('profit_yen', 'sum'), 損失円=('loss_yen', 'sum')).reset_index()
    ranked = ranked[(ranked['返済数'] >= 3) & (ranked['有取引数'] >= 2)].copy()
    ranked['得点'] = ranked['中央値'] + ranked['平均'] - .25 * ranked['平均下落']
    ranked = ranked.sort_values(['得点', '方式'], ascending=[False, True])
    return dict(学習=sessions, 銘柄=symbol, 思想=philosophy, 新旧=origin, 系統=family,
                採用=ranked.iloc[0].to_dict() if len(ranked) else None,
                候補数=len(ranked), 上位=ranked.head(20).to_dict('records'))


def selections(frame: pd.DataFrame, configs: list[dict]) -> dict:
    """機能: 時間順の選択方針と、保留検証へ持ち込む固定候補を記録する。

    引数: frame (DataFrame)、configs (list[dict])。返り値: 主候補・代表条件・時間順結果 (dict)。
    """
    philosophies = sorted(frame['思想'].unique())
    primary, representatives, walks, walk_rows = {}, {}, [], []
    for symbol in SYMBOLS:
        primary[symbol] = choose(frame, TRAIN, symbol)
        for philosophy in philosophies:
            representatives[f'{symbol}|{philosophy}'] = choose(frame, TRAIN, symbol, philosophy=philosophy)
        for origin in ['既存', '新規']:
            representatives[f'{symbol}|{origin}'] = choose(frame, TRAIN, symbol, origin=origin)
        for count in [2, 3, 4, 5]:
            for philosophy in [None, *philosophies]:
                row = choose(frame, TRAIN[:count], symbol, philosophy=philosophy)
                row['評価'] = TRAIN[count]
                walks.append(row)
                if row['採用']:
                    cell = frame[(frame['方式'] == row['採用']['方式']) & (frame['セッション'] == TRAIN[count]) & (frame['銘柄'] == symbol)].iloc[0]
                    walk_rows.append(dict(cell.to_dict(), 選択対象思想=philosophy or '全方式', 学習数=count))
    fixed = ['旧主候補_P01', '旧T12', '旧S17', 'P16_R1_T05', 'P16_R-1_T05']
    ids = sorted({x['採用']['方式'] for x in [*primary.values(), *representatives.values()] if x['採用']} | set(fixed))
    result = dict(主候補=primary, 思想別代表=representatives, 固定比較=fixed, 照合ID=ids,
                  追加条件を選び直すこと=False, 手数料=0, 売買気配差控除=0,
                  選択説明='設定上限で換算した各セッション収支の中央値＋平均−0.25×平均最大下落。最低３返済取引・２有取引セッション。')
    save(OUT/'時間順選択.json', walks)
    pd.DataFrame(walk_rows).to_csv(OUT/'時間順評価.csv', index=False, encoding='utf-8-sig')
    save(OUT/'最終選択.json', result)
    return result


def details(prepared: dict, configs: list[dict], ids: list[str], prefix: str) -> None:
    """機能: 固定候補の全脚・全資産曲線・セッション損益を保存する。

    引数: prepared (dict)、configs (list[dict])、ids (list[str])、prefix (str)。返り値: None。
    """
    mapping = {c['id']: c for c in configs}
    trades, curves, rows = [], {}, []
    for method in ids:
        cfg = mapping[method]
        for (session, symbol), ready in prepared.items():
            result = engine.simulate(ready, cfg['family'], cfg, detail=True)
            rows.append(result_row(ready, cfg, result))
            trades.extend(dict(方式=method, **t) for t in result['trades'])
            curves[f'{method}|{session}|{symbol}'] = result['equity']
    save(OUT/f'{prefix}_全取引.json', trades)
    save(OUT/f'{prefix}_資産曲線.json', curves)
    pd.DataFrame(rows).to_csv(OUT/f'{prefix}_セッション集計.csv', index=False, encoding='utf-8-sig')


def main() -> None:
    """機能: 学習６セッションだけで全条件探索と選択を終える。

    引数: なし。返り値: None。保留日中や現在APIは開かない。
    """
    started = time.monotonic()
    configs = catalog.configs()
    for cfg in configs:
        engine.parameters(cfg)
    save(OUT/'条件一覧.json', configs)
    save(OUT/'信号条件一覧.json', catalog.profiles())
    sources = [OUT/f for f in ['research.py', 'catalog.py', 'data.py', 'exact_engine.py', 'new_signals.py', '検証計画.md']]
    save(OUT/'実行前記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')), 条件数=len(configs),
         学習=TRAIN, 保留=data.HOLDOUT, SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}))
    prepared = build_inputs(TRAIN)
    with (OUT/'学習入力.pkl').open('wb') as stream:
        pickle.dump(prepared, stream, protocol=pickle.HIGHEST_PROTOCOL)
    rows, blocks = [], []
    for cell_i, ((session, symbol), ready) in enumerate(prepared.items()):
        cache = {}
        for config_i, cfg in enumerate(configs):
            key = cfg['id'][:-1] if cfg['id'].endswith(('_U0', '_U1')) else cfg['id']
            if session.endswith('Day') and key in cache:
                result = cache[key]
            else:
                result = engine.simulate(ready, cfg['family'], cfg)
                if session.endswith('Day'):
                    cache[key] = result
            rows.append(result_row(ready, cfg, result))
            if len(result['raw']):
                blocks.append(np.column_stack([np.full(len(result['raw']), config_i), np.full(len(result['raw']), cell_i), result['raw']]))
        print(f'{session} {symbol}: {len(configs)}条件、{time.monotonic()-started:.1f}秒', flush=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT/'全条件_セッション集計.csv', index=False, encoding='utf-8-sig')
    np.savez_compressed(OUT/'全取引数値.npz', trades=np.vstack(blocks))
    save(OUT/'数値形式.json', dict(条件=[c['id'] for c in configs], セル=list(prepared),
         列=['条件index', 'セルindex', *engine.RAW_COLUMNS]))
    selected = selections(frame, configs)
    details(prepared, configs, selected['照合ID'], '学習代表')
    save(OUT/'実行完了.json', dict(条件数=len(configs), セル数=len(frame), 全脚数=sum(len(b) for b in blocks),
         秒=time.monotonic()-started, 主候補={s:c['採用'] for s,c in selected['主候補'].items()}, 現在API取得数=0))
    print(json.dumps(clean({s:c['採用'] for s,c in selected['主候補'].items()}), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
