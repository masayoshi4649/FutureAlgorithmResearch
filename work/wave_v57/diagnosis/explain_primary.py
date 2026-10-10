"""事前に固定した主条件3つを、返済理由と約定価格の寄与に分けて事後記述する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
VALUES = {'TOPIX': 1000., 'NK225': 10.}
REASONS = {1: '中値トレーリング', 2: '場内返済', 3: '補充壁の保護線割れ'}


def stats(values: list[float]) -> dict:
    """機能: 保有秒数の件数・中央値・平均・四分位を、空集合を不明としてまとめる。

    引数: values(list[float])。返り値: 記述統計(dict)。
    """
    return dict(組数=len(values), 中央値秒=float(np.median(values)) if values else None,
                平均秒=float(np.mean(values)) if values else None,
                第1四分位秒=float(np.quantile(values, .25)) if values else None,
                第3四分位秒=float(np.quantile(values, .75)) if values else None)


def trade_rows(account: dict, frame: dict) -> list[dict]:
    """機能: 各実売買を同じ原本行の中値・売買気配と照合し、価格差の寄与を分解する。

    引数: account(dict)、frame(dict)。返り値: 返済組別の診断行(list[dict])。
    注文行・枚数・方向を固定し、注文条件や約定時刻は変更しない。
    """
    seq, times = frame['seq'], frame['time_s']
    value = VALUES[account['symbol']]
    orders = {(int(order[10]), int(order[4])): order for order in account['orders']}
    rows = []
    for trade in account['trades']:
        cid = int(trade[9])
        entry_order, exit_order = orders[cid, 1], orders[cid, 2]
        i, j = int(np.searchsorted(seq, trade[11])), int(np.searchsorted(seq, trade[12]))
        assert seq[i] == trade[11] and seq[j] == trade[12]
        assert times[i] == trade[0] and times[j] == trade[1]
        assert frame['last'][i] == trade[4] and frame['last'][j] == trade[5]
        side, qty = int(trade[2]), int(trade[3])
        raw_pnl = side * (trade[5] - trade[4]) * qty * value
        mid_pnl = side * (frame['mid'][j] - frame['mid'][i]) * qty * value
        entry_advantage = side * (frame['mid'][i] - trade[4]) * qty * value
        exit_advantage = side * (trade[5] - frame['mid'][j]) * qty * value
        quote_entry = frame['ask'][i] if side > 0 else frame['bid'][i]
        quote_exit = frame['bid'][j] if side > 0 else frame['ask'][j]
        quote_pnl = side * (quote_exit - quote_entry) * qty * value
        np.testing.assert_allclose(raw_pnl, trade[6], atol=1e-8)
        np.testing.assert_allclose(raw_pnl - mid_pnl, entry_advantage + exit_advantage, atol=1e-8)
        assert int(trade[7]) in REASONS
        result = dict(
            セッション=account['session'], 銘柄=account['symbol'], 組=cid,
            返済理由=REASONS[int(trade[7])], 方向=side, 枚数=qty,
            entry_seq=int(seq[i]), exit_seq=int(seq[j]), 保有秒=float(times[j] - times[i]),
            最終価格損益円=raw_pnl, 中値損益円=mid_pnl, 売買気配損益円=quote_pnl,
            入口の最終価格有利差円=entry_advantage, 出口の最終価格有利差円=exit_advantage,
            入口が直前有効原本行と同じ約定時計=bool(i > 0 and times[i] == times[i - 1]),
            出口が直前有効原本行と同じ約定時計=bool(j > 0 and times[j] == times[j - 1]),
            入口判断と約定が同じ約定時計=bool(entry_order[0] == entry_order[1]),
            出口判断と約定が同じ約定時計=bool(exit_order[0] == exit_order[1]),
            入口が直前有効原本行と同じ最終価格=bool(i > 0 and frame['last'][i] == frame['last'][i - 1]),
            出口が直前有効原本行と同じ最終価格=bool(j > 0 and frame['last'][j] == frame['last'][j - 1]),
            入口の最終価格が現在の気配外=bool(trade[4] < frame['bid'][i] or trade[4] > frame['ask'][i]),
            出口の最終価格が現在の気配外=bool(trade[5] < frame['bid'][j] or trade[5] > frame['ask'][j]),
        )
        rows.append(result)
    np.testing.assert_allclose(sum(row['最終価格損益円'] for row in rows), account['net'], atol=1e-8)
    np.testing.assert_allclose(sum(row['中値損益円'] for row in rows), account['sensitivity']['中値']['net'], atol=1e-8)
    np.testing.assert_allclose(sum(row['売買気配損益円'] for row in rows), account['sensitivity']['売買気配']['net'], atol=1e-8)
    return rows


def summarize(rows: list[dict]) -> dict:
    """機能: 理由別にも再利用できる損益・保有時間・最終価格差の集計を作る。

    引数: rows(list[dict])。返り値: 記述集計(dict)。条件や順位を選び直さない。
    """
    count = len(rows)
    wins = [row for row in rows if row['最終価格損益円'] > 0]
    losses = [row for row in rows if row['最終価格損益円'] < 0]
    flat = [row for row in rows if row['最終価格損益円'] == 0]
    result = dict(
        返済組数=count, 利益円=sum(row['最終価格損益円'] for row in wins),
        損失円=-sum(row['最終価格損益円'] for row in losses),
        最終価格収支円=sum(row['最終価格損益円'] for row in rows),
        中値収支円=sum(row['中値損益円'] for row in rows),
        売買気配収支円=sum(row['売買気配損益円'] for row in rows),
        入口の最終価格有利差総額円=sum(row['入口の最終価格有利差円'] for row in rows),
        出口の最終価格有利差総額円=sum(row['出口の最終価格有利差円'] for row in rows),
        勝ち保有時間=stats([row['保有秒'] for row in wins]),
        負け保有時間=stats([row['保有秒'] for row in losses]),
        同値保有時間=stats([row['保有秒'] for row in flat]),
        中値で勝ちとなる保有時間=stats([row['保有秒'] for row in rows if row['中値損益円'] > 0]),
        中値で負けとなる保有時間=stats([row['保有秒'] for row in rows if row['中値損益円'] < 0]),
    )
    for label in ('入口', '出口'):
        for description in ('が直前有効原本行と同じ約定時計', '判断と約定が同じ約定時計',
                            'が直前有効原本行と同じ最終価格', 'の最終価格が現在の気配外'):
            key = f'{label}{description}'
            n = sum(row[key] for row in rows)
            result[f'{key}組数'] = n
            result[f'{key}割合'] = n / count if count else None
    result['最終価格有利差合計円'] = result['入口の最終価格有利差総額円'] + result['出口の最終価格有利差総額円']
    np.testing.assert_allclose(result['最終価格有利差合計円'], result['最終価格収支円'] - result['中値収支円'], atol=1e-8)
    return result


def describe(total: dict, reasons: dict) -> list[str]:
    """機能: 主条件の会計結果を、原因の断定や条件選択をせず短く説明する。

    引数: total(dict)、reasons(dict)。返り値: 結果の平易な記述(list[str])。
    """
    if not total['返済組数']:
        return ['この主条件では取引が発生せず、勝敗について評価できない。']
    last, mid, quote = total['最終価格収支円'], total['中値収支円'], total['売買気配収支円']
    text = []
    if last > 0 and mid <= 0:
        text.append('最終価格での約定は黒字だが、中値の価格経路では黒字を維持しない。入口と出口の最終価格差が成績を押し上げた会計構造である。')
    elif mid > 0 and quote <= 0:
        text.append('同じ注文行の中値では黒字だが、買ask・売bidでは黒字を維持しない。価格経路の利益だけで売買気配の差を吸収できたとは言えない。')
    elif quote > 0:
        text.append('同じ注文行の中値・売買気配でも黒字を維持した。ただし補充なしの対照や未知期間の検証を行っておらず、補充固有の効果とは断定しない。')
    else:
        text.append('同じ注文行の中値・売買気配でも黒字を確認できなかった。約定最終価格を置き換えるだけでは改善の結論にならない。')
    ordered = sorted(reasons.items(), key=lambda item: item[1]['最終価格収支円'])
    worst_name, worst = ordered[0]
    best_name, best = ordered[-1]
    text.append(f'返済理由別の最終価格収支は、{worst_name}が{worst["最終価格収支円"]:+,.0f}円、{best_name}が{best["最終価格収支円"]:+,.0f}円。返済理由による会計分類であり、原因を切り分けた対照実験ではない。')
    text.append(f'最終価格と中値の差の寄与は入口{total["入口の最終価格有利差総額円"]:+,.0f}円、出口{total["出口の最終価格有利差総額円"]:+,.0f}円。')
    return text


def main() -> None:
    """機能: 事前主条件3つだけを診断し、理由別会計と価格感度の照合結果を保存する。

    引数: なし。返り値: なし(None)。未生成の売買結果では実行せず、成績から条件を選ばない。
    """
    path = BASE / '売買結果.json'
    if not path.exists():
        raise SystemExit('売買結果が未生成です。診断の準備だけ完了しました。')
    source = json.loads(path.read_text(encoding='utf8'))
    frame = pickle.loads((BASE / 'features.pkl').read_bytes())
    primary = [method for method in source['methods'] if method['primary']]
    assert len(primary) == 3
    assert {method['id'] for method in primary} == set(source['meta']['main_ids'])
    methods, all_rows = [], []
    for method in primary:
        rows = []
        for account in method['accounts']:
            rows.extend(trade_rows(account, frame[account['session'], account['symbol']]))
        for row in rows:
            row['手法ID'] = method['id']
        all_rows.extend(rows)
        symbols = {}
        for symbol in ('TOPIX', 'NK225'):
            selected = [row for row in rows if row['銘柄'] == symbol]
            total = summarize(selected)
            by_reason = {reason: summarize([row for row in selected if row['返済理由'] == reason])
                         for reason in REASONS.values()}
            assert total['返済組数'] == sum(value['返済組数'] for value in by_reason.values())
            np.testing.assert_allclose(total['最終価格収支円'], method['summary'][symbol]['net'], atol=1e-8)
            symbols[symbol] = dict(全体=total, 返済理由別=by_reason, 短い説明=describe(total, by_reason))
        methods.append(dict(手法ID=method['id'], 手法名=method['entry_name'], 銘柄別=symbols))
    result = dict(
        目的='事前に主条件と定めた3方式について、返済理由と価格評価の寄与を分解する。成績順位による主条件の変更はしない。',
        入力結果SHA256=hashlib.sha256(path.read_bytes()).hexdigest(), 主条件=[method['id'] for method in primary],
        返済理由='壁の保護線割れは固定構造線を中値が越えたため返済したという機械的理由。補充主体が逃げた・板注文を全取消したと判明した意味ではない。',
        価格差定義='入口の有利差=方向×(中値−最終価格)×枚数×倍率。出口の有利差=方向×(最終価格−中値)×枚数×倍率。正が最終価格約定に有利。二つの合計は最終価格収支−中値収支に一致。',
        同時計の意味='原本行が進んでもCurrentPriceTimeが直前有効行から変わらない注文を数えた。実際に同時刻に新しい約定が成立した証明でも、受信遅延秒数でもない。',
        同値価格='同じ最終約定価格が続く行で仮想約定した数も併記する。実注文の約定保証はない。',
        感度の扱い='同じ注文行・方向・枚数を中値または買ask/売bidで評価。原本順の台帳と既存sensitivityへ独立照合した。約定待ち・板消費・スリッページの再現ではない。',
        因果制約='補充を使わない対照戦略との比較ではないので、観測された利益を補充固有の効果とは断定しない。返済理由も結果の会計分類であり原因の証明ではない。',
        保有時間='勝敗は主表示の最終価格損益で分類。参考として中値損益による勝敗別も併記。',
        既存感度照合=True, 価格差会計一致=True, 新規条件追加=False, ATR使用=False,
        手法別=methods,
    )
    (HERE / '主条件の返済理由と価格差.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    (HERE / '主条件診断台帳.pkl').write_bytes(pickle.dumps(all_rows, pickle.HIGHEST_PROTOCOL))
    brief = []
    for method in methods:
        for symbol, values in method['銘柄別'].items():
            whole = values['全体']
            brief.append(dict(手法=method['手法ID'], 銘柄=symbol, 組数=whole['返済組数'],
                              最終価格=whole['最終価格収支円'], 中値=whole['中値収支円'], 気配=whole['売買気配収支円'],
                              入口有利差=whole['入口の最終価格有利差総額円'], 出口有利差=whole['出口の最終価格有利差総額円'],
                              返済理由={key: dict(組数=value['返済組数'], 最終価格=value['最終価格収支円'], 中値=value['中値収支円'])
                                        for key, value in values['返済理由別'].items()}))
    print(json.dumps(brief, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
