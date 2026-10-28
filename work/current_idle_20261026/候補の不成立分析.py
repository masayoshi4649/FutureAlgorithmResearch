import bisect
import collections
import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'D07夜間再生'


def timestamp(value):
    """時計をUNIX秒へ変換する。

    引数: value(str)は地域指定済みISO時計。
    返り値: floatはUNIX秒。
    """
    return datetime.datetime.fromisoformat(value).timestamp()


def load_raw(reference):
    """再生と同じフィルターで取得済み原板を読み取る。

    引数: reference(str)はNK225またはTOPIX。
    返り値: list[dict]は価格時計、気配、原ファイル行番号。売買は再生しない。
    """
    rows, previous = [], 0
    start = timestamp('2026-10-26T17:00:00+09:00')
    cutoff = timestamp('2026-10-26T18:37:11+09:00')
    with (ROOT / 'data' / f'{reference}_book.jsonl').open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            board = json.loads(line)
            try:
                at = timestamp(board['CurrentPriceTime'])
            except (ValueError, KeyError, TypeError):
                continue
            if not start <= at < cutoff or at < previous or not board.get('CurrentPrice', 0) > 0:
                continue
            previous = at
            bid = (board.get('Buy1') or {}).get('Price', 0)
            ask = (board.get('Sell1') or {}).get('Price', 0)
            rows.append(dict(time=at, clock=board['CurrentPriceTime'], bid=bid, ask=ask,
                             mid=(bid + ask) / 2, valid=bid > 0 and ask > bid, raw_line=number))
    return rows


def end_cause(row, raw, times):
    """候補の取消行について実コードの鮮度判定に必要な根拠を抽出する。

    引数: row(dict)は取消診断、raw(dict)とtimes(dict)は原板と市場別時計。
    返り値: tuple[str,dict]は排他的な分類と時計・気配の根拠。
    """
    detail = row['detail']
    missing = detail['unknown_columns']
    now = timestamp(row['time_jst'])
    evidence = {'unknown_columns': missing, 'bid': detail['bid'], 'ask': detail['ask']}
    if not detail['quote_valid']:
        return '日経の売買気配同値', evidence
    own = 12 in missing or 13 in missing
    peer = 22 in missing
    for column, seconds in [(12, 30), (13, 120)]:
        if column not in missing:
            continue
        index = bisect.bisect_left(times['NK225'], now - seconds, 0, row['index'] + 1) - 1
        old = raw['NK225'][index]
        evidence[f'own_{seconds}s'] = {
            'baseline_clock': old['clock'], 'target_offset_seconds': now - seconds - old['time'],
            'allowed_offset_seconds': 30, 'baseline_quote_valid': old['valid'], 'raw_line': old['raw_line']}
    if peer:
        index = bisect.bisect_left(times['TOPIX'], now) - 1
        old = raw['TOPIX'][index]
        evidence['peer'] = {'last_clock': old['clock'], 'age_seconds': now - old['time'],
                            'allowed_age_seconds': 15, 'raw_line': old['raw_line']}
    if own and peer:
        return '日経短期基準とTOPIX時計の双方が鮮度不足', evidence
    if own:
        return '日経短期変化の基準時計が鮮度不足', evidence
    if peer:
        return 'TOPIXの価格時計が15秒超', evidence
    evidence.update(efficiency=detail['direction_efficiency_40m'], required_efficiency=.35)
    return '方向効率が突破型の0.35未満へ低下', evidence


