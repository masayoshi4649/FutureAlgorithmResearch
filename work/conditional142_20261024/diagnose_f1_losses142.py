"""日経F1の保存注文を担当別に分け、赤字全15場と分散効果を再会計する。"""

import json
import pickle
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import verify_mechanics142 as audit


HERE, ROOT, OLD = audit.HERE, audit.ROOT, audit.OLD
ROLES = ('主担当', '補完担当', '追加担当')


def role(parent, uid):
    """
    機能: 凍結コードの親識別子領域に従い、主・補完・追加を分ける。
    引数: parent/uid(int)は保存親IDと玉ID。
    返り値: strは担当名。昼B5のUID999補完、夜400万補完、300万追加を区別する。
    """
    return '追加担当' if 3_000_000 <= parent < 4_000_000 else '補完担当' if uid == 999 else '主担当'


def stamp(times, index):
    """
    機能: 原行の保存価格時計を日本時間文字列にする。
    引数: times(ndarray)、index(int)は時計列と位置。
    返り値: strは日本時間ISO表記。独立した受信時刻を意味しない。
    """
    return datetime.fromtimestamp(float(times[index]), ZoneInfo('Asia/Tokyo')).isoformat()


def reason_text(code, new, owner):
    """
    機能: 同じ番号でも新規・返済の意味を区別し、確認できた理由名を付す。
    引数: code(int)、new(bool)、owner(str)は理由番号・新規別・担当。
    返り値: strは理由の説明。細分類未接続の旧条件は推測しない。
    """
    if new:
        if owner == '補完担当':
            return 'Z04の固定方向で補完新規' if code == 1424 else f'既存参加補完の新規通知{code}'
        if owner == '追加担当':
            return {142: '順行後の追撃', 144: '低効率帯の反転候補から再進行新規', 140: '帯突破の追従新規'}.get(code, f'追加入口{code}')
        return f'旧主担当の新規通知{code}'
    return {1: '元の組損切り', 2: '元の追跡返済', 7: '順行幅の部分利確', 30: '順行後の悪化で半減',
            32: '損失幅・損失予算に到達', 70: '利益保護線への戻り', 72: '境界破綻と相手逆行',
            75: '二市場逆行の継続', 93: '場末返済', 94: '米国開始静観',
            1421: '長短方向管理による全返済', 1431: '長短方向管理による半減',
            1434: 'Z04の短期と中期の反証継続'}.get(code, f'旧返済条件{code}（細分類未接続）')


