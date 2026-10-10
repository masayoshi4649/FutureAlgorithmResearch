"""二連敗休止の改善を、同じ数の組を無作為に見送る対照と比較する。"""

import gzip
import json
from pathlib import Path

import numpy as np

from research import HERE, SYMBOLS, load, read, save


def main() -> None:
    """機能: セッション別取引数を揃えた5000対照の中でO03の位置を求める。

    引数: なし。返り値: なし(None)。研究内の無作為比較を保存する。
    """
    _, ledgers = load()
    selected = next(r for r in read(HERE / '選択結果.json')['候補'] if r['spec']['id'] == 'O03')
    selected_rows = {(r['session'], r['symbol']): r for r in selected['sessions']}
    names = sorted({key[0] for key in ledgers})
    groups = dict(開発10=names[:10], 検証9=names[10:19], 既知追加4=names[19:], 全23=names)
    rng = np.random.default_rng(20261007)
    simulated = {}
    for key, ledger in sorted(ledgers.items()):
        gains = np.array([r[3] * ledger['config']['point_value'] for r in ledger['cycles']])
        count = selected_rows[key]['cycles']
        order = np.argsort(rng.random((5000, len(gains))), axis=1)
        simulated[key] = gains[order[:, :count]].sum(axis=1)
    output = {}
    for label, sessions in groups.items():
        output[label] = {}
        for symbol in SYMBOLS:
            draws = sum(simulated[session, symbol] for session in sessions)
            actual = sum(selected_rows[session, symbol]['net_yen'] for session in sessions)
            output[label][symbol] = dict(実際収支=actual, 無作為平均=float(draws.mean()),
                無作為5パーセント=float(np.quantile(draws, .05)), 無作為95パーセント=float(np.quantile(draws, .95)),
                無作為が実際以上の割合=float(np.mean(draws >= actual)))
    save('無作為見送り対照.json', dict(全合格=True, 対象='O03', 試行数=5000, seed=20261007,
         条件='銘柄・セッションごとに実行組数をO03と同じにし、E01の組から無作為に選ぶ。',
         解釈='研究内の記述的な対照。複数候補選択や時系列依存を補正した有意差・将来優位の証明ではない。', 結果=output))
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
