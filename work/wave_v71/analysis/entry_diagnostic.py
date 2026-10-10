"""機能: 管理決済と独立に、実新規気配から方向先着を検証用の未来原本で採点する。"""

import argparse
import json
from pathlib import Path
import pickle
import sys

import numpy as np
from numba import njit


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCES = ('T1L1', 'T2L0', 'T3L1', 'T4L0', 'E01P', 'R01P')
LEVELS = (8, 16)
PERIODS = ('前16', '後12', '全28', '追加1', '全29')


@njit(cache=False)
def _trees(bid, ask):
    """機能: 有効な買売気配の区間最大・最小木を採点専用に作成する。

    引数: bid/ask(ndarray)。返り値: tuple(ndarray4行木,int葉数)。
    木の順序は買最大・買最小・売最大・売最小。無効行は極値に採用しない。
    """
    size = 1
    while size < len(bid):
        size *= 2
    tree = np.empty((4, size * 2), dtype=np.float64)
    tree[0, :] = tree[2, :] = -np.inf
    tree[1, :] = tree[3, :] = np.inf
    for i in range(len(bid)):
        if np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i] > 0 and ask[i] >= bid[i]:
            tree[0, size + i] = tree[1, size + i] = bid[i]
            tree[2, size + i] = tree[3, size + i] = ask[i]
    for node in range(size - 1, 0, -1):
        tree[0, node] = max(tree[0, node * 2], tree[0, node * 2 + 1])
        tree[1, node] = min(tree[1, node * 2], tree[1, node * 2 + 1])
        tree[2, node] = max(tree[2, node * 2], tree[2, node * 2 + 1])
        tree[3, node] = min(tree[3, node * 2], tree[3, node * 2 + 1])
    return tree, size


@njit(cache=False)
def _first(tree, size, channel, start, end, threshold, below):
    """機能: 指定原本範囲で価格が閾値へ初めて達した行を左から探索する。

    引数: tree(ndarray)、size/channel/start/end(int)、threshold(float)、below(bool)。
    返り値: intの最初の原本行。未到達は-1。範囲外の未来行は結果へ使わない。
    """
    if end < start:
        return -1
    nodes = np.empty(128, dtype=np.int64)
    lefts = np.empty(128, dtype=np.int64)
    rights = np.empty(128, dtype=np.int64)
    count = 1
    nodes[0], lefts[0], rights[0] = 1, 0, size - 1
    while count:
        count -= 1
        node, left, right = nodes[count], lefts[count], rights[count]
        if right < start or left > end:
            continue
        extreme = tree[channel, node]
        if (below and extreme > threshold) or (not below and extreme < threshold):
            continue
        if left == right:
            return left
        middle = (left + right) // 2
        nodes[count], lefts[count], rights[count] = node * 2 + 1, middle + 1, right
        nodes[count + 1], lefts[count + 1], rights[count + 1] = node * 2, left, middle
        count += 2
    return -1


@njit(cache=False)
def _extrema(tree, size, high_channel, low_channel, start, end):
    """機能: 指定原本区間の有効気配の最大と最小だけを計算する。

    引数: tree(ndarray)、size/high_channel/low_channel/start/end(int)。
    返り値: tuple(float最大,float最小)。有効観測なしは(-inf,+inf)。
    """
    high, low = -np.inf, np.inf
    left, right = start + size, end + size
    while left <= right:
        if left % 2:
            high = max(high, tree[high_channel, left])
            low = min(low, tree[low_channel, left])
            left += 1
        if right % 2 == 0:
            high = max(high, tree[high_channel, right])
            low = min(low, tree[low_channel, right])
            right -= 1
        left //= 2
        right //= 2
    return high, low


