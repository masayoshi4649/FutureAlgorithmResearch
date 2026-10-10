"""補充監視の実入口を固定し、将来の固定時点中値を売買から分離して事後測定する。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / 'wave_v57'
INPUT_PATH = HERE.parents[1] / 'wave_v55/clean_inputs.pkl'
HORIZONS = (60, 300, 900, 1800)
VALUE_PER_POINT = {'TOPIX': 1000., 'NK225': 10.}
JST = timezone(timedelta(hours=9))


def stamp(value: float) -> str:
    """機能: 約定時計の秒数を日本時間の文字列へ変換する。

    引数: value(float)。返り値: 日本時間の文字列(str)。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def mean(values: list[float]) -> float | None:
    """機能: 欠測を0へ補完せず、利用可能値の平均を返す。

    引数: values(list[float])。返り値: 平均または不明(float|None)。
    """
    return float(np.mean(values)) if values else None


def labeled_entries(method_id: str, account: dict, frame: dict, ready: dict) -> list[dict]:
    """機能: 実新規約定行を固定し、返済時刻を使わず4つの固定将来時点を観測する。

    引数: method_id(str)、account/frame/ready(dict)。返り値: 入口別・時間別の診断ラベル(list[dict])。
    同時刻の全有効行の最後をas-of採用するため、リアルタイム入口へ流用しない。
    """
    seq, times, mids = frame['seq'], frame['time_s'], frame['mid']
    assert np.all(np.diff(times) >= 0) and np.all(np.diff(seq) > 0)
    rows = []
    entries = [order for order in account['orders'] if order[4] == 1]
    assert len(entries) == account['cycles']
    for entry in entries:
        i = int(np.searchsorted(seq, int(entry[3])))
        assert seq[i] == entry[3] and times[i] == entry[1]
        origin_time, origin_mid, side = float(times[i]), float(mids[i]), int(entry[5])
        for seconds in HORIZONS:
            target = origin_time + seconds
            row = dict(手法ID=method_id, セッション=account['session'], 銘柄=account['symbol'],
                       組=int(entry[10]), 入口原本行=int(seq[i]), 入口時計=origin_time,
                       入口時刻=stamp(origin_time), 入口中値=origin_mid, 方向=side,
                       観測秒=seconds, target時計=target, target時刻=stamp(target),
                       有効=False, 欠測理由=None, asof原本行=None, asof時計=None,
                       asof時刻=None, 古さ秒=None, target同時計の有効原本行数=None,
                       時点中値=None, 方向付き変化呼値=None, 方向付き変化bps=None)
            if target > ready['limit']:
                row['欠測理由'] = '場の返済判断時刻を超過'
                rows.append(row)
                continue
            j = int(np.searchsorted(times, target, side='right') - 1)
            if j < 0:
                row['欠測理由'] = '対象時点以前の有効行なし'
                rows.append(row)
                continue
            actual, age = float(times[j]), float(target - times[j])
            assert j >= i and actual <= target
            assert j == len(times) - 1 or times[j + 1] > target
            row.update(asof原本行=int(seq[j]), asof時計=actual, asof時刻=stamp(actual), 古さ秒=age,
                       target同時計の有効原本行数=int(np.searchsorted(times, target, side='right')
                                                    - np.searchsorted(times, target, side='left')))
            if age > 5.:
                row['欠測理由'] = '約定時計が5秒より古い'
                rows.append(row)
                continue
            change = side * float(mids[j] - origin_mid)
            row.update(有効=True, 時点中値=float(mids[j]), 方向付き変化呼値=change / ready['tick'],
                       方向付き変化bps=change / origin_mid * 10000.)
            rows.append(row)
    return rows


