"""元の全場赤字群が実際の反転再生でどう変わったか、前16だけを集計する。"""
from pathlib import Path
import hashlib
import json


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
SYMBOLS = ('TOPIX', 'NK225')


def load(path):
    """
    機能: 保存JSONを読む。
    引数: path (Path)。
    返り値: dict の内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


# ----------------------------------------
def summary(rows):
    """
    機能: 元又は逆の前半対象集合を、全場赤字と合計損益で集計する。
    引数: rows (list[dict]) の各条件前半比較。
    返り値: dict の件数。無取引は黒字と数えない。
    """
    return dict(条件数=len(rows),
        逆も両商品全16場赤字=sum(all(row['逆前16'][s]['赤字場数'] == 16 for s in SYMBOLS) for row in rows),
        逆が少なくとも片方合計赤字=sum(any(row['逆前16'][s]['収支円'] < 0 for s in SYMBOLS) for row in rows),
        逆が両商品合計黒字=sum(all(row['逆前16'][s]['収支円'] > 0 for s in SYMBOLS) for row in rows),
        逆が両商品合計赤字=sum(all(row['逆前16'][s]['収支円'] < 0 for s in SYMBOLS) for row in rows),
        逆が赤字なしでも片方以上合計ゼロ=sum(all(row['逆前16'][s]['収支円'] >= 0 for s in SYMBOLS) and any(row['逆前16'][s]['収支円'] == 0 for s in SYMBOLS) for row in rows),
        逆が両商品全16場黒字=sum(all(row['逆前16'][s]['黒字場数'] == 16 for s in SYMBOLS) for row in rows),
        黒字条件ID=[row['親ID'] for row in rows if all(row['逆前16'][s]['収支円'] > 0 for s in SYMBOLS)])


# ----------------------------------------
def main():
    """
    機能: 反転188条件を集計し、元全16場赤字66条件の仮説を検証する。
    引数: なし。
    返り値: None。順位や代表を変更せず、後半を参照しない。
    """
    origin_path = HERE / '前16だけの負け安定と費用分解.json'
    original = load(origin_path)
    lookup = {row['ID']: row for row in original['全188条件の元損益と分類']}
    paths = sorted((BASE / 'first/results').glob('*.json'))
    assert len(paths) == 188
    pairs = []
    for path in paths:
        result = load(path)
        c = result['config']
        assert c['polarity'] == -1 and c['latency'] == 5
        old = lookup[c['parent_id']]
        assert len({row['session'] for row in result['rows']}) == 16
        now = {symbol: dict(収支円=result['periods']['前16'][symbol]['net'],
                            利益円=result['periods']['前16'][symbol]['profit'],
                            損失円=result['periods']['前16'][symbol]['loss'],
                            決済組数=result['periods']['前16'][symbol]['trades'],
                            赤字場数=result['periods']['前16'][symbol]['losing_sessions'],
                            黒字場数=result['periods']['前16'][symbol]['winning_sessions'],
                            無取引場数=result['periods']['前16'][symbol]['no_trade_sessions']) for symbol in SYMBOLS}
        pairs.append(dict(親ID=c['parent_id'], 逆ID=c['id'], 新規モード=c['entry_mode'],
            元が両商品全16場赤字=all(old['前16'][symbol]['赤字場数'] == 16 for symbol in SYMBOLS),
            元前16={symbol: {key: old['前16'][symbol][key] for key in ('収支円', '中値経路損益円', '費用C円', '赤字場数', '黒字場数', '無取引場数', '決済組数')} for symbol in SYMBOLS},
            逆前16=now))
    allred = [row for row in pairs if row['元が両商品全16場赤字']]
    assert len(allred) == 66
    output = dict(対象='既知の前16で、元188条件と新規・返済を再実行した逆188条件を比較。元の損益符号だけを反転した値ではない。',
        選定='追加の代表選定・再順位付けを行わない。A/B/Cは既に事前固定。後14と全30の新結果は未参照。',
        元が両商品全16場赤字の66条件=summary(allred), 逆188全条件=summary(pairs),
        元全場赤字66の新規方式別={f'M{mode}': summary([row for row in allred if row['新規モード'] == mode]) for mode in (0, 1)},
        元全場赤字66の明細=allred,
        注意='条件どうしは入口・閾値を共有し、独立した66回又は188回の実験ではない。金額ゼロ・無取引は黒字に含めない。',
        出典SHA256={str(path.relative_to(BASE)): hashlib.sha256(path.read_bytes()).hexdigest() for path in [origin_path] + paths})
    target = HERE / '前半の毎場赤字66条件を実際に反転した集計.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: output[key] for key in ('元が両商品全16場赤字の66条件', '逆188全条件', '元全場赤字66の新規方式別')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
