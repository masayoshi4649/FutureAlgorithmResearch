"""固定候補の全玉明細と前回03:01以降の増分を保存する。"""

from __future__ import annotations

import argparse
import json
import pickle

import numpy as np
import pandas as pd

import reference
import selection

OUT = reference.OUT
legacy = reference.import_v14('details')
metrics = reference.import_v14('metrics')
pair = reference.import_v14('pair_engine')
account = reference.import_v14('risk_guard')


def metric_columns(cycles: list[dict], sessions: list[str]) -> dict:
    """機能: サイクル単位の指標を表示用の平らな辞書へ変換する。

    引数: cycles (list[dict])、sessions (list[str])。返り値: dict。
    """
    result = metrics.summarize(cycles, sessions, 'yen')
    return {f'cycle_{k}': v for k, v in result.items() if not isinstance(v, (dict, list)) and k not in ('method', 'symbol')}


def write_bundle(prefix: str, rows: list[dict], trades: list[dict], cycles: list[dict], curves: dict) -> None:
    """機能: 表・全脚・サイクル・評価曲線を同じ接頭辞へ保存する。

    引数: prefix (str)、rows/trades/cycles (list[dict])、curves (dict)。返り値: なし (None)。
    """
    pd.DataFrame(rows).to_csv(OUT / f'{prefix}_セッション集計.csv', index=False, encoding='utf-8-sig')
    for label, value in [('全取引', trades), ('サイクル', cycles), ('資産曲線', curves)]:
        reference.save(OUT / f'{prefix}_{label}.json', value)


