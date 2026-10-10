"""先に固定して実行した20条件の結果を読み、追跡幅の違いを事後に記述する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
WIDTH_ORDER = ('W05', 'W10', 'W20', 'S1')


def account_metrics(method: dict, symbol: str) -> dict:
    """機能: 実行済み台帳から保有時間、平均勝ち負け、利益減少量などを集める。

    引数: method(dict)、symbol(str)。返り値: 当該方式・銘柄の記述統計(dict)。
    返済損益や取引時刻は再計算・変更せず、幅を変えた新規実験も追加しない。
    """
    accounts = [value for value in method['accounts'] if value['symbol'] == symbol]
    trades = np.asarray([row for account in accounts for row in account['trades']], dtype=float).reshape(-1, 16)
    groups = np.asarray([row for account in accounts for row in account['width_groups']], dtype=float).reshape(-1, 9)
    summary = method['summary'][symbol]
    assert len(trades) == summary['cycles'] == len(groups)
    np.testing.assert_allclose(trades[:, 6].sum(), summary['net'])
    nonflat = trades[:, 5] != trades[:, 4]
    inferred_values = trades[nonflat, 6] / (trades[nonflat, 2] * trades[nonflat, 3]
                                          * (trades[nonflat, 5] - trades[nonflat, 4]))
    assert len(inferred_values) > 0
    value = float(np.median(inferred_values))
    np.testing.assert_allclose(inferred_values, value)
    giveback_per_lot = trades[:, 14] * trades[:, 8] * value - trades[:, 6] / trades[:, 3]
    assert (giveback_per_lot >= -1e-6).all()
    loss = trades[:, 6] < 0
    result = dict(
        手法ID=method['id'], 入口=method['entry_name'], 幅名=method['width_name'],
        収支円=summary['net'], 利益円=summary['profit'], 損失円=summary['loss'],
        往復組数=len(trades), 勝ち組数=summary['wins'], 負け組数=summary['losses'],
        勝率=summary['win_rate'], 一枚平均利益円=summary['win_per_lot'],
        一枚平均損失円=summary['loss_per_lot'], 一枚平均利益損失比=summary['payoff'],
        利益返済枚数=summary['win_qty'], 損失返済枚数=summary['loss_qty'],
        保有時間中央値分=float(np.median(trades[:, 15])),
        保有時間平均分=float(np.mean(trades[:, 15])),
        五分以内返済組数=int((trades[:, 15] <= 5.).sum()),
        五分以内の損失組数=int(((trades[:, 15] <= 5.) & loss).sum()),
        五分以内の損失円=float(-trades[(trades[:, 15] <= 5.) & loss, 6].sum()),
        追跡幅中央値=float(np.median(trades[:, 8])),
        追跡幅最小=float(np.min(trades[:, 8])), 追跡幅最大=float(np.max(trades[:, 8])),
        保有中最大利益から返済までの減少額一枚中央値円=float(np.median(giveback_per_lot)),
        保有中最大利益から返済までの減少額一枚平均円=float(np.mean(giveback_per_lot)),
        最良場除外収支円=summary['without_best'],
        期間収支円={label: value['net'] for label, value in method['periods'][symbol].items()},
        固定候補基準合格=summary['candidate_pass'],
    )
    return result


def delta_metrics(before: dict, after: dict) -> dict:
    """機能: 同じ入口の異なる固定幅条件について、結果の増減を表示する。

    引数: before(dict)、after(dict) は集計済み記述統計。返り値: 差分(dict)。
    保有時間の変化で後続入口も変わるため、同一注文時刻の置換効果とは扱わない。
    """
    return dict(
        比較=f'{before["手法ID"]} → {after["手法ID"]}',
        収支差円=after['収支円'] - before['収支円'],
        往復組数差=after['往復組数'] - before['往復組数'],
        保有時間中央値差分=after['保有時間中央値分'] - before['保有時間中央値分'],
        一枚平均利益差円=after['一枚平均利益円'] - before['一枚平均利益円'],
        一枚平均損失差円=after['一枚平均損失円'] - before['一枚平均損失円'],
        利益減少額一枚中央値差円=(after['保有中最大利益から返済までの減少額一枚中央値円']
                                       - before['保有中最大利益から返済までの減少額一枚中央値円']),
    )


def main() -> None:
    """機能: 5入口×4幅の完了済み結果を集約し、観測と限界を日本語JSONへ保存する。

    引数: なし。返り値: なし(None)。新手法・新閾値・追加バックテストを作らない。
    """
    path = HERE / '売買結果.json'
    data = json.loads(path.read_text(encoding='utf8'))
    lookup = {method['id']: method for method in data['methods']}
    assert len(lookup) == 20
    families = []
    totals = dict(比較数=0, 幅拡大で組数減少=0, 幅拡大で保有中央値増加=0,
                  幅拡大で平均利益増加=0, 幅拡大で平均損失増加=0,
                  幅拡大で収支改善=0, 幅拡大で収支悪化=0)
    for family in ('P01', 'P02', 'P03', 'P04', 'P05'):
        symbols = {}
        for symbol in ('TOPIX', 'NK225'):
            rows = [account_metrics(lookup[f'{family}_{width}'], symbol) for width in WIDTH_ORDER]
            comparisons = [delta_metrics(rows[0], rows[1]), delta_metrics(rows[1], rows[2]),
                           delta_metrics(rows[0], rows[2]), delta_metrics(rows[0], rows[3])]
            widest = comparisons[2]
            totals['比較数'] += 1
            totals['幅拡大で組数減少'] += widest['往復組数差'] < 0
            totals['幅拡大で保有中央値増加'] += widest['保有時間中央値差分'] > 0
            totals['幅拡大で平均利益増加'] += widest['一枚平均利益差円'] > 0
            totals['幅拡大で平均損失増加'] += widest['一枚平均損失差円'] > 0
            totals['幅拡大で収支改善'] += widest['収支差円'] > 0
            totals['幅拡大で収支悪化'] += widest['収支差円'] < 0
            symbols[symbol] = dict(幅別=rows, 差分=comparisons)
        families.append(dict(入口ID=family, 入口名=lookup[f'{family}_W05']['entry_name'], 銘柄別=symbols))

    # ----------------------------------------
    # 以下は固定実験を終えた後の記述であり、一般法則の認定や条件の追加に使わない。
    narratives = {
        'P01': '始値方向への参加は、固定幅を広げるほど両銘柄で収支が低下した。NKは61,000→22,000→10,000円で黒字を残したが、TOPIXは−217,500→−377,500→−615,000円。大きい幅で待つだけでは改善しなかった。',
        'P02': 'BB外への順張りは3つの固定幅すべてで両銘柄赤字。TOPIXは0.10%で損失が減った後0.20%で拡大。NKは幅拡大で損失が少し減ったが黒字には届かなかった。',
        'P03': 'BB内への復帰を逆向きに取る0.05%だけが両銘柄黒字（TOPIX142,500円、NK57,000円）。ただし0.10%では−5,000/−107,000円、0.20%では0/201,000円で、幅と利益に単調な関係はない。',
        'P04': '直前20分の高安突破は全4幅で両銘柄赤字。TOPIXは0.10%まで損失減少後、0.20%で拡大。NKも幅を広げるだけで優位性は得られなかった。',
        'P05': 'EMA交差は0.10%で両銘柄の収支が最も良かった。NKは0.05%の−98,000円から0.10%の105,000円へ改善したが、TOPIXは同条件でも−87,500円。0.20%への拡大で両銘柄とも再び低下した。',
    }
    for family in families:
        family['観測の短い説明'] = narratives[family['入口ID']]
    result = dict(
        性質='先に固定した20条件の完了後の記述分析。幅や閾値を追加・最適化していない。',
        出典SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
        実行枚数=data['meta']['qty'], 対象=data['meta']['scope'],
        全体観測='始値0.05%から0.20%へ広げると、5入口×2銘柄の全10比較で取引数が減り、保有中央値・勝ち一枚平均・負け一枚平均が全て増えた。収支は3比較で改善、7比較で悪化し、広いほど利益が出る関係ではなかった。',
        狭幅の観測='0.05%幅の保有中央値はおおむね2〜4分。小さい値幅で決済されやすく取引数が多い一方、一枚当たり平均損失は小さい。ただし細かな往復が赤字の原因だとこの集計だけで断定しない。',
        広幅の観測='0.20%幅の保有中央値はおおむね18〜43分。勝ち取引の平均利益は大きくなる一方、平均損失と最大含み益から返済までの減少額も大きくなる。長く待てば安定するとは示せなかった。',
        標準偏差幅='S1は判断時20分終値標準偏差なので、固定割合3条件のような狭広の順序には置けない。実約定幅中央値はTOPIX1.5〜2.0、NK40〜50。0.05%幅中央値TOPIX2.5、NK40に対し、NKでは入口によってS1の方が広い。',
        取引集合の限界='幅を変えると決済時刻が変わり、その間に見送る後続入口も変わる。ここでの収支差は注文時刻固定の出口幅だけの効果ではない。',
        利益減少額の定義='その取引で観測した最大順行幅から、実返済損益を引いた一枚当たり額。初めから損失なら0から損失への減少を含む。最高値で売れたはずだという実現可能利益ではない。',
        集計母数の限界='23場は均一な準備時間を持たない。別添review/準備可能時間の記録.json参照。既研究期間なので未知データへの再現性は示していない。',
        結論='安定候補基準を両銘柄で満たす条件は0。P03_W05は両銘柄で総収支正という観測候補だが、幅変更で符号が崩れ、3期間の全てで黒字でもない。',
        W05からW20への集計=totals, 入口別=families,
    )
    assert totals['幅拡大で収支改善'] == 3 and totals['幅拡大で収支悪化'] == 7
    (HERE / '幅の比較.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(全体観測=result['全体観測'], 集計=totals,
                         手法別={row['入口ID']: row['観測の短い説明'] for row in families}), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
