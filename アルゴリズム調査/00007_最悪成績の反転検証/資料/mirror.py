"""元手法を仮想運転した約定イベントに従い、反対側の板で全建玉を再評価する。"""

from __future__ import annotations

import hashlib
import heapq
import json
from pathlib import Path
import pickle
import time

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / 'wave_v11'
COMPLETE = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
            '2026-09-22_Night', '2026-09-23_Day']
DETAIL_COLUMNS = ['条件index', 'セルindex', '元配列種別', '元建玉番号', '元方向',
                  '元新規行', '元返済評価行', '元返済済', '元ATR', '元新規価格', '元返済評価価格',
                  '元純益点', '元mid値動き益点', '元入口出口半spread点', '元追加費用点',
                  '理論反転純益点', '入口出口spread点',
                  '容量反転新規行', '容量反転返済評価行', '容量反転返済済',
                  '容量反転新規価格', '容量反転返済評価価格', '容量反転純益点',
                  '次行反転新規行', '次行反転返済評価行', '次行反転返済済',
                  '次行反転新規価格', '次行反転返済評価価格', '次行反転純益点']


def save(path: Path, value: object) -> None:
    """機能: 日本語の検証記録を UTF-8 の JSON に保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def load_archive() -> tuple[list, dict, dict, dict]:
    """機能: 凍結済みの全条件・入力・原取引を変更せず読み込む。

    引数: なし。返り値: 条件・形式・再生入力・取引ブロック (tuple)。
    """
    configs = json.loads((SOURCE / '条件一覧.json').read_text(encoding='utf-8'))
    schema = json.loads((SOURCE / '数値形式.json').read_text(encoding='utf-8'))
    with (SOURCE / '再生入力.pkl').open('rb') as stream:
        prepared = pickle.load(stream)
    blocks = {}
    with np.load(SOURCE / '全売買数値.npz') as archive:
        for engine, rows in archive.items():
            for key, at in pd.DataFrame(rows[:, :2]).groupby([0, 1]).indices.items():
                blocks[tuple(map(int, key))] = rows[at, 2:]
    assert schema['条件'] == [c['id'] for c in configs]
    return configs, schema, prepared, blocks


def original_components(ready: dict, raw: np.ndarray) -> dict:
    """機能: 元純益と同時点反転純益を板・追加費用・mid変化へ厳密分解する。

    引数: ready (dict)、raw (ndarray)。返り値: 各脚の価格分解 (dict)。
    """
    first, last, side = raw[:, 4].astype(int), raw[:, 5].astype(int), raw[:, 1]
    entry_spread = ready['ask'][first] - ready['bid'][first]
    exit_spread = ready['ask'][last] - ready['bid'][last]
    mid = (ready['bid'] + ready['ask']) / 2
    movement = side * (mid[last] - mid[first])
    spread = entry_spread + exit_spread
    fee = np.full(len(raw), 2 * ready['tick'])
    original = movement - spread / 2 - fee
    reverse = -movement - spread / 2 - fee
    np.testing.assert_allclose(original, raw[:, 14], atol=1e-8)
    np.testing.assert_allclose(reverse, -original - spread - 2 * fee, atol=1e-8)
    return dict(original=original, reverse=reverse, movement=movement, spread=spread, fee=fee)


def quantity_shortfalls(ready: dict, raw: np.ndarray) -> list[dict]:
    """機能: 同じ板行・同じ反転売買方向へ必要な枚数を合算し数量不足を検査する。

    引数: ready (dict)、raw (ndarray)。返り値: 数量不足行の一覧 (list[dict])。
    """
    used = {}
    for row in raw:
        first, last = int(row[4]), int(row[5])
        side = 'bid' if row[1] > 0 else 'ask'
        used[(first, side)] = used.get((first, side), 0) + 1
        if row[13]:
            side = 'ask' if row[1] > 0 else 'bid'
            used[(last, side)] = used.get((last, side), 0) + 1
    return [dict(板行=i, 原本行=int(ready['seq'][i]), 側=side, 必要枚数=q,
                 板枚数=float(ready[side + '_qty'][i]))
            for (i, side), q in sorted(used.items()) if q > ready[side + '_qty'][i]]


def replay_capacity(ready: dict, raw: np.ndarray, cap: int, lag: int = 0) -> tuple[np.ndarray, dict]:
    """機能: 反転注文を数量共有・実保有上限・返済優先で待機させ、実現可能な価格を得る。

    引数: ready (dict)、raw (ndarray)、cap (int)、lag (int)。
    返り値: 各脚の新規行/末尾行/返済済/新規価格/返済評価価格/純益点と監査値 (tuple)。
    lag=0 は同時点の数量考慮参考計算、lag=1 は元約定を観測した次行発注。
    """
    count = len(raw)
    result = np.zeros((count, 6))
    result[:, :2] = -1
    if count == 0:
        return result, dict(数量待ち行数=0, 上限待ち行数=0, 新規取消数=0, 返済不成立数=0,
                            新規遅延数=0, 返済遅延数=0, 最大実保有枚数=0)
    # ----------------------------------------
    # 状態は未発火・新規待機・保有・返済待機・返済済・新規取消の順に 0..5 とする。
    states = np.zeros(count, dtype=np.int8)
    final = min(len(ready['seq']) - 1,
                int(np.searchsorted(ready['time_s'], ready['limit'] + 300, side='left')) - 1)
    queue = []
    for j, row in enumerate(raw):
        heapq.heappush(queue, (int(row[4]), 2, j, 0))
        if row[13]:
            heapq.heappush(queue, (int(row[5]), 0, j, 1))
    quantities, cap_waits, gross, peak_gross = 0, 0, 0, 0
    current, remaining_bid, remaining_ask = -1, 0., 0.
    while queue:
        i, priority, j, kind = heapq.heappop(queue)
        if i > final:
            break
        if i != current:
            current = i
            remaining_bid, remaining_ask = ready['bid_qty'][i], ready['ask_qty'][i]
        side = -raw[j, 1]
        if kind == 0:
            states[j] = 1
            heapq.heappush(queue, (i + lag, 3, j, 2))
            continue
        if kind == 1:
            if states[j] == 1:
                states[j] = 5
            elif states[j] == 2:
                states[j] = 3
                heapq.heappush(queue, (i + lag, 1, j, 3))
            continue
        opening = kind == 2
        if states[j] != (1 if opening else 3):
            continue
        use_ask = side > 0 if opening else side < 0
        available = remaining_ask if use_ask else remaining_bid
        if opening and gross >= cap:
            cap_waits += 1
            heapq.heappush(queue, (i + 1, priority, j, kind))
            continue
        if available < 1:
            quantities += 1
            heapq.heappush(queue, (i + 1, priority, j, kind))
            continue
        if use_ask:
            remaining_ask -= 1
        else:
            remaining_bid -= 1
        price = ready['ask'][i] if use_ask else ready['bid'][i]
        if opening:
            states[j] = 2
            result[j, 0], result[j, 3] = i, price
            gross += 1
            peak_gross = max(peak_gross, gross)
        else:
            states[j] = 4
            result[j, 1:3], result[j, 4] = [i, 1], price
            gross -= 1
        assert 0 <= gross <= cap
    # ----------------------------------------
    # 未返済は同じ原板末尾で費用を予約した清算価値として残す。
    for j, row in enumerate(raw):
        if states[j] == 1:
            states[j] = 5
        if result[j, 0] < 0:
            continue
        if states[j] in (2, 3):
            result[j, 1] = final
            result[j, 4] = ready['bid'][final] if -row[1] > 0 else ready['ask'][final]
        result[j, 5] = -row[1] * (result[j, 4] - result[j, 3]) - 2 * ready['tick']
    active = result[:, 0] >= 0
    closed = result[:, 2] == 1
    values = dict(数量待ち行数=quantities, 上限待ち行数=cap_waits,
                  新規取消数=int((~active).sum()),
                  返済不成立数=int((active & ~closed & (raw[:, 13] == 1)).sum()),
                  新規遅延数=int((active & (result[:, 0] > raw[:, 4])).sum()),
                  返済遅延数=int((closed & (result[:, 1] > raw[:, 5])).sum()), 最大実保有枚数=peak_gross)
    return result, values


def financial_columns(prefix: str, net: np.ndarray, closed: np.ndarray,
                      active: np.ndarray, tick: float, multiplier: int) -> dict:
    """機能: 確定利益・確定損失・未返済評価と費用倍評価を別々に集計する。

    引数: prefix (str)、net/closed/active (ndarray)、tick (float)、multiplier (int)。
    返り値: 接頭辞を付けた集計列 (dict)。
    """
    realized = net[active & closed] * multiplier
    opened = net[active & ~closed] * multiplier
    return {prefix + key: value for key, value in dict(
        取引数=int((active & closed).sum()), 未返済数=int((active & ~closed).sum()),
        勝ち数=int((realized > 0).sum()), 負け数=int((realized < 0).sum()),
        利益円=float(realized[realized > 0].sum()), 損失円=float(-realized[realized < 0].sum()),
        収支円=float(realized.sum()), 評価損益円=float(opened.sum()),
        総評価円=float(realized.sum() + opened.sum()),
        費用倍収支円=float(realized.sum() - (active & closed).sum() * 2 * tick * multiplier),
        費用倍総評価円=float(net[active].sum() * multiplier - active.sum() * 2 * tick * multiplier),
    ).items()}


def process_cell(ready: dict, raw: np.ndarray, config: dict, config_i: int,
                 cell_i: int) -> tuple[dict, np.ndarray, list[dict]]:
    """機能: 一条件・一セッション・一銘柄について価格反転と数量考慮反転を比較する。

    引数: ready/config (dict)、raw (ndarray)、config_i/cell_i (int)。
    返り値: 集計・全脚数値・数量不足記録 (tuple)。
    """
    multiplier = 1000 if ready['symbol'] == 'NK225' else 10000
    tick, cap = ready['tick'], config.get('max_positions', 1)
    parts = original_components(ready, raw)
    shortages = quantity_shortfalls(ready, raw)
    capacity, audit = replay_capacity(ready, raw, cap, lag=0)
    delayed, audit_delay = replay_capacity(ready, raw, cap, lag=1)
    closed, active = raw[:, 13] == 1, np.ones(len(raw), dtype=bool)
    row = dict(方式=config['id'], 思想=config['philosophy'], 系統=config['family'],
               群=config.get('group', config['family']), セッション=ready['session'], 銘柄=ready['symbol'],
               設定最大枚数=cap, 同時点反転数量不足行数=len(shortages))
    row.update(financial_columns('元', parts['original'], closed, active, tick, multiplier))
    row.update(financial_columns('理論反転', parts['reverse'], closed, active, tick, multiplier))
    for prefix, result, diagnostics in [('容量反転', capacity, audit), ('次行反転', delayed, audit_delay)]:
        row.update(financial_columns(prefix, result[:, 5], result[:, 2] == 1,
                                     result[:, 0] >= 0, tick, multiplier))
        row.update({prefix + key: value for key, value in diagnostics.items()})
        row[prefix + '全返済要件'] = diagnostics['返済不成立数'] == 0
        row[prefix + '枚数上限換算収支円'] = row[prefix + '収支円'] / cap
    for mask, suffix in [(closed, ''), (active, '評価込み')]:
        row['元mid値動き益' + suffix + '円'] = float(parts['movement'][mask].sum() * multiplier)
        row['元半spread' + suffix + '円'] = float(parts['spread'][mask].sum() / 2 * multiplier)
        row['元追加費用' + suffix + '円'] = float(parts['fee'][mask].sum() * multiplier)
        row['元実効費用' + suffix + '円'] = row['元半spread' + suffix + '円'] + row['元追加費用' + suffix + '円']
        row['両売買spread' + suffix + '円'] = float(parts['spread'][mask].sum() * multiplier)
        row['両売買追加費用' + suffix + '円'] = float(2 * parts['fee'][mask].sum() * multiplier)
    row['単純符号反転との差円'] = row['理論反転収支円'] + row['元収支円']
    row['容量制約価格差円'] = row['容量反転総評価円'] - row['理論反転総評価円']
    base = np.column_stack([np.full(len(raw), config_i), np.full(len(raw), cell_i),
                            np.full(len(raw), int(config['engine'] == 'orders')),
                            raw[:, 0], raw[:, 1], raw[:, 4], raw[:, 5], raw[:, 13], raw[:, 6],
                            raw[:, 7], raw[:, 8], parts['original'], parts['movement'], parts['spread'] / 2,
                            parts['fee'], parts['reverse'], parts['spread'], capacity, delayed])
    return row, base, shortages


def export_trades(details: np.ndarray, schema: dict, prepared: dict,
                  ids: list[str], path: Path) -> None:
    """機能: 指定代表の次行反転売買を図解用の時刻・価格・方向の JSON にする。

    引数: details (ndarray)、schema/prepared (dict)、ids (list[str])、path (Path)。
    返り値: なし (None)。新規未約定取消は取引一覧に混入させない。
    """
    rows = []
    allowed = {i for i, name in enumerate(schema['条件']) if name in ids}
    for item in details:
        condition_i, cell_i = int(item[0]), int(item[1])
        if condition_i not in allowed or item[23] < 0:
            continue
        session, symbol = schema['セル'][cell_i]
        ready = prepared[(session, symbol)]
        first, last = int(item[23]), int(item[24])
        multiplier = 1000 if symbol == 'NK225' else 10000
        rows.append(dict(method=schema['条件'][condition_i], session=session, symbol=symbol,
                         execution='次行反転', entry=float(ready['time_s'][first]), ep=float(item[26]),
                         exit=float(ready['time_s'][last]), xp=float(item[27]), side=int(-item[4]),
                         closed=bool(item[25]), net=float(item[28] * multiplier),
                         entry_seq=int(ready['seq'][first]), exit_seq=int(ready['seq'][last]),
                         original_entry=float(ready['time_s'][int(item[5])]),
                         original_exit=float(ready['time_s'][int(item[6])]),
                         original_net=float(item[11] * multiplier)))
    save(path, rows)


def main() -> None:
    """機能: 全保存取引の反転・数量再生・費用分解を実行し、独立検査用数値を保存する。

    引数: なし。返り値: なし (None)。ネットワーク通信と現在 API 取得は行わない。
    """
    started = time.monotonic()
    protected = ['条件一覧.json', '数値形式.json', '全売買数値.npz', '再生入力.pkl',
                 '全条件_セッション集計.csv', 'single.py', 'orders.py']
    hashes = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in protected}
    configs, schema, prepared, blocks = load_archive()
    rows, details, shortages = [], [], []
    for cell_i, key in enumerate(schema['セル']):
        ready = prepared[tuple(key)]
        for config_i, config in enumerate(configs):
            raw = blocks.get((config_i, cell_i), np.empty((0, 24 if config['engine'] == 'orders' else 21)))
            row, detail, scarce = process_cell(ready, raw, config, config_i, cell_i)
            rows.append(row)
            if len(detail):
                details.append(detail)
            shortages.extend(dict(方式=config['id'], セッション=key[0], 銘柄=key[1], **r) for r in scarce)
        print(f'{key}: {len(configs)} 条件を反転、{time.monotonic() - started:.1f} 秒', flush=True)
    # ----------------------------------------
    # 原会計と全脚の入力不変性を確認し、保存する。
    frame = pd.DataFrame(rows)
    original = pd.read_csv(SOURCE / '全条件_セッション集計.csv').set_index(['方式', 'セッション', '銘柄'])
    check = frame.set_index(['方式', 'セッション', '銘柄']).loc[original.index]
    for column in ['取引数', '未返済数', '利益円', '損失円', '収支円', '評価損益円']:
        np.testing.assert_allclose(check['元' + column], original[column], atol=1e-7)
    for name, expected in hashes.items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == expected, name
    all_details = np.vstack(details)
    frame.to_csv(OUT / '反転_全条件セッション集計.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(shortages).to_csv(OUT / '反転_同時点数量不足.csv', index=False, encoding='utf-8-sig')
    np.savez_compressed(OUT / '反転_全取引数値.npz', 反転=all_details)
    save(OUT / '反転_数値形式.json', dict(列=DETAIL_COLUMNS, 条件=schema['条件'], セル=schema['セル'],
         説明='各行は元建玉と一対一対応。新規行 -1 は未約定取消。純益点は往復追加費用 2 呼値控除済み。'))
    export_trades(all_details, schema, prepared, ['P_P16_05'], OUT / '反転_代表取引.json')
    save(OUT / '反転_実行記録.json', dict(条件数=len(configs), セル数=len(frame), 全脚数=len(all_details),
         同時点反対側数量不足行数=len(shortages), 現在API取得数=0, 原本SHA256=hashes,
         実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 秒=time.monotonic() - started,
         定義=dict(理論反転='元の同一新規・返済行で反対側気配を使用。数量制約のない分解値。',
                   容量反転='同時点の数量考慮参考計算。同一元約定行から反対側 L1 枚数を共有し、不足分は次行待機。返済優先、実保有上限厳守。因果的な主評価は次行反転。',
                   次行反転='元仮想約定イベントを観測した次の原板行から反転注文。数量共有・上限は容量反転と同じ。',
                   元mid値動き益='元方向×新規返済mid差。元純益=この値−入口出口halfspread−往復追加費用。',
                   部分セッション='未返済を末尾清算価値に含める。既知部分セッションは条件選択に使用しない。',
                   適用限界='元の板は最終約定時計であり受信時計ではない。同時刻内は原本行順。最良気配の再補充・市場影響は完全再現できない。')))
    print(json.dumps(dict(セル数=len(frame), 脚数=len(all_details), 秒=time.monotonic() - started), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
