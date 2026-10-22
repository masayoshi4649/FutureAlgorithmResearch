"""保存後の比較会計を読むだけで、気配約定への変更が悪化した場を分解する。"""

from datetime import datetime, timezone, timedelta
import gzip
import pickle

import numpy as np

from bridge import HERE, ROOT, digest, read, save
from specification import VALUE


def packet(path) -> dict:
    """
    機能: 完成済み台帳又は共有紙上注文だけを読む。
    引数: path(Path)はgzip pickle保存物。
    返り値: dict。金融再生を行わない。
    """
    with gzip.open(path, 'rb') as stream:
        return pickle.load(stream)


def point(q: dict, row: int, last: np.ndarray) -> dict:
    """
    機能: 保存原行の時計・連番と現在値及び両気配を示す。
    引数: q(dict)、row(int)、last(ndarray)は同じ原連番の価格。
    返り値: dict。真の受信時計とは区別する。
    """
    return dict(正常行=row, 原連番=int(q['seq'][row]),
        板価格時計=datetime.fromtimestamp(float(q['time_s'][row]), timezone(timedelta(hours=9))).isoformat(),
        CurrentPrice=float(last[row]), 買気配=float(q['bid'][row]), 売気配=float(q['ask'][row]))


def statistics(rows: list[dict]) -> dict:
    """
    機能: 合計利益より場の安定を評価する固定の事後統計を算出する。
    引数: rows(list[dict])は商品別の全33小会計。
    返り値: dict。無取引を黒字へ数えない。
    """
    ranked = sorted(rows, key=lambda r: r['収支'], reverse=True)
    back = rows[16:]
    return dict(セッション収支中央値=float(np.median([r['収支'] for r in rows])),
        上位3場=[dict(session=r['session'], 収支=r['収支']) for r in ranked[:3]],
        上位3場除外収支=sum(r['収支'] for r in ranked[3:]),
        後17中央値=float(np.median([r['収支'] for r in back])),
        後17上位3場除外収支=sum(r['収支'] for r in sorted(back, key=lambda r: r['収支'], reverse=True)[3:]),
        黒字場割合=sum(r['収支'] > 0 for r in rows) / len(rows),
        活動場内黒字割合=sum(r['収支'] > 0 for r in rows) / sum(r['親数'] > 0 for r in rows)
            if any(r['親数'] for r in rows) else None,
        注記='中央値は全場。無取引は零として残し、黒字には含めない。')


