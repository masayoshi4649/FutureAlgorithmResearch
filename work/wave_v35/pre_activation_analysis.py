"""固定A0の全組を原価格の順行幅で分け、追跡始動前の損失を事後会計する。"""
from pathlib import Path
import pickle
import numpy as np
import conditional_runner as runner

HERE, ROOT = runner.HERE, runner.ROOT


def aggregate(rows: list) -> dict:
    """機能: 全組と保守的な未始動組の金額・件数を集計する。

    引数: rows (list[dict])。返り値: 集計 (dict)。利益玉のみを選ばない。
    """
    selected = [r for r in rows if r['退出行含む1_5A0未満']]
    losses = sum(r['返済脚損失円'] for r in rows)
    selected_losses = sum(r['返済脚損失円'] for r in selected)
    return {'全組数': len(rows), '全組収支円': sum(r['収支円'] for r in rows),
        '全返済脚利益円': sum(r['返済脚利益円'] for r in rows), '全返済脚損失円': losses,
        '未始動組数': len(selected), '未始動勝ち組数': sum(r['収支円'] > 1e-6 for r in selected),
        '未始動負け組数': sum(r['収支円'] < -1e-6 for r in selected),
        '未始動同値組数': sum(abs(r['収支円']) <= 1e-6 for r in selected),
        '未始動組収支円': sum(r['収支円'] for r in selected),
        '未始動勝ち組利益円': sum(max(0., r['収支円']) for r in selected),
        '未始動負け組損失円': sum(max(0., -r['収支円']) for r in selected),
        '未始動返済脚利益円': sum(r['返済脚利益円'] for r in selected),
        '未始動返済脚損失円': selected_losses,
        '全返済脚損失に占める未始動損失割合': selected_losses / losses if losses else None,
        '未始動以外の組収支円': sum(r['収支円'] for r in rows if not r['退出行含む1_5A0未満']),
        '退出行だけで始動閾値到達組数': sum(r['退出行だけで1_5A0到達'] for r in rows)}