def account(orders, ready, quotes):
    """
    機能: 保存注文を親・担当・方向・返済理由へ会計し、保有評価損の同時性を測る。
    引数: orders(ndarray)、ready/quotes(dict)は十列注文と原行時計・気配。
    返り値: dictは手数料後親会計、注文内訳、同時保有の観測記録。
    """
    cash = audit.audit_orders(orders, dict(ready=ready, quotes=quotes), 10)
    times = ready['time_s']
    n = len(times)
    changes = np.zeros((3, n, 3))
    parents, tickets, reasons = {}, {}, {}
    for o in orders:
        fill, decision, pid, side, qty = map(int, o[:5])
        price, code, new, uid, fee = float(o[5]), int(o[6]), bool(o[7]), int(o[8]), int(o[9])
        owner = role(pid, uid)
        p = parents.setdefault(pid, dict(parent=pid, role=owner, side=side, gross=0., fees=0., net=0.,
            first_row=fill, last_row=fill, first_time=stamp(times, fill), last_time=stamp(times, fill),
            quantity=0, orders=[]))
        p['fees'] += fee
        p['last_row'], p['last_time'] = fill, stamp(times, fill)
        key = pid, uid
        rkey = owner, new, code
        breakdown = reasons.setdefault(rkey, dict(role=owner, new=new, code=code,
            reason=reason_text(code, new, owner), orders=0, quantity=0, gross=0., fees=0))
        breakdown['orders'] += 1
        breakdown['quantity'] += qty
        breakdown['fees'] += fee
        gross = 0.
        if new:
            tickets[key] = [qty, side, price]
            p['quantity'] += qty
            changes[ROLES.index(owner), fill, 0 if side > 0 else 1] += qty
            changes[ROLES.index(owner), fill, 2] += side * qty * price
        else:
            held, direction, entry = tickets[key]
            assert held >= qty and direction == -side
            tickets[key][0] -= qty
            gross = direction * (price - entry) * qty * 100.
            p['gross'] += gross
            breakdown['gross'] += gross
            changes[ROLES.index(owner), fill, 0 if direction > 0 else 1] -= qty
            changes[ROLES.index(owner), fill, 2] -= direction * qty * entry
        p['orders'].append(dict(fill_row=fill, decision_row=decision, fill_seq0=int(ready['seq'][fill]),
            decision_seq0=int(ready['seq'][decision]), time=stamp(times, fill), decision_time=stamp(times, decision),
            new=new, side=side, quantity=qty, price=price, fee=fee, gross=gross,
            uid=uid, reason=code, reason_text=reason_text(code, new, owner)))
    for p in parents.values():
        p['net'] = p['gross'] - p['fees']
    assert abs(sum(p['net'] for p in parents.values()) - cash) < 1e-6
    by_role = {}
    for owner in ROLES:
        chosen = [p for p in parents.values() if p['role'] == owner]
        by_role[owner] = summarize(chosen)
    by_direction = {('買い' if side > 0 else '売り'): summarize([p for p in parents.values() if p['side'] == side]) for side in (1, -1)}
    state = np.cumsum(changes, axis=1)
    opened = state[:, :, 0] + state[:, :, 1]
    values = 100. * (state[:, :, 0] * quotes['bid'][None, :] - state[:, :, 1] * quotes['ask'][None, :] - state[:, :, 2])
    primary_value, added_value = values[0] + values[1], values[2]
    primary_open, added_open = opened[0] + opened[1], opened[2]
    simultaneous = (primary_open > 0) & (added_open > 0)
    both_loss = simultaneous & (primary_value < 0) & (added_value < 0) & quotes['quote_valid']
    indexes = np.flatnonzero(both_loss)
    durations = np.r_[np.diff(times), 0.]
    durations = np.where((durations >= 0) & (durations <= 15.) & quotes['quote_valid'], durations, 0.)
    simultaneous_loss = dict(observed=bool(len(indexes)), qualified_priceclock_seconds=float(durations[both_loss].sum()),
        simultaneous_holding_seconds=float(durations[simultaneous].sum()), first_time=None, worst_sum_open_gross=None)
    if len(indexes):
        i = int(indexes[np.argmin((primary_value + added_value)[indexes])])
        simultaneous_loss.update(first_time=stamp(times, int(indexes[0])), worst_time=stamp(times, i),
            worst_sum_open_gross=float(primary_value[i] + added_value[i]), primary_open_gross=float(primary_value[i]),
            addon_open_gross=float(added_value[i]), primary_quantity=int(primary_open[i]), addon_quantity=int(added_open[i]))
    return dict(net=cash, roles=by_role, directions=by_direction, reasons=list(reasons.values()),
        parents=list(parents.values()), simultaneous_open_loss=simultaneous_loss,
        core_supplement_overlap=bool(np.any((opened[0] > 0) & (opened[1] > 0))))


def summarize(parents):
    """
    機能: 完結親を単位として利益・損失・PFを算出する。
    引数: parents(list[dict])は親ごとの費用後会計。
    返り値: dictは親単位統計。PFの分母0はnullとする。
    """
    profit = sum(p['net'] for p in parents if p['net'] > 0)
    loss = -sum(p['net'] for p in parents if p['net'] < 0)
    return dict(parents=len(parents), profit=profit, loss=loss, net=profit-loss,
        pf=profit/loss if loss else None, fees=sum(p['fees'] for p in parents),
        winning_parents=sum(p['net'] > 0 for p in parents), losing_parents=sum(p['net'] < 0 for p in parents),
        quantity=sum(p['quantity'] for p in parents))