@njit(cache=False)
def _score(tree, size, bid, ask, schedule, tick, end):
    """機能: 同一入口列を実新規価格から±8/16呼値先着と最大順逆行へ採点する。

    引数: tree/bid/ask/schedule(ndarray)、size/end(int)、tick(float)。
    返り値: ndarray12列の採点。入口/判断/方向/建値/8符号行/16符号行/最大順逆行と極値行。
    未来を用いる処理は検証ラベルだけで、入口信号や注文管理へ返さない。
    """
    result = np.zeros((len(schedule), 12), dtype=np.float64)
    for j in range(len(schedule)):
        row, decision, side = int(schedule[j, 0]), int(schedule[j, 1]), int(schedule[j, 3])
        price = ask[row] if side == 1 else bid[row]
        result[j, 0:4] = np.array([float(row), float(decision), float(side), price])
        start = row + 1
        high_channel, low_channel = (0, 1) if side == 1 else (2, 3)
        for k in range(2):
            level = 8.0 if k == 0 else 16.0
            if side == 1:
                forward = _first(tree, size, high_channel, start, end, price + level * tick, False)
                adverse = _first(tree, size, low_channel, start, end, price - level * tick, True)
            else:
                forward = _first(tree, size, low_channel, start, end, price - level * tick, True)
                adverse = _first(tree, size, high_channel, start, end, price + level * tick, False)
            outcome, arrival = 0, -1
            if forward >= 0 and (adverse < 0 or forward < adverse):
                outcome, arrival = 1, forward
            elif adverse >= 0 and (forward < 0 or adverse < forward):
                outcome, arrival = -1, adverse
            result[j, 4 + 2 * k] = outcome
            result[j, 5 + 2 * k] = arrival
        high, low = _extrema(tree, size, high_channel, low_channel, start, end)
        if np.isfinite(high) and np.isfinite(low):
            mfe = max(0.0, ((high - price) if side == 1 else (price - low)) / tick)
            mae = max(0.0, ((price - low) if side == 1 else (high - price)) / tick)
            if mfe > 0:
                mfe_row = _first(tree, size, high_channel if side == 1 else low_channel,
                                 start, end, high if side == 1 else low, side == -1)
            else:
                mfe_row = -1
            if mae > 0:
                mae_row = _first(tree, size, low_channel if side == 1 else high_channel,
                                 start, end, low if side == 1 else high, side == 1)
            else:
                mae_row = -1
            result[j, 8:12] = np.array([mfe, mae, float(mfe_row), float(mae_row)])
        else:
            result[j, 10:12] = -1.0
    return result


def _endpoint(times, bid, ask, limit):
    """機能: 場内返済判断の次有効気配行を採点終端として決める。

    引数: times/bid/ask(ndarray)、limit(float)は場内安全返済時刻。
    返り値: tuple(int終端行,bool完結,int強制返済判断行)。不足時は利用可能終端で右打切る。
    """
    decision = np.flatnonzero(times >= limit - 60.0)
    if not len(decision):
        return len(times) - 1, False, -1
    row = int(decision[0])
    valid = np.flatnonzero(np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid)
                          & (np.arange(len(times)) > row))
    if not len(valid):
        return len(times) - 1, False, row
    return int(valid[0]), True, row


def _summary(labels, level):
    """機能: 一致した入口ラベルの順行先着・逆行先着・未到達を別集計する。

    引数: labels(list[dict])、level(int)は8または16。
    返り値: dictの全入口分母と到達済み分母の両方の確率。空群はNoneで勝ちに数えない。
    """
    name = str(level)
    favorable = sum(r[name]['outcome'] == 1 for r in labels)
    adverse = sum(r[name]['outcome'] == -1 for r in labels)
    total = len(labels)
    unreached = total - favorable - adverse
    censored = sum(r[name]['censored'] for r in labels)
    reached = favorable + adverse
    return {'total': total, 'favorable': favorable, 'adverse': adverse,
            'unreached': unreached, 'censored': censored,
            'favorable_rate_all': favorable / total if total else None,
            'favorable_rate_reached': favorable / reached if reached else None,
            'active_sessions': len(set(r['session'] for r in labels)),
            'mfe_median_ticks': float(np.median([r['mfe_ticks'] for r in labels])) if total else None,
            'mae_median_ticks': float(np.median([r['mae_ticks'] for r in labels])) if total else None,
            'remaining_minutes_median': float(np.median([r['remaining_seconds'] / 60 for r in labels])) if total else None}


