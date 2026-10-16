"""固定された3親の元台帳だけから、反転仮説の根拠と弱点を記録する。"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import pickle
import numpy as np
from original_losses import source_inputs


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))


def load(path):
    """
    機能: 固定選定又は元結果・台帳を読み取る。
    引数: path (Path)。
    返り値: dict の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8')) if path.suffix == '.json' else pickle.loads(path.read_bytes())


# ----------------------------------------
def example(parent, key, trade, ready, books, orders):
    """
    機能: 元取引一組の観測時計、中値、実約定気配と料金を記録する。
    引数: parent/key (dict/tuple)、trade (ndarray)、ready/books (dict)、orders (ndarray)。
    返り値: dict の元取引具体例。新反転約定は生成しない。
    """
    symbol = key[1]
    value = 1000 if symbol == 'TOPIX' else 10
    cid, entry, exit = [int(v) for v in trade[:3]]
    side, qty = int(trade[3]), int(trade[4])
    source = books[key]
    middle_entry = float(source['bid'][entry] + source['ask'][entry]) / 2
    middle_exit = float(source['bid'][exit] + source['ask'][exit]) / 2
    scale = value * qty
    mid = side * (middle_exit - middle_entry) * scale
    spread = side * (trade[5] - middle_entry) * scale + side * (middle_exit - trade[6]) * scale
    fees = float(trade[7] + trade[8])
    assert abs(mid - spread - fees - trade[10]) < .01
    pair = orders[orders[:, 2] == cid]
    assert len(pair) == 2
    times = {}
    for order in pair:
        kind = '新規' if order[7] else '返済'
        times[kind] = dict(判断JST=datetime.fromtimestamp(float(order[10]), JST).isoformat(),
                          約定JST=datetime.fromtimestamp(float(order[12]), JST).isoformat())
    return dict(枠=parent['label'], 親ID=parent['parent_id'], セッション=key[0], 商品=symbol, 組=cid,
        方向='買い' if side > 0 else '売り', 枚数=qty, 時計=times,
        新規値=float(trade[5]), 返済値=float(trade[6]), 新規中値=middle_entry, 返済中値=middle_exit,
        中値損益M円=mid, 気配差円=spread, 料金円=fees, 費用C円=spread + fees, 元収支円=float(trade[10]),
        同一経路を仮定した反転算術円=-mid-spread-fees,
        反転再生の実績ではない=True, M1経路固定の仮定=parent['original']['entry_mode'] == 1,
        新規原本seq=int(ready[key]['seq'][entry]), 返済原本seq=int(ready[key]['seq'][exit]))


