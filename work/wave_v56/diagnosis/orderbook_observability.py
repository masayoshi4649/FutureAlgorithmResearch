"""保存済みの原始板観測で、執行側代理・表示数量・気配移動をどこまで分けられるか調べる。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]
RAW_CACHE = WORK / 'wave_v52/measurement/features.pkl'
QUOTE_CACHE = WORK / 'wave_v52/measurement/quotes.pkl'
COLUMNS = (
    'time_s', 'seq', 'source_time_s', 'source_first_seq', 'source_last_seq',
    'source_bid_last', 'source_ask_last', 'source_mid_last', 'source_last',
    'source_age', 'raw_events', 'valid_events', 'continuity_resets', 'volume_time_s',
    'exec_buy', 'exec_sell', 'exec_unknown', 'source_volume_delta',
    'noexec_bid_add', 'noexec_bid_remove', 'noexec_ask_add', 'noexec_ask_remove',
    'refill_bid_fixed_quote', 'refill_ask_fixed_quote', 'quote_ticks',
    'volume_resets', 'unavailable_volume_events', 'depth_incomplete_events',
    'depth_disordered_events', 'depth_duplicate_events', 'supply_bid_near', 'supply_ask_near',
)


def select_blocks(key: tuple, original: pd.DataFrame, ready: dict, quotes: dict) -> tuple[pd.DataFrame, dict]:
    """機能: 原始数量変化と同じ源区間の開始前・終了時の気配を照合する。

    引数: key(tuple)、original(pd.DataFrame)、ready/quotes(dict)。
    返り値: 有効区間表と品質監査(tuple[pd.DataFrame,dict])。旧指標列は取り込まない。
    """
    frame = original.loc[:, COLUMNS].copy()
    seq = ready['seq']
    first = np.searchsorted(seq, frame['source_first_seq'].to_numpy(dtype=int))
    last = np.searchsorted(seq, frame['source_last_seq'].to_numpy(dtype=int))
    safe_first = np.minimum(first, len(seq) - 1)
    safe_last = np.minimum(last, len(seq) - 1)
    boundary_valid = ((first > 0) & (first < len(seq)) & (last < len(seq))
                      & (seq[safe_first] == frame['source_first_seq'].to_numpy())
                      & (seq[safe_last] == frame['source_last_seq'].to_numpy())
                      & (seq[np.maximum(safe_first - 1, 0)] + 1 == frame['source_first_seq'].to_numpy()))
    valid = (boundary_valid & frame['raw_events'].eq(frame['valid_events'])
             & frame['continuity_resets'].eq(0) & frame['volume_resets'].eq(0)
             & frame['unavailable_volume_events'].eq(0)
             & frame['depth_incomplete_events'].eq(0) & frame['depth_disordered_events'].eq(0)
             & frame['depth_duplicate_events'].eq(0) & frame['source_age'].le(60.))
    selected = frame.loc[valid].copy()
    origin = first[valid] - 1
    selected['before_bid'] = quotes['bid'][origin]
    selected['before_ask'] = quotes['ask'][origin]
    selected['before_mid'] = quotes['mid'][origin]
    selected['before_last'] = ready['last'][origin]
    selected['mid_change_ticks'] = (selected['source_mid_last'] - selected['before_mid']) / ready['tick']
    selected['last_change_ticks'] = (selected['source_last'] - selected['before_last']) / ready['tick']
    np.testing.assert_allclose(selected['mid_change_ticks'], selected['quote_ticks'], atol=1e-10)
    np.testing.assert_allclose(selected['exec_buy'] + selected['exec_sell'] + selected['exec_unknown'],
                               selected['source_volume_delta'], atol=1e-10)
    selected['session'], selected['symbol'] = key
    selected['sell_net'] = selected['exec_sell'] - selected['exec_buy']
    selected['bid_display_net'] = selected['noexec_bid_add'] - selected['noexec_bid_remove']
    selected['ask_display_net'] = selected['noexec_ask_add'] - selected['noexec_ask_remove']
    selected['bid_lower'] = selected['source_bid_last'] < selected['before_bid']
    selected['ask_higher'] = selected['source_ask_last'] > selected['before_ask']
    return selected, dict(セッション=key[0], 銘柄=key[1], 原始公開区間数=len(frame),
                           今回の連続有効区間数=len(selected),
                           除外区間数=int((~valid).sum()), 中値変化と原始累積値一致=True)


def quote_last_counts(ready: dict, quotes: dict) -> dict:
    """機能: 最終価格の変化が最良気配の移動を伴ったかを原本の隣接有効行で数える。

    引数: ready/quotes(dict)。返り値: 約定値・気配の動きの件数(dict)。
    最良気配不変で最終価格だけ変わる場合も、実売買側が判明したとは扱わない。
    """
    adjacent = np.diff(ready['seq']) == 1
    dl, dm = np.diff(ready['last']), np.diff(quotes['mid'])
    quote_fixed = (np.diff(quotes['bid']) == 0) & (np.diff(quotes['ask']) == 0)
    moving = adjacent & (dl != 0)
    return dict(隣接有効原本行の比較数=int(adjacent.sum()), 最終価格変化数=int(moving.sum()),
                最終価格変化で両最良気配不変数=int((moving & quote_fixed).sum()),
                最終価格変化で中値不変数=int((moving & (dm == 0)).sum()),
                最終価格と中値が逆方向の変化数=int((moving & (dl * dm < 0)).sum()),
                有効原本行数=len(ready['seq']),
                最終価格が現在の気配外の行数=int(((ready['last'] < quotes['bid']) | (ready['last'] > quotes['ask'])).sum()))


def examples(frame: pd.DataFrame, maximum: int = 3) -> list[dict]:
    """機能: 条件に該当する最初の原本区間を、成績を参照せず検証用に抜き出す。

    引数: frame(pd.DataFrame)、maximum(int)。返り値: 先頭順の具体例(list[dict])。
    """
    columns = ('session', 'source_time_s', 'source_first_seq', 'source_last_seq',
               'exec_buy', 'exec_sell', 'exec_unknown', 'source_volume_delta',
               'before_bid', 'before_ask', 'source_bid_last', 'source_ask_last', 'mid_change_ticks',
               'noexec_bid_add', 'noexec_bid_remove', 'noexec_ask_add', 'noexec_ask_remove',
               'refill_bid_fixed_quote', 'refill_ask_fixed_quote')
    return frame.loc[:, columns].head(maximum).to_dict(orient='records')


def summarize_market(frame: pd.DataFrame) -> dict:
    """機能: 売り代理・表示数量減少・回復と、同区間の中値変化の共存を記述する。

    引数: frame(pd.DataFrame)。返り値: 件数・四分位別観測・具体例(dict)。
    四分位は全保存標本を使う事後記述であり、予測変数や取引閾値にはしない。
    """
    selling = frame[frame['sell_net'] > 0]
    q25, q50, q75 = np.quantile(selling['exec_sell'], [.25, .5, .75])
    strongest = frame['sell_net'].gt(0) & frame['exec_sell'].ge(q75)
    small = frame['sell_net'].gt(0) & frame['exec_sell'].le(q25)
    absorption = strongest & frame['mid_change_ticks'].ge(0) & frame['refill_bid_fixed_quote'].gt(0)
    small_withdrawal = (small & frame['bid_display_net'].lt(0) & frame['bid_lower']
                        & frame['mid_change_ticks'].lt(0))
    zero_volume_withdrawal = (frame['source_volume_delta'].eq(0) & frame['bid_display_net'].lt(0)
                             & frame['bid_lower'] & frame['mid_change_ticks'].lt(0))
    buying = frame['sell_net'].lt(0)
    buy_q75 = float(np.quantile(frame.loc[buying, 'exec_buy'], .75))
    mirrored = buying & frame['exec_buy'].ge(buy_q75) & frame['mid_change_ticks'].le(0) & frame['refill_ask_fixed_quote'].gt(0)
    bins = []
    boundaries = (-np.inf, q25, q50, q75, np.inf)
    for index in range(4):
        chosen = selling[(selling['exec_sell'] > boundaries[index]) & (selling['exec_sell'] <= boundaries[index + 1])]
        bins.append(dict(区分=index + 1, 下限超=None if index == 0 else float(boundaries[index]),
                         上限以下=None if index == 3 else float(boundaries[index + 1]), 区間数=len(chosen),
                         中値下落区間数=int(chosen['mid_change_ticks'].lt(0).sum()),
                         中値不変区間数=int(chosen['mid_change_ticks'].eq(0).sum()),
                         中値上昇区間数=int(chosen['mid_change_ticks'].gt(0).sum()),
                         中値変化呼値中央値=None if chosen.empty else float(chosen['mid_change_ticks'].median())))
    return dict(
        有効源区間数=len(frame), 売り側代理優勢区間数=len(selling),
        出来高正増分合計=float(frame['source_volume_delta'].sum()),
        執行側不明数量割合=float(frame['exec_unknown'].sum() / frame['source_volume_delta'].sum()),
        売り側代理優勢時の売り量四分位=[float(q25), float(q50), float(q75)],
        売り量四分位別= bins,
        強い売り代理かつ中値非下落と買い表示回復=dict(母数=int(strongest.sum()), 共存区間数=int(absorption.sum()), 原本例=examples(frame[absorption])),
        小さい売り代理かつ買い表示純減と買い気配中値下落=dict(母数=int(small.sum()), 共存区間数=int(small_withdrawal.sum()), 原本例=examples(frame[small_withdrawal])),
        出来高増分ゼロかつ買い表示純減と買い気配中値下落=dict(母数=int(frame['source_volume_delta'].eq(0).sum()), 共存区間数=int(zero_volume_withdrawal.sum()), 原本例=examples(frame[zero_volume_withdrawal])),
        対称な強い買い代理かつ中値非上昇と売り表示回復=dict(共存区間数=int(mirrored.sum()), 買い代理量上位四分位境界=buy_q75, 原本例=examples(frame[mirrored])),
    )


def main() -> None:
    """機能: 全46原本の保存キャッシュだけから、測れる現象と測れない原因を分ける。

    引数: なし。返り値: なし(None)。価格予測、損益探索、ATR計算は行わない。
    """
    inputs = pickle.loads((WORK / 'wave_v55/clean_inputs.pkl').read_bytes())
    quotes = pickle.loads(QUOTE_CACHE.read_bytes())
    original = pickle.loads(RAW_CACHE.read_bytes())
    blocks, audits = [], []
    counters = {symbol: {} for symbol in ('TOPIX', 'NK225')}
    for key in sorted(inputs):
        frame, audit = select_blocks(key, original[key], inputs[key], quotes[key])
        blocks.append(frame)
        audits.append(audit)
        count = quote_last_counts(inputs[key], quotes[key])
        for name, value in count.items():
            counters[key[1]][name] = counters[key[1]].get(name, 0) + value
    combined = pd.concat(blocks, ignore_index=True)
    summaries = {symbol: summarize_market(combined[combined['symbol'] == symbol]) for symbol in counters}
    for count in counters.values():
        count['最終価格変化中の両最良気配不変割合'] = count['最終価格変化で両最良気配不変数'] / count['最終価格変化数']
        count['最終価格変化中の中値不変割合'] = count['最終価格変化で中値不変数'] / count['最終価格変化数']
    output = dict(
        目的='価格移動と執行側代理・表示供給の変化を分けて観測し、同じ現象に別の原因があり得る限界を明記する。',
        直接観測=['原本に表示されたbid/askと数量', '累積出来高の増減', '前後とも表示される同じ価格の数量の減少・増加', '最良気配の移動・スプレッド・中値変化'],
        代理または推定=['出来高増分を最終価格と直前bid/askで分類した買い側/売り側執行代理。増分内の全約定を同じ側と保証できない。',
                        '同じ価格で30秒以内に減った表示量が戻った数量。前の減少残高を上限に計算するが、注文主体の同一性は不明。',
                        '売り代理が多くても中値が下がらず買い表示が戻る現象は吸収と整合するが、吸収の原因や将来上昇は未確定。'],
        識別不可能=['真のaggressor内訳・個別約定の時系列', '新規建てか返済か、参加者の在庫・焦り・動機',
                    '同一主体の補充、隠れ注文、取消と未反映約定の完全な分離', '取引所受信時刻・自分がその気配で約定できたか'],
        売買の対応='成立した各約定には同量の買い手と売り手がいる。売り側代理優勢とは総売買量の不一致ではなく、直前気配を跨いだ側の代理に偏りがあるという意味。',
        価格の区別='最終価格は最後の成立値、中値は現在表示されたbid/askの平均。最終価格変化だけを供給価格の移動とみなさない。',
        源区間='同じ約定時計値の原本ブロックを閉じてから公開した原始量。価格差はsource_mid_firstからではなく、そのブロック先頭の直前原本行から末尾まで。原始quote_ticksと一致を検証。',
        連続性='源区間に最良/深板不正、出来高欠測/resetがなく、先頭直前原本行が有効で隣接し、公開遅延60秒以内に限定。区間内の真の受信時間は不明。',
        強弱の定義='売り代理優勢区間の売り代理量の全保存標本25/75%点を、今回の事後記述だけに使う。リアルタイム閾値・取引条件・未来価格の説明変数には使わない。',
        ゼロ出来高の限界='累積出来高が増えていない表示更新を確認しているだけで、取引所で取引が一切なかったと断定しない。出来高更新遅延と取消の識別はできない。',
        共存の限界='大きいブロック内での執行代理・表示回復・価格変化の共存であり、補充が価格を支えたという因果識別ではない。',
        将来損益探索=False, 新規戦略選択=False, ATR使用=False, 現在API取得数=0,
        原始キャッシュSHA256=hashlib.sha256(RAW_CACHE.read_bytes()).hexdigest(),
        気配と最終価格の比較=counters, 銘柄別=summaries, 口座別品質=audits,
    )
    (HERE / '板の観測可能性.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    (HERE / '観測可能区間.pkl').write_bytes(pickle.dumps(combined, pickle.HIGHEST_PROTOCOL))
    print(json.dumps(dict(気配と最終価格の比較=counters,
                         銘柄別={symbol: {key: value for key, value in summary.items() if not isinstance(value, list)}
                                 for symbol, summary in summaries.items()}), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