def portfolio_summary(sessions):
    """
    機能: 主担当側と追加側の相関、損失の相殺・赤字化を場単位で測る。
    引数: sessions(list[dict])は保存注文を分解した全場又は同昼夜の会計。
    返り値: dictは無取引ゼロを含む相関と実際の損益の和による分散指標。
    """
    primary = np.array([s['roles']['主担当']['net'] + s['roles']['補完担当']['net'] for s in sessions])
    addon = np.array([s['roles']['追加担当']['net'] for s in sessions])
    active = np.array([s['roles']['追加担当']['parents'] > 0 for s in sessions])
    parents = [p for s in sessions for p in s['parents']]
    names = lambda mask: [s['session'] for s, take in zip(sessions, mask) if take]
    biggest = sorted(zip(addon.tolist(), (s['session'] for s in sessions)), reverse=True)[:3]
    return dict(sessions=len(sessions), primary=summarize([p for p in parents if p['role'] != '追加担当']),
        addon=summarize([p for p in parents if p['role'] == '追加担当']),
        addon_largest_positive_sessions=[dict(session=scene, net=value) for value, scene in biggest if value > 0],
        addon_net_excluding_top3=float(addon.sum()-sum(max(0., value) for value, scene in biggest)),
        role_summary={r: summarize([p for p in parents if p['role'] == r]) for r in ROLES},
        session_net_correlation=float(np.corrcoef(primary, addon)[0, 1]),
        active_addon_sessions=int(active.sum()), addon_inactive_sessions=int((~active).sum()),
        active_addon_session_correlation=float(np.corrcoef(primary[active], addon[active])[0, 1]) if active.sum() > 1 else None,
        primary_negative_to_positive=names((primary < 0) & (primary+addon > 0)),
        primary_positive_to_negative=names((primary > 0) & (primary+addon < 0)),
        both_sleeves_negative=names((primary < 0) & (addon < 0)),
        primary_negative_addon_positive=names((primary < 0) & (addon > 0)),
        primary_positive_addon_negative=names((primary > 0) & (addon < 0)),
        opposite_sign_sessions=int(np.count_nonzero(primary*addon < 0)),
        both_sleeves_positive=names((primary > 0) & (addon > 0)),
        primary_negative_sessions=int(np.count_nonzero(primary < 0)),
        combined_negative_sessions=int(np.count_nonzero(primary+addon < 0)))


def classification(session):
    """
    機能: 会計上の赤字構造を排他的に分類する。
    引数: session(dict)は担当別損益。
    返り値: strは原因機構の推測ではなく、損失の発生担当と相殺関係。
    """
    primary = session['roles']['主担当']['net'] + session['roles']['補完担当']['net']
    addon = session['roles']['追加担当']['net']
    if addon > 0:
        return '追加の利益で主担当側の損失を縮小したが不足'
    if primary > 0:
        return '主担当側の黒字を追加の赤字が上回る'
    if addon < 0 and primary < 0:
        return '主担当側と追加側がともに赤字'
    if session['roles']['主担当']['net'] < 0 and session['roles']['補完担当']['net'] > 0:
        return '補完が主担当の損失を縮小したが不足'
    if session['roles']['主担当']['net'] < 0 and session['roles']['補完担当']['net'] < 0:
        return '主担当と補完が別の取引でともに赤字'
    return '主担当側だけが赤字・追加の相殺なし'