def decompose(key: tuple, price: dict, bbo: dict, q: dict, last: np.ndarray, paper: dict) -> dict:
    """
    機能: 共通親の入口/出口の価格差と、片側だけの親を実会計から厳密に分ける。
    引数: key(tuple)、price/bbo/q/paper(dict)、last(ndarray)は保存済み事実。
    返り値: dict。事後診断であり、新規入口へ未来値を渡さない。
    """
    multiplier = VALUE[key[1]]
    lp = {p['親']: p for p in price['parent']}; bp = {p['親']: p for p in bbo['parent']}
    common = set(lp) & set(bp); missed = set(lp) - set(bp); added = set(bp) - set(lp)
    parts = dict(入口の気配差=0., 入口時点の変化=0., 返済の気配差=0., 返済時点の変化=0.,
                 共通親の費用変化=0., BBO見送りで失った利益=0., BBO見送りで避けた損失=0., BBOだけの入口収支=0.)
    details = []
    for cid in sorted(common):
        lo = price['orders'][price['orders'][:, 2] == cid]
        bo = bbo['orders'][bbo['orders'][:, 2] == cid]
        le = lo[lo[:, 7] == 1]; be = bo[bo[:, 7] == 1]
        assert len(le) == len(be) == 1 and le[0, 3] == be[0, 3] and le[0, 4] == be[0, 4]
        side, qty, row = int(be[0, 3]), int(be[0, 4]), int(be[0, 0])
        entry_spread = -side * qty * (be[0, 5] - last[row]) * multiplier
        entry_timing = -side * qty * (last[row] - le[0, 5]) * multiplier
        lx = lo[lo[:, 7] == 0]; bx = bo[bo[:, 7] == 0]
        assert lx[:, 4].sum() == bx[:, 4].sum() == qty
        actual_cash = float(np.sum(-bx[:, 3] * bx[:, 4] * bx[:, 5]) * multiplier)
        same_row_last = float(np.sum(-bx[:, 3] * bx[:, 4] * last[bx[:, 0].astype(int)]) * multiplier)
        reference_cash = float(np.sum(-lx[:, 3] * lx[:, 4] * lx[:, 5]) * multiplier)
        exit_spread = actual_cash - same_row_last; exit_timing = same_row_last - reference_cash
        fee = lp[cid]['費用'] - bp[cid]['費用']
        assert np.isclose(bp[cid]['収支'] - lp[cid]['収支'],
            entry_spread + entry_timing + exit_spread + exit_timing + fee, atol=.0001, rtol=0)
        for name, value in (('入口の気配差', entry_spread), ('入口時点の変化', entry_timing),
                            ('返済の気配差', exit_spread), ('返済時点の変化', exit_timing), ('共通親の費用変化', fee)):
            parts[name] += value
        details.append(dict(親=cid, 方向=side, LP収支=lp[cid]['収支'], BBO収支=bp[cid]['収支'],
            収支変化=bp[cid]['収支'] - lp[cid]['収支'], 入口気配差=entry_spread,
            入口時点変化=entry_timing, 返済気配差=exit_spread, 返済時点変化=exit_timing,
            指値公開=point(q, int(be[0, 1]), last), 旧新規=point(q, int(le[0, 0]), last),
            BBO新規=point(q, row, last), BBO最終返済=point(q, int(bx[-1, 0]), last)))
    missing = []
    for cid in sorted(missed):
        net = lp[cid]['収支']
        parts['BBO見送りで失った利益' if net > 0 else 'BBO見送りで避けた損失'] -= net
        entry = price['orders'][(price['orders'][:, 2] == cid) & (price['orders'][:, 7] == 1)][0]
        posted = bbo['limit_events'][(bbo['limit_events'][:, 2] == cid) & (bbo['limit_events'][:, 1] == 1)][0]
        cancellations = bbo['limit_events'][(bbo['limit_events'][:, 2] == cid) & np.isin(bbo['limit_events'][:, 1], [3, 4])]
        source, fill, side = int(entry[1]), int(entry[0]), int(entry[3])
        end = int(cancellations[0, 0]) if len(cancellations) else len(last) - 1
        inclusive = bool(len(cancellations) and cancellations[0, 1] == 3)
        stop = end + (1 if inclusive else 0)
        path = q['ask' if side > 0 else 'bid'][source + 1:stop]
        normal = q['quote_valid'][source + 1:stop]
        reached = normal & ((path <= posted[8]) if side > 0 else (path >= posted[8]))
        missing.append(dict(親=cid, 方向=side, 旧親収支=net, 収支変化=-net,
            指値線=float(posted[8]), 指値公開=point(q, source, last), 旧Last約定行=point(q, fill, last),
            取消判断=point(q, end, last), 取消種別='紙上返済' if inclusive else '既知休止又は期限',
            取消前正常気配到達数=int(reached.sum()), 当時に使える差='旧Last到達の瞬間でも売買気配が指値線に到達したとは限らない。',
            事後だけの結果='旧親が最終黒字か赤字か。これを新規条件には使用していない。'))
    parts['BBOだけの入口収支'] = sum(bp[c]['収支'] for c in added)
    delta = bbo['summary']['収支'] - price['summary']['収支']
    assert np.isclose(sum(parts.values()), delta, atol=.0001, rtol=0)
    return dict(session=key[0], symbol=key[1], LP収支=price['summary']['収支'], BBO収支=bbo['summary']['収支'],
        収支変化=delta, 分解=parts, 共通親数=len(common), BBO見送り親数=len(missed), BBOだけの親数=len(added),
        共通親の具体例=sorted(details, key=lambda d: d['収支変化'])[:3], BBO見送り親=missing,
        分解一致=True, 注意='気配差はBBO実約定行のCurrentPriceとの差。CurrentPriceが気配外の時は逆符号もあり、常にコストとは限らない。時点差は待機による価格経路の変更。')