def aggregate(rows: list[dict], sessions: list[str]) -> dict:
    """機能: entry別の分布とセッション平均を別々に集計する。

    引数: rows(list[dict]) は同じ手法・銘柄・固定時点、sessions(list[str]) は全23場。
    返り値: 母数・欠測・方向割合・場平均(dict)。独立試行とみなす検定はしない。
    """
    valid = [row for row in rows if row['有効']]
    counts = {label: sum(row['欠測理由'] == label for row in rows)
              for label in ('場の返済判断時刻を超過', '対象時点以前の有効行なし', '約定時計が5秒より古い')}
    per_session = []
    for session in sessions:
        total = [row for row in rows if row['セッション'] == session]
        chosen = [row for row in total if row['有効']]
        ticks = [row['方向付き変化呼値'] for row in chosen]
        bps = [row['方向付き変化bps'] for row in chosen]
        per_session.append(dict(セッション=session, 入口数=len(total), 有効入口数=len(chosen),
                                欠測数=len(total) - len(chosen),
                                平均呼値=mean(ticks), 平均bps=mean(bps)))
    result = dict(入口数=len(rows), 有効入口数=len(valid), 欠測数=len(rows) - len(valid), 欠測理由別=counts,
                  有効率=len(valid) / len(rows) if rows else None, 場数=len(sessions),
                  有効な場数=sum(row['有効入口数'] > 0 for row in per_session),
                  targetとasofが同時計の入口数=sum(row['古さ秒'] == 0 for row in valid),
                  target同時計に複数rawがあった入口数=sum(row['target同時計の有効原本行数'] > 1 for row in valid),
                  最大採用古さ秒=max([row['古さ秒'] for row in valid], default=None),
                  各場=per_session)
    for label, column, session_column in (('呼値', '方向付き変化呼値', '平均呼値'), ('bps', '方向付き変化bps', '平均bps')):
        values = [row[column] for row in valid]
        n = len(values)
        positive, negative, flat = sum(x > 0 for x in values), sum(x < 0 for x in values), sum(x == 0 for x in values)
        session_values = [row[session_column] for row in per_session if row[session_column] is not None]
        result[label] = dict(
            entry加重平均=mean(values), entry中央値=float(np.median(values)) if values else None,
            正方向数=positive, 逆方向数=negative, 同値数=flat,
            正方向割合=positive / n if n else None, 逆方向割合=negative / n if n else None,
            同値割合=flat / n if n else None,
            同値除外正方向割合=positive / (positive + negative) if positive + negative else None,
            場平均の等ウェイト平均=mean(session_values),
            二十三場中で場平均が正の場数=sum(x > 0 for x in session_values),
            二十三場中で場平均が負の場数=sum(x < 0 for x in session_values),
            二十三場中で場平均が同値の場数=sum(x == 0 for x in session_values),
        )
        assert positive + negative + flat == len(valid)
    assert sum(counts.values()) + len(valid) == len(rows)
    return result


def original_mid_accounting(accounts: list[dict], frames: dict, symbol: str, expected: dict) -> dict:
    """機能: 元の入口・出口を中値で再評価し、同値除外勝率と1枚平均損益比を計算する。

    引数: accounts(list[dict])、frames(dict)、symbol(str)、expected(dict)。
    返り値: 元売買の中値会計(dict)。この関数の出口を固定時点ラベルへ渡さない。
    """
    pnls, quantities = [], []
    for account in accounts:
        frame = frames[account['session'], symbol]
        for trade in account['trades']:
            i, j = np.searchsorted(frame['seq'], [int(trade[11]), int(trade[12])])
            assert frame['seq'][i] == trade[11] and frame['seq'][j] == trade[12]
            pnl = float(trade[2] * trade[3] * VALUE_PER_POINT[symbol] * (frame['mid'][j] - frame['mid'][i]))
            pnls.append(pnl)
            quantities.append(int(trade[3]))
    pnl, qty = np.asarray(pnls), np.asarray(quantities)
    positive, negative, flat = pnl > 0, pnl < 0, pnl == 0
    profit, loss = float(pnl[positive].sum()), float(-pnl[negative].sum())
    win_qty, loss_qty = int(qty[positive].sum()), int(qty[negative].sum())
    wins, losses = int(positive.sum()), int(negative.sum())
    avg_win, avg_loss = profit / win_qty if win_qty else None, loss / loss_qty if loss_qty else None
    payoff = avg_win / avg_loss if avg_win is not None and avg_loss is not None else None
    break_even = avg_loss / (avg_win + avg_loss) if payoff is not None else None
    win_rate = wins / (wins + losses) if wins + losses else None
    for name, actual in (('profit', profit), ('loss', loss), ('net', profit - loss), ('win_qty', win_qty), ('loss_qty', loss_qty)):
        np.testing.assert_allclose(actual, expected[name], atol=1e-8)
    return dict(
        往復組数=len(pnls), 勝ち組数=wins, 負け組数=losses, 同値組数=int(flat.sum()),
        同値除外勝率=win_rate, 利益円=profit, 損失円=loss, 収支円=profit - loss,
        利益返済枚数=win_qty, 損失返済枚数=loss_qty,
        一枚平均勝ち円=avg_win, 一枚平均負け円=avg_loss, 一枚平均勝ち負け比=payoff,
        損益分岐勝率=break_even,
        勝率と損益分岐勝率の差=None if win_rate is None or break_even is None else win_rate - break_even,
        元の中値感度集計と一致=True,
    )


