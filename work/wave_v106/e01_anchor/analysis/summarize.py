"""候補の安定性と、基準親の利益返し/初期逆行に対する違いを保存後に点検する。"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import common
from prepare import packet
from liquidation_path import liquidation_curve


def clock(q: dict, row: int) -> dict:
    """
    機能: 保存原行を価格時計と連番へ対応付ける。
    引数: q(dict)、row(int)は同一素材と行。
    返り値: dict。実受信時計ではない。
    """
    return dict(行=row, 原連番=int(q['seq'][row]), 板価格時計=datetime.fromtimestamp(
        float(q['time_s'][row]), timezone(timedelta(hours=9))).isoformat())


def stats(rows: list[dict]) -> dict:
    """
    機能: 各場の中央値・利益集中・上位3除外を計算する。
    引数: rows(list[dict])は商品別固定33会計。
    返り値: dict。無取引は零で残して勝ちへ含めない。
    """
    ranked = sorted(rows, key=lambda r: r['収支'], reverse=True); back = rows[16:]
    net = sum(r['収支'] for r in rows)
    return dict(中央値=float(np.median([r['収支'] for r in rows])),
        上位3場除外収支=sum(r['収支'] for r in ranked[3:]),
        後17中央値=float(np.median([r['収支'] for r in back])),
        後17上位3場除外収支=sum(r['収支'] for r in sorted(back, key=lambda r:r['収支'], reverse=True)[3:]),
        最高利益場=ranked[0]['session'], 最高利益場収支=ranked[0]['収支'],
        最高利益場全純益比=ranked[0]['収支']/net if net>0 else None,
        赤字場=sum(r['収支']<0 for r in rows), 無取引場=sum(r['親数']==0 for r in rows),
        注記='利益除外と親分類は事後診断。売買条件へ使わない。')


def classify(base: dict, q: dict, tick: float) -> dict:
    """
    機能: 基準の親自身の料金後清算経路と1tick先着を、完結範囲内だけで分ける。
    引数: base/q(dict)、tick(float)は保存基準とnative呼値。
    返り値: dict[int,dict]。分類は将来結果なので当時入口に使用できない。
    """
    curve, _ = liquidation_curve(base, base['key'][1]); groups = {}
    for parent in base['parent']:
        start, end, side = parent['新規行'], parent['最終返済行'], parent['方向']
        preceding = sum(p['収支'] for p in base['parent'] if p['最終返済行'] < start)
        own = curve[start:end+1] - preceding
        assert np.isclose(own[-1], parent['収支'], atol=1e-7, rtol=0.)
        normal = q['quote_valid'][start:end+1]
        maximum = float(own[normal].max()); recovered = maximum > 0
        if parent['収支'] < 0:
            group = '赤字かつ一度清算利益あり' if recovered else '赤字で清算利益なし'
        elif parent['収支'] > 0:
            group = '基準の最終黒字'
        else:
            group = '基準の零収支'
        quote = q['bid' if side > 0 else 'ask'][start:end+1]
        move = side * (quote - quote[0]); forward = np.flatnonzero(normal & (move >= tick - 1e-8))
        adverse = np.flatnonzero(normal & (move <= -tick + 1e-8))
        first_forward = int(forward[0]) if len(forward) else None
        first_adverse = int(adverse[0]) if len(adverse) else None
        first = '逆行先' if first_adverse is not None and (first_forward is None or first_adverse < first_forward) else (
            '順行先' if first_forward is not None else '双方未到達')
        legs = base['trades'][:,0] == parent['親']
        partial_profit = any(t[3] < parent['枚数'] and value > 0
                             for t, value in zip(base['trades'][legs], base['leg_net_yen'][legs]))
        groups[parent['親']] = dict(分類=group, 基準収支=parent['収支'], 最大親清算益=maximum,
            初回清算気配から1tick先着=first, 決済済み利益脚あり=partial_profit,
            注意='1tick先着は建値ではなく初回bid/ask清算気配からの対称移動。分類はいずれも事後。')
    return groups


def example(ledger: dict, material: dict, parent: dict) -> dict:
    """
    機能: 大きな赤字親の公開線と実新規/全返済を時計・価格へ対応付ける。
    引数: ledger/material/parent(dict)は保存会計と対象親。
    返り値: dict。入口で見抜けた兆候と将来勝敗を混同しない。
    """
    q = material['quote']; orders = ledger['orders'][ledger['orders'][:,2] == parent['親']]
    entry = orders[orders[:,7] == 1][0]; source = int(entry[1])
    posted = ledger['limit_events'][(ledger['limit_events'][:,1] == 1) & (ledger['limit_events'][:,2] == parent['親'])][0]
    refs = ledger['reference_at_posts'][ledger['paper_feed_rows'] == source]
    assert len(refs) == 1
    return dict(**parent, 公開=dict(**clock(q, source), 参照値=float(refs[0]), 指値線=float(posted[8]),
        原Last=float(material['ready']['last'][source]), 当時bid=float(q['bid'][source]), 当時ask=float(q['ask'][source])),
        新規=dict(**clock(q, int(entry[0])), 価格=float(entry[5])),
        返済=[dict(**clock(q, int(o[0])), 判断=clock(q, int(o[1])), 価格=float(o[5]), 枚数=int(o[4]))
              for o in orders if int(o[7]) == 0])


def run() -> None:
    """
    機能: 基準親の事後分類を全三候補へ対応し、赤字3場の具体例も保存する。
    引数: なし。
    返り値: None。金融/紙上/原本/APIを再実行しない。
    """
    result = common.read(common.HERE / '結果.json'); assert result['全合格']
    target = common.HERE / '安定性と基準の逆行及び利益返しの違い.json'; assert not target.exists()
    source = common.read(common.REFERENCE / '結果.json')
    material = common.read(common.HERE / 'prepared.pkl')
    statistics = {name:{symbol:stats([r for r in value['rows'] if r['symbol']==symbol])
        for symbol in ('TOPIX','NK225')} for name,value in result['results'].items()}
    worst = {name:{symbol:[r['session'] for r in sorted(
        [r for r in value['rows'] if r['symbol']==symbol and r['収支']<0], key=lambda r:r['収支'])[:3]]
        for symbol in ('TOPIX','NK225')} for name,value in result['results'].items()}
    outcomes = {name:{symbol:{} for symbol in ('TOPIX','NK225')} for name in result['results']}
    tick_outcomes = {name:{symbol:{} for symbol in ('TOPIX','NK225')} for name in result['results']}
    classifications = []; examples = []; hashes = {}
    for key, input_data in sorted(material.items()):
        session,symbol = key
        path = common.REFERENCE / 'ledgers/L_D20_BBO' / (session+'_'+symbol+'.pkl.gz')
        relative = str(path.relative_to(common.REFERENCE)).replace('\\','/')
        assert common.digest(path) == source['台帳SHA256'][relative]
        hashes[str(path.relative_to(common.ROOT)).replace('\\','/')] = common.digest(path)
        base = packet(path); groups = classify(base, input_data['quote'], input_data['ready']['tick'])
        classifications.extend(dict(session=session, symbol=symbol, 親=cid, **g) for cid,g in groups.items())
        for name in result['results']:
            path = common.HERE / 'ledgers' / name / (session+'_'+symbol+'.pkl.gz')
            relative = str(path.relative_to(common.HERE)).replace('\\','/')
            assert common.digest(path) == result['台帳SHA256'][relative]
            hashes[str(path.relative_to(common.ROOT)).replace('\\','/')] = common.digest(path)
            candidate = packet(path); new_parents = {p['親']:p for p in candidate['parent']}
            for cid, group in groups.items():
                new = new_parents.get(cid); delta = (new['収支'] if new else 0.) - group['基準収支']
                for label, destination in ((group['分類'],outcomes[name][symbol]),
                                           (group['初回清算気配から1tick先着'],tick_outcomes[name][symbol])):
                    aggregate = destination.setdefault(label,dict(基準親数=0, 候補にも入口あり=0, 見送り=0,
                        基準収支=0., 候補収支=0., 収支変化=0., 決済済み利益脚あり基準親=0))
                    aggregate['基準親数']+=1; aggregate['候補にも入口あり']+=int(new is not None)
                    aggregate['見送り']+=int(new is None); aggregate['基準収支']+=group['基準収支']
                    aggregate['候補収支']+=new['収支'] if new else 0.; aggregate['収支変化']+=delta
                    aggregate['決済済み利益脚あり基準親']+=int(group['決済済み利益脚あり'])
            extra=[p for p in candidate['parent'] if p['親'] not in groups]
            aggregate=outcomes[name][symbol].setdefault('基準未約定の追加親',dict(基準親数=0,
                候補にも入口あり=0, 見送り=0, 基準収支=0., 候補収支=0., 収支変化=0., 決済済み利益脚あり基準親=0))
            aggregate['候補にも入口あり']+=len(extra); aggregate['候補収支']+=sum(p['収支'] for p in extra)
            aggregate['収支変化']+=sum(p['収支'] for p in extra)
            if session in worst[name][symbol]:
                bad = sorted([p for p in candidate['parent'] if p['収支']<0], key=lambda p:p['収支'])
                examples.append(dict(case=name, session=session, symbol=symbol,
                    session収支=candidate['summary']['収支'], 全赤字親数=len(bad),
                    最大赤字親2件=[example(candidate,input_data,p) for p in bad[:2]]))
    for name,value in result['results'].items():
        for symbol in ('TOPIX','NK225'):
            expected=value['symbols'][symbol]['収支']-source['results']['L_D20_BBO']['symbols'][symbol]['収支']
            assert np.isclose(sum(v['収支変化'] for v in outcomes[name][symbol].values()), expected, atol=1e-7, rtol=0.)
    common.save(target,dict(全合格=True, scope='全33既知の保存台帳事後診断。分類を入口に使わない。',
        安定性=statistics, 料金後利益経路別=outcomes, 初回1tick先着別=tick_outcomes,
        基準親分類=classifications, 赤字上位3場=worst, 具体時刻価格=examples, 分解一致=True,
        分類定義='基準親自身の実料金及び残UID清算料を引いた利益経路で区分。1tick先着は初回清算quoteが原点。',
        注意='建値差は測定したが、元影の密な当時停止線は保存packetにない。真の初期S距離は未計測。',
        sourceSHA256=common.digest(Path(__file__)), 残料sourceSHA256=common.digest(common.REFERENCE/'liquidation_path.py'),
        結果SHA256=common.digest(common.HERE/'結果.json'), 基準SHA256=common.digest(common.REFERENCE/'結果.json'),
        入力台帳SHA256=hashes, 新金融=0, 紙上再生=0, API=0, 原本再読=0))
    print('安定性・親の利益返し/初期1tick・赤字3場を保存',flush=True)


if __name__ == '__main__':
    run()