def evaluate(prepared: dict, targets: list[dict], prefix: str, extra_prefix: str) -> None:
    """機能: 指定済み銘柄条件だけを再生し、週全体と既知境界からの増分を分ける。

    引数: prepared (dict)、targets (list[dict])、prefix/extra_prefix (str)。返り値: なし (None)。
    """
    mapping = {c['id']: c for c in reference.configs()}
    sessions = [s for s in reference.SESSIONS if (s, 'NK225') in prepared]
    boundary = pd.Timestamp(reference.KNOWN_CUTOFF).timestamp()
    rows, trades, cycles, curves = [], [], [], {}
    extra_rows, extra_trades, extra_cycles, extra_curves, audits = [], [], [], {}, []
    pair_inputs = {}
    raw_blocks = {}
    for number, target in enumerate(targets):
        method, symbol = target['method'], target['symbol']
        cfg = mapping[method]
        for session in sessions:
            meta = dict(方式=method, 銘柄=symbol, セッション=session, 思想=cfg['philosophy'],
                設定最大枚数=cfg['max_legs'], engine=cfg['engine'])
            if cfg['engine'] == 'pair':
                if session not in pair_inputs:
                    pair_inputs[session] = pair.prepare_session(session, tapes=[prepared[(session, k)] for k in reference.SYMBOLS])
                ready = pair_inputs[session]
                result = pair.run(ready, cfg, detail=True)
                cs = result['cycles']
                ts = legacy.pair_trades(result['legs'], method)
                curve = legacy.normalize_pair_curve(result['curve'])
                full_equity = np.asarray(result['curve'], dtype=float)[:, 3]
                summary = dict(result['summary'])
            else:
                ready = prepared[(session, symbol)]
                result, cs = legacy.single_result(ready, cfg)
                ts = [dict(方式=method, 枚数=1, **t) for t in result['trades']]
                curve, summary = result['equity'], dict(result['summary'])
                full_equity = account.account_arrays(result['raw'], ready['last'])[0] * reference.engine.MULTIPLIERS[symbol]
                raw_blocks[(method, session, symbol)] = result['raw']
            summary['最小評価損益円'] = float(min(0., full_equity.min()))
            summary['最大評価損益円'] = float(max(0., full_equity.max()))
            rows.append(dict(meta, **summary, **metric_columns(cs, [session])))
            trades.extend(ts); cycles.extend(cs)
            curves[f'{method}|{session}|{symbol}'] = curve
            # ----------------------------------------
            # 既知区間の損益を未知の成果へ再加算しない。
            if session in reference.SESSIONS[8:]:
                extra_rows.append(dict(meta, **summary, **metric_columns(cs, [session]), carried_cycles=0, baseline_equity_yen=0.))
                extra_trades.extend(ts); extra_cycles.extend(cs)
                extra_curves[f'{method}|{session}|{symbol}'] = curve
            elif session == reference.KNOWN_NIGHT:
                if cfg['engine'] != 'pair':
                    after, ac, audit = legacy.split_single(ready, result, cs, cfg, boundary)
                    suffix_equity = full_equity[ready['time_s'] >= boundary] - audit['baseline_equity_yen']
                    extra_rows.append(dict(meta, **after['summary'], **metric_columns(ac, [session]),
                        carried_cycles=audit['carried_cycles'], baseline_equity_yen=audit['baseline_equity_yen'],
                        最小評価損益円=float(min(0., suffix_equity.min())), 最大評価損益円=float(max(0., suffix_equity.max()))))
                    extra_trades.extend(dict(方式=method, 枚数=1, **t) for t in after['trades'])
                    extra_cycles.extend(ac)
                    extra_curves[f'{method}|{session}|{symbol}'] = after['equity']
                    audits.append(dict(meta, **audit))
                else:
                    after = pair.split_at_boundary(result, ready, boundary)
                    ac = after['cycles']
                    closed = sum(c['closed_yen'] for c in ac)
                    opened = sum(c['open_yen'] for c in ac)
                    am = dict(net_yen=after['net_yen'], closed_net_yen=closed, open_yen=opened,
                        profit_yen=sum(t['net_yen'] for t in after['legs'] if t['complete'] and t['net_yen'] > 0),
                        loss_yen=sum(t['net_yen'] for t in after['legs'] if t['complete'] and t['net_yen'] < 0),
                        max_drawdown_yen=after['max_drawdown_yen'], open_count=sum(c['open_legs'] for c in ac),
                        closed_count=sum(c['closed_legs'] for c in ac), carried_cycles=sum(c['carried'] for c in ac),
                        baseline_equity_yen=after['baseline_equity_yen'],
                        最小評価損益円=float(min(0., after['curve'][:, 1].min())),
                        最大評価損益円=float(max(0., after['curve'][:, 1].max())))
                    extra_rows.append(dict(meta, **am, **metric_columns(ac, [session])))
                    extra_trades.extend(legacy.pair_trades(after['legs'], method, True)); extra_cycles.extend(ac)
                    full = after['curve']
                    minute = np.floor(full[:, 0] / 60)
                    idx = np.unique(np.r_[0, np.where(np.diff(minute) != 0)[0] + 1, len(minute) - 1]) if len(minute) else []
                    extra_curves[f'{method}|{session}|{symbol}'] = [[boundary, -1, 0., 0., 0., 0., 0.]] + [
                        [full[i, 0], -1, full[i, 1], 0., 0., 0., 0.] for i in idx]
                    audits.append(dict(meta, baseline_equity_yen=after['baseline_equity_yen'], new_period_net_yen=after['net_yen']))
        print(f'{prefix} {number+1}/{len(targets)} {symbol} {method}', flush=True)
    write_bundle(prefix, rows, trades, cycles, curves)
    write_bundle(extra_prefix, extra_rows, extra_trades, extra_cycles, extra_curves)
    reference.save(OUT / f'{prefix}_境界照合.json', audits)
    with (OUT / f'{prefix}_数値.pkl').open('wb') as stream:
        pickle.dump(raw_blocks, stream, protocol=pickle.HIGHEST_PROTOCOL)
    # ----------------------------------------
    # 前回表示時点の２候補と、今回同じ時点までの既返済履歴・全玉評価を照合する。
    former = json.loads((reference.ROOT / 'work/wave_v15/結果_全体.json').read_text(encoding='utf-8'))
    checks = []
    for old in former:
        method, symbol = old['方式'], old['銘柄']
        matched = [a for a in audits if a['方式'] == method and a['銘柄'] == symbol]
        if not matched:
            continue
        np.testing.assert_allclose(matched[0]['baseline_equity_yen'], old['summary']['net_yen'], atol=1e-5)
        keys = ['サイクル番号', '脚番号', '方向', '新規時刻', '返済評価時刻', '新規価格', '返済評価価格', '固定ATR', '収支円']
        a = [t for t in old['trades'] if t['返済済み']]
        b = [t for t in trades if t['方式'] == method and t['銘柄'] == symbol and t['セッション'] == reference.KNOWN_NIGHT
             and t['返済済み'] and t['返済評価時刻'] < boundary]
        a = sorted(a, key=lambda t: (t['サイクル番号'], t['脚番号']))
        b = sorted(b, key=lambda t: (t['サイクル番号'], t['脚番号']))
        np.testing.assert_allclose([[t[k] for k in keys] for t in a], [[t[k] for k in keys] for t in b], atol=1e-6)
        checks.append(dict(方式=method, 銘柄=symbol, 既返済脚数=len(a), 旧締切評価円=matched[0]['baseline_equity_yen'], 一致=True))
    reference.save(OUT / f'{prefix}_前回表示一致.json', checks)


