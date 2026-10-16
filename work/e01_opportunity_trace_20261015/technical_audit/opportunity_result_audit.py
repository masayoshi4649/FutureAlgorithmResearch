"""完成非金融診断を一目的一読で独立再集計し、機会・勝率との混同を防ぐ。"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT/'work/e01_opportunity_trace_20261015'
CAPTURE = HERE/'captured_opportunity_result'
OUTPUT = HERE/'初回不成立後の現在資格と別分母の独立小集計監査.json'
PROFILES = ('VOL_SELECTED', 'PRICE_BOTH', 'VOL_SELECTED_PRICE_BOTH')
SOURCE_SHA = 'ec3fe4293dbaefe3ecb11a2c6cf1301bb2a5a857cd2ac58ff218226d356c01f7'
CHECKS = Counter()


def check(ok: bool, label: str) -> None:
    """
    機能: 保存点から検算可能な条件だけを分類して確認する。
    引数: ok(bool)、label(str) は条件と分類。
    返り値: None。不一致は停止し、未保存を補わない。
    """
    assert bool(ok), label
    CHECKS[label] += 1


def capture(relative: str, name: str, expected: str | None = None) -> tuple[dict, str]:
    """
    機能: 根授権の完成結果又は小射影を各一読し、解析前に同bytesを私有保全する。
    引数: relative/name(str)、expected(str|None) は許可された位置・別名・指定指紋。
    返り値: tuple[dict,str] は保全内容とSHA256。元cache/旧金融/台帳は取得しない。
    """
    path = ROOT/relative
    check(path.resolve().is_relative_to(WORK) and path.stat().st_size < 20*1024*1024, '許可二小結果だけを読む')
    saved = path.read_bytes()
    digest = hashlib.sha256(saved).hexdigest()
    if expected:
        check(digest == expected, '根の指定完成結果SHA')
    target = CAPTURE/name
    check(not target.exists(), 'parse前の同bytes保全を上書きしない')
    target.write_bytes(saved)
    return json.loads(saved), digest


def point(value: dict, symbol: str) -> None:
    """
    機能: 保存点の方向票、予定料金、価格支持、資格交差を独立算術で検算する。
    引数: value(dict)、symbol(str) は一保存点と商品。
    返り値: None。省略された正常行や共通受信時刻は作らない。
    """
    side = value['side']
    check(side in (-1, 0, 1), '保存点の紙上side')
    flags, volume, price = value['flags'], value['volume'], value['price']
    if volume['known']:
        check(volume['reason'] == 0 and volume['count'] == volume['up']+volume['down'] and volume['up'] >= 0 and volume['down'] >= 0, '既知出来高票の分子分母')
        if volume['count']:
            expected = side*(volume['up']-volume['down'])/volume['count']
            check(math.isclose(volume['signed_balance'], expected, rel_tol=0., abs_tol=1e-12), '現在紙上sideをunsigned票へ一回')
        else:
            check(volume['signed_balance'] is None, '既知零票のbalance欠測')
    else:
        check(volume['reason'] != 0 and all(volume[k] is None for k in ('up', 'down', 'count', 'signed_balance')), '未知debugを方向票として出さない')
    threshold = .5 if symbol == 'TOPIX' else .25
    vol_ok = bool(volume['known'] and volume['count'] >= 2 and volume['signed_balance'] is not None and volume['signed_balance'] >= threshold)
    pri_ok = all((price['own_known'], price['peer_known'], price['own_count'] >= 2, price['peer_count'] >= 2))
    pri_ok = bool(pri_ok and price['own_balance'] is not None and price['peer_balance'] is not None and side*price['own_balance'] >= .25 and side*price['peer_balance'] >= .25)
    strong = bool(pri_ok and side*price['own_balance'] >= .75 and side*price['peer_balance'] >= .75)
    market = bool(flags['paper_active'] and not flags['quiet'] and not flags['deadline'] and flags['period_ok'] and flags['usable'] and flags['paper_context_ok'] and flags['cost_ok'])
    for profile, condition in zip(PROFILES, (vol_ok, pri_ok, vol_ok and pri_ok)):
        check(value['window_profiles'][profile] == condition, '保存票から情報profile独立再判定')
        check(value['market_eligible_without_actual_state'][profile] == bool(market and condition), '情報profileと市場資格の交差')
    check(value['planned_allowance_ticks'] == int(strong), '両価格min2強支持は予定許容でありFAK実測でない')
    check(flags['paper_active'] == (side != 0) and flags['volume_known'] == volume['known'], '旗と現在紙上状態')
    if price['peer_known']:
        check(price['peer_row'] >= 0 and price['peer_raw_seq'] >= 0 and 0 < price['peer_age_proxy_seconds'] <= 60, 'peer strict過去と年齢は代理時計')
    if value['bid'] is not None and value['ask'] is not None:
        q, mult, fee = (10, 1000, 418) if symbol == 'TOPIX' else (20, 10, 220)
        expected_cost = (value['ask']-value['bid'])*q*mult+2*fee
        quote = value['ask'] if side > 0 else value['bid']
        check(math.isclose(value['public_cost_yen'], expected_cost, rel_tol=0., abs_tol=1e-8), '保存両BBO予定料金floor算術')
        check(math.isclose(value['public_cost_limit_yen'], .5*quote*q*mult*.00075, rel_tol=0., abs_tol=1e-8), '予定公開費用枠の当時価格')
    check(all('未測' in value[k] for k in ('busy', 'session_stop_state', 'first_goodquote_FAK')), '実状態FAKの未測を保持')


def main() -> None:
    """
    機能: 全33の別母集団と初回不成立後の現在資格を独立に再集計する。
    引数: なし。
    返り値: None。根の二結果一読以外の入力取得、金融再生、共有編集は0。
    """
    check(not OUTPUT.exists() and not CAPTURE.exists(), '独立新目的の一読開始')
    CAPTURE.mkdir()
    diagnostic, sha = capture('work/e01_opportunity_trace_20261015/prepare_v2/元公開と紙上継続窓の資格診断.json', '完成非金融結果の同bytes保全.json', SOURCE_SHA)
    root, root_sha = capture('work/e01_opportunity_trace_20261015/root_review/初回不成立後の現在資格と別母集団の小集計.json', '根小射影の同bytes保全.json')
    audit = json.loads((HERE/'保存原始型だけの修正と初回読取履歴の独立SOURCE_ONLY接続.json').read_bytes())
    check(diagnostic['全合格'] and diagnostic['source_SHA256'] == audit['source_SHA256'] and diagnostic['固定SHA256'] == audit['metadata_SHA256']['二cacheの小目録固定.json'], '独立source接続済み最終指紋')
    check(diagnostic['計画SHA256'] == audit['metadata_SHA256']['元公開と紙上継続窓の非金融一読診断計画.json'], '固定と計画の系譜')
    check(len(diagnostic['sessions']) == len(set(diagnostic['sessions'])) == len(diagnostic['cases']) == 33 and set(diagnostic['sessions']) == set(diagnostic['cases']), '対象は同じ全33場')
    check(root['全合格'] and root['source_SHA256'] == SOURCE_SHA and root['算術検査数'] == 5555, '根小射影の指定出典')
    check(diagnostic['読取計数'] == diagnostic['元本文読取履歴'] == audit['元本文読取履歴'], '初回処理済66と修正目的66を別履歴で保持')
    check(all(diagnostic[k] == 0 for k in ('金融', '元111実台帳', '原NPZ', '原board', 'API')), '非金融診断の読取境界')
    aggregates, by_session, examples = {}, {}, {'TOPIX': [], 'NK225': []}
    extra = {}
    total_points = 0
    for symbol in ('TOPIX', 'NK225'):
        counts, reasons = Counter(), Counter()
        profiles = {p: Counter() for p in PROFILES}
        all_normal = {side: {p: Counter() for p in PROFILES} for side in ('BUY', 'SELL')}
        diagnostic_only = {p: Counter() for p in PROFILES}
        for session in diagnostic['sessions']:
            account = diagnostic['cases'][session]['accounts'][symbol]
            pubs, episodes = account['original_publications'], account['paper_direction_episodes']
            stored_counts = account['counts']
            check(len(pubs) == stored_counts['original_publications'] and len(episodes) == stored_counts['paper_direction_episodes'], 'PUBと紙上方向区間の保存分母')
            parent = {(p['paper_parent'], p['original_feed_side']): p for p in pubs}
            check(len(parent) == len(pubs), '同場PUB親sideは唯一')
            counts['元公開'] += len(pubs)
            counts['紙上方向区間'] += len(episodes)
            current_counts = Counter(元公開=len(pubs), 紙上方向区間=len(episodes))
            for p in pubs:
                point(p, symbol)
                total_points += 1
                reasons[str(p['qualification_reason_without_actual_state'])] += 1
                original = p['original_signed_volume']
                v = p['volume']
                check(original['known'] == v['known'] and original['reason'] == v['reason'] and original['count'] == v['count'], '当行公開scalarと現在窓の分母資格同値')
                if v['known'] and v['count']:
                    expected = p['original_feed_side']*(v['up']-v['down'])/v['count']
                    check(math.isclose(original['signed_balance'], expected, rel_tol=0., abs_tol=1e-12), '元公開signedは元feedside一回')
                else:
                    check(original['signed_balance'] is None, '元公開未知又は零票をNone保持')
            buy, sell = (account['all_normal_directional_qualification'][side] for side in ('BUY', 'SELL'))
            check(buy['normal_observations'] == sell['normal_observations'] and buy['price_clock_values'] == sell['price_clock_values'], '全normalのBUYSELLは同じ基礎母集団であり足し倍増しない')
            check(stored_counts['active_normal_observations'] <= buy['normal_observations'], '紙上条件付き群は全normalの部分群')
            counts['全normal観測'] += buy['normal_observations']
            counts['全価格時計値'] += buy['price_clock_values']
            for profile in PROFILES:
                for side, group in (('BUY', buy), ('SELL', sell)):
                    value = group['profiles'][profile]
                    check(0 <= value['qualified_with_common_market_observations'] <= value['window_qualified_observations'] <= group['normal_observations'], '全normalの資格包含と母数上限')
                    check(0 <= value['qualified_price_clock_values'] <= value['qualified_with_common_market_observations'] and 0 <= value['continuous_qualified_normal_runs'] <= value['qualified_with_common_market_observations'], 'clock値数と連続区間を観測行数と分離')
                    all_normal[side][profile].update(value)
                check(buy['profiles'][profile]['window_qualified_observations']+sell['profiles'][profile]['window_qualified_observations'] <= buy['normal_observations'], '同じprofile正負閾値は重複資格にならない')
            for side, group in (('BUY', buy), ('SELL', sell)):
                for key in group['profiles']['VOL_SELECTED_PRICE_BOTH']:
                    check(group['profiles']['VOL_SELECTED_PRICE_BOTH'][key] <= min(group['profiles']['VOL_SELECTED'][key], group['profiles']['PRICE_BOTH'][key]) if key != 'continuous_qualified_normal_runs' else True, 'AND観測値の集合包含')
            active_sum, episode_later_sum = 0, {p: 0 for p in PROFILES}
            for episode in episodes:
                pub = parent[(episode['paper_parent'], episode['side'])]
                begin, last = episode['begin'], episode['last_observed']
                point(begin, symbol)
                point(last, symbol)
                total_points += 2
                check(begin['normal_row'] == pub['normal_row'] and begin['raw_seq'] == pub['raw_seq'] and begin['price_time_s'] == pub['price_time_s'], '区間の入口は当行原PUBであり過去巻戻しなし')
                check(last['normal_row']-begin['normal_row']+1 == episode['normal_observations'] and episode['later_normal_observations'] == episode['normal_observations']-1, '区間観測行とPUB以後の行の分母')
                check(0 < episode['price_clock_values'] <= episode['normal_observations'] and last['price_time_s'] >= begin['price_time_s'], '区間clock重複の別母数')
                active_sum += episode['normal_observations']
                for profile in PROFILES:
                    value = episode['profiles'][profile]
                    initial = bool(pub['market_eligible_without_actual_state'][profile])
                    later = value['market_qualified_later_rows']
                    information_initial = bool(pub['window_profiles'][profile])
                    check(0 <= later <= value['window_qualified_later_rows'] <= episode['later_normal_observations'], '紙上群の情報資格と市場資格の包含')
                    check((value['first_later'] is not None) == (value['last_later'] is not None) == (later > 0), '後の資格点がある時だけ値を保存')
                    check(value['qualified_price_clock_values'] <= later and value['continuous_qualified_normal_runs'] <= later+int(initial), '紙上群clockと連続資格の別数')
                    prefix_expected = later+int(initial)-int(last['market_eligible_without_actual_state'][profile])
                    check(value['eligible_observations_before_last_row'] == prefix_expected, '最後当行を含めない過去適格観測数')
                    for p in (value['first_later'], value['last_later']):
                        if p is None:
                            continue
                        point(p, symbol)
                        total_points += 1
                        check(pub['normal_row'] < p['normal_row'] <= last['normal_row'] and pub['raw_seq'] < p['raw_seq'] <= last['raw_seq'] and pub['price_time_s'] <= p['price_time_s'] <= last['price_time_s'], '後資格は原seq未来かつ同clock許容の範囲内')
                        check(p['paper_parent'] == episode['paper_parent'] and p['side'] == episode['side'] and p['market_eligible_without_actual_state'][profile], '後資格点の同紙上群profile')
                    if later:
                        check(value['first_later']['normal_row'] <= value['last_later']['normal_row'], 'firstlastは保存範囲の順序')
                    q = profiles[profile]
                    q['区間'] += 1
                    q['元公開時資格成立'] += int(initial)
                    q['元公開時資格不成立'] += int(not initial)
                    q['後で資格が成立する区間'] += int(later > 0)
                    q['初回不成立後に成立する区間'] += int(not initial and later > 0)
                    q['後の資格観測'] += later
                    diagnostic_only[profile]['情報だけの初回不成立'] += int(not information_initial)
                    diagnostic_only[profile]['情報は成立したが市場資格が不成立'] += int(information_initial and not initial)
                    episode_later_sum[profile] += later+int(initial)
                    if not initial and later:
                        current_counts[profile+'_初回不成立後成立'] += 1
                        if profile == 'VOL_SELECTED_PRICE_BOTH':
                            first = value['first_later']
                            zone = timezone(timedelta(hours=9))
                            examples[symbol].append(dict(session=session, paper_parent=episode['paper_parent'], side=episode['side'],
                                original=pub, later=first, 元表示時刻=datetime.fromtimestamp(pub['price_time_s'], zone).isoformat(),
                                後の表示時刻=datetime.fromtimestamp(first['price_time_s'], zone).isoformat(),
                                遅れ価格時計代理秒=first['price_time_s']-pub['price_time_s'],
                                source='両市場価格と自出来高の現在資格が、初回不成立後に成立した最初の観測。未来損益不使用。'))
            check(active_sum == stored_counts['active_normal_observations'], '全紙上区間の行数合計が活動群母数')
            for profile in PROFILES:
                check(episode_later_sum[profile] == stored_counts['profile_rows'][profile], '区間PUBと後行を合わせた資格行の全数一致')
            by_session.setdefault(session, {})[symbol] = dict(current_counts)
        aggregates[symbol] = dict(counts=dict(counts), 暫定公開理由=dict(reasons), 紙上区間={p: dict(v) for p, v in profiles.items()},
                                  全normal両方向={side: {p: dict(v) for p, v in table.items()} for side, table in all_normal.items()})
        extra[symbol] = {p: dict(v) for p, v in diagnostic_only.items()}
    check(aggregates == root['集計'], '独立全33集計と根小射影の全項目一致')
    check(by_session == root['場別'], '独立全66商品場の小射影一致')
    check({s: v[:2] for s, v in examples.items()} == root['例'], '例は時系列先頭二件で未来損益選択なし')
    expected = {'TOPIX': (147, 124, 102, 138, 86), 'NK225': (152, 95, 83, 130, 97)}
    for symbol, (episodes, failed, later, both_failed, both_later) in expected.items():
        a = aggregates[symbol]
        check(a['counts']['紙上方向区間'] == episodes and a['紙上区間']['VOL_SELECTED']['元公開時資格不成立'] == failed and a['紙上区間']['VOL_SELECTED']['初回不成立後に成立する区間'] == later, '根の初VOL市場不成立後成立の分子分母')
        check(a['紙上区間']['VOL_SELECTED_PRICE_BOTH']['元公開時資格不成立'] == both_failed and a['紙上区間']['VOL_SELECTED_PRICE_BOTH']['初回不成立後に成立する区間'] == both_later, '根のSELECTED両価格AND市場不成立後成立の分子分母')
    result = dict(全合格=True,状態='完成非金融診断の保存範囲で独立再集計。実参加機会/方向正答率/金融効果は未測。',
        検査数=sum(CHECKS.values()),分類=dict(CHECKS),保存点算術確認数=total_points,集計=aggregates,初回不成立の追加分解=extra,
        完成結果SHA256=sha,根小射影SHA256=root_sha,監査source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        読取=dict(完成結果=1,根小射影=1,元66cache=0,元小目録=0,旧金融本文=0,金融=0,NPZ=0,実台帳=0,原board=0,API=0,共有編集=0),
        分母=['元PUB・紙上方向区間はTOP147/NK152。再成立の分母は各profileの初回市場資格不成立区間。',
            'VOL初回市場不成立TOP124/NK95、後資格ありTOP102/NK83。情報票だけの初回不成立とは異なり、期間/quiet/費用等も含む。',
            'ANDはVOL_SELECTEDとPRICE_BOTH。TOP volume閾値.5/NK.25。旧VOL25_PRICE_BOTHとTOP閾値が異なる。',
            '全normalのBUY/SELLは同じ観測母集団を方向別に測る。両方向のnormal母数を足して独立標本数にしない。',
            '全normal群の共通資格はnormal/quiet/期間。紙上ATR/方向/公開費用/実busy/場停止/FAKの制約を含まない。'],
        未独立確認=['疎保存されないnormal全行からのカウンタ再構築','first_laterの最短性を全normal系列から再計算','物理受信先後',
            '実busy/FAK失効/場stop後の参加可否','distinct新票の最終seq','後に利益になった割合・新取引損益'],
        限界='今回の確認は保存カウンタの算術・包含と保存点の当時資格。観測や連続区間を独立取引機会・正答率に変換しない。')
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('独立非金融小集計 '+str(result['検査数'])+' 合格。SHA '+hashlib.sha256(OUTPUT.read_bytes()).hexdigest(), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        path = HERE/'独立非金融小集計初版False.json'
        assert not path.exists()
        path.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),分類=dict(CHECKS),
            監査source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),元cache=0,金融=0,API=0), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise
