"""別実装の約定価格・決済会計との一致、入力不変と時系列を検査する。"""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT/'アルゴリズム調査/00046_E01の15秒最悪約定比較'
OTHER = ROOT/'work/e01_worst15_independent'


def read(path: Path) -> object:
    """機能: 保存JSONを読む。

    引数: path(Path)。返り値: 保存値(object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    """機能: 全価格・金額の別実装一致と、数量・時刻の成立を確認する。

    引数: なし。返り値: なし(None)。不一致では検証記録を発行しない。
    """
    data = read(REPORT/'計算結果.json')
    other_orders = {(r['セッション'],r['銘柄'],r['注文番号']):r for r in read(OTHER/'注文明細.json')}
    other_trades = {(r['セッション'],r['銘柄'],r['決済番号']):r for r in read(OTHER/'決済明細.json')}
    other_sessions = {(r['セッション'],r['銘柄']):r for r in read(OTHER/'独立計算.json')['セッション別']}
    order_count = trade_count = 0
    for row in data['sessions']:
        key = row['session'],row['symbol']
        position = 0
        last_row = -1
        for index,order in enumerate(row['orders']):
            other = other_orders[*key,index]
            assert order['worst_price'] == other['最悪価格']
            assert order['ideal_price'] == other['理想価格']
            assert order['adverse_yen'] == -other['収支差円']
            assert order['decision_time'] <= order['worst_time'] <= order['decision_time']+15
            assert order['decision_row'] <= order['worst_row']
            assert order['worst_row'] >= last_row
            last_row = order['worst_row']
            position += order['side'] * order['quantity']
            assert abs(position) <= (5 if row['symbol']=='TOPIX' else 10)
            order_count += 1
        assert position == 0
        for index,trade in enumerate(row['trades']):
            other = other_trades[*key,index]
            assert trade['ideal_pnl'] == other['理想損益円']
            assert trade['worst_pnl'] == other['最悪損益円']
            assert not trade['worst_entry_after_exit_decision']
            assert not trade['worst_entry_after_exit_fill']
            trade_count += 1
        reference = other_sessions[key]
        for mode, label in [('ideal','理想'),('worst','15秒最悪')]:
            for field, word in [('profit','利益円'),('loss','損失円'),('net','収支円'),
                                ('win_units','利益枚数'),('loss_units','損失枚数'),('flat_units','同値枚数')]:
                assert row[mode][field] == reference[label][word]
    assert order_count == len(other_orders) == 469 and trade_count == len(other_trades) == 291
    for source,digest in data['sources'].items():
        assert hashlib.sha256((ROOT/source).read_bytes()).hexdigest() == digest
    strict = read(REPORT/'発注判断時刻の監査.json')
    assert strict['全合格'] and strict['対象注文数'] == order_count
    assert strict['厳密起点による価格変化数'] == 0
    for symbol in ('TOPIX','NK225'):
        assert strict['合計'][symbol]['厳密起点'] == data['totals'][symbol]['worst']['net']
    result = {'全合格':True,'セッション数':19,'口座数':38,'別実装との約定価格一致':order_count,
              '別実装との決済損益一致':trade_count,'全口座利益損失枚数一致':True,
              '元の理想値は00044と一致':data['audit']['ideal_equals_00044'],
              '判断後15秒窓と数量上限を確認':True,'最悪時刻による注文順序逆転なし':True,
              'セッション境界と入力終端による窓短縮なし':data['audit']['dataset_short_windows']==data['audit']['session_short_windows']==0,
              '入力台帳指紋不変':True,'現在セッション追加取得数':0,
              '発注判断時刻の厳密監査':True,
              '注意':'独立実装は全fill起点。成行返済をsource起点に厳密化しても全最悪価格・損益が一致する。',
              '計算結果SHA256':hashlib.sha256((REPORT/'計算結果.json').read_bytes()).hexdigest()}
    (REPORT/'検証記録.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
