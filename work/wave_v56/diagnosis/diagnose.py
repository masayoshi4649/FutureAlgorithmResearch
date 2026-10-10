"""固定済み売買の入口・保有・出口を分け、原本の前後の動きを事後診断する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / 'wave_v55'
METHODS = ('P03_W05', 'P02_W05', 'P04_W05', 'P05_W05')


def first_event(values: np.ndarray, threshold: float, positive: bool) -> int | None:
    """機能: 基準からの方向付き変化が指定幅へ初めて達した原本配列位置を返す。

    引数: values(ndarray)、threshold(float)、positive(bool)。
    返り値: 最初の位置または未観測(int|None)。同じ時刻でも原本行順を保つ。
    """
    index = np.flatnonzero(values >= threshold if positive else values <= -threshold)
    return int(index[0]) if len(index) else None


def first_side(positive: int | None, negative: int | None) -> str:
    """機能: 順行側と逆行側の到達順を比較する。

    引数: positive/negative(int|None)。返り値: 順行先着・逆行先着・双方未観測(str)。
    """
    if positive is None and negative is None:
        return '双方未観測'
    if negative is None or (positive is not None and positive < negative):
        return '順行先着'
    return '逆行先着'


def quality(times: np.ndarray, start: float, end: float) -> dict:
    """機能: 事後区間内の約定時計の空白と末尾観測の鮮度を記録する。

    引数: times(ndarray)、start/end(float)。返り値: 観測品質(dict)。
    空白は通信欠落と無約定を区別できず、欠けた価格を補間しない。
    """
    if len(times) == 0:
        return dict(行数=0, 末尾空白秒=max(0., end - start), 最大時計空白秒=max(0., end - start))
    edges = np.r_[start, times, end]
    return dict(行数=len(times), 末尾空白秒=max(0., end - float(times[-1])),
                最大時計空白秒=float(np.max(np.diff(edges), initial=0.)))


def feature_context(frame: pd.DataFrame) -> dict:
    """機能: 判断時までに公表済みだった方向と連続観測分数を原本行に対応させる。

    引数: frame(pd.DataFrame)。返り値: 公開seqから文脈を引く辞書(dict)。
    未来の値、場の終値、後で定義した上昇日・下落日は使用しない。
    """
    result, run, ready_run, previous = {}, 0, 0, None
    for row in frame.itertuples(index=False):
        consecutive = previous is not None and row.source_bar_start - previous == 60.
        run = run + 1 if consecutive else 1
        ready_run = ready_run + 1 if consecutive and row.can_trade else int(row.can_trade)
        ema = int(np.sign(row.ema8 - row.ema21))
        change = int(np.sign(row.close - row.prev_close)) if np.isfinite(row.prev_close) else None
        result[int(row.seq)] = dict(EMA方向=ema, 直前足方向=change, 連続観測分数=run,
                                   連続準備分数=ready_run, 判断公表時刻=float(row.time_s))
        previous = row.source_bar_start
    return result


def diagnose_trade(method: str, account: dict, trade: np.ndarray, group: np.ndarray,
                   order: np.ndarray, ready: dict, contexts: dict) -> dict:
    """機能: 実際の一つの建玉を固定して、入口後30分と実返済後5/15分を観測する。

    引数: method(str)、account(dict)、trade/group/order(ndarray)、ready/contexts(dict)。
    返り値: 一組の事後観測(dict)。将来到達値は執行可能な利確価格として扱わない。
    """
    times, seq, prices = ready['time_s'], ready['seq'], ready['last']
    i = int(np.searchsorted(seq, int(trade[11])))
    j = int(np.searchsorted(seq, int(trade[12])))
    assert seq[i] == trade[11] and seq[j] == trade[12]
    assert prices[i] == trade[4] and prices[j] == trade[5]
    assert order[3] == trade[11] and order[2] < order[3]
    assert group[3] == i and group[4] == j
    side, entry, width = int(trade[2]), float(trade[4]), float(trade[8])
    holding = side * (prices[i:j + 1] - entry) / width
    realized = float(side * (trade[5] - entry) / width)
    mfe, mae = float(np.max(holding, initial=0.)), float(-np.min(holding, initial=0.))
    np.testing.assert_allclose([realized, mfe, mae], [group[2], group[7], group[8]], atol=1e-8)
    end = min(float(times[i]) + 1800., float(ready['limit']))
    stop = int(np.searchsorted(times, end, side='right'))
    path = side * (prices[i:stop] - entry) / width
    future_times = times[i:stop]
    q = quality(future_times, float(times[i]), end)
    hits = {}
    for level in (1, 2):
        positive, negative = first_event(path, level, True), first_event(path, level, False)
        hits[f'{level}W先着'] = first_side(positive, negative)
        hits[f'順行{level}W到達秒'] = None if positive is None else float(future_times[positive] - times[i])
        hits[f'逆行{level}W到達秒'] = None if negative is None else float(future_times[negative] - times[i])
        hits[f'順行{level}W原本行'] = None if positive is None else int(seq[i + positive])
        hits[f'逆行{level}W原本行'] = None if negative is None else int(seq[i + negative])
    changed = np.flatnonzero(path != 0.)
    first_move = '不変' if not len(changed) else ('順行' if path[changed[0]] > 0 else '逆行')
    context = contexts[int(order[2])]
    assert context['判断公表時刻'] == order[0]
    alignment = '同方向' if side * context['EMA方向'] > 0 else ('逆方向' if side * context['EMA方向'] < 0 else '横ばい')
    candle_alignment = ('不明' if context['直前足方向'] is None else
                        '同方向' if side * context['直前足方向'] > 0 else
                        '逆方向' if side * context['直前足方向'] < 0 else '横ばい')
    run = context['連続観測分数']
    run_label = '20〜29分' if run < 30 else '30〜59分' if run < 60 else '60分以上'
    result = dict(
        手法ID=method, セッション=account['session'], 銘柄=account['symbol'], 組=int(trade[9]),
        新規判断原本行=int(order[2]), 新規約定原本行=int(trade[11]), 返済約定原本行=int(trade[12]),
        新規時刻=float(times[i]), 返済時刻=float(times[j]), 方向=side, 新規価格=entry,
        固定幅=width, 収支円=float(trade[6]), 実損益W=realized, 保有分=float(trade[15]),
        保有中MFE_W=mfe, 保有中MAE_W=mae, 順行最大から返済までの減少W=mfe - realized,
        最大順行に対する確定損益比=None if mfe == 0 else realized / mfe,
        損失返済=bool(realized < 0), 保有中1W未達=bool(mfe < 1.),
        保有中1W以上順行して非利益=bool(mfe >= 1. and realized <= 0.),
        保有中2W以上順行=bool(mfe >= 2.),
        入口後観測分=(end - float(times[i])) / 60., 入口後30分全長=bool(end - float(times[i]) >= 1800.),
        入口後観測品質=q, 入口後最初の価格変化=first_move,
        入口後最大順行W=float(np.max(path, initial=0.)), 入口後最大逆行W=float(-np.min(path, initial=0.)),
        判断時EMAとの関係=alignment, 判断時直前足との関係=candle_alignment,
        連続観測時間層=run_label, 判断時文脈=context,
        **hits,
    )

    # ----------------------------------------
    # 返済後は実際に記録された価格だけを見る。場末の短縮区間を完全区間と混ぜない。
    for minutes in (5, 15):
        after_end = min(float(times[j]) + minutes * 60., float(ready['limit']))
        after_stop = int(np.searchsorted(times, after_end, side='right'))
        after_path = side * (prices[j + 1:after_stop] - entry) / width
        after_times = times[j + 1:after_stop]
        aq = quality(after_times, float(times[j]), after_end)
        full = after_end - float(times[j]) >= minutes * 60.
        result[f'返済後{minutes}分'] = dict(
            全長あり=full, 観測分=max(0., after_end - float(times[j])) / 60., 観測品質=aq,
            有効比較=bool(full and len(after_times) and aq['末尾空白秒'] <= 60.),
            建値以上を観測=bool(len(after_path) and np.max(after_path) >= 0.),
            順行1W以上を観測=bool(len(after_path) and np.max(after_path) >= 1.),
            順行2W以上を観測=bool(len(after_path) and np.max(after_path) >= 2.),
            最大順行W=None if not len(after_path) else float(np.max(after_path)),
        )
    return result


def ratio(numerator: int, denominator: int) -> float | None:
    """機能: 母数0を不明値として、観測件数の割合を求める。

    引数: numerator/denominator(int)。返り値: 割合または不明(float|None)。
    """
    return numerator / denominator if denominator else None


def summarize(rows: list[dict]) -> dict:
    """機能: 将来観測を取引の最適出口に置き換えず、分類別の母数と割合をまとめる。

    引数: rows(list[dict])。返り値: 損益・到達順・返済後の回復観測の集計(dict)。
    """
    n = len(rows)
    if not n:
        return dict(組数=0)
    losses = [row for row in rows if row['損失返済']]
    result = dict(
        組数=n, 損失組数=len(losses), 収支円=sum(row['収支円'] for row in rows),
        実損益W平均=float(np.mean([row['実損益W'] for row in rows])),
        保有中MFE_W中央値=float(np.median([row['保有中MFE_W'] for row in rows])),
        保有中MAE_W中央値=float(np.median([row['保有中MAE_W'] for row in rows])),
        順行最大から返済までの減少W中央値=float(np.median([row['順行最大から返済までの減少W'] for row in rows])),
        損失かつ保有中1W未達組数=sum(row['保有中1W未達'] for row in losses),
        保有中1W以上順行して非利益組数=sum(row['保有中1W以上順行して非利益'] for row in rows),
        保有中1W以上順行して損失組数=sum(row['保有中MFE_W'] >= 1. and row['実損益W'] < 0. for row in rows),
        保有中1W以上順行して同値組数=sum(row['保有中MFE_W'] >= 1. and row['実損益W'] == 0. for row in rows),
        保有中2W以上順行組数=sum(row['保有中2W以上順行'] for row in rows),
        入口後30分全長あり組数=sum(row['入口後30分全長'] for row in rows),
        入口後60秒超の時計空白あり組数=sum(row['入口後観測品質']['最大時計空白秒'] > 60. for row in rows),
    )
    for level in (1, 2):
        result[f'{level}W先着内訳'] = {label: sum(row[f'{level}W先着'] == label for row in rows)
                                      for label in ('順行先着', '逆行先着', '双方未観測')}
    result['入口後最初の価格変化内訳'] = {label: sum(row['入口後最初の価格変化'] == label for row in rows)
                                       for label in ('順行', '逆行', '不変')}
    result['損失組の1W先着内訳'] = {label: sum(row['1W先着'] == label for row in losses)
                                   for label in ('順行先着', '逆行先着', '双方未観測')}
    for minutes in (5, 15):
        compare = [row for row in losses if row[f'返済後{minutes}分']['有効比較']]
        before1 = [row for row in compare if row['保有中1W未達']]
        break_even = sum(row[f'返済後{minutes}分']['建値以上を観測'] for row in compare)
        plus1 = sum(row[f'返済後{minutes}分']['順行1W以上を観測'] for row in compare)
        firstplus1 = sum(row[f'返済後{minutes}分']['順行1W以上を観測'] for row in before1)
        result[f'損失返済後{minutes}分の観測'] = dict(
            比較母数=len(compare), 場末短縮または末尾観測不足=len(losses) - len(compare),
            建値回復組数=break_even, 建値回復割合=ratio(break_even, len(compare)),
            順行1W到達組数=plus1, 順行1W到達割合=ratio(plus1, len(compare)),
            保有中1W未達だった比較母数=len(before1),
            保有中未達で返済後1W到達組数=firstplus1,
            保有中未達で返済後1W到達割合=ratio(firstplus1, len(before1)),
            比較区間内60秒超空白組数=sum(row[f'返済後{minutes}分']['観測品質']['最大時計空白秒'] > 60. for row in compare),
        )
    # ----------------------------------------
    # 観測後ラベルは重なり得るので、排他的な原因別会計として合算しない。
    clean = [row for row in rows if row['入口後30分全長']
             and row['入口後観測品質']['最大時計空白秒'] <= 60.]
    result['30分全長かつ時計空白60秒以内'] = dict(
        組数=len(clean),
        順行1W先着=sum(row['1W先着'] == '順行先着' for row in clean),
        逆行1W先着=sum(row['1W先着'] == '逆行先着' for row in clean),
        順行2W先着=sum(row['2W先着'] == '順行先着' for row in clean),
        逆行2W先着=sum(row['2W先着'] == '逆行先着' for row in clean),
    )
    return result


def main() -> None:
    """機能: 指定された4方式の実入口だけを追跡し、診断台帳と短い集計を保存する。

    引数: なし。返り値: なし(None)。原本・特徴・売買条件は変更せずATRも使わない。
    """
    result_path = SOURCE / '売買結果.json'
    source = json.loads(result_path.read_text(encoding='utf8'))
    ready = pickle.loads((SOURCE / 'clean_inputs.pkl').read_bytes())
    features = pickle.loads((SOURCE / '特徴.pkl').read_bytes())
    contexts = {key: feature_context(value) for key, value in features.items()}
    records, summaries = [], []
    for method in source['methods']:
        if method['id'] not in METHODS:
            continue
        rows = []
        for account in method['accounts']:
            key = account['session'], account['symbol']
            orders = {int(order[10]): np.asarray(order) for order in account['orders'] if order[4] == 1}
            groups = {int(group[0]): np.asarray(group) for group in account['width_groups']}
            for trade in account['trades']:
                group_id = int(trade[9])
                row = diagnose_trade(method['id'], account, np.asarray(trade), groups[group_id],
                                     orders[group_id], ready[key], contexts[key])
                rows.append(row)
        records.extend(rows)
        symbols = {}
        for symbol in ('TOPIX', 'NK225'):
            symbol_rows = [row for row in rows if row['銘柄'] == symbol]
            totals = summarize(symbol_rows)
            assert totals['組数'] == method['summary'][symbol]['cycles']
            np.testing.assert_allclose(totals['収支円'], method['summary'][symbol]['net'])
            symbols[symbol] = dict(
                全体=totals,
                判断時EMAとの関係={label: summarize([row for row in symbol_rows if row['判断時EMAとの関係'] == label])
                                  for label in ('同方向', '逆方向', '横ばい')},
                判断時直前足との関係={label: summarize([row for row in symbol_rows if row['判断時直前足との関係'] == label])
                                    for label in ('同方向', '逆方向', '横ばい', '不明')},
                連続観測時間別={label: summarize([row for row in symbol_rows if row['連続観測時間層'] == label])
                                for label in ('20〜29分', '30〜59分', '60分以上')},
            )
        summaries.append(dict(手法ID=method['id'], 手法名=method['entry_name'], 銘柄別=symbols))
    assert len(summaries) == 4
    output = dict(
        目的='入口の直後の方向、保有中の順行逆行、返済後の戻りを別々に測る。原因や心理を断定せず、実行可能な最適出口を後付けしない。',
        手法=list(METHODS), 総組数=len(records), 入力結果SHA256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
        W定義='各実取引で新規判断時に固定した追跡幅。ATRは不使用。',
        入口後区間='各実約定行から30分以内、ただし場の固定返済判断時刻まで。±1W/±2Wは原本行順の先着。到達しない側は未観測とし、先着確率の補間はしない。',
        最初の変化='新規価格と異なる最初の原本価格が順行か逆行か。同じ約定時刻に複数行あっても原本順を使う。',
        回復定義='実損失返済後5/15分の原本価格が建値以上または+1Wに届いたか。場末短縮または末尾観測が60秒以上古い区間は回復割合の分母から除外。',
        観測限界='約定時計空白は欠測と無約定を区別できない。各30分・回復区間の空白件数を保存し、30分全長で空白60秒以内の層も併記する。',
        方向文脈='新規判断の公開行に一致する確定EMA8とEMA21の関係・直前足変化だけを利用。後から場全体の上昇下落で分類しない。',
        連続時間='新規判断時に確定済みだった1分足の連続観測数で20〜29/30〜59/60分以上に記述区分。戦略ゲートには使わない。',
        解釈禁止='将来回復・最大順行はその後の値動きの観測であり、損切りを待てば確実に取れた利益ではない。途中の含み損、場末返済、変更時の後続取引への影響は別問題。',
        仕様による機械的性質='初回から1Wトレーリングするため、+1W到達時には返済線が原則建値に来る。従って+1W到達後の損失が少ないのはこの仕様から予想される性質であり、新しい市場法則や入口が悪いことの確証ではない。原本次行約定の飛びで損失になる例外はある。',
        分類の重なり='逆行先着、返済後回復、順行後利益減少は同じ組で共存できる。排他的原因として合算しない。',
        元結果との整合='全新規・返済原本行、価格、損益、保有MFE/MAEを元台帳と照合済み。',
        新規戦略選択=False, 新規閾値追加=False, 現在API取得数=0,
        手法別=summaries,
    )
    (HERE / '診断台帳.pkl').write_bytes(pickle.dumps(records, pickle.HIGHEST_PROTOCOL))
    (HERE / '入口途中出口の診断.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    brief = []
    for method in summaries:
        for symbol, values in method['銘柄別'].items():
            total = values['全体']
            brief.append(dict(手法=method['手法ID'], 銘柄=symbol, 組数=total['組数'],
                              収支円=total['収支円'], 損失組数=total['損失組数'],
                              一W先着=total['1W先着内訳'], 二W先着=total['2W先着内訳'],
                              保有中MFE_W中央値=total['保有中MFE_W中央値'],
                              保有中MAE_W中央値=total['保有中MAE_W中央値'],
                              損失かつ保有中一W未達=total['損失かつ保有中1W未達組数'],
                              損失後5分=total['損失返済後5分の観測'],
                              損失後15分=total['損失返済後15分の観測'],
                              保有中一W以上後損失=total['保有中1W以上順行して損失組数'],
                              保有中一W以上後同値=total['保有中1W以上順行して同値組数']))
    short = dict(
        要点=['入口から30分内の±1W先着は4方式とも両銘柄でほぼ拮抗し、この測定だけで高い方向予測力は確認できない。',
              '損失組の大半は保有中+1W未達。ただし初回から1W追跡するため+1W到達で返済線が建値となる、仕様上ほぼ必然の性質。市場の新発見や入口原因の確証とはしない。',
              '損失返済後15分に建値へ戻る組は多いが、+1Wへの到達は少なくなる。途中逆行を無視して待てば利益が出たという意味ではない。',
              'P03はほとんどが判断時EMAと逆方向。これは入口規則の性質による偏りであり、EMAとの順逆だけを原因として比較できない。',
              '連続観測時間の層で成績差はあるが銘柄・方式で方向が揃わない。層別結果から新しい取引閾値を追加しない。'],
        総組数=len(records), 各方式=brief, 使い方='この要約と詳細JSONは事後診断であり、将来価格を実売買へ混入するものではない。',
    )
    (HERE / '診断要約.json').write_text(json.dumps(short, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(brief, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