def main():
    """保存済み再生結果だけを集計し、候補の不成立根拠を保存する。

    引数: なし。返り値: なし。新たな戦略試行・外部通信は行わない。
    """
    raw = {market: load_raw(market) for market in ['NK225', 'TOPIX']}
    times = {market: [row['time'] for row in rows] for market, rows in raw.items()}
    logs = [json.loads(line) for line in (OUT / '起動1700_判断推移.jsonl').read_text(encoding='utf-8').splitlines()]
    lifecycles = []
    for owner in ['addon', 'episode']:
        active = None
        for row in logs:
            if row.get('kind') != '入口状態' or row['detail']['owner'] != owner:
                continue
            detail = row['detail']
            if detail['arm'] and active is None:
                active = {'start': row, 'observed_states': [row]}
            elif detail['arm'] and active is not None:
                active['observed_states'].append(row)
            elif not detail['arm'] and active is not None:
                initial = active['start']['detail']
                begin = active['start']['index']
                mids = [r['mid'] for r in raw['NK225'][begin:row['index']] if r['valid']]
                side, risk, level = initial['arm'], initial['arm_risk'], initial['arm_level']
                extreme, best_rebound = mids[0], 0
                for price in mids:
                    extreme = min(extreme, price) if side == 1 else max(extreme, price)
                    best_rebound = max(best_rebound, side * (price - extreme))
                cause, evidence = end_cause(row, raw, times)
                lifecycle = {
                    'owner': owner, 'side': side, 'start': active['start']['time_jst'], 'end': row['time_jst'],
                    'start_index': begin, 'end_index': row['index'], 'boundary': level, 'risk': risk,
                    'first_mid': mids[0], 'minimum_mid': min(mids), 'maximum_mid': max(mids),
                    'maximum_directional_boundary_distance': max(side * (price - level) for price in mids),
                    'maximum_running_rebound_points': best_rebound,
                    'breakout_progress_required': .5 * risk if owner == 'addon' else None,
                    'range_rebound_required': .25 * risk if owner == 'episode' else None,
                    'highest_stage': max(r['detail']['stage'] for r in active['observed_states']),
                    'continuous_confirmation_started': any(r['detail']['since_known'] for r in active['observed_states']),
                    'cancel_category': cause, 'cancel_evidence': evidence,
                    'start_detail': initial, 'last_observed_before_cancel': active['observed_states'][-1],
                }
                lifecycles.append(lifecycle)
                active = None
        if active is not None:
            raise RuntimeError('終端に未整理の候補が残っています')
    categories = collections.Counter(row['cancel_category'] for row in lifecycles)
    count_by_owner = collections.Counter(row['owner'] for row in lifecycles)
    all_addon_under_progress = all(row['maximum_directional_boundary_distance'] < row['breakout_progress_required']
                                   for row in lifecycles if row['owner'] == 'addon')
    result = {
        'scope': '2026-10-26_Night、17:00起動、18:37:11排他的終端までの確定済み再生を再集計',
        'candidate_count': len(lifecycles), 'candidate_counts': dict(count_by_owner),
        'cancellation_categories': dict(categories),
        'all_addon_progress_unmet_before_cancel': all_addon_under_progress,
        'confirmation_start_count': sum(row['continuous_confirmation_started'] for row in lifecycles),
        'lifecycles': lifecycles,
        'limits': [
            '欠測はアルゴリズムの有効性判定であり、通信断を証明しない。価格時計が進まない板行も元データに含む。',
            '診断の理由別原行件数は滞在時間率ではない。',
            '取消をなくす反実仮想は未実施。欠測取消を緩和すれば取引や利益が増えるとは結論しない。',
            '気配同値は現在実装が無効とする条件であり、市場そのものの異常とは断定しない。',
        ],
    }
    (OUT / '全候補ライフサイクル.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# D07夜間の無取引理由（2026年10月26日）', '',
             '17:00起動の確定済み再生を集計した。追加の戦略試行・条件変更は行っていない。', '',
             '**追加枠の買い候補13回、別入口の売り候補6回。全19回で発注前の30秒連続確認まで到達しなかった。**', '',
             '主枠5枚は22:52まで時間条件で待機する。残る3枚・2枚枠は監視していたが、候補成立から発注成立まで進まなかった。', '',
             '| 取消の直接理由 | 件数 |', '| --- | ---: |']
    lines.extend(f'| {name} | {number} |' for name, number in categories.items())
    lines += ['', '有効性不足による取消は18/19回。ただし追加枠13回は、取消までの原板を全て確認しても、最初の「境界から0.5R進む」という価格条件自体に届いていない。取消だけを原因にすることはできない。', '',
              '## 具体例', '',
              '- **17:42:27、追加枠の買い候補**：境界62,715、R=215。次段階に進む価格は62,822.5。候補中の正常気配中値は最高62,735で未達。17:43:01には方向効率が0.3761から0.3462となり、突破型の必要値0.35を下回って取消。',
              '- **17:44:33、追加枠の買い候補**：境界62,715、R=215、同じく必要62,822.5。最高62,735で未達。17:44:47に参照TOPIXの価格時計が17:44:21となって26秒経過し、15秒条件を超えて取消。受信停止だったとまでは言えない。',
              '- **18:19:49、別入口の売り候補**：境界62,865、R=102.5。少なくとも高値から25.625ptの反落が必要。候補中は最高62,860から最安62,845への15ptしかなく未達。18:20:58の30秒比較に使える直前基準は18:19:49で、比較目標18:20:28より39秒古い。許容30秒を超え、方向値を未知として取消。', '',
              '## 全候補', '', '| 枠 | 方向 | 候補開始 | 取消 | 境界 | R | 気配中値の最小〜最大 | 直接の取消理由 |',
              '| --- | --- | --- | --- | ---: | ---: | --- | --- |']
    for item in lifecycles:
        lines.append(f"| {item['owner']} | {'買い' if item['side'] == 1 else '売り'} | {item['start'][11:19]} | {item['end'][11:19]} | {item['boundary']:g} | {item['risk']:g} | {item['minimum_mid']:g}〜{item['maximum_mid']:g} | {item['cancel_category']} |")
    lines += ['', '## 解釈の限界', ''] + [f'- {item}' for item in result['limits']]
    lines += ['', '再生原板はCurrentPriceTime順で、当時の受信時計・miniの発注気配・実口座は再現していない。発注判断も独立源候補も0だった事実と、実稼働の受信経路まで完全一致したとの主張は区別する。', '']
    (OUT / '候補不成立の具体例.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'lifecycles'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
