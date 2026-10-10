"""出口変更後の新規経路を、一致する約定とそれ以外へ事後に分ける。"""

from datetime import datetime
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import atr_runner as runner


def campaigns(rows: list[dict]) -> dict:
    """機能: 新規行・建値・方向・枚数・A0が一致する組の照合キーを作る。

    引数: rows (list[dict]) は全26台帳。返り値: 厳密新規条件をキーとする組 (dict)。
    """
    output = {}
    for record in rows:
        orders = {int(r[2]): r for r in record['orders'] if r[7] == 1}
        for cycle in record['cycles']:
            order = orders[int(cycle[0])]
            key = (record['session'], record['symbol'], int(order[0]), order[5], int(order[3]), int(order[4]), cycle[5])
            assert key not in output
            output[key] = {'session': key[0], 'symbol': key[1], 'entry_row': key[2], 'entry_price': key[3],
                           'direction': key[4], 'qty': key[5], 'initial_atr': key[6], 'campaign': int(cycle[0]),
                           'exit_row': int(cycle[2]), 'net_yen': cycle[3] * record['config']['point_value']}
    return output


def main() -> None:
    """機能: H019主二方式の保存全玉から、新規経路の変化と説明用時系列を保存する。

    引数: なし。返り値: なし (None)。事後説明であり、条件探索・採否変更を行わない。
    """
    files = [runner.HERE / 'ledgers' / ('H019__' + mode + '__V000.json.gz') for mode in ('A0', 'AT')]
    old, new = [campaigns(runner.read(path)) for path in files]
    common = set(old) & set(new)
    summaries = {}
    for symbol in ('TOPIX', 'NK225'):
        matched = [k for k in common if k[1] == symbol]
        old_only = [k for k in old.keys() - new.keys() if k[1] == symbol]
        new_only = [k for k in new.keys() - old.keys() if k[1] == symbol]
        summaries[symbol] = {
            '同じ新規組数': len(matched), '固定だけの新規組数': len(old_only), '更新だけの新規組数': len(new_only),
            '同じ新規の固定収支': sum(old[k]['net_yen'] for k in matched),
            '同じ新規の更新収支': sum(new[k]['net_yen'] for k in matched),
            '固定だけの収支': sum(old[k]['net_yen'] for k in old_only),
            '更新だけの収支': sum(new[k]['net_yen'] for k in new_only)}
        r = summaries[symbol]
        r['一致新規の返済差'] = r['同じ新規の更新収支'] - r['同じ新規の固定収支']
        r['異なる新規経路の差'] = r['更新だけの収支'] - r['固定だけの収支']
        r['総差'] = r['一致新規の返済差'] + r['異なる新規経路の差']
        target = [runner.read(runner.HERE / 'summaries' / ('H019__' + mode + '__V000.json'))['all_symbols'][symbol]['net_yen'] for mode in ('A0', 'AT')]
        assert abs(r['総差'] - (target[1] - target[0])) < 1e-6
    report = {'用途': '主二方式の事後の台帳分解。未一致新規の差は時刻や条件も異なり純粋な再新規禁止効果ではない。',
              '損益再生': False, '条件変更': False, '現在データ': False,
              '照合条件': 'セッション/銘柄/新規原本行/価格/方向/枚数/初期ATRの全一致',
              '銘柄別': summaries, '参照SHA256': {str(p.relative_to(runner.ROOT)): runner.digest(p) for p in files},
              '同じ新規': [{'固定': old[k], '更新': new[k]} for k in sorted(common)],
              '固定だけ': [old[k] for k in sorted(old.keys() - new.keys())],
              '更新だけ': [new[k] for k in sorted(new.keys() - old.keys())]}
    runner.save(runner.HERE / '新規経路の事後分解.json', report)
    inputs = pickle.loads((runner.OLD / 'inputs.pkl').read_bytes())
    lines = ['# 出口変更と新規経路の事後分解', '', report['用途'], '',
             '|銘柄|一致新規数|固定のみ数|更新のみ数|一致新規の返済差 円|異なる新規の差 円|総差 円|',
             '|---|---:|---:|---:|---:|---:|---:|']
    for symbol, r in summaries.items():
        lines.append('|' + symbol + '|' + '|'.join(f"{r[k]:+,.0f}" for k in ('同じ新規組数', '固定だけの新規組数', '更新だけの新規組数', '一致新規の返済差', '異なる新規経路の差', '総差')) + '|')
    lines += ['', '## 説明用の2セッション', '', '9/29は今回の動機となった日。9/25は保有継続と再新規の違いが明確な事後例。これらを次の閾値最適化には使っていない。', '',
              '|日|方式|方向|新規|全返済|初回枚数|組収支 円|', '|---|---|---|---|---|---:|---:|']
    for mode, values in (('固定', old), ('更新', new)):
        for key, record in sorted(values.items()):
            if key[1] != 'TOPIX' or key[0] not in ('2026-09-25_Day', '2026-09-29_Day'):
                continue
            times = inputs[key[:2]]['time_s']
            entry, exit_time = [datetime.fromtimestamp(times[record[k]], ZoneInfo('Asia/Tokyo')).strftime('%H:%M:%S') for k in ('entry_row', 'exit_row')]
            lines.append(f"|{key[0]}|{mode}|{'買' if record['direction'] > 0 else '売'}|{entry}|{exit_time}|{record['qty']}|{record['net_yen']:+,.0f}|")
    lines += ['', '出口を早めた場合、元の入口が再度使える時刻も変わる。同じ新規をした組の返済差だけで全期間の改善を推定できない。再新規を制限する価値は別の機械規則で事前固定し、新しい対応比較をしなければ分からない。']
    (runner.HERE / '新規経路の事後分解.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(summaries)


if __name__ == '__main__':
    main()