# ----------------------------------------
def main():
    """
    機能: root固定A/B/Cを元前16の台帳で照合し、追加選定を行わず説明を保存する。
    引数: なし。
    返り値: None。反転再生結果と後14は未参照。
    """
    fixed_path = HERE.parent / '事前固定.json'
    fixed = load(fixed_path)
    old_fixed = load(ROOT / 'work/wave_v81/初回事前固定.json')
    front = old_fixed['前16']
    all_path = HERE / '前16だけの負け安定と費用分解.json'
    previous = load(all_path)
    lookup = {record['ID']: record for record in previous['全188条件の元損益と分類']}
    ready, books, paths = source_inputs(front)
    paths.extend([fixed_path, all_path])
    results, examples, account_count, trade_count = [], [], 0, 0
    for parent in fixed['pairs']:
        result_path = ROOT / parent['source']
        result = load(result_path)
        ledger_path = result_path.parent.parent / 'ledgers' / (parent['parent_id'] + '.pkl')
        ledger = load(ledger_path)
        paths.extend([result_path, ledger_path])
        record = lookup[parent['parent_id']]
        results.append(dict(枠=parent['label'], 選定理由=parent['name'], 親ID=parent['parent_id'],
            前16=record['前16'], 自市場始終分類別=record['自市場の上昇下落横ばい別']))
        for symbol in ('TOPIX', 'NK225'):
            candidates = []
            scale = 1000 if symbol == 'TOPIX' else 10
            for session in front:
                key = (session, symbol)
                trades = ledger[key]['trades']
                entry, exit = trades[:, 1].astype(int), trades[:, 2].astype(int)
                b = books[key]
                mid_entry = (np.asarray(b['bid'][entry], dtype=float) + np.asarray(b['ask'][entry], dtype=float)) / 2
                mid_exit = (np.asarray(b['bid'][exit], dtype=float) + np.asarray(b['ask'][exit], dtype=float)) / 2
                mid = trades[:, 3] * trades[:, 4] * scale * (mid_exit - mid_entry)
                spread = trades[:, 3] * trades[:, 4] * scale * ((trades[:, 5] - mid_entry) + (mid_exit - trades[:, 6]))
                fees = trades[:, 7] + trades[:, 8]
                assert np.allclose(mid - spread - fees, trades[:, 10], atol=1e-7)
                row = next(value for value in result['rows'] if value['session'] == session and value['symbol'] == symbol)
                assert abs(float(mid.sum()) - row['net'] - row['fees'] - row['spread_drag']) < .01
                assert abs(float(spread.sum()) - row['spread_drag']) < .01
                account_count += 1; trade_count += len(trades)
                candidates.extend((key, trade) for trade in trades)
            for label, pair in (('元の最大損失', min(candidates, key=lambda pair: pair[1][10])),
                                ('元の最大利益', max(candidates, key=lambda pair: pair[1][10]))):
                item = example(parent, pair[0], pair[1], ready, books, ledger[pair[0]]['orders'])
                item['選択'] = label
                examples.append(item)
    conclusion = [
        'Aは両商品16/16場が赤字だが、TOPIXの中値損失592,500円に対し費用Cは70,777,440円。日経は中値では124,000円の利益だった。全日負けの主因は方向を全日外すことではなく、短い方向反転に大量に出入りする費用である。',
        'Bも両商品16/16場赤字で、中値ではTOPIX14場・日経12場が赤字。方向を外した頻度は高いが、中値損失は費用Cの20.8%・14.2%にすぎない。中値方向を反転できても、その幅だけでは売買費用を払えない。',
        'Cは全日負けではない。元はTOPIX10赤字/5黒字/1休止、日経9赤字/6黒字/1休止。中値損失がCの2.72倍・2.08倍あり、同時刻方向反転の算術上は費用を超える余地がある。ただし、元前半の反転余地を使って選んだ探索候補である。',
        'Cの日経は横ばい分類2場の中値−271,000円が前半全体の中値−233,000円を全て説明する。上昇分類8場は＋10,000円、下落6場は＋28,000円。TOPIXは上昇8場の中値−710,000円が主体で、両商品が同じ局面で外す法則ではない。',
        '横ばい分類は始終差だけであり、場の途中で大きく上下した可能性を排除しない。前半横ばいはTOPIX1場・日経2場だけなので、その区分の一般性は確認できない。',
        '元188のうち両商品全16場赤字は66条件。その66条件で、両商品の中値損失が費用Cを超えた条件は0。中値自体が両商品全16場赤字の条件も0。日々の赤字の安定性と、方向の外れの安定性は区別が必要である。']
    output = dict(対象='事前固定A/B/Cの元前16だけ。新しい反転損益、後14、全30の逆結果は参照しない。',
        結論=conclusion, 前半3枠根拠=results, 元台帳からの損益具体例=examples,
        台帳照合=dict(口座数=account_count, 決済組数=trade_count, 全組中値損益から気配差料金を引いて元収支一致=True),
        算術注意='掲載した同一経路の反転算術は新しい逆手法の実績ではない。M0の同時刻・同枚数でR逆=−R元−2C。AのM1は不成立・再参加経路が変わり得るため、その式を新逆実績として使わない。',
        事後分類の使用='終中値を含む分類は損失原因の説明だけで使用。戦略・手法選定・新パラメータには使用しない。',
        出典SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    target = HERE / '固定3枠の元前半だけの根拠.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(保存=str(target), 台帳照合=output['台帳照合'], 具体例数=len(examples)), ensure_ascii=False))


if __name__ == '__main__':
    main()