def main():
    """
    機能: 全50場の構成を保存注文に照合し、全15赤字場のJSONと短い報告を作る。
    引数: なし。
    返り値: None。新しい発注判断・金融再生・条件選択は行わない。
    """
    report = audit.read(HERE / 'report_data142.json')
    rows = [r for r in report['rows'] if r['symbol'] == 'NK225' and r['method'] == 'F1']
    packets = {x['session']: x for f in (OLD/'known_manifest140.json', OLD/'inputs/input_manifest.json') for x in audit.read(f)['packets']}
    cache = {r['session']: r for r in audit.read(HERE/'結果142.json')['cache'] if r['symbol'] == 'NK225'}
    sessions = []
    for row in rows:
        scene = row['session']
        source = packets[scene]
        path = ROOT/source['path']
        assert audit.digest(path) == source['sha256']
        packet = pickle.loads(path.read_bytes())
        ref = cache[scene]
        path = ROOT/ref['path']
        assert audit.digest(path) == ref['sha256']
        with np.load(path) as saved:
            orders = saved[row['component_method']]
            primary = orders[orders[:, 2] < 3_000_000] if row['kind'] == 'Day' else orders[(orders[:, 2] < 3_000_000) | (orders[:, 2] == 4_000_000)]
            expected = saved['B5' if row['kind'] == 'Day' else 'Z04']
            np.testing.assert_array_equal(primary, expected)
            addon = orders[(orders[:, 2] >= 3_000_000) & (orders[:, 2] < 4_000_000)].copy()
            addon[:, 2] -= 3_000_000
            if row['kind'] == 'Night':
                np.testing.assert_array_equal(addon, saved['A_C13'])
            else:
                with np.load(ROOT/'work/raw_diagnosis141_20261024/results/measurement'/f'NK225_{scene}.npz') as old:
                    np.testing.assert_array_equal(addon, old['A_G02'])
            measured = account(orders, packet['inputs'][scene, 'NK225'], packet['quotes'][scene, 'NK225'])
        assert measured['net'] == row['net']
        assert sum(p['net'] for p in measured['parents'] if p['net'] > 0) == row['profit']
        assert -sum(p['net'] for p in measured['parents'] if p['net'] < 0) == row['loss']
        measured.update(session=scene, kind=row['kind'], component=row['component_method'])
        measured['classification'] = classification(measured) if measured['net'] < 0 else '黒字又は収支同値'
        sessions.append(measured)
    losses = [s for s in sessions if s['net'] < 0]
    assert len(rows) == 50 and len(losses) == 15
    stats = {group: portfolio_summary([s for s in sessions if group == '全場' or s['kind'] == group]) for group in ('全場', 'Day', 'Night')}
    output = dict(新金融再生=0, symbol='NK225mini', fee_per_side=38.5, multiplier=100,
        配分='主担当側最大5枚（旧主担当と参加補完）＋追加側最大5枚の独立枠。片方向合計10枚。昼G02初回最大2、夜C13初回最大2。',
        構成={'Day': 'B5（旧主担当と既存場内参加補完）＋G02追加', 'Night': 'Z04（旧主担当＋排他的な夜補完）＋C13追加'},
        会計定義='利益・損失・PFは新規から全返済までの完結親ごと、全注文の手数料を含む。理由別は新規手数料を別掲し、返済grossと返済手数料を表示する。',
        同時性定義='同時評価損は保存約定を保持し、当行BBOで保有玉だけを評価した手数料前の負額。実現済み損益は含めない。秒数は正常板かつ次時計差15秒以内の区間だけ。受信時間ではない。',
        原因区別='分類は保存会計による発生箇所。方向誤判定や再進行失敗という因果の確定には、別途判断時特徴・原板の照合が必要。',
        分散統計=stats, 赤字分類=dict(Counter(s['classification'] for s in losses)), 赤字場=losses,
        全場担当損益=[dict(session=s['session'], kind=s['kind'], net=s['net'], roles=s['roles'],
            simultaneous_open_loss=s['simultaneous_open_loss'], core_supplement_overlap=s['core_supplement_overlap']) for s in sessions])
    audit.save(HERE/'F1赤字場と構成担当の内訳.json', output)
    write_markdown(output)
    print(json.dumps(dict(赤字分類=output['赤字分類'], 分散統計=stats), ensure_ascii=False))


