"""既知データの上位候補に対し、選択バイアスと日付依存を敵対的に点検する。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / 'wave_v23'
SYMBOLS = ['TOPIX', 'NK225']
TARGET, BASE = 'X05_G08', 'F32_G08'
MULT = {'TOPIX': 1000., 'NK225': 10.}
SEED, REPETITIONS = 20260929, 5000


def read(name: str):
    """機能: 前回成果を読み取り専用で読む。

    引数: name (str)。返り値: JSON 内容 (object)。
    """
    return json.loads((SOURCE / name).read_text(encoding='utf-8'))


def finite_json(value):
    """機能: 非有限値を隠さず文字列へ変換して JSON に保存できる形へ整える。

    引数: value (object)。返り値: JSON 互換値 (object)。
    """
    if isinstance(value, dict):
        return {str(key): finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [finite_json(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return '正の無限大' if value == np.inf else '負の無限大' if value == -np.inf else None
    return value


def pf(profit: float, loss: float) -> float:
    """機能: 総利益と総損失から PF を計算し、無損失・無取引を区別する。

    引数: profit/loss (float)。返り値: PF (float)。
    """
    return profit / loss if loss > 0 else np.inf if profit > 0 else np.nan


def summary(rows: list[dict]) -> dict:
    """機能: 同一銘柄の確定損益・決済枚数を合計する。

    引数: rows (list[dict])。返り値: 集計値 (dict)。
    """
    fields = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'cycles']
    result = {name: sum(row[name] for row in rows) for name in fields}
    result['PF'] = pf(result['gross_profit_yen'], result['gross_loss_yen'])
    result['セッション数'] = len(rows)
    result['黒字セッション数'] = sum(row['net_yen'] > 0 for row in rows)
    return result


def pair(rows: list[dict]) -> dict:
    """機能: X05 と F32 を同じセッション集合で比較する。

    引数: rows (list[dict])。返り値: 銘柄別の比較 (dict)。
    """
    output = {}
    for symbol in SYMBOLS:
        x = summary([row for row in rows if row['id'] == TARGET and row['symbol'] == symbol])
        base = summary([row for row in rows if row['id'] == BASE and row['symbol'] == symbol])
        output[symbol] = {TARGET: x, BASE: base, '収支差円_X05引くF32': x['net_yen'] - base['net_yen'], 'PF差_X05引くF32': x['PF'] - base['PF']}
    return output


def interval(values: np.ndarray) -> dict:
    """機能: 標本再抽出値の中央 95 パーセント区間と非定義件数を返す。

    引数: values (ndarray)。返り値: 分位点と診断件数 (dict)。
    """
    valid = values[~np.isnan(values)]
    result = dict(標本数=len(values), 非定義数=int(np.isnan(values).sum()), 無限大数=int(np.isinf(values).sum()))
    if len(valid):
        result.update(下側2_5=float(np.quantile(valid, .025)), 中央=float(np.quantile(valid, .5)), 上側97_5=float(np.quantile(valid, .975)))
    return result


def trade_breakdown(inputs: dict, sessions: list[str], selected_rows: list[dict]) -> tuple[dict, dict]:
    """機能: 元の返済台帳から売買方向別損益と最大勝ち除外を独立に求める。

    引数: inputs (dict)、sessions (list[str])、selected_rows (list[dict])。
    返り値: 売買別内訳と勝ち依存検査 (tuple[dict,dict])。
    """
    directions, removals = {}, {}
    for method in [TARGET, BASE]:
        directions[method], removals[method] = {}, {}
        with np.load(SOURCE / 'trades' / f'{method}.npz', allow_pickle=False) as archive:
            for symbol in SYMBOLS:
                trades = []
                for session in sessions:
                    block = archive[f'{session}_{symbol}_trades']
                    values = block[:, 10] * MULT[symbol]
                    expected = next(row['net_yen'] for row in selected_rows if row['id'] == method and row['symbol'] == symbol and row['session'] == session)
                    np.testing.assert_allclose(values.sum(), expected, atol=.00001, rtol=0)
                    for index, (row, value) in enumerate(zip(block, values)):
                        stamp = inputs[(session, symbol)]['time_s'][int(row[7])]
                        trades.append(dict(セッション=session, 返済番号=index, 売買='ロング' if row[2] > 0 else 'ショート',
                                           枚数=int(row[3]), 損益円=float(value), 返済暦日=datetime.fromtimestamp(stamp, timezone(timedelta(hours=9))).date().isoformat()))
                directions[method][symbol] = {}
                for side in ['ロング', 'ショート']:
                    block = [row for row in trades if row['売買'] == side]
                    values = np.array([row['損益円'] for row in block], dtype=float)
                    profit, loss = np.maximum(values, 0).sum(), -np.minimum(values, 0).sum()
                    directions[method][symbol][side] = dict(利益円=float(profit), 損失円=float(loss), 収支円=float(values.sum()),
                        PF=pf(profit, loss), 取引数=len(block), 利益枚数=sum(row['枚数'] for row in block if row['損益円'] > 0),
                        損失枚数=sum(row['枚数'] for row in block if row['損益円'] < 0))
                rows = [row for row in selected_rows if row['id'] == method and row['symbol'] == symbol]
                total = summary(rows)
                result = {}
                for unit in ['セッション', '開始日', '勝ち取引']:
                    if unit == '勝ち取引':
                        ranked = sorted([row for row in trades if row['損益円'] > 0], key=lambda row: row['損益円'], reverse=True)
                    else:
                        groups = {}
                        for row in rows:
                            key = row['session'] if unit == 'セッション' else row['session'][:10]
                            groups.setdefault(key, []).append(row)
                        ranked = []
                        for key, group in groups.items():
                            s = summary(group)
                            if s['net_yen'] > 0:
                                ranked.append(dict(対象=key, 損益円=s['net_yen'], 利益円=s['gross_profit_yen'], 損失円=s['gross_loss_yen']))
                        ranked.sort(key=lambda row: row['損益円'], reverse=True)
                    for count in [1, 2]:
                        removed = ranked[:count]
                        removed_profit = sum(row['損益円'] if unit == '勝ち取引' else row['利益円'] for row in removed)
                        removed_loss = sum(0 if unit == '勝ち取引' else row['損失円'] for row in removed)
                        remaining = total['net_yen'] - sum(row['損益円'] for row in removed)
                        result[f'最大{count}{unit}除外'] = dict(除外=removed, 残収支円=remaining,
                            残PF=pf(total['gross_profit_yen'] - removed_profit, total['gross_loss_yen'] - removed_loss))
                removals[method][symbol] = result
    return directions, removals


def bootstrap(rows: list[dict], days: list[str]) -> tuple[dict, np.ndarray]:
    """機能: 両銘柄・両手法へ同じ開始日ブロックを抽出し、差の区間を作る。

    引数: rows (list[dict])、days (list[str])。返り値: 比較結果と抽出回数行列 (tuple[dict,ndarray])。
    枚数や銘柄金額を混ぜず、同日相関と手法間の対応を保つ。
    """
    rng = np.random.default_rng(SEED)
    indices = rng.integers(0, len(days), size=(REPETITIONS, len(days)))
    counts = np.stack([np.bincount(row, minlength=len(days)) for row in indices])
    metrics = np.zeros((2, len(days), 2, 3))
    for method_i, method in enumerate([TARGET, BASE]):
        for day_i, day in enumerate(days):
            for symbol_i, symbol in enumerate(SYMBOLS):
                selected = [row for row in rows if row['id'] == method and row['symbol'] == symbol and row['session'].startswith(day)]
                summed = summary(selected)
                metrics[method_i, day_i, symbol_i] = [summed['net_yen'], summed['gross_profit_yen'], summed['gross_loss_yen']]
    sampled = np.einsum('bd,mdsk->bmsk', counts, metrics)
    with np.errstate(divide='ignore', invalid='ignore'):
        ratios = sampled[:, :, :, 1] / sampled[:, :, :, 2]
        ratio_difference = ratios[:, 0] - ratios[:, 1]
    difference = sampled[:, 0, :, 0] - sampled[:, 1, :, 0]
    result = {}
    for symbol_i, symbol in enumerate(SYMBOLS):
        result[symbol] = dict(X05収支円区間=interval(sampled[:, 0, symbol_i, 0]), F32収支円区間=interval(sampled[:, 1, symbol_i, 0]),
                             収支差円区間=interval(difference[:, symbol_i]), PF差区間=interval(ratio_difference[:, symbol_i]),
                             再抽出標本で差が正の割合=float(np.mean(difference[:, symbol_i] > 0)))
    correlation = {}
    for method_i, method in enumerate([TARGET, BASE]):
        correlation[method] = float(np.corrcoef(metrics[method_i, :, :, 0].T)[0, 1])
    correlation['X05引くF32の日次差'] = float(np.corrcoef((metrics[0, :, :, 0] - metrics[1, :, :, 0]).T)[0, 1])
    report = dict(seed=SEED, 反復回数=REPETITIONS, ブロック数=len(days), ブロック単位='セッション名の開始日。両銘柄と両手法へ同じ日を同時再抽出。',
                  両銘柄の差が同時に正となる標本割合=float(np.mean(np.all(difference > 0, axis=1))),
                  銘柄別=result, 日次収支の銘柄間相関=correlation,
                  解釈='中央95%再抽出区間。選択バイアス未補正の記述的診断。真の将来収益や優越確率ではない。',
                  制限='7開始日しかなく日付間独立も未保証。9/29はデイのみ、他6日はデイとナイトで露出時間が違う。開始日ブロック間にまたがる夜間の暦日相関は完全には保存できない。')
    return report, counts


def maximum_null(rows: list[dict], days: list[str], counts: np.ndarray) -> dict:
    """機能: 1520候補対F32の差を日付ごと再中心化し、最大統計量の参考帰無を作る。

    引数: rows (list[dict])、days (list[str])、counts (ndarray)。返り値: 参考の上側確率と明示的限界 (dict)。
    日次差の標準偏差は元標本で固定し、全候補・両銘柄へ同じブロック重複数を使う。
    """
    identifiers = sorted({row['id'] for row in rows})
    positions = {identifier: i for i, identifier in enumerate(identifiers)}
    day_positions = {day: i for i, day in enumerate(days)}
    net = np.zeros((len(identifiers), len(days), len(SYMBOLS)))
    for row in rows:
        net[positions[row['id']], day_positions[row['session'][:10]], SYMBOLS.index(row['symbol'])] += row['net_yen']
    difference = net - net[positions[BASE]][None, :, :]
    mean = difference.mean(axis=1)
    standard_deviation = difference.std(axis=1, ddof=1)
    have = standard_deviation > 1e-12
    statistic = np.divide(np.sqrt(len(days)) * mean, standard_deviation, out=np.zeros_like(mean), where=have)
    centered = difference - mean[:, None, :]
    maxima = np.zeros((REPETITIONS, len(SYMBOLS)))
    target_null = np.zeros_like(maxima)
    for start in range(0, REPETITIONS, 250):
        sampled_mean = np.einsum('bd,mds->bms', counts[start:start + 250], centered) / len(days)
        null = np.divide(np.sqrt(len(days)) * sampled_mean, standard_deviation[None, :, :],
                         out=np.zeros_like(sampled_mean), where=have[None, :, :])
        maxima[start:start + 250] = np.maximum(0., null.max(axis=1))
        target_null[start:start + 250] = null[:, positions[TARGET], :]
    results = {}
    for symbol_i, symbol in enumerate(SYMBOLS):
        observed = statistic[positions[TARGET], symbol_i]
        max_i = int(np.argmax(statistic[:, symbol_i]))
        tail = lambda values, level: float((1 + np.count_nonzero(values >= level)) / (REPETITIONS + 1))
        results[symbol] = dict(X05の観測統計量=float(observed),
            X05だけを固定した参考上側確率=tail(target_null[:, symbol_i], observed),
            全候補最大値に対するX05の参考上側確率=tail(maxima[:, symbol_i], observed),
            実標本で最大の候補=identifiers[max_i], 実標本最大統計量=float(statistic[max_i, symbol_i]),
            実標本最大値の参考上側確率=tail(maxima[:, symbol_i], statistic[max_i, symbol_i]),
            再中心化最大統計量の95パーセント点=float(np.quantile(maxima[:, symbol_i], .95)),
            日次差標準偏差がゼロの候補数=int((~have[:, symbol_i]).sum()))
    return dict(候補数=len(identifiers), 基準=BASE, 反復回数=REPETITIONS, seed=SEED,
                統計量='sqrt(7) × 日次損益差平均 / 元標本の日次差標準偏差。単位は銘柄内で相殺。基準自身の差は0。',
                再中心化='各候補の各銘柄で日次差平均を引き、全候補・両銘柄共通の開始日ブロック抽出を適用。',
                銘柄別=results, 正式な多重検定補正p値ではない=True,
                限界='これは同一小標本に条件付きの最大値参照分布。候補とF32基準がデータを見て設計・選択されていること、設計変更、過去研究、7ブロックの少なさ、日付間依存を補正できない。元の資格/PFによる選定規則の帰無分布でもない。1520候補は数量・損失予算も異なり、標準偏差で単位を消しても同じ資本リスクでの比較になるわけではない。最大値を出した別候補の小さな上側値から、その手法の優越や統計的有意性を主張しない。',
                主張可能範囲='候補を1つだけ固定して扱うと見落とす、多数候補の極値による見かけの強さを診断する参考値に限る。')


def main() -> None:
    """機能: X05対F32の依存性・選択履歴・再抽出診断を新規領域へまとめる。

    引数: なし。返り値: なし (None)。原本・前回成果の変更とAPI取得は行わない。
    """
    OUT.mkdir(exist_ok=True)
    all_rows = read('全条件セッション集計.json') + read('選択統合のセッション集計.json')
    selected_rows = [row for row in all_rows if row['id'] in [TARGET, BASE]]
    sessions = sorted({row['session'] for row in selected_rows})
    days = sorted({session[:10] for session in sessions})
    inputs = pickle.loads((SOURCE / 'inputs.pkl').read_bytes())
    calendar = set()
    for value in inputs.values():
        for day in np.unique(np.floor((value['time_s'] + 9 * 3600) / 86400)).astype(int):
            calendar.add(datetime.fromtimestamp(int(day) * 86400, timezone.utc).date().isoformat())
    rankings = read('全条件の期間集計.json') + read('選択統合の期間集計.json')
    combined_rank = sorted(rankings, key=lambda row: (tuple(row['score']), row['id']), reverse=True)
    rank_positions = {row['id']: i + 1 for i, row in enumerate(combined_rank)}
    chronology = [
        dict(時刻=read('探索前の固定記録.json')['時刻'], 証拠='探索前の固定記録.json', 内容='全13セッション既読として58信号×20管理=1160条件を固定。'),
        dict(時刻=datetime.fromtimestamp((SOURCE / '選択結果.json').stat().st_mtime, timezone(timedelta(hours=9))).isoformat(), 証拠='選択結果.json とファイル更新時刻', 内容='元1160条件の首位F32_G08を選定。更新時刻は補助証拠であり、後述の凍結記録でも選定済みを確認。'),
        dict(時刻=read('live/現在照合の凍結記録.json')['凍結時刻'], 証拠='live/現在照合の凍結記録.json', 内容='F32_G08を主候補に既知13区間の選定後、現在ナイトを一回取得する前に凍結。'),
        dict(時刻=read('探索前の選択条件.json')['時刻'], 証拠='探索前の選択条件.json', 内容='F32を中間・初期選択とするX00〜X09を追加設計。X05もmiddle=F32。'),
        dict(時刻=read('選択統合の探索前固定.json')['時刻'], 証拠='選択統合の探索前固定.json', 内容='追加18選択器×20管理=360条件の境界修正後の固定。元1160と合計1520条件。'),
    ]
    by_period = {kind: pair([row for row in selected_rows if row['session'].endswith(kind)]) for kind in ['Day', 'Night']}
    week_keys = sorted({datetime.fromisoformat(day).isocalendar().week for day in days})
    by_week = {f'2026年第{week}週': pair([row for row in selected_rows if datetime.fromisoformat(row['session'][:10]).isocalendar().week == week]) for week in week_keys}
    day_pairs = {day: pair([row for row in selected_rows if row['session'].startswith(day)]) for day in days}
    session_pairs = {session: pair([row for row in selected_rows if row['session'] == session]) for session in sessions}
    leave_one_out = {day: pair([row for row in selected_rows if not row['session'].startswith(day)]) for day in days}
    side, remove = trade_breakdown(inputs, sessions, selected_rows)
    bootstrap_result, counts = bootstrap(selected_rows, days)
    multiple = maximum_null(all_rows, days, counts)
    baseline_walk = read('逐次選択の結果.json')
    selector_walk = read('選択統合の逐次選択.json')
    walk = dict(元1160条件逐次=baseline_walk['symbols'], 追加360条件逐次=selector_walk['symbols'],
                注意='どちらも全期間を見た設計の事後再現。追加側の利益を真の未見検証として扱わない。追加側NKは最大勝ち区間1つを除くと−400円。')
    report = dict(結論='X05は既知13区間で両銘柄黒字だが、F32に対する一貫した改善と選択後の将来再現性は立証されない。',
                  対象=TARGET, 比較=BASE, 合計探索数=1520, 全候補を同じ既存基準で再整列した順位={TARGET: rank_positions[TARGET], BASE: rank_positions[BASE]},
                  首位の意味='X05は追加選択器360条件内の首位。全1520条件を元の基準で合同順位化した首位ではない。',
                  データ=dict(セッション数=len(sessions), 開始日ブロック数=len(days), 開始日=days, 観測のある暦日数=len(calendar), 観測暦日=sorted(calendar),
                              独立標本ではない='TOPIXとNKは同じ相場を観測し、同日デイ・ナイトや隣接日も独立とは限らない。26銘柄セッションを26独立観測として扱わない。'),
                  設計と選択の時系列=chronology, 全期間比較=pair(selected_rows), セッション別=session_pairs,
                  日中夜間=by_period, 週別=by_week, 開始日別=day_pairs, ロングショート=side,
                  最大勝ち除外=remove, 一開始日除外=leave_one_out, 対応日付ブートストラップ=bootstrap_result,
                  再中心化した全候補最大値の参考帰無=multiple, 逐次選択の対比=walk,
                  原本と前回成果変更なし=True, API取得数=0,
                  総括上の制限='再抽出と勝ち除外は有限の既知標本の依存診断。上位候補の探索後バイアス、F32を見てからの設計、相場の非定常性を消さず、未来の利益確率を推定したものではない。')
    cleaned = finite_json(report)
    (OUT / 'statistical_adversarial.json').write_text(json.dumps(cleaned, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(finite_json(dict(全期間比較=report['全期間比較'], 順位=report['全候補を同じ既存基準で再整列した順位'], ブートストラップ=bootstrap_result, 最大値帰無=multiple)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
