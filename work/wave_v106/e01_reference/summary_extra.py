"""完成済み会計だけから利益の集中率と赤字場に限定した差分診断を追加する。"""

import numpy as np

from bridge import HERE, ROOT, digest, read, save
from diagnose import decompose, packet


def run() -> None:
    """
    機能: 純益と総利益の分母を区別して集中率を示し、赤字悪化上位3場を補足する。
    引数: なし。
    返り値: None。既存結果を変更せず、再金融・原本・APIは使わない。
    """
    result = read(HERE / '結果.json'); assert result['全合格']
    prior = read(HERE / '安定性と悪化上位3場の分解.json')
    concentration = {}; selected = {}
    price_rows = {(r['session'], r['symbol']): r for r in result['results']['L_D20_PRICE']['rows']}
    for name, value in result['results'].items():
        concentration[name] = {}
        for symbol in ('TOPIX', 'NK225'):
            rows = [r for r in value['rows'] if r['symbol'] == symbol]
            best = max(rows, key=lambda r: r['収支']); net = sum(r['収支'] for r in rows)
            positive_session_net = sum(r['収支'] for r in rows if r['収支'] > 0)
            concentration[name][symbol] = dict(最高利益場=best['session'], 最高利益場収支=best['収支'],
                全収支に対する最高利益場比率=best['収支'] / net if net > 0 else None,
                黒字場純益合計に対する最高利益場比率=best['収支'] / positive_session_net if positive_session_net > 0 else None,
                黒字場純益合計=positive_session_net, 全収支=net,
                注記='全収支比は黒字場と赤字場を相殺した合計が分母、黒字場純益比は黒字セッションの収支合計が分母。親総利益割合とは別。')
    for symbol in ('TOPIX', 'NK225'):
        negative = [r for r in result['results']['L_D20_BBO']['rows'] if r['symbol'] == symbol and r['収支'] < 0]
        selected[symbol] = [(r['session'], symbol) for r in sorted(negative,
            key=lambda r: r['収支'] - price_rows[r['session'], symbol]['収支'])[:3]]
    old = {(d['session'], d['symbol']): d for d in prior['具体分解']}
    targets = [key for symbol in ('TOPIX', 'NK225') for key in selected[symbol]]
    unknown = [key for key in targets if key not in old]
    inputs = {}; hashes = {}
    if unknown:
        path = ROOT / 'work/wave_v83/prepared/inputs.pkl'
        proof = read(ROOT / 'work/wave_v83/prepared/価格入力の照合.json')
        assert digest(path) == proof['出力SHA256']
        inputs = read(path); quotes = read(HERE / 'prepared/quotes.pkl')
        hashes['work/wave_v83/prepared/inputs.pkl'] = proof['出力SHA256']
        hashes['prepared/quotes.pkl'] = digest(HERE / 'prepared/quotes.pkl')
    details = []
    for key in targets:
        if key in old:
            details.append(dict(old[key], 保存原因資料再利用=True))
            continue
        session, symbol = key
        q = quotes[key]; last = inputs[key]['price'] if key in inputs else None
        if last is None:
            path = HERE / 'prepared' / session / 'features' / f'約定系列_{symbol}_{session}.npz'
            with np.load(path, allow_pickle=False) as tape:
                last = tape['last']
        else:
            for name in ('seq', 'time_s'):
                np.testing.assert_array_equal(q[name], inputs[key][name])
        packets = {}
        for name in ('L_D20_PRICE', 'L_D20_BBO'):
            path = HERE / 'ledgers' / name / (session + '_' + symbol + '.pkl.gz')
            relative = str(path.relative_to(HERE)).replace('\\', '/')
            assert digest(path) == result['台帳SHA256'][relative]
            hashes[relative] = digest(path); packets[name] = packet(path)
        path = HERE / 'paper' / (session + '_' + symbol + '.pkl.gz')
        relative = str(path.relative_to(HERE)).replace('\\', '/')
        assert digest(path) == result['紙上SHA256'][relative]; hashes[relative] = digest(path)
        details.append(dict(decompose(key, packets['L_D20_PRICE'], packets['L_D20_BBO'], q, last, packet(path)),
                            保存原因資料再利用=False))
    save(HERE / '最高利益場の集中率と赤字場の分解.json', dict(全合格=True,
        scope='完成後の会計のみ。新条件の探索ではない。', 結果SHA256=digest(HERE / '結果.json'),
        元原因SHA256=digest(HERE / '安定性と悪化上位3場の分解.json'), sourceSHA256=digest(HERE / 'summary_extra.py'),
        利益集中率=concentration, 赤字場選定='BBO収支<0の場で、BBO−LP差が小さい順の3場/商品。',
        赤字場選択=selected, 赤字場分解=details, 再利用原因件数=len(targets) - len(unknown),
        追加原因件数=len(unknown), 入力台帳SHA256=hashes, 金融再生=0, API=0, 原本再読=0))
    print('最高利益場集中率と赤字悪化上位3場の補足完了', flush=True)


if __name__ == '__main__':
    run()
