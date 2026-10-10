"""固定済み全条件から銘柄別首位の隣接条件だけを記述比較し、新条件を追加しない。"""

import json
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
TIMES = [5, 15, 30, 60, 120, 240]
WIDTHS = ['W05', 'W10', 'W20']
AGGRESSIONS = ['A0', 'A1', 'A2']


def metrics(method: dict, symbol: str) -> dict:
    """機能: 指定条件の費用前後・週・追加ロット寄与を抜粋する。

    引数: method(dict)、symbol(str)。
    返り値: 比較用の小さな辞書(dict)。主気配評価だけを使用する。
    """
    value = method['summary'][symbol]
    chosen = {name: value[name] for name in ('gross_pnl', 'fees', 'net', 'pf', 'payoff', 'cycles',
              'positive_sessions', 'active_sessions', 'without_best', 'drawdown', 'additions',
              'initial_lot_net', 'added_lot_net', 'hold_mean_minutes', 'hold_median_minutes')}
    chosen['weeks'] = {week: {name: data[name] for name in ('gross_pnl', 'fees', 'net', 'profit', 'loss', 'cycles')}
                       for week, data in method['weeks'][symbol].items()}
    chosen['最大黒字場の寄与'] = value['net'] - value['without_best']
    other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    chosen['同条件の反対銘柄'] = {'symbol': other, 'net': method['summary'][other]['net']}
    return chosen


def lot_breakdown(method: dict, symbol: str) -> dict:
    """機能: 入口ロット別台帳から初回と追加の粗損益・配賦費用・純損益を分ける。

    引数: method(dict)、symbol(str)。
    返り値: 二種のロット集計(dict)。合計は元の実注文費用後会計と一致する。
    """
    ledgers = pickle.loads((HERE / method['ledger']).read_bytes())
    output = {}
    for action, name in ((1, '初回'), (3, '有利方向への追加')):
        records = [row for key, values in ledgers.items() if key[1] == symbol and key[2] == 'quote'
                   for row in values['trades'] if row[23] == action]
        output[name] = {'入口ロット数': len(records), '返済枚数': sum(int(row[3]) for row in records),
                        'gross_pnl': sum(float(row[6]) for row in records),
                        'fees': sum(float(row[7]) for row in records), 'net': sum(float(row[8]) for row in records)}
    assert abs(sum(v['net'] for v in output.values()) - method['summary'][symbol]['net']) < 1e-5
    return output


def main() -> None:
    """機能: 指定された二つの首位条件について一軸だけ異なる直近条件を比べる。

    引数: なし。
    返り値: なし(None)。損益後の説明だけで条件選定や再計算を行わない。
    """
    source = json.loads((HERE / '集計結果.json').read_text(encoding='utf-8'))
    methods = {item['id']: item for item in source['methods']}
    results = []
    for symbol, identifier in (('TOPIX', 'D4_H30_W20_A1'), ('NK225', 'D3_H120_W20_A2')):
        base = methods[identifier]
        neighbors = []
        for axis, name, grid in (('minutes', '保有期限だけ変更', TIMES),
                                  ('width_id', '幅だけ変更', WIDTHS), ('aggression', '積極度だけ変更', AGGRESSIONS)):
            position = grid.index(base['config'][axis])
            values = grid[max(0, position - 1):position] + grid[position + 1:position + 2]
            for value in values:
                matching = [m for m in methods.values() if m['family'] == base['family']
                            and all(m['config'][key] == (value if key == axis else base['config'][key])
                                    for key in ('minutes', 'width_id', 'aggression'))]
                assert len(matching) == 1
                candidate = matching[0]
                item = metrics(candidate, symbol)
                brief = {name: item[name] for name in ('gross_pnl', 'fees', 'net', 'cycles', 'without_best',
                                                      'initial_lot_net', 'added_lot_net')}
                brief['週純益'] = {week: data['net'] for week, data in item['weeks'].items()}
                neighbors.append(dict(変更軸=name, 変更値=value, id=candidate['id'], **brief,
                                      基準との差=item['net'] - base['summary'][symbol]['net']))
        result = dict(symbol=symbol, id=identifier, 基準=metrics(base, symbol), 隣接条件=neighbors,
                      隣接黒字数=sum(row['net'] > 0 for row in neighbors), 隣接条件数=len(neighbors),
                      入口種別損益=lot_breakdown(base, symbol),
                      注記='全て既知25場の固定格子上の事後比較。積極度は数量/追加/休止の組合せで、個別因果効果ではない。')
        results.append(result)
    report = {'対象': results, '売買コード変更': False, '再バックテスト': False,
              '週': '10/5週は5場の途中週。後付けの首位選定であり未知の安定性を示さない。',
              '重要': '有利追加ロットの純益はロット別会計。追加しなかった場合との因果差は注文集合が変わるので断定しない。'}
    (HERE / '銘柄別首位の隣接比較.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