def aggregate() -> None:
    """機能: 固定代表の期間別損益と、過去だけで選んだ翌区間成績をまとめる。

    引数: なし。返り値: なし (None)。新しい順位付けを行わない。
    """
    record = json.loads((OUT / '最終選択.json').read_text(encoding='utf-8'))
    cs = json.loads((OUT / '代表_サイクル.json').read_text(encoding='utf-8'))
    added = json.loads((OUT / '追加_サイクル.json').read_text(encoding='utf-8'))
    table = pd.read_csv(OUT / '代表_セッション集計.csv')
    extra = pd.read_csv(OUT / '追加_セッション集計.csv')
    bundles = []
    for target in record['照合対象']:
        method, symbol = target['method'], target['symbol']
        parts = {}
        for name, source, sessions, frame in [
            ('旧７区間', cs, reference.TRAIN, table), ('開発９区間', cs, reference.DEVELOPMENT, table),
            ('最終保留', cs, [reference.HOLDOUT], table), ('全10区間', cs, reference.SESSIONS, table),
            ('今回追加', added, reference.SESSIONS[7:], extra)]:
            selected = [c for c in source if c['method'] == method and c['symbol'] == symbol and c['session'] in sessions]
            values = metrics.summarize(selected, sessions, 'yen')
            sums = sorted((r['net'] for r in values['sessions']), reverse=True)
            values['上位２区間を除く収支円'] = float(sum(sums[2:])) if len(sums) > 2 else None
            cells = frame[frame['方式'].eq(method) & frame['銘柄'].eq(symbol) & frame['セッション'].isin(sessions)]
            values['最大セッション内下落円'] = float(cells.max_drawdown_yen.max()) if len(cells) else 0.
            cumulative, high, drawdown = 0., 0., 0.
            for session in sessions:
                row = cells[cells['セッション'].eq(session)].iloc[0]
                drawdown = max(drawdown, float(row.max_drawdown_yen), high - cumulative - float(row['最小評価損益円']))
                high = max(high, cumulative + float(row['最大評価損益円']))
                cumulative += float(row.net_yen)
            values['期間全体の最大下落円'] = drawdown
            values['確定利益脚合計円'] = float(cells.profit_yen.sum())
            values['確定損失脚合計円'] = float(cells.loss_yen.sum())
            parts[name] = values
        bundles.append(dict(**target, 指標=parts))
    reference.save(OUT / '週合計指標.json', bundles)
    walks = json.loads((OUT / '時間順選択.json').read_text(encoding='utf-8'))
    rows, combined = [], {}
    for walk in walks:
        chosen = walk['採用']
        if chosen is None:
            continue
        method, symbol, session = chosen['method'], walk['銘柄'], walk['評価']
        selected = [c for c in cs if c['method'] == method and c['symbol'] == symbol and c['session'] == session]
        row = dict(方式=method, 銘柄=symbol, 評価=session, 学習数=len(walk['学習']), 判定=walk['判定'], **metric_columns(selected, [session]))
        rows.append(row)
        combined.setdefault(symbol, []).extend(dict(c, method='時間順選択') for c in selected)
    pd.DataFrame(rows).to_csv(OUT / '時間順実評価.csv', index=False, encoding='utf-8-sig')
    reference.save(OUT / '時間順合計.json', {s: metrics.summarize(v, reference.SESSIONS[3:], 'yen') for s, v in combined.items()})


def main() -> None:
    """機能: 前回２候補の開発再生か、最終固定後の代表全週再生を行う。

    引数: CLI --development/--final。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description='固定した銘柄条件の週明細')
    parser.add_argument('--final', action='store_true')
    args = parser.parse_args()
    prepared = reference.load_inputs('development')
    if args.final:
        selection.freeze_check()
        prepared.update(reference.load_inputs('holdout'))
        record = json.loads((OUT / '最終選択.json').read_text(encoding='utf-8'))
        evaluate(prepared, record['照合対象'], '代表', '追加')
        aggregate()
        selection.freeze_check()
        reference.save(OUT / '最終保留_評価記録.json', dict(完了時刻=pd.Timestamp.now(tz='Asia/Tokyo').isoformat(),
            最終保留=reference.HOLDOUT, 固定条件のみ=True, 固定後再選択=False,
            全条件保留順位付け=False, API取得=0, 凍結記録SHA256=reference.sha256(OUT / '最終保留_凍結記録.json')))
    else:
        targets = [dict(method=m, symbol=s) for s, m in reference.FIXED_TARGETS.items()]
        evaluate(prepared, targets, '前回候補', '前回候補追加')


if __name__ == '__main__':
    main()
