"""価格受容・拒否の比較用に、当該場の非重複1分の量と過去尺度を作る。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / 'wave_v53'
MEASUREMENT = HERE.parent / 'wave_v52/measurement'
sys.path.insert(0, str(MEASUREMENT))
from quotes import load_inputs_only

SUM_MAP = {
    'minute_volume': 'source_volume_delta', 'minute_exec_buy': 'exec_buy',
    'minute_exec_sell': 'exec_sell', 'minute_exec_unknown': 'exec_unknown',
    'minute_noexec_bid_add': 'noexec_bid_add', 'minute_noexec_bid_remove': 'noexec_bid_remove',
    'minute_noexec_ask_add': 'noexec_ask_add', 'minute_noexec_ask_remove': 'noexec_ask_remove',
    'minute_quote_events': 'quote_events', 'minute_trade_events': 'trade_events',
    'minute_no_trade_events': 'no_trade_events', 'minute_observed_rows': 'valid_events',
    'minute_continuity_resets': 'continuity_resets', 'minute_volume_resets': 'volume_resets',
    'minute_volume_missing': 'unavailable_volume_events', 'minute_depth_incomplete': 'depth_incomplete_events',
    'minute_depth_disordered': 'depth_disordered_events', 'minute_depth_duplicate': 'depth_duplicate_events',
}
MEDIANS = {
    'past20_volume_median': 'minute_volume', 'past20_depth_median': 'minute_depth',
    'past20_activity_median': 'minute_quote_events', 'past20_supply_abs_median': 'minute_supply_abs',
}


def save(path: Path, value: object) -> None:
    """機能: 有限JSONで仕様・監査・分布だけを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def build_account(base: pd.DataFrame, blocks: pd.DataFrame, ready: dict) -> pd.DataFrame:
    """機能: 当該場だけの確定1分数量と現在足を除く過去20分中央値を追加する。

    引数: base(DataFrame:既存確定足)、blocks(DataFrame:公開済み原始量)、ready(dict)。
    返り値: 基礎列を継承した特徴(DataFrame)。銘柄名による計算分岐はない。
    """
    output = base.copy(deep=True)
    a = {name: blocks[name].to_numpy() for name in blocks.columns}
    pref = {name: np.r_[0., np.cumsum(a[name])] for name in set(SUM_MAP.values())}
    records = []
    for row in base.itertuples():
        left = int(np.searchsorted(a['source_time_s'], row.source_bar_start, side='left'))
        right = min(int(np.searchsorted(a['source_time_s'], row.source_bar_start + 60., side='left')),
                    int(np.searchsorted(a['seq'], row.seq, side='right')))
        start_index = int(np.searchsorted(ready['time_s'], row.source_bar_start, side='left'))
        end_index = int(np.searchsorted(ready['time_s'], row.source_bar_start + 60., side='left'))
        assert end_index == int(row.ready_index) and ready['seq'][end_index] == row.seq
        count = max(0, right - left)
        current = {target: float(pref[source][right] - pref[source][left]) if count else 0.
                   for target, source in SUM_MAP.items()}
        current.update(minute_ready_rows=float(end_index - start_index), minute_blocks=float(count),
                       minute_valid=False, minute_source_last_seq=np.nan,
                       minute_max_source_age=np.nan, minute_near_bid=np.nan, minute_near_ask=np.nan)
        if count:
            assert (a['source_time_s'][left:right] >= row.source_bar_start).all()
            assert (a['source_time_s'][left:right] < row.source_bar_start + 60.).all()
            assert (a['seq'][left:right] <= row.seq).all()
            assert (a['source_last_seq'][left:right] < row.seq).all()
            current['minute_source_last_seq'] = float(a['source_last_seq'][left:right].max())
            current['minute_max_source_age'] = float(a['source_age'][left:right].max())
            weights = a['depth_valid_events'][left:right]
            if weights.sum() > 0:
                current['minute_near_bid'] = float(np.average(a['supply_bid_near'][left:right], weights=weights))
                current['minute_near_ask'] = float(np.average(a['supply_ask_near'][left:right], weights=weights))
            bad = sum(current[name] for name in ('minute_continuity_resets', 'minute_volume_resets',
                                                 'minute_volume_missing', 'minute_depth_incomplete',
                                                 'minute_depth_disordered', 'minute_depth_duplicate'))
            current['minute_valid'] = bool(bad == 0 and current['minute_max_source_age'] <= 60.
                                          and current['minute_observed_rows'] == current['minute_ready_rows'])
        records.append(current)
    minute = pd.DataFrame(records, index=output.index)
    for name in minute.columns:
        output[name] = minute[name].astype(bool if name == 'minute_valid' else float)
    output['minute_depth'] = output.minute_near_bid + output.minute_near_ask
    net_supply = ((output.minute_noexec_bid_add - output.minute_noexec_bid_remove)
                  - (output.minute_noexec_ask_add - output.minute_noexec_ask_remove))
    output['minute_supply_norm'] = net_supply.div(output.minute_depth).where(output.minute_valid & (output.minute_depth > 0))
    output['minute_supply_abs'] = output.minute_supply_norm.abs()
    for name in MEDIANS:
        output[name] = np.nan
    output['past20_valid_count'] = 0
    t = output.source_bar_start.to_numpy()
    valid = output.minute_valid.to_numpy()
    for i, row in enumerate(output.itertuples()):
        left = int(np.searchsorted(t, row.source_bar_start - 1200., side='left'))
        positions = np.flatnonzero(valid[left:i]) + left
        output.loc[output.index[i], 'past20_valid_count'] = len(positions)
        if len(positions) < 10 or row.time_s - ready['start'] < 1200.:
            continue
        assert np.all(t[positions] < row.source_bar_start)
        for target, source in MEDIANS.items():
            values = output[source].iloc[positions].to_numpy()
            assert np.isfinite(values).all()
            output.loc[output.index[i], target] = float(np.median(values))
    for target, numerator, denominator in (
        ('relative_volume', 'minute_volume', 'past20_volume_median'),
        ('relative_depth', 'minute_depth', 'past20_depth_median'),
        ('relative_activity', 'minute_quote_events', 'past20_activity_median')):
        output[target] = output[numerator].div(output[denominator]).where(output.minute_valid & (output[denominator] > 0))
    net_exec = output.minute_exec_buy - output.minute_exec_sell
    output['pressure'] = net_exec.div(output.past20_volume_median).where(output.minute_valid & (output.past20_volume_median > 0))
    output['response_atr'] = (output.close - output.prev_close).div(output.atr5).where((output.source_bar_start.diff() == 60.) & (output.atr5 > 0))
    output['known_fraction'] = ((output.minute_exec_buy + output.minute_exec_sell).div(output.minute_volume)
                                .where(output.minute_valid & (output.minute_volume > 0)))
    count = output.minute_trade_events + output.minute_no_trade_events
    output['minute_exec_update_fraction'] = output.minute_trade_events.div(count).where(output.minute_valid & (count > 0))
    output['aligned_response_atr'] = (np.sign(net_exec) * output.response_atr).where(output.minute_valid & (net_exec != 0))
    # ----------------------------------------
    # 分母不足・未観測はNaNを残し、比率の発散や未知のゼロ置換を許さない。
    for column in ('relative_volume', 'relative_depth', 'relative_activity', 'pressure',
                   'response_atr', 'known_fraction', 'minute_supply_norm', 'aligned_response_atr'):
        assert not np.isinf(output[column].to_numpy()).any()
    np.testing.assert_array_equal(output.minute_exec_buy + output.minute_exec_sell + output.minute_exec_unknown,
                                  output.minute_volume)
    pd.testing.assert_frame_equal(output[list(base.columns)], base, check_exact=True)
    return output


