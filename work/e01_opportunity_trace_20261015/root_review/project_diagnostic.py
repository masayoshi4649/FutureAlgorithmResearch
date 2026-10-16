"""完成した当時窓診断を一読し、元公開と後の資格を小さく集計する。"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE.parent
SYMBOLS = ('TOPIX', 'NK225')
PROFILES = ('VOL_SELECTED', 'PRICE_BOTH', 'VOL_SELECTED_PRICE_BOTH')
ZONE = timezone(timedelta(hours=9))


def time_text(point: dict) -> str:
    """
    機能: 保存価格時計を日本時間の表示へ変換する。
    引数: point(dict)は価格時計代理を含む観測点。
    返り値: strは表示時刻。真の受信時刻とはしない。
    """
    return datetime.fromtimestamp(point['price_time_s'], ZONE).isoformat()


def main() -> None:
    """
    機能: 全33場の診断結果を一読し、初回不成立後の現在資格を分離する。
    引数: なし。初回失敗と修正診断は同じ33場の観測とする。
    返り値: None。新規注文、未来先着率、利益機会の判定は作らない。
    """
    path = WORK / 'prepare_v2/元公開と紙上継続窓の資格診断.json'
    content = path.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    assert sha == 'ec3fe4293dbaefe3ecb11a2c6cf1301bb2a5a857cd2ac58ff218226d356c01f7'
    result = json.loads(content.decode('utf-8-sig'))
    assert result['全合格'] and len(result['sessions']) == len(result['cases']) == 33
    assert result['読取計数']['TradeGate本文一読'] == result['読取計数']['TradeExit本文一読'] == 33
    assert result['金融'] == result['元111実台帳'] == result['原NPZ'] == result['原board'] == result['API'] == 0
    aggregates = {}
    by_session = {}
    example_candidates = {s: [] for s in SYMBOLS}
    checks = 0
    for symbol in SYMBOLS:
        reasons = Counter()
        counts = Counter()
        phase_profiles = {name: Counter() for name in PROFILES}
        all_profiles = {side: {name: Counter() for name in PROFILES} for side in ('BUY', 'SELL')}
        for session in result['sessions']:
            a = result['cases'][session]['accounts'][symbol]
            publications = a['original_publications']
            episodes = a['paper_direction_episodes']
            assert len(publications) == a['counts']['original_publications']
            assert len(episodes) == a['counts']['paper_direction_episodes']
            pub_by_parent = {}
            for p in publications:
                key = (p['paper_parent'], p['original_feed_side'])
                assert key not in pub_by_parent
                pub_by_parent[key] = p
                reasons[str(p['qualification_reason_without_actual_state'])] += 1
            counts['元公開'] += len(publications)
            counts['紙上方向区間'] += len(episodes)
            buy = a['all_normal_directional_qualification']['BUY']
            sell = a['all_normal_directional_qualification']['SELL']
            assert buy['normal_observations'] == sell['normal_observations']
            counts['全normal観測'] += buy['normal_observations']
            counts['全価格時計値'] += buy['price_clock_values']
            session_counts = Counter(元公開=len(publications), 紙上方向区間=len(episodes))
            for name in PROFILES:
                for side in ('BUY', 'SELL'):
                    values = a['all_normal_directional_qualification'][side]['profiles'][name]
                    assert 0 <= values['qualified_with_common_market_observations'] <= values['window_qualified_observations'] <= buy['normal_observations']
                    assert values['qualified_price_clock_values'] <= values['qualified_with_common_market_observations']
                    assert values['continuous_qualified_normal_runs'] <= values['qualified_with_common_market_observations']
                    all_profiles[side][name].update(values)
                    checks += 3
                assert buy['profiles'][name]['window_qualified_observations'] + sell['profiles'][name]['window_qualified_observations'] <= buy['normal_observations']
                checks += 1
            for episode in episodes:
                p = pub_by_parent[(episode['paper_parent'], episode['side'])]
                for name in PROFILES:
                    values = episode['profiles'][name]
                    later = values['market_qualified_later_rows']
                    assert 0 <= later <= values['window_qualified_later_rows'] <= episode['later_normal_observations']
                    assert (values['first_later'] is not None) == (later > 0)
                    assert (values['last_later'] is not None) == (later > 0)
                    checks += 3
                    q = phase_profiles[name]
                    q['区間'] += 1
                    initial = p['market_eligible_without_actual_state'][name]
                    q['元公開時資格成立'] += int(initial)
                    q['元公開時資格不成立'] += int(not initial)
                    q['後で資格が成立する区間'] += int(later > 0)
                    q['初回不成立後に成立する区間'] += int(not initial and later > 0)
                    q['後の資格観測'] += later
                    if not initial and later > 0:
                        session_counts[name + '_初回不成立後成立'] += 1
                    if later:
                        first = values['first_later']
                        assert first['normal_row'] > p['normal_row'] and first['raw_seq'] > p['raw_seq']
                        assert first['side'] == episode['side'] and first['market_eligible_without_actual_state'][name]
                        checks += 2
                    if name == 'VOL_SELECTED_PRICE_BOTH' and not initial and later > 0:
                        first = values['first_later']
                        example_candidates[symbol].append(dict(
                            session=session, paper_parent=episode['paper_parent'], side=episode['side'],
                            original=p, later=first, 元表示時刻=time_text(p), 後の表示時刻=time_text(first),
                            遅れ価格時計代理秒=first['price_time_s'] - p['price_time_s'],
                            source='両市場価格と自出来高の現在資格が、初回不成立後に成立した最初の観測。未来損益不使用。'))
            by_session.setdefault(session, {})[symbol] = dict(session_counts)
        aggregates[symbol] = dict(counts=counts, 暫定公開理由=reasons,
                                 紙上区間=phase_profiles, 全normal両方向=all_profiles)

    # ----------------------------------------
    # 例は時系列先頭を採り、損益による選び直しをしない。
    examples = {s: example_candidates[s][:2] for s in SYMBOLS}
    output = dict(全合格=True, source_path=path.relative_to(ROOT).as_posix(), source_SHA256=sha,
                  結果読取=1, 算術検査数=checks, 対象場=33, 集計=aggregates, 場別=by_session, 例=examples,
                  初版読取='同じ33場の66cache。最終JSON保存失敗。',
                  修正版読取='同じ33場の66cache。保存型修正目的。新しい独立場や有効性標本ではない。',
                  非金融=True, 新金融=0, 元実台帳=0, 原板=0, API=0,
                  未測=['実busy/場停止/FAK失効との交差', '最後の実方向票のfresh seq', '新手法の先着率・損益'],
                  注意='元PUB・紙上方向区間・normal観測・価格時計値を区別。全normal共通資格は公開費用や実保有を含まない。')
    (HERE / '初回不成立後の現在資格と別母集団の小集計.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(全合格=True, 算術検査数=checks,
                          集計={s: dict(数=aggregates[s]['counts'], 理由=aggregates[s]['暫定公開理由'], 紙上区間=aggregates[s]['紙上区間']) for s in SYMBOLS},
                          新金融=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