def main() -> None:
    """機能: 仕様メモに従い固定主条件の入口診断と別会計を保存する。

    引数: なし。返り値: なし(None)。新しい売買・入口選び・最適化は行わない。
    """
    spec_path = HERE / '仕様メモ.json'
    specification = json.loads(spec_path.read_text(encoding='utf8'))
    assert specification['固定観測秒'] == list(HORIZONS)
    result_path = SOURCE / '売買結果.json'
    source = json.loads(result_path.read_text(encoding='utf8'))
    raw_frames = pickle.loads((SOURCE / 'features.pkl').read_bytes())
    frames = {key: {name: value[name] for name in ('seq', 'time_s', 'mid')} for key, value in raw_frames.items()}
    del raw_frames
    inputs = pickle.loads(INPUT_PATH.read_bytes())
    sessions = source['sessions']
    assert len(sessions) == 23
    methods = [method for method in source['methods'] if method['primary']]
    assert len(methods) == 3 and {method['id'] for method in methods} == set(source['meta']['main_ids'])
    reports, all_labels = [], []
    for method in methods:
        symbols = {}
        for symbol in ('TOPIX', 'NK225'):
            accounts = [account for account in method['accounts'] if account['symbol'] == symbol]
            labels = []
            for account in accounts:
                key = account['session'], symbol
                labels.extend(labeled_entries(method['id'], account, frames[key], inputs[key]))
            all_labels.extend(labels)
            by_time = {str(seconds): aggregate([row for row in labels if row['観測秒'] == seconds], sessions)
                       for seconds in HORIZONS}
            accounting = original_mid_accounting(accounts, frames, symbol, method['summary'][symbol]['sensitivity']['中値'])
            assert all(row['入口数'] == accounting['往復組数'] for row in by_time.values())
            symbols[symbol] = dict(固定時点別=by_time, 元売買の中値会計=accounting)
        reports.append(dict(手法ID=method['id'], 手法名=method['entry_name'], 銘柄別=symbols))
    output = dict(
        仕様メモSHA256=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        入力結果SHA256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
        仕様=specification, 固定将来ラベル行数=len(all_labels),
        固定観測と会計の分離='固定時点診断は新規ordersのみ使用し元tradesの返済を参照しない。元中値会計だけ別関数で元返済を利用。',
        時計の限界='5秒以内という鮮度はCurrentPriceTime基準であり、受信時刻の鮮度を保証しない。同時計の最後の原本行は事後ラベルとしてのみ使用。',
        勝率の読み方='損益分岐勝率と実勝率の差は同じ元売買会計の別表現であり、独立した予測力の証拠ではない。',
        場平均の読み方='entry加重平均と場ごとの等ウェイト平均を分離。重複する入口区間を独立な標本として扱わず、統計的有意や因果効果を断定しない。',
        新規売買条件なし=True, ATR使用=False, API取得数=0, 手法別=reports,
    )
    (HERE / '入口固定時点の診断.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    (HERE / '入口別将来診断ラベル.pkl').write_bytes(pickle.dumps(all_labels, pickle.HIGHEST_PROTOCOL))
    brief = []
    for method in reports:
        for symbol, value in method['銘柄別'].items():
            times = value['固定時点別']
            account = value['元売買の中値会計']
            brief.append(dict(手法=method['手法ID'], 銘柄=symbol,
                              固定時点={seconds: dict(有効数=row['有効入口数'], 入口数=row['入口数'],
                                                      entry平均呼値=row['呼値']['entry加重平均'],
                                                      場等ウェイト平均呼値=row['呼値']['場平均の等ウェイト平均'],
                                                      平均正の場数=row['呼値']['二十三場中で場平均が正の場数'])
                                        for seconds, row in times.items()},
                              元mid勝率=account['同値除外勝率'], 損益比=account['一枚平均勝ち負け比'],
                              分岐勝率=account['損益分岐勝率']))
    print(json.dumps(brief, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
