"""赤字場にも手数料後の清算利益があったかを、完成後の事実として調べる。"""

from datetime import datetime, timezone, timedelta
import numpy as np

from bridge import HERE, digest, read, save
from diagnose import packet
from liquidation_path import liquidation_curve


def clock(q: dict, row: int) -> dict:
    """
    機能: 正常原行の連番と価格時計を短い表示へ変換する。
    引数: q(dict)、row(int)は保存入力と行。
    返り値: dict。受信時計ではない。
    """
    return dict(行=row, 原連番=int(q['seq'][row]),
        板価格時計=datetime.fromtimestamp(float(q['time_s'][row]), timezone(timedelta(hours=9))).isoformat())


def last_losses(ledger: dict, q: dict, peak: int) -> list[dict]:
    """
    機能: その場の時系列最後の赤字親2件を、全実返済に対応付ける。
    引数: ledger/q(dict)、peak(int)は保存会計・気配・事後最大行。
    返り値: list[dict]。最大後だけに限らず選定規則を明示する。
    """
    parents = sorted([p for p in ledger['parent'] if p['収支'] < 0], key=lambda p: p['最終返済行'])[-2:]
    results = []
    for parent in parents:
        orders = ledger['orders'][ledger['orders'][:, 2] == parent['親']]
        entry = orders[orders[:, 7] == 1][0]
        exits = orders[orders[:, 7] == 0]
        results.append(dict(**parent,
            指値公開=clock(q, int(entry[1])), 新規=dict(**clock(q, int(entry[0])), 価格=float(entry[5])),
            全返済=[dict(**clock(q, int(o[0])), 判断=clock(q, int(o[1])), 価格=float(o[5]), 枚数=int(o[4]), 理由=int(o[6])) for o in exits],
            最大後に開始=bool(entry[0] > peak), 最大後に完結=bool(exits[-1, 0] > peak)))
    return results


def run() -> None:
    """
    機能: 全33の初回正味清算利益と赤字13場の最大及び最後の負けを保存する。
    引数: なし。
    返り値: None。政策金融や未来最大に基づく売買を実行しない。
    """
    result = read(HERE / '結果.json'); assert result['全合格']
    proof = read(HERE / 'UID別残返済料の人工検査.json'); assert proof['全合格']
    assert proof['sourceSHA256'] == digest(HERE / 'liquidation_path.py')
    target = HERE / '赤字13場の清算利益経路と最後の損失親.json'; assert not target.exists()
    quote_path = HERE / 'prepared/quotes.pkl'; quotes = read(quote_path)
    baseline = result['results']['L_D20_BBO']; rows = baseline['rows']
    paths = []; red = []; hashes = {}
    for row in rows:
        key = row['session'], row['symbol']; q = quotes[key]
        path = HERE / 'ledgers/L_D20_BBO' / (key[0] + '_' + key[1] + '.pkl.gz')
        name = str(path.relative_to(HERE)).replace('\\', '/')
        assert digest(path) == result['台帳SHA256'][name]; hashes[name] = digest(path)
        ledger = packet(path); curve, reserved = liquidation_curve(ledger, key[1])
        assert len(curve) == len(q['seq'])
        normal = np.flatnonzero(q['quote_valid']); assert len(normal)
        peak = int(normal[np.argmax(curve[normal])])
        positive = normal[curve[normal] > 0]
        first = int(positive[0]) if len(positive) else None
        record = dict(session=key[0], symbol=key[1], 最終収支=row['収支'], 活動=row['親数'] > 0,
            一度でも正味清算利益あり=bool(len(positive)), 最初の正味清算利益行=first,
            最初の正味清算利益=clock(q, first) if first is not None else None,
            最初の正味清算利益額=float(curve[first]) if first is not None else None,
            最大正味清算値=float(curve[peak]), 最大行=clock(q, peak), 最大時残返済料=int(reserved[peak]),
            注記='全経路を見た事後の到達事実。最大行は売買判断に使っていない。')
        paths.append(record)
        if row['収支'] < 0:
            red.append(dict(**record,
                最大より前に完結した赤字親数=sum(p['収支'] < 0 and p['最終返済行'] < peak for p in ledger['parent']),
                最大当行までに完結した赤字親数=sum(p['収支'] < 0 and p['最終返済行'] <= peak for p in ledger['parent']),
                最後の赤字親2件=last_losses(ledger, q, peak)))
    assert len(paths) == 66 and len(red) == 26
    summary = {}
    for symbol in ('TOPIX', 'NK225'):
        own = [r for r in paths if r['symbol'] == symbol]; negative = [r for r in red if r['symbol'] == symbol]
        assert len(own) == 33 and len(negative) == 13
        summary[symbol] = dict(全場=33, 活動場=sum(r['活動'] for r in own),
            正味清算利益到達場=sum(r['一度でも正味清算利益あり'] for r in own),
            赤字場=13, 赤字でも一旦清算利益あり=sum(r['一度でも正味清算利益あり'] for r in negative),
            赤字で一度も清算利益なし=sum(not r['一度でも正味清算利益あり'] for r in negative),
            赤字場の事後最大清算値中央値=float(np.median([r['最大正味清算値'] for r in negative])),
            無取引を勝ちとしない=True)
    save(target, dict(全合格=True, scope='L_D20_BBO全33の保存経路・赤字13場/商品。事後診断のみ。',
        集計=summary, 全33初回経路=paths, 赤字場詳細=red,
        評価='利益到達と次気配での実清算成績は別。既知の最大値で決済した仮想成功は計上していない。',
        清算値定義='bid買玉/ask売玉による時価−既に実注文に課した料金−当時残UIDごとのfloor返済料。',
        選択規則='各商品の全赤字13場。具体親は時系列で最後に完結した赤字2親。全損失を残す。',
        sourceSHA256={p.name: digest(p) for p in (HERE / 'liquidation_path.py', HERE / 'diagnose_loss_paths.py')},
        結果SHA256=digest(HERE / '結果.json'), 人工SHA256=digest(HERE / 'UID別残返済料の人工検査.json'),
        気配SHA256=digest(quote_path), 台帳SHA256=hashes, 読取台帳数=66, 紙上再生=0, 金融再生=0, API=0, 原本再読=0))
    print('全33の清算利益経路と赤字13場×両商品を保存', flush=True)


if __name__ == '__main__':
    run()