def main() -> None:
    """機能: H019の3時計・全13と後7について、台帳と生価格だけで未始動損失を分解する。

    引数: なし。返り値: なし (None)。注文器再生・戦略変更・現在参照は行わない。
    """
    inputs_path = HERE.parent / 'wave_v23/inputs.pkl'
    inputs = pickle.loads(inputs_path.read_bytes())
    fixed = runner.read(HERE / '探索条件の固定.json')
    ids = [f'H019__A0__{variant}' for variant in ('V000', 'C080', 'C120')]
    paths = [inputs_path, HERE / 'engine_conditional.py', HERE / '探索条件の固定.json', Path(__file__)]
    paths += [HERE / folder / (name + suffix) for name in ids for folder, suffix in (('ledgers', '.json.gz'), ('sessions', '.json.gz'), ('summaries', '.json'))]
    before = {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in paths}
    output, summaries = [], {}
    for name in ids:
        summary = runner.read(HERE / 'summaries' / (name + '.json'))
        ledgers = runner.read(HERE / 'ledgers' / (name + '.json.gz'))
        raw_rows = runner.read(HERE / 'sessions' / (name + '.json.gz'))
        target = {(r['session'], r['symbol']): r for r in raw_rows}
        assert len(ledgers) == len(target) == 26
        for ledger in ledgers:
            key = ledger['session'], ledger['symbol']; ready = inputs[key]
            cfg = ledger['config']; assert cfg['activation_atr'] == 1.5 and cfg['main_trail'] == 3.
            assert cfg['add_mode'] == cfg['reverse_mode'] == cfg['hedge_ratio'] == 0
            orders = np.asarray(ledger['orders'], float).reshape(-1, 8)
            cycles = np.asarray(ledger['cycles'], float).reshape(-1, 10)
            trades = np.asarray(ledger['trades'], float).reshape(-1, 11)
            prepares = np.asarray(ledger['prepare_events'], float).reshape(-1, 7)
            links = {int(r[0]): r for r in ledger['entry_preparations']}
            openings = {int(o[2]): o for o in orders if o[7] == 1}
            events = np.asarray(ledger['trail_events'], float).reshape(-1, 15)
            assert len(cycles) == len(openings) == len(links)
            local = []
            for cycle in cycles:
                campaign, begin, end = map(int, cycle[:3]); opening = openings[campaign]
                link = links[campaign]; prepare = prepares[int(link[2])]
                assert int(opening[0]) == int(link[1]) == begin
                assert int(link[3]) == int(prepare[1]) and prepare[4] == cycle[5]
                side, anchor, a0 = int(opening[3]), float(opening[5]), float(cycle[5])
                assert side == int(cycle[8]) == int(prepare[2]) and a0 > 0
                legs = trades[trades[:, 0] == campaign]
                assert np.all(legs[:, 4] == anchor) and np.all(legs[:, 2] == side)
                pnl = legs[:, 10] * cfg['point_value']
                net = float(cycle[3] * cfg['point_value'])
                assert abs(float(pnl.sum()) - net) <= 1e-6
                movement = side * (ready['last'][begin:end + 1] - anchor)
                assert np.isfinite(movement).all()
                maximum = float(max(0., np.max(movement)))
                before_exit = float(max(0., np.max(movement[:-1]))) if len(movement) > 1 else 0.
                below = maximum < 1.5 * a0
                progressed = events[events[:, 1] == campaign]
                if below:
                    assert len(progressed) == 0, '原価格未到達なのに追跡が始動'
                    assert not np.any(legs[:, 9] == 2), '原価格未到達なのに追跡返済'
                record = {'id': name, 'session': key[0], 'symbol': key[1], 'campaign': campaign,
                    '初回方向': side, '新規行': begin, '退出行': end, '準備行': int(prepare[1]),
                    '約定建値_anchor': anchor, '準備時A0': a0, '初回数量': int(opening[4]),
                    '最大順行価格幅_退出行含む': maximum, '最大順行A0比_退出行含む': maximum / a0,
                    '最大順行A0比_退出行除く': before_exit / a0, '退出行含む1_5A0未満': bool(below),
                    '退出行だけで1_5A0到達': bool(before_exit < 1.5 * a0 <= maximum),
                    '記録された追跡進行件数': len(progressed), '収支円': net,
                    '返済脚利益円': float(pnl[pnl > 1e-6].sum()),
                    '返済脚損失円': float(-pnl[pnl < -1e-6].sum()),
                    '返済理由': [runner.engine.REASONS[int(r[9])] for r in legs]}
                local.append(record); output.append(record)
            values = aggregate(local)
            for field, original in (('全組収支円', 'net_yen'), ('全返済脚利益円', 'gross_profit_yen'), ('全返済脚損失円', 'gross_loss_yen')):
                assert abs(values[field] - target[key][original]) <= 1e-6
        summaries[name] = {}
        for period, sessions in (('all_symbols', fixed['全セッション']), ('symbols', fixed['共通評価7セッション'])):
            summaries[name][period] = {}
            for symbol in runner.SYMBOLS:
                rows = [r for r in output if r['id'] == name and r['symbol'] == symbol and r['session'] in sessions]
                values = aggregate(rows)
                assert abs(values['全組収支円'] - summary[period][symbol]['net_yen']) <= 1e-6
                assert abs(values['全返済脚損失円'] - summary[period][symbol]['gross_loss_yen']) <= 1e-6
                summaries[name][period][symbol] = values
    assert before == {name: runner.digest(ROOT / name) for name in before}
    value = {'事後診断': True, '戦略変更': False, '注文器再生': False, 'API取得数': 0, '現在保存物使用': False,
        '対象': ids, '分類': '約定建値をanchor、初回準備ATRをA0とし、新規行〜退出行を両端込みで生価格の最大順行を計算。厳密に1.5A0未満。',
        '保守性': '退出行はその行の返済処理後に追跡を設定できない場合も含む。この行だけの到達組も未始動から除外する。',
        '会計': '負け額は負け組の純損失と全返済脚損失を分離。利益玉・同値玉も全組集計へ含む。',
        '限界': '同じ入口、同じ初期ストップ、始動1.5A0を保ち、始動後の幅だけ変える場合に触れない損失。始動前の数量調整まで不可能とする意味ではない。',
        '全組数': len(output), '集計': summaries, '全組': output, '参照SHA256': before}
    runner.save(HERE / '追跡始動前の損失分解.json', value)
    lines = ['# 追跡始動前の損失分解', '', '結果後の会計診断。注文器再生・戦略変更は行っていない。約定建値と準備時A0を用い、**退出行を含む生価格最大順行が1.5A0未満**の組だけを保守的に分類した。', '',
        '|条件|期間|銘柄|全組|未始動組|全収支|未始動収支|未始動の負け額|全損失に占める割合|',
        '|---|---|---|---:|---:|---:|---:|---:|---:|']
    for name, periods in summaries.items():
        for period, symbols in periods.items():
            for symbol, s in symbols.items():
                ratio = s['全返済脚損失に占める未始動損失割合']
                lines.append(f"|{name}|{'全13' if period == 'all_symbols' else '後7'}|{symbol}|{s['全組数']}|{s['未始動組数']}|{s['全組収支円']:,.0f}円|{s['未始動組収支円']:,.0f}円|{s['未始動負け組損失円']:,.0f}円|{ratio:.1%}|" if ratio is not None else '')
    lines += ['', '各セルは保存された全組・全返済の集計と一致。未始動以外の利益で相殺された金額もJSONへ残した。原価格は返済行も含むため、実際には追跡できなかった境界例を未始動へ過大算入しない。', '',
        '注文器は新規約定時に anchor を実際の約定価格へ固定し、A0は新規準備時の pending_atr を引き継ぐ。台帳の新規価格・準備起点・全返済元建値・cyclesのA0を全組で照合した。', '',
        '**入口と初期ストップを同じに保ち、1.5A0到達後の追跡幅だけを変える方式は、この未始動群へ作用しない。** 部分調整を始動前から行う別仮説まで不可能とする結果ではない。一方、始動後の出口改善で入口時計問題も解いたと説明する根拠にはならない。']
    (HERE / '追跡始動前の損失分解.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(__import__('json').dumps(summaries, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