def run() -> None:
    """
    機能: 完成後の安定性統計と、商品別悪化上位3場の会計原因だけを保存する。
    引数: なし。
    返り値: None。再金融・API・原本再読取を行わない。
    """
    result = read(HERE / '結果.json'); assert result['全合格']
    assert not (HERE / '安定性と悪化上位3場の分解.json').exists()
    additions = {}; selected = {}
    for name, value in result['results'].items():
        additions[name] = {symbol: statistics([r for r in value['rows'] if r['symbol'] == symbol])
                          for symbol in ('TOPIX', 'NK225')}
    price_rows = {(r['session'], r['symbol']): r for r in result['results']['L_D20_PRICE']['rows']}
    for symbol in ('TOPIX', 'NK225'):
        candidates = [r for r in result['results']['L_D20_BBO']['rows'] if r['symbol'] == symbol]
        selected[symbol] = [(r['session'], symbol) for r in sorted(candidates,
            key=lambda r: r['収支'] - price_rows[r['session'], symbol]['収支'])[:3]]
    old_prices_path = ROOT / 'work/wave_v83/prepared/inputs.pkl'
    proof = read(ROOT / 'work/wave_v83/prepared/価格入力の照合.json')
    assert digest(old_prices_path) == proof['出力SHA256']
    old_prices = read(old_prices_path)
    q_all = read(HERE / 'prepared/quotes.pkl')
    detail = []; hashes = {}
    for key in [key for symbol in ('TOPIX', 'NK225') for key in selected[symbol]]:
        session, symbol = key
        last = old_prices[key]['price'] if key in old_prices else None
        if last is None:
            path = HERE / 'prepared' / session / 'features' / f'約定系列_{symbol}_{session}.npz'
            with np.load(path, allow_pickle=False) as tape:
                last = tape['last']
        q = q_all[key]
        if key in old_prices:
            for name in ('seq', 'time_s'):
                np.testing.assert_array_equal(q[name], old_prices[key][name])
        assert len(last) == len(q['seq'])
        packets = {}
        for name in ('L_D20_PRICE', 'L_D20_BBO'):
            path = HERE / 'ledgers' / name / (session + '_' + symbol + '.pkl.gz')
            relative = str(path.relative_to(HERE)).replace('\\', '/')
            assert digest(path) == result['台帳SHA256'][relative]
            hashes[relative] = digest(path); packets[name] = packet(path)
        path = HERE / 'paper' / (session + '_' + symbol + '.pkl.gz')
        relative = str(path.relative_to(HERE)).replace('\\', '/')
        assert digest(path) == result['紙上SHA256'][relative]
        hashes[relative] = digest(path)
        detail.append(decompose(key, packets['L_D20_PRICE'], packets['L_D20_BBO'], q, last, packet(path)))
    save(HERE / '安定性と悪化上位3場の分解.json', dict(全合格=True,
        scope='保存済み全33集計の事後統計と、LP→BBO商品別悪化上位3場のみの原因。新条件選定ではない。',
        結果SHA256=digest(HERE / '結果.json'), sourceSHA256=digest(HERE / 'diagnose.py'),
        安定性補足=additions, 選択規則='L_D20_BBO収支−L_D20_PRICE収支の小さい3場を商品別に機械選択。',
        選択=selected, 具体分解=detail, 台帳SHA256=hashes, 旧83入力SHA256=proof['出力SHA256'],
        金融再生=0, API=0, 原本再読=0,
        PF定義='完結親の料金後総利益/総損失。部分返済の勝率・枚数と混同しない。',
        警告='実ミニ/マイクロ板の値ではなくラージBBO代理。表示数量と列順の部分約定は未再現。'))
    print('全33安定性とBBO悪化上位3場の会計分解完了', flush=True)


if __name__ == '__main__':
    run()
