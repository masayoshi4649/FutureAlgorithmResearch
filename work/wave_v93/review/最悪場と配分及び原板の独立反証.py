"""最悪場の原板、固定配分の非干渉と補完、最大勝ち依存を独立に反証する。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R


def worst_cases(ident: str, result: dict, ledgers: dict, material: dict, wanted: dict) -> dict:
    """
    機能: 商品別の赤字上位3場と各場の大きな損失3親を同seq原板へ戻す。
    引数: ident (str)、result/ledgers/material/wanted (dict)。
    返り値: dict は当時板・中心・判断・実約定・停止証拠の具体記録。
    """
    output = {}
    for symbol in R.SYMBOLS:
        selected = sorted((r for r in result['rows'] if r['symbol'] == symbol and r['net'] < 0),
                          key=lambda r: (r['net'], r['session']))[:3]
        output[symbol] = []
        for summary in selected:
            key = summary['session'], symbol
            record, ledger = material['prices'][key], ledgers[key]
            mapped = R.published_grid(record, material['grids'][key[0]]['grid'])
            parent_diagnostics = {int(row[0]): dict(zip(ledger['range_parent_columns'], map(float, row)))
                                  for row in ledger['range_parent_diagnostics']}
            details = []
            for trade in sorted(ledger['trades'], key=lambda t: t[11])[:3]:
                if trade[11] >= 0:
                    continue
                source, side = int(trade[1]), int(trade[4])
                orders = ledger['orders'][(ledger['orders'][:, 2] == trade[0]) & (ledger['orders'][:, 3] == source)]
                assert len(orders) == 2
                decision, entry, exit_row = int(trade[15]), int(trade[2]), int(trade[3])
                valid = np.flatnonzero(record['quote_valid'][entry:exit_row + 1]) + entry
                assert len(valid)
                quotes = record['bid'] if side == 1 else record['ask']
                progress = side * (quotes[valid] - trade[6])
                peak = int(valid[np.argmax(progress)])
                trough = int(valid[np.argmin(progress)])
                diagnosis = parent_diagnostics.get(int(trade[0])) if source == 1 else None
                timeline = []
                if source == 1:
                    same = ledger['events'][(ledger['events'][:, 2] == 1)
                                            & (ledger['events'][:, 10] == trade[14])
                                            & (ledger['events'][:, 0] <= decision)]
                    for code in (12, 16, 17, 22, 27, 28, 29, 30):
                        for event in same[same[:, 3] == code][-1:]:
                            timeline.append({'種類': ledger['event_codes'][code], '原板': R.point(key, int(event[0]), material, mapped, wanted),
                                             '当時基準': float(event[7]), '詳細': float(event[11])})
                extreme = None
                if diagnosis:
                    extreme = R.point(key, int(diagnosis['extreme_row']), material, mapped, wanted)
                    assert abs(extreme['mid'] - diagnosis['extreme']) < 1e-8
                details.append({'親': int(trade[0]), '源': 'J2' if source == 0 else 'O06',
                                '方向': '買い' if side == 1 else '売り', '枚数': int(trade[5]), '収支円': float(trade[11]),
                                '新規判断': R.point(key, decision, material, mapped, wanted),
                                '新規実約定': R.point(key, entry, material, mapped, wanted),
                                '返済判断': R.point(key, int(orders[1, 1]), material, mapped, wanted),
                                '返済実約定': R.point(key, exit_row, material, mapped, wanted),
                                '返済理由': ledger['reasons'][int(trade[13])],
                                '反発親の固定記録': diagnosis, '観測極値の原板': extreme,
                                '準備と入口経緯': timeline,
                                '事後最大順行': {'幅pt': float(progress.max()), '原板': R.point(key, peak, material, mapped, wanted)},
                                '事後最大逆行': {'幅pt': float(progress.min()), '原板': R.point(key, trough, material, mapped, wanted)}})
            output[symbol].append({'場': key[0], '利益円': summary['profit'], '損失円': summary['loss'],
                                   '収支円': summary['net'], '全親の独立会計': R.totals(ledger['trades']),
                                   '源別': summary['sources'], '大きな損失親3': details})
    return output


def source_independence(ledgers: dict, results: dict, fixed: dict) -> dict:
    """
    機能: 配分S03の各源を同枚数S00/S02へ全注文・全行清算時価まで照合する。
    引数: ledgers/results/fixed (dict)。
    返り値: dict は源非干渉、数学上限、追加と置換及び日別補完の結果。
    """
    output = {}
    columns = [0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
    for symbol in R.SYMBOLS:
        count = [0, 0]
        for session in fixed['全31']:
            key = session, symbol
            mixed = ledgers['S03'][key]
            for source, ident in [(0, 'S00'), (1, 'S02')]:
                single = ledgers[ident][key]
                a, b = single['orders'][single['orders'][:, 3] == source], mixed['orders'][mixed['orders'][:, 3] == source]
                assert np.array_equal(a[:, columns], b[:, columns]), (key, ident, '源別経済注文')
                assert single['source_curve_column_SHA256'][source] == mixed['source_curve_column_SHA256'][source]
                count[source] += 1
            left = ledgers['S02'][key]
            assert np.array_equal(left['range_parent_diagnostics'][:, 1:], mixed['range_parent_diagnostics'][:, 1:], equal_nan=True)
            assert left['risk_state_SHA256'] == mixed['risk_state_SHA256']
        mixed_metric = results['S03']['periods']['全31'][symbol]
        small = results['S00']['periods']['全31'][symbol]
        full = results['S01']['periods']['全31'][symbol]
        range_metric = results['S02']['periods']['全31'][symbol]
        assert abs(mixed_metric['net'] - small['net'] - range_metric['net']) < 1e-4
        gains = sum(v['profit'] for v in mixed_metric['sources'].values())
        losses = sum(v['loss'] for v in mixed_metric['sources'].values())
        share = gains / (gains + losses) if gains + losses else None
        assert share == mixed_metric['profit_share']
        active_shares = [v['profit_share'] for v in mixed_metric['sources'].values() if v['profit_share'] is not None]
        assert share is None or min(active_shares) - 1e-12 <= share <= max(active_shares) + 1e-12
        daily = []
        for session in fixed['全31']:
            source = [R.totals(ledgers['S03'][session, symbol]['trades'][ledgers['S03'][session, symbol]['trades'][:, 1] == i]) for i in (0, 1)]
            daily.append({'場': session, '追従': source[0]['net'], '反発': source[1]['net'],
                          '合計': source[0]['net'] + source[1]['net'], '両源活動': all(v['campaigns'] > 0 for v in source)})
        a, b, total = (np.array([v[name] for v in daily]) for name in ('追従', '反発', '合計'))
        full_net = np.array([next(v['net'] for v in results['S01']['rows'] if v['session'] == s and v['symbol'] == symbol) for s in fixed['全31']])
        corr = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else None
        output[symbol] = {'源同枚数全注文全行清算一致口座': {'追従': count[0], '反発': count[1]},
                          '反発源予定状態と親固定記録の一致': True,
                          'S00への反発追加収支円': mixed_metric['net'] - small['net'],
                          'S00への反発追加最大下落差円': mixed_metric['equity_drawdown'] - small['equity_drawdown'],
                          'S01同上限からの置換収支円': mixed_metric['net'] - full['net'],
                          'S01同上限からの置換最大下落差円': mixed_metric['equity_drawdown'] - full['equity_drawdown'],
                          '源別実金額利益割合': {n: v['profit_share'] for n, v in mixed_metric['sources'].items()},
                          '配分金額利益割合': share, '最高源割合': max(active_shares) if active_shares else None,
                          '加重平均上限一致': True, '場収支相関': corr,
                          '両源赤字場': int(np.sum((a < 0) & (b < 0))),
                          '追従赤字を合計黒字へ救った場': int(np.sum((a < 0) & (total > 0))),
                          '追従黒字を合計赤字へ変えた場': int(np.sum((a > 0) & (total < 0))),
                          'S03場収支標本標準偏差': float(np.std(total, ddof=1)),
                          'S01場収支標本標準偏差': float(np.std(full_net, ddof=1)), '全31源別場収支': daily}
    return output


def dependence(results: dict, ledgers: dict, fixed: dict) -> dict:
    """
    機能: 全16条件について最大利益親と最大利益日を一つ除いた後の親会計を算出する。
    引数: results/ledgers/fixed (dict)。
    返り値: dict は事後依存診断。除外を売買ルールへ使わない。
    """
    output = {}
    for ident, result in results.items():
        output[ident] = {}
        for symbol in R.SYMBOLS:
            combined = np.concatenate([ledgers[ident][s, symbol]['trades'] for s in fixed['全31']])
            index = int(np.argmax(combined[:, 11])) if len(combined) else None
            removed = float(combined[index, 11]) if index is not None else None
            remaining = np.delete(combined, index, axis=0) if index is not None else combined
            metric = result['periods']['全31'][symbol]
            assert removed is None or abs(R.totals(remaining)['net'] - metric['net'] + removed) < 1e-4
            output[ident][symbol] = {'除外最大親収支円': removed, '最大親除外': R.totals(remaining),
                                    '最大利益日': metric['best_day'], '最大日除外': metric['without_best_day'],
                                    '買売別': metric['directions'], '前16': result['periods']['前16'][symbol],
                                    '後15': result['periods']['後15'][symbol]}
    return output


def main() -> None:
    """
    機能: 根の全正式完了許可後、原板と配分及び最大勝ち依存の反証を保存する。
    引数: --根許可後 (bool)。
    返り値: None。新規の条件探索・売買再生を行わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    proof = R.read(R.HERE / '全16条件全31の独立親会計と同一判断及び再参加経路分解.json')
    risk = R.read(R.HERE / '全16条件の予定入口と停止証拠及び失敗休止の独立診断.json')
    assert proof['全合格'] and proof['口座'] == 992 and risk['全合格']
    assert proof['根集計SHA256'] == risk['根集計SHA256'] == R.digest(R.WORK / 'analysis/比較結果.json')
    selected = R.read(R.WORK / '前16参考代表.json')['selected']
    data = R.module('最悪板の独立読取93', R.WORK / 'data.py')
    material = data.load_inputs()
    ledgers = {v['id']: R.load_ledgers(v['id']) for v in fixed['条件']}
    identities = list(dict.fromkeys((fixed['主'], selected, 'S03')))
    wanted = {}
    cases = {i: worst_cases(i, assembled['results'][i], ledgers[i], material, wanted) for i in identities}
    raw_proofs = R.attach_raw(wanted)
    source_proof = source_independence(ledgers, assembled['results'], fixed)
    lost_wins = {}
    for pair in ('C00→C02', 'C01→C02', 'C05→C06', 'C05→C07', 'C06→C11'):
        lost_wins[pair] = {}
        for symbol in R.SYMBOLS:
            groups = proof['部品差分'][pair][symbol]['O06']['同一判断符号変化']
            before_win = sum(v['親'] for name, v in groups.items() if name.startswith('利益→'))
            became_loss = groups.get('利益→損失', {'親': 0})['親']
            lost_wins[pair][symbol] = {'同一判断に対応した元利益親': before_win,
                                      '元利益から新損失へ変わった親': became_loss,
                                      '元利益を損失へ変えた割合': became_loss / before_win if before_win else None,
                                      '全符号群': groups}
    both80 = proof['両商品金額80']
    R.save('主と前16参考及び配分の最悪3場と原板及び敵対的結論.json', {
        '全合格': True, '主': fixed['主'], '前16固定参考': selected, '条件数': 16, '場数': 31,
        '口座': 992, '両商品金額80': both80, '最悪場': cases, '原本同seq照合': raw_proofs,
        '配分源非干渉と追加及び置換': source_proof, '元勝ちを失った割合': lost_wins,
        '全16の最大利益親及び最大利益日除外': dependence(assembled['results'], ledgers, fixed),
        '条件を結果で変更': False, '後成績で主及び参考の差替え': False,
        '注意': ['原板の厚さだけから消化・補充・取消や参加者意図を断定しない。',
                 '代理時計は真の受信時刻でない。mini/micro全量の実約定可能性は未証明。',
                 '事後最大値と除外診断を売買条件へ逆流させない。',
                 '異なる思想でも同じ方向を持てば同時損失を出す。低相関でPF4が作れるとは扱わない。'],
        '根拠SHA256': {str(p.relative_to(R.ROOT)): R.digest(p) for p in (
            R.HERE / '全16条件全31の独立親会計と同一判断及び再参加経路分解.json',
            R.HERE / '全16条件の予定入口と停止証拠及び失敗休止の独立診断.json')},
        '計算コードSHA256': R.digest(Path(__file__)), **R.provenance()})
    print('最悪場原板・配分源非干渉・最大勝ち依存の敵対的診断を保存しました', flush=True)


if __name__ == '__main__':
    main()
