"""固定代表の入口確認・途中判断・保険・時間上限を、同設定の対照と照合する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import socket

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('前16', '後13', '全29')
REASONS = {1: '保険の初期損切り', 2: '保険のトレーリング', 3: '保有時間上限',
           4: '場内全返済', 6: '両市場の反対合意', 7: '両市場の支持消失'}


def load(path: Path) -> object:
    """機能: 保存済みJSON又は配列台帳を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。原本を変更しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 大きな保存入力も一定メモリー量で指紋化する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存分析からネットワークへ接続することを禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、例外を送出する。
    """
    raise RuntimeError('保存分析からの通信は禁止')


def metric(a: dict) -> dict:
    """機能: 全決済の金額・件数・平均・活動と気配差を抜き出す。

    引数: a(dict)。返り値: 比較用指標(dict)。無取引は勝ちに含めない。
    """
    p, loss, count = float(a['profit']), float(a['loss']), int(a['trades'])
    assert abs(p - loss - a['net']) < 1e-5
    return dict(利益=p, 損失=loss, 収支=float(a['net']), 手数料=a['fees'], 取引数=count,
        勝数=a['wins'], 負数=a['losses'], 活動場数=a['active_sessions'], 黒字場数=a['positive_sessions'],
        金額損失割合=loss / (p + loss) if p + loss else None,
        平均一取引収支=a['net'] / count if count else None,
        平均利益=p / a['wins'] if a['wins'] else None,
        平均負け=loss / a['losses'] if a['losses'] else None,
        勝率=a['wins'] / count if count else None, 平均勝負比=a['payoff'],
        最大一取引損失=a['max_trade_loss'], 最大黒字場除外収支=a['without_best_session'],
        最大時価下落=a['drawdown'], 平均保有分=a['hold_seconds'] / count / 60. if count else None,
        気配差負担=a['spread_drag'], 同じ売買時点の中値置換収支=a['net'] + a['spread_drag'])


def comparison(a: dict, b: dict) -> dict:
    """機能: 損失総額の減少と、一取引当たりの収支改善を区別する。

    引数: a/b(dict)。返り値: 案・対照・差分(dict)。実行経路差を因果効果とは呼ばない。
    """
    x, y = metric(a), metric(b)
    mean = None if x['平均一取引収支'] is None or y['平均一取引収支'] is None else x['平均一取引収支'] - y['平均一取引収支']
    share = None if x['金額損失割合'] is None or y['金額損失割合'] is None else x['金額損失割合'] - y['金額損失割合']
    loss_delta = x['損失'] - y['損失']
    if x['取引数'] == 0:
        note = '無取引であり損失零を有効な売買の成功と数えない。'
    elif mean is None:
        note = '対照が無取引であり一取引平均は比較不能。'
    elif loss_delta < 0 and mean <= 0:
        note = '損失総額は減ったが一取引平均は改善せず、取引削減を含む。'
    elif mean > 0:
        note = '一取引平均は改善。黒字・損小利大・活動場数・前後の再現は別確認。'
    else:
        note = '一取引平均の改善は確認できない。'
    return dict(案=x, 対照=y, 収支変化=x['収支'] - y['収支'], 利益変化=x['利益'] - y['利益'],
        損失変化=loss_delta, 取引数変化=x['取引数'] - y['取引数'],
        取引削減率=1. - x['取引数'] / y['取引数'] if y['取引数'] else None,
        平均一取引収支変化=mean, 金額損失割合変化=share,
        単純件数換算の損失差=x['損失'] - y['損失'] * x['取引数'] / y['取引数'] if y['取引数'] else None,
        診断=note)


def consistency(a: dict, b: dict, sessions: list[str], symbol: str) -> dict:
    """機能: 場別・セッション日付別の収支差と最大黒字場依存を比較する。

    引数: a/b(dict)、sessions(list[str])、symbol(str)。返り値: 一貫性(dict)。
    """
    x = {r['session']: r for r in a['rows'] if r['symbol'] == symbol and r['session'] in sessions}
    y = {r['session']: r for r in b['rows'] if r['symbol'] == symbol and r['session'] in sessions}
    assert set(x) == set(y) == set(sessions)
    rows, days = [], defaultdict(lambda: dict(案収支=0., 対照収支=0., 案取引数=0, 対照取引数=0))
    for session in sessions:
        p, q = x[session], y[session]
        row = dict(セッション=session, 案収支=p['net'], 対照収支=q['net'],
                   収支差=p['net'] - q['net'], 案取引数=p['trades'], 対照取引数=q['trades'])
        rows.append(row)
        for label in ('案収支', '対照収支', '案取引数', '対照取引数'):
            days[session[:10]][label] += row[label]
    active = [r for r in rows if r['案取引数'] or r['対照取引数']]
    daily = [dict(日付=day, **v, 収支差=v['案収支'] - v['対照収支']) for day, v in sorted(days.items())]
    active_days = [r for r in daily if r['案取引数'] or r['対照取引数']]
    positive = [r for r in rows if r['案収支'] > 0]
    best = max(positive, key=lambda r: (r['案収支'], r['セッション'])) if positive else None
    return dict(比較活動場数=len(active), 改善場数=sum(r['収支差'] > 0 for r in active),
        悪化場数=sum(r['収支差'] < 0 for r in active), 同値活動場数=sum(r['収支差'] == 0 for r in active),
        場別差中央値=float(np.median([r['収支差'] for r in active])) if active else None,
        比較活動日数=len(active_days), 改善日数=sum(r['収支差'] > 0 for r in active_days),
        悪化日数=sum(r['収支差'] < 0 for r in active_days),
        日付定義='セッション名の日付で日中・夜間を合算。実時計の暦日分割ではない。',
        最大案黒字場=best['セッション'] if best else None,
        同じ最大案黒字場除外の案収支=sum(r['案収支'] for r in rows) - (best['案収支'] if best else 0.),
        同じ最大案黒字場除外の対照収支=sum(r['対照収支'] for r in rows) - (best['対照収支'] if best else 0.),
        場別=rows, 日付別=daily)


def trade_summary(rows: list[dict]) -> dict:
    """機能: ラベルを先に決めた取引群の全会計を集計する。

    引数: rows(list[dict])。返り値: 群別会計(dict)。
    """
    values = [r['収支'] for r in rows]
    p, loss = sum(max(0., n) for n in values), sum(max(0., -n) for n in values)
    wins, loses, count = sum(n > 0 for n in values), sum(n < 0 for n in values), len(rows)
    return dict(取引数=count, 勝数=wins, 負数=loses, 利益=p, 損失=loss, 収支=sum(values),
        平均一取引収支=sum(values) / count if count else None,
        勝率=wins / count if count else None, 金額損失割合=loss / (p + loss) if p + loss else None,
        平均利益=p / wins if wins else None, 平均負け=loss / loses if loses else None,
        手数料=sum(r['手数料'] for r in rows), 気配差負担=sum(r['気配差負担'] for r in rows),
        平均保有分=sum(r['保有秒'] for r in rows) / count / 60. if count else None)


def seconds_summary(values: list[float]) -> dict:
    """機能: 代理時計上の判断・約定遅延を分布として示す。

    引数: values(list[float])。返り値: 件数・中央値・百分位等(dict)。
    """
    a = np.asarray(values, dtype=float)
    return dict(件数=len(a), 中央値=float(np.median(a)) if len(a) else None,
        九十百分位=float(np.quantile(a, .9)) if len(a) else None,
        最大=float(a.max()) if len(a) else None, 零秒件数=int((a == 0).sum()),
        注記='最終約定の代理時計による秒数。同時計の次原本行は零秒になり得るが実行時間零の証明ではない。')


def counterpart(all_results: dict, c: dict, **changes: object) -> str | None:
    """機能: 指定した一要素だけを変えた固定対照を探索する。

    引数: all_results/c(dict)、changes(dict)。返り値: 一意の対照ID又はなし(str|None)。
    M0は確認秒を使わず、従来入口のM0はF15を代表した重複なしの一条件である。
    """
    fields = ('legacy_entry', 'entry_source', 'signal_id', 'entry_confirm',
              'manage_mode', 'manage_confirm', 'width_fraction', 'hold_seconds')
    target = {k: c[k] for k in fields}
    target.update(changes)
    if target['manage_mode'] == 0:
        target.pop('manage_confirm')
        if target['legacy_entry']:
            target.pop('signal_id')
    found = [ident for ident, r in all_results.items() if all(r['config'][k] == value for k, value in target.items())]
    assert len(found) <= 1, ('対照重複', target, found)
    return found[0] if found else None


def decision_grid(times: np.ndarray, grid: np.ndarray, mapped: np.ndarray, decision: int) -> int:
    """機能: 共通格子が写像された原本判断行から、最新の対応格子を特定する。

    引数: times/grid/mapped(ndarray)、decision(int)。返り値: 格子番号又は-1(int)。
    """
    g = int(np.searchsorted(mapped, decision, side='right') - 1)
    if g < 0 or mapped[g] != decision or times[decision] - grid[g] > 10. + 1e-8:
        return -1
    return g


def trade_details(c: dict, archive: dict, ready: dict, book: dict, states: dict, grids: dict) -> tuple[list[dict], dict]:
    """機能: 入口・返済判断の過去状態ラベルを先に作り、既存決済会計を結び付ける。

    引数: c/archive/ready/book/states/grids(dict)。返り値: 全決済明細と判断遅延(list[dict],dict)。
    新しい損益再生は行わず、返済後情報を状態分類へ参照しない。
    """
    rows, latencies = [], defaultdict(list)
    for key, ledger in archive.items():
        session, symbol = key
        times = ready[key]['time_s']
        st = states[c['signal_id']][session]
        mapped = np.searchsorted(times, st['grid'], side='left')
        entries = {int(o[2]): o for o in ledger['orders'] if o[7] == 1}
        closes = {int(o[2]): o for o in ledger['orders'] if o[7] == 0}
        assert len(entries) == len(closes) == len(ledger['trades'])
        for o in ledger['orders']:
            kind = '新規' if o[7] else '返済'
            delta = float(times[int(o[0])] - times[int(o[1])])
            assert int(o[0]) > int(o[1]) >= 0 and delta >= 0
            latencies[(session, symbol, kind)].append(delta)
        for t in ledger['trades']:
            cid, side = int(t[0]), int(t[3])
            en, ex = entries[cid], closes[cid]
            entry_i, exit_i = int(t[1]), int(t[2])
            assert entry_i == int(en[0]) and exit_i == int(ex[0])
            reason = int(ex[6])
            # ----------------------------------------
            # 返済判断までの弱支持だけを使って、片方・両方の支持消失を分類する。
            support_label = '対象外'
            neutral_label = '対象外'
            evidence = None
            if reason in (6, 7):
                g = decision_grid(times, st['grid'], mapped, int(ex[1]))
                assert g >= 0 and st['valid'][g]
                assert st['grid'][g] <= times[int(ex[1])]
                top_lost, nk_lost = int(st['own_weak'][g]) != side, int(st['peer_weak'][g]) != side
                support_label = '両市場' if top_lost and nk_lost else 'TOPIXのみ' if top_lost else 'NK225のみ' if nk_lost else '両市場支持あり'
                assert reason != 7 or support_label != '両市場支持あり'
                evidence = dict(格子=g, 判断時刻=float(st['grid'][g]),
                    TOP参照行=int(st['source_top'][g]), NK参照行=int(st['source_nk'][g]),
                    TOP強方向=int(st['own_strong'][g]), NK強方向=int(st['peer_strong'][g]),
                    TOP弱方向=int(st['own_weak'][g]), NK弱方向=int(st['peer_weak'][g]))
                assert all(evidence[name] >= 0 for name in ('TOP参照行', 'NK参照行'))
                for s, field in (('TOPIX', 'TOP参照行'), ('NK225', 'NK参照行')):
                    source_time = float(ready[(session, s)]['time_s'][evidence[field]])
                    assert source_time < evidence['判断時刻'] - 5.
                    evidence[s + '参照情報の古さ秒'] = evidence['判断時刻'] - source_time
                signal = c['signal_id']
                if signal.startswith('F'):
                    window = int(signal[2:] if signal.startswith('FD') else signal[1:])
                    poor = {}
                    for s in SYMBOLS:
                        w = grids[session]['markets'][s]['windows'][window]
                        known = bool(w['source_valid'][g] and not w['missing_ofi'][g])
                        small = int(w['nonzero_ofi_count'][g]) < 3
                        poor[s] = known and (bool(w['zero_ofi_denominator'][g]) or small)
                        evidence[s + '非ゼロOFI件数'] = int(w['nonzero_ofi_count'][g])
                        evidence[s + '実参照区間秒'] = float(w['actual_seconds'][g])
                    neutral_label = '両市場' if all(poor.values()) else 'TOPIXのみ' if poor['TOPIX'] else 'NK225のみ' if poor['NK225'] else '少数零OFIなし'
            fee = float(t[7] + t[8])
            mid_entry = float((book[key]['bid'][entry_i] + book[key]['ask'][entry_i]) / 2.)
            mid_exit = float((book[key]['bid'][exit_i] + book[key]['ask'][exit_i]) / 2.)
            value = 1000. if symbol == 'TOPIX' else 10.
            spread = side * (mid_exit - mid_entry) * float(t[4]) * value - float(t[9])
            rows.append(dict(セッション=session, 銘柄=symbol, 取引番号=cid, 方向=side,
                新規理由=int(en[6]), 返済理由=reason, 支持消失箇所=support_label,
                判断時点の少数零OFI=neutral_label, 判断証拠=evidence,
                新規判断行=int(en[1]), 新規行=entry_i, 返済判断行=int(ex[1]), 返済行=exit_i,
                保有秒=float(times[exit_i] - times[entry_i]), 手数料=fee,
                気配差負担=spread, 収支=float(t[10]),
                新規判断から約定秒=float(times[entry_i] - times[int(en[1])]),
                返済判断から約定秒=float(times[exit_i] - times[int(ex[1])])))
    return rows, latencies


def details_period(rows: list[dict], sessions: list[str], symbol: str, summary: dict,
                   archive: dict, latencies: dict) -> dict:
    """機能: 全取引を返済理由・反転・支持消失箇所で分割し総額と照合する。

    引数: rows(list[dict])、sessions(list[str])、symbol(str)、summary/archive/latencies(dict)。
    返り値: 理由別・反転別・遅延診断(dict)。
    """
    part = [r for r in rows if r['セッション'] in sessions and r['銘柄'] == symbol]
    all_stats = trade_summary(part)
    for label, original in (('収支', 'net'), ('利益', 'profit'), ('損失', 'loss'), ('手数料', 'fees'), ('気配差負担', 'spread_drag')):
        assert abs(all_stats[label] - summary[original]) < 1e-5, (label, symbol)
    assert all_stats['取引数'] == summary['trades']
    exits = {label: trade_summary([r for r in part if r['返済理由'] == reason]) for reason, label in REASONS.items()}
    assert sum(r['取引数'] for r in exits.values()) == len(part)
    flips = [r for r in part if r['新規理由'] == 12]
    stats = [a['stats'] for key, a in archive.items() if key[0] in sessions and key[1] == symbol]
    assert len(flips) == sum(int(a[7]) for a in stats)
    return dict(全決済照合=True, 返済理由別=exits,
        保険返済割合=sum(r['返済理由'] in (1, 2) for r in part) / len(part) if part else None,
        反転新規=trade_summary(flips), 通常新規=trade_summary([r for r in part if r['新規理由'] != 12]),
        反転取消数=sum(int(a[8]) for a in stats),
        支持消失返済の箇所別={label: trade_summary([r for r in part if r['返済理由'] == 7 and r['支持消失箇所'] == label])
                         for label in ('TOPIXのみ', 'NK225のみ', '両市場')},
        支持消失判断時の少数零OFI={label: trade_summary([r for r in part if r['返済理由'] == 7 and r['判断時点の少数零OFI'] == label])
                         for label in ('TOPIXのみ', 'NK225のみ', '両市場', '少数零OFIなし', '対象外')},
        管理判断時の最も古い参照秒=seconds_summary([max(r['判断証拠'][s + '参照情報の古さ秒'] for s in SYMBOLS)
                         for r in part if r['判断証拠'] is not None]),
        判断から約定秒={kind: seconds_summary([n for session in sessions for n in latencies.get((session, symbol, kind), [])])
                       for kind in ('新規', '返済')},
        注記='理由別収支は因果効果ではない。反転新規の収支は反転なし対照との差分利益ではない。')


def distribution(results: list[dict]) -> dict:
    """機能: 全固定条件の黒字・無取引・少数取引分布を示す。

    引数: results(list[dict])。返り値: 三期間の分布(dict)。代表は選び直さない。
    """
    out = {}
    for period in PERIODS:
        out[period] = {s: dict(条件数=len(results),
            黒字数=sum(r['periods'][period][s]['net'] > 0 for r in results),
            無取引数=sum(r['periods'][period][s]['trades'] == 0 for r in results),
            二十取引未満数=sum(r['periods'][period][s]['trades'] < 20 for r in results)) for s in SYMBOLS}
        out[period]['両銘柄黒字数'] = sum(all(r['periods'][period][s]['net'] > 0 for s in SYMBOLS) for r in results)
    return out


def main() -> None:
    """機能: 全結果と前半選定が完成した後だけ、固定対照と理由別診断を保存する。

    引数: --states(str)は損益なし状態の保存先、--selection(str)は固定前半選定。
    返り値: なし(None)。分析領域のみ書き込み、ネットワーク通信と条件変更をしない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--states', default='prepared/signals_delay5.pkl')
    parser.add_argument('--grids', default='inputs/grids.pkl')
    parser.add_argument('--selection', default='前半選定.json')
    parser.add_argument('--delay-dir', action='append', default=[])
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    fixed_path, selection_path = WORK / '事前固定.json', WORK / args.selection
    assert fixed_path.exists() and selection_path.exists(), '事前固定と前半選定完成後だけ実行する'
    fixed, selection = load(fixed_path), load(selection_path)
    assert selection['前16だけで選択'] and selection['後13で変更なし']
    result_paths = sorted((WORK / 'results').glob('*.json'))
    assert len(result_paths) == 996, '全996条件完成後だけ実行する'
    results = {r['config']['id']: r for r in (load(p) for p in result_paths)}
    assert len(results) == 996
    specification_path = WORK / 'inputs/入力と即時板特徴の仕様.json'
    specification = load(specification_path)
    paths = [fixed_path, selection_path, specification_path, Path(__file__),
             HERE / '診断方針の事前記録.json', WORK / args.states, WORK / args.grids, *result_paths]
    ready, book = {}, {}
    for name, destination in (('ready', ready), ('book', book)):
        for value in specification['input_paths'][name]:
            path = ROOT / value
            destination.update(load(path))
            paths.append(path)
    states = load(WORK / args.states)
    grids = load(WORK / args.grids)
    if 5 in grids:
        grids = grids[5]
    delays = {}
    for value in args.delay_dir:
        seconds, folder = value.split('=', 1)
        directory = Path(folder) if Path(folder).is_absolute() else WORK / folder
        delays[int(seconds)] = {r['config']['id']: r for r in (load(p) for p in directory.glob('*.json'))}
        paths += list(directory.glob('*.json'))
    main_ids = [a['id'] if isinstance(a, dict) else a for a in selection['主3']]
    representatives, ledger_cache, detail_cache = {}, {}, {}
    # ----------------------------------------
    # 代表の設定だけから対照を列挙し、損益大小で比較相手を変更しない。
    for choice in selection['代表']:
        ident = choice['id'] if isinstance(choice, dict) else choice
        result, c = results[ident], results[ident]['config']
        comparisons = {}
        for mode in (0, 1, 2, 3):
            for confirm in ((0,) if mode == 0 else (15, 30)):
                other = counterpart(results, c, manage_mode=mode, manage_confirm=confirm)
                if other is not None:
                    comparisons[f'管理M{mode}_確認{confirm}秒'] = other
        for value in (0, 10):
            other = counterpart(results, c, entry_confirm=value)
            if other is not None:
                comparisons[f'入口確認{value}秒'] = other
        for width in (.002, .004):
            other = counterpart(results, c, width_fraction=width)
            if other is not None:
                comparisons[f'保険幅{width * 100:.1f}％'] = other
        for hold in (0., 1800.):
            other = counterpart(results, c, hold_seconds=hold)
            if other is not None:
                comparisons['場末まで' if hold == 0 else '保有30分'] = other
        periods = {p: {s: dict(成績=metric(result['periods'][p][s])) for s in SYMBOLS} for p in PERIODS}
        comparison_output = {}
        for label, other in comparisons.items():
            counter = results[other]
            comparison_output[label] = dict(ID=other, 期間別={p: {s: dict(
                **comparison(result['periods'][p][s], counter['periods'][p][s]),
                一貫性=consistency(result, counter, fixed[p], s)) for s in SYMBOLS} for p in PERIODS})
        sensitivity = {}
        for delay, delayed in sorted(delays.items()):
            controls = {ident, *(other for label, other in comparisons.items() if label.startswith('管理'))}
            assert all(other in delayed for other in controls), ('固定遅延感度不足', delay, ident)
            sensitivity[str(delay)] = {}
            for other in sorted(controls):
                r = delayed[other]
                assert r['delay'] == r['config']['delay'] == delay
                assert all(r['config'][k] == results[other]['config'][k]
                           for k in ('signal_id', 'legacy_entry', 'entry_confirm', 'manage_mode',
                                     'manage_confirm', 'width_fraction', 'hold_seconds'))
                sensitivity[str(delay)][other] = {p: {s: comparison(r['periods'][p][s], results[other]['periods'][p][s])
                                                            for s in SYMBOLS} for p in PERIODS}
        # ----------------------------------------
        # 代表と比較対象の台帳を全決済会計に照合し、固定時点の状態分類を添える。
        detail_output = {}
        for other in sorted({ident, *comparisons.values()}):
            r = results[other]
            if other not in ledger_cache:
                path = WORK / 'ledgers' / (other + '.pkl')
                assert digest(path) == r['ledger_SHA256']
                archive = load(path)
                paths.append(path)
                ledger_cache[other] = archive
                detail_cache[other] = trade_details(r['config'], archive, ready, book, states, grids)
            rows, latency = detail_cache[other]
            detail_output[other] = {p: {s: details_period(rows, fixed[p], s, r['periods'][p][s],
                                        ledger_cache[other], latency) for s in SYMBOLS} for p in PERIODS}
        failures = {}
        for symbol in SYMBOLS:
            later = periods['後13'][symbol]['成績']
            bad = []
            if later['収支'] <= 0:
                bad.append('後半費用後収支が正でない')
            if later['平均勝負比'] is None or later['平均勝負比'] <= 1:
                bad.append('後半平均利益対平均負けが一を超えない')
            if later['最大黒字場除外収支'] <= 0:
                bad.append('後半最大黒字場を除くと黒字でない')
            failures[symbol] = bad
        representatives[ident] = dict(前半選定=choice, 主候補=ident in main_ids, 固定設定=c,
            期間別=periods, 同設定比較=comparison_output, 途中と出口の内訳=detail_output,
            後半有望条件の未達内訳=failures, 固定遅延感度=sensitivity)
    groups = {f'管理M{mode}': distribution([r for r in results.values() if r['config']['manage_mode'] == mode]) for mode in (0, 1, 2, 3)}
    groups.update({f'機構{family}': distribution([r for r in results.values() if r['config']['family'] == family]) for family in range(1, 7)})
    output = dict(代表変更なし=True, 条件追加なし=True, API取得数=0, 実注文数=0,
        主候補ID=main_ids, 固定代表=representatives, 全996の分布=distribution(list(results.values())),
        管理と機構別分布=groups,
        基準ID=selection['基準'], 基準成績={p: {s: metric(results[selection['基準']]['periods'][p][s])
                                            for s in SYMBOLS} for p in PERIODS},
        比較解釈='同じ入口候補でも返済が変わると次新規の可否が変わるため、管理対照は売買経路全体の比較。取引数と平均一取引を分ける。',
        反転解釈='M3も反対合意時にはM2と同様に返済後再確認して反転する。支持消失だけなら返済して待つ。',
        速度解釈='5秒格子・5秒遅延・確認時間・次有効原本約定。代理時計上の過去情報であり実受信同期と実行遅延を証明しない。',
        中値解釈='同じ売買行の中値置換は気配差負担の説明用で、入口と出口を再実行した成績ではない。',
        既知期間='前16選定・後13固定確認。ただし29場は旧探索で既知であり完全未知の検証ではない。',
        入力SHA256={str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))})
    target = HERE / '板支持による途中判断の効果と限界.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(照合合格=True, 全条件=len(results), 固定代表=len(representatives), 使用台帳=len(ledger_cache)), ensure_ascii=False))


if __name__ == '__main__':
    main()