def build(ready, features, schedule, periods):
    """機能: 24入口系列を各場で採点し、幅・保険管理に依存しない期間診断を作る。

    引数: ready/features/schedule(dict)は場銘柄原本と24個のN×5共通新規列、
    periods(dict[str,list[str]])は前16/後12/全28/追加1/全29。
    返り値: dict。集計[source_G#][期間][銘柄][str(8/16)]がレポートAPI。
    """
    labels, accounts = [], []
    for key in sorted(ready):
        session, symbol = key
        r, f = ready[key], features[key]
        times = np.asarray(r['time_s'], dtype=np.float64)
        bid, ask = np.asarray(f['bid'], dtype=np.float64), np.asarray(f['ask'], dtype=np.float64)
        if not (len(times) == len(bid) == len(ask)):
            raise ValueError('時刻と両気配の原本行数が一致しません。')
        if len(schedule[key]) != 24:
            raise ValueError('入口列は6入口×4確認の24系列を指定してください。')
        end, complete, closing_decision = _endpoint(times, bid, ask, float(r['limit']))
        tree, size = _trees(bid, ask)
        for source_index, source in enumerate(SOURCES):
            for gate in range(4):
                entries = np.asarray(schedule[key][source_index * 4 + gate], dtype=np.float64).reshape((-1, 5))
                if len(entries):
                    rows = entries[:, 0].astype(np.int64)
                    if (np.any(rows < 0) or np.any(rows >= len(times))
                            or np.any(entries[:, 1] >= rows)
                            or np.any((entries[:, 3] != 1) & (entries[:, 3] != -1))):
                        raise ValueError('入口列の約定行・判断行・方向が不正です。')
                    if not np.all(np.isfinite(bid[rows]) & np.isfinite(ask[rows])
                                  & (bid[rows] > 0) & (ask[rows] >= bid[rows])):
                        raise ValueError('実新規の原本行に有効な両気配がありません。')
                raw = _score(tree, size, bid, ask, entries, float(r['tick']), end)
                current = []
                for cid, a in enumerate(raw):
                    row = int(a[0])
                    item = {'session': session, 'symbol': symbol, 'source': source,
                            'gate': 'G' + str(gate), 'series': source + '_G' + str(gate),
                            'cid': cid, 'fill_i': row, 'decision_i': int(a[1]), 'side': int(a[2]),
                            'entry_price': float(a[3]), 'entry_time_s': float(times[row]),
                            'label_end_i': end, 'label_complete': complete,
                            'remaining_seconds': max(0.0, float(times[end] - times[row])) if end >= 0 else 0.0,
                            'mfe_ticks': float(a[8]), 'mae_ticks': float(a[9]),
                            'mfe_i': int(a[10]), 'mae_i': int(a[11])}
                    for k, level in enumerate(LEVELS):
                        outcome, arrival = int(a[4 + k * 2]), int(a[5 + k * 2])
                        item[str(level)] = {'outcome': outcome, 'arrival_i': arrival,
                                            'arrival_seconds': float(times[arrival] - times[row]) if arrival >= 0 else None,
                                            'censored': bool(not complete and outcome == 0)}
                    current.append(item)
                labels.extend(current)
                accounts.append({'session': session, 'symbol': symbol, 'series': source + '_G' + str(gate),
                                 'closing_decision_i': closing_decision, 'label_end_i': end,
                                 'label_complete': complete,
                                 'levels': {str(level): _summary(current, level) for level in LEVELS}})
        print(json.dumps({'入口採点済み': session, '銘柄': symbol, '採点終端': end,
                          '場内返済まで原本あり': complete}, ensure_ascii=False), flush=True)
    # ----------------------------------------
    # 期間の所属は外から固定して渡す。採点値を見て期間を作り直さない。
    summary = {}
    for source in SOURCES:
        for gate in range(4):
            series = source + '_G' + str(gate)
            summary[series] = {}
            for period in PERIODS:
                if period not in periods:
                    raise ValueError('前16/後12/全28/追加1/全29の固定期間が必要です。')
                sessions = set(periods[period])
                summary[series][period] = {}
                for symbol in ('TOPIX', 'NK225'):
                    selected = [r for r in labels if r['series'] == series and r['symbol'] == symbol
                                and r['session'] in sessions]
                    summary[series][period][symbol] = {str(level): _summary(selected, level) for level in LEVELS}
    comparison = []
    for source in SOURCES:
        for period in PERIODS:
            for symbol in ('TOPIX', 'NK225'):
                for gate in range(1, 4):
                    for level in LEVELS:
                        base = summary[source + '_G0'][period][symbol][str(level)]
                        a = summary[source + '_G' + str(gate)][period][symbol][str(level)]
                        comparison.append({'source': source, 'gate': 'G' + str(gate), 'period': period,
                                           'symbol': symbol, 'level': level, 'base_total': base['total'],
                                           'total': a['total'],
                                           'entry_count_ratio': a['total'] / base['total'] if base['total'] else None,
                                           'rate_all_delta': a['favorable_rate_all'] - base['favorable_rate_all']
                                           if a['total'] and base['total'] else None,
                                           'rate_reached_delta': a['favorable_rate_reached'] - base['favorable_rate_reached']
                                           if a['favorable_rate_reached'] is not None and base['favorable_rate_reached'] is not None else None})
    return {
        '定義': '実新規buyask/sellbidから、後続の返済buybid/sellaskの±8/±16ラージ呼値先着。決済管理と独立。',
        '終端': 'limit−60の最初の場内返済判断行の次有効原本行。不足は右打切り。60分保有期限とは独立。',
        '料金との関係': '方向幅自体は料金前の呼値。気配差は実新規/返済価格に含む。実取引収支は別途往復手数料込み。',
        '未来価格の用途': '採点のみ。入口フィルター・注文管理・前半以外の選び直しへ戻さない。',
        '未到達': '全入口分母では勝ちにしない。到達済み分母の率も併記。censoredは未到達のうち場内返済終端まで原本がない数。',
        'G3': '受信時刻同期を証明できない代理時計参考。主選定対象外。',
        '入口数比': '60分共通枠内の予約時刻も変わり得るため純フィルター採用率ではなく実約定入口数比。',
        'API取得': 0, '実注文': 0, '入口幅設定へ依存': False,
        '集計': summary, '確認強化前後': comparison, '場別': accounts, '入口採点': labels,
    }