def describe(values: pd.Series) -> dict:
    """機能: 将来情報を使わず、観測列の有限件数・欠測・分位点を求める。

    引数: values(Series)。返り値: 分布情報(dict)。
    """
    known = values[np.isfinite(values)]
    return dict(有限数=len(known), 欠測数=len(values) - len(known), ゼロ数=int((known == 0).sum()),
                分位点={str(q): float(known.quantile(q)) for q in (0., .01, .1, .5, .9, .99, 1.)} if len(known) else {})


def main() -> None:
    """機能: 共通規則で全23場を拡張し、途中切断・源範囲・数量保存を監査する。

    引数: なし。返り値: なし(None)。損益・台帳・将来収益を開かず原本も変更しない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    save(HERE / '測定仕様.json', dict(
        共通化='銘柄名による計算分岐なし。同じ分窓、同じ中央値、同じ最低観測数を用いる。前セッションを参照しない。',
        一分='v53確定中値足のsource_bar_start以上、60秒後未満に属する源blockを、判断seqまでに公開された分だけ合計する。重複窓にしない。',
        有効性='公開blockが1つ以上、源年齢60秒以下、連続性/出来高欠測・reset/10段不備がなく、源有効行数が当分のready全有効行数と一致。失われた公開blockも検出する。',
        量='出来高/執行代理/非出来高増加行の同価格数量増減は源block合計。板厚さは距離加重供給の深板正常行数による平均。近接の距離重みは既存exp(-呼値距離/2)。',
        無効分='元数量の観測合計と品質理由は保持するが、相対量・供給偏りなど利用用の派生量はNaN。源blockなしの合計0は未観測でありminute_valid=False。',
        過去中央値='source_bar_startの直前20分で現在足を除き、minute_validな分が10以上、かつ判断時刻が場開始20分後以降のときだけ中央値。past20_valid_countを保存。欠測は0で補完しない。',
        活動='minute_quote_events（最良気配が変化した観測回数）。真の全注文数や参加者数ではない。',
        供給='minute_supply_norm=((非出来高買追加−買減少)−(売追加−売減少))/(minute_near_bid+ask)。過去絶対値中央値も同じ時間窓で作る。取消や同一主体の補充とは断定しない。',
        相対量='出来高・厚さ・活動をそれぞれ過去中央値で割る。分母0/未知はNaN。中央値0自体は観測値として保持しゲートの利用側で不成立とする。',
        圧と応答='pressure=(買執行代理−売執行代理)/過去出来高中央値。response_atr=(確定close−前分close)/確定ATR5。両者を互いに割らない。前分が欠落なら応答は未知。',
        既知率='known_fraction=(買代理+売代理)/出来高。分類可能だった数量比であって真の方向正答率ではない。',
        更新率='minute_exec_update_fractionは出来高増加を伴った隣接観測の比率。約定への参加人数・意思・心理は分からない。',
        時刻限界='CurrentPriceTimeは約定時計であり板受信時計ではない。実際の分区間の更新速度を再現できたとは扱わない。',
        イベント='イベント開始時に中央値を固定する処理と供給/活動ゲートは別プログラムの責任。この特徴器はその時点までの中央値だけを出す。',
        将来及び損益不参照=True, 現在API取得数=0, コードSHA256=source_hash))
    base = pickle.loads((PREVIOUS / '特徴.pkl').read_bytes())
    blocks = pickle.loads((MEASUREMENT / 'features.pkl').read_bytes())
    inputs = load_inputs_only()
    output = {}
    for key, frame in base.items():
        output[key] = build_account(frame, blocks[key], inputs[key])
    (HERE / '特徴.pkl').write_bytes(pickle.dumps(output, pickle.HIGHEST_PROTOCOL))
    checks = []
    for key, frame in base.items():
        for fraction in (.35, .75):
            size = max(1, int(len(frame) * fraction))
            part = frame.iloc[:size].copy()
            cutoff = int(part.seq.iloc[-1])
            ready = inputs[key]
            count = int(np.searchsorted(ready['seq'], cutoff, side='right'))
            sliced = {name: value[:count] if isinstance(value, np.ndarray) and len(value) == len(ready['seq']) else value
                      for name, value in ready.items()}
            actual = build_account(part, blocks[key].loc[blocks[key].seq <= cutoff].copy(), sliced)
            pd.testing.assert_frame_equal(actual, output[key].iloc[:size], check_exact=True)
            checks.append(dict(セッション=key[0], 銘柄=key[1], 切断比率=fraction, 一致行数=len(actual), 原本切断行=cutoff))
    columns = ('minute_volume', 'minute_near_bid', 'minute_near_ask', 'minute_quote_events',
               'minute_supply_norm', 'past20_valid_count', 'past20_volume_median', 'past20_depth_median',
               'past20_activity_median', 'past20_supply_abs_median', 'relative_volume', 'relative_depth',
               'relative_activity', 'pressure', 'response_atr', 'known_fraction', 'minute_exec_update_fraction')
    distribution, accounts = {}, []
    for symbol in sorted({key[1] for key in output}):
        joined = pd.concat([frame for key, frame in output.items() if key[1] == symbol], ignore_index=True)
        distribution[symbol] = {name: describe(joined[name]) for name in columns}
        distribution[symbol]['品質'] = dict(全分数=len(joined), 有効分数=int(joined.minute_valid.sum()),
                                           過去中央値利用可能分数=int(joined.past20_volume_median.notna().sum()),
                                           行数不一致分数=int((joined.minute_observed_rows != joined.minute_ready_rows).sum()))
    for key, frame in output.items():
        accounts.append(dict(セッション=key[0], 銘柄=key[1], 分数=len(frame), 有効分数=int(frame.minute_valid.sum()),
                             過去中央値有効=int(frame.past20_volume_median.notna().sum()),
                             供給閾値正かつ当分有効=int(((frame.past20_supply_abs_median > 0) & frame.minute_valid).sum())))
    assert source_hash == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    save(HERE / '観測分布.json', distribution)
    save(HERE / '特徴監査.json', dict(合格=True, 口座数=len(output), 分数=sum(len(x) for x in output.values()),
                                      一分非重複=True, 全量保存=True, 基礎全列不変=True,
                                      現在足を中央値に含めない=True, 途中切断=checks,
                                      口座別=accounts, 追加列=[name for name in next(iter(output.values())).columns if name not in next(iter(base.values())).columns],
                                      コードSHA256=source_hash, 損益将来不参照=True, 現在API取得数=0))
    print('完成', len(output), sum(len(x) for x in output.values()), 'prefix', len(checks), flush=True)


if __name__ == '__main__':
    main()