def write_markdown(data):
    """
    機能: 全赤字場の担当別損益と、全50場での分散効果を短く報告する。
    引数: data(dict)は照合済み会計。
    返り値: None。JSONと同名のMarkdownを新規保存する。
    """
    overall = data['分散統計']['全場']
    lines = ['# 日経F1の赤字15場と担当の分散効果', '',
        'F1は一つの入口ではない。昼はB5（旧主担当＋既存参加補完）とG02追加、夜はZ04（旧主担当＋条件付き補完）とC13追加を並行運転する。主担当側最大5枚＋追加側最大5枚で、同じ方向にも反対方向にも保有できる。新規判断の再生はしていない。', '',
        '日経mini、1pt＝100円、片道1枚38.5円を注文単位で切り捨て。以下の利益・損失・PFは完結親単位の費用後会計。', '',
        '|担当側・対象|総利益|総損失|収支|PF|', '|---|---:|---:|---:|---:|']
    for group in ('全場', 'Day', 'Night'):
        for key, label in (('primary', '主担当側'), ('addon', '追加側')):
            v = data['分散統計'][group][key]
            lines.append(f"|{label}・{group}|{v['profit']:,.0f}|{v['loss']:,.0f}|{v['net']:+,.0f}|{v['pf']:.3f}|")
    lines += ['', f"全50場の主担当側と追加側の収支相関は {overall['session_net_correlation']:.3f}。追加が取引した {overall['active_addon_sessions']} 場だけでは {overall['active_addon_session_correlation']:.3f}。主担当側の赤字を黒字へ変えたのは {len(overall['primary_negative_to_positive'])} 場、逆に黒字を赤字へ変えたのは {len(overall['primary_positive_to_negative'])} 場、両側とも赤字は {len(overall['both_sleeves_negative'])} 場。相関が低くても、すべての損失を相殺する仕組みにはなっていない。", '',
        f"追加側単独の全50場収支は上位3場を除くと {overall['addon_net_excluding_top3']:+,.0f}円。夜追加も上位3場除外では {data['分散統計']['Night']['addon_net_excluding_top3']:+,.0f}円となる。F1全体の上位3場除外黒字とは別の指標であり、追加担当だけが日々安定した収益源という意味ではない。", '',
        '|赤字セッション|通常主担当|参加補完|追加|F1収支|会計上の分類|', '|---|---:|---:|---:|---:|---|']
    for s in data['赤字場']:
        v = s['roles']
        lines.append(f"|{s['session']}|{v['主担当']['net']:+,.0f}|{v['補完担当']['net']:+,.0f}|{v['追加担当']['net']:+,.0f}|{s['net']:+,.0f}|{s['classification']}|")
    lines += ['', '各場で最も損失の大きい完結親を以下に示す。時刻は保存価格時計。親収支は途中の部分返済を含むため、最初と最後の価格差だけでは計算できない。全親・全注文・売買方向・新規と返済理由・原行番号はJSONに保持した。', '']
    for s in data['赤字場']:
        p = min(s['parents'], key=lambda x: x['net'])
        start, end = p['orders'][0], p['orders'][-1]
        lines.append(f"- {s['session']}：{p['role']} {'買い' if p['side'] > 0 else '売り'}、{start['time'][11:19]} {start['quantity']}枚 @{start['price']:g} → {end['time'][11:19]} 最終返済 @{end['price']:g}、親収支 {p['net']:+,.0f}円。最終理由は{end['reason_text']}。")
    lines += ['', '会計から確定できるのは、主担当だけの損失、追加の相殺不足、追加による黒字の食い潰し、両側の赤字の区別まで。短期の反発を継続方向と誤認した、支持崩れを遅れて判断した、という説明は判断時の特徴・原板照合を要する原因仮説であり、この集計だけで確定しない。', '',
        '根拠コード：`report142.py`の昼夜構成、`run142.py`のM1/Z04/C13接続、`policies142.py`のJ04、`night_trader142.py`の主担当・補完排他と1〜5枚換算、`active_trader142.py`の追加上限、`../aggressive140_20261024/round2_140.py`の独立枠合成。昼G02は入口確認だけの改修で、夜C13の利益保護前追撃禁止を昼にも適用した結果ではない。']
    (HERE/'F1赤字場と構成担当の内訳.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