def main():
    """機能: rootの固定済み原本・期間を読んで採点を実行しJSONへ保存する。

    引数: コマンド引数--fixed(Path)は損益前固定JSON。
    返り値: None。analysis内の入口方向の独立診断.jsonを保存する。固定前には実行しない。
    """
    parser = argparse.ArgumentParser(description='実新規から方向先着を検証用に採点する。')
    parser.add_argument('--fixed', type=Path, default=ROOT / '事前固定.json')
    args = parser.parse_args()
    if not args.fixed.is_file():
        raise RuntimeError('固定JSONが存在しないため実原本の採点を開始しません。')
    fixed = json.loads(args.fixed.read_text(encoding='utf-8'))
    sys.path.insert(0, str(ROOT))
    import study
    ready, features = study.material()
    schedule = pickle.loads((ROOT / 'inputs/schedule.pkl').read_bytes())
    if 'periods' in fixed:
        periods = fixed['periods']
    else:
        prior = fixed['全セッション'] if '全セッション' in fixed else fixed['全28']
        extra = fixed['追加追試'] if '追加追試' in fixed else fixed['追加1']
        periods = {'前16': fixed['前16'], '後12': fixed['後12'], '全28': prior,
                   '追加1': extra, '全29': prior + extra}
    result = build(ready, features, schedule, periods)
    (HERE / '入口方向の独立診断.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'24系列口座数': len(result['場別']), '実約定入口数': len(result['入口採点']),
                      '保存': '入口方向の独立診断.json'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
