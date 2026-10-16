"""全30場を始終中値で事後分類する。売買判断と手法選定には接続しない。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import pickle
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))
THRESHOLD = .001


def load(path):
    """
    機能: 既存の観測又は仕様を読み取る。
    引数: path (Path)。
    返り値: dict の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8')) if path.suffix == '.json' else pickle.loads(path.read_bytes())


# ----------------------------------------
def bounds(session):
    """
    機能: 既存の生板抽出と同じ通常監視区間を求める。
    引数: session (str) は開始日とDay/Night。
    返り値: tuple[float, float] の開始秒・排他的終了秒。
    """
    date, kind = session.rsplit('_', 1)
    day = datetime.fromisoformat(date).replace(tzinfo=JST)
    if kind == 'Day':
        return (day + timedelta(hours=8, minutes=45)).timestamp(), (day + timedelta(hours=15, minutes=40)).timestamp()
    assert kind == 'Night'
    return (day + timedelta(hours=17)).timestamp(), (day + timedelta(days=1, hours=5, minutes=55)).timestamp()


# ----------------------------------------
def main():
    """
    機能: 保存された有効気配の始終を±0.1%固定で上昇・下落・横ばいへ分類する。
    引数: なし。
    返り値: None。相場分類JSONだけを新規保存し、損益は参照しない。
    """
    meta_path = ROOT / 'work/wave_v77/inputs/metadata.json'
    meta = load(meta_path)
    ready, books, paths = {}, {}, [meta_path, ROOT / 'work/wave_v8/raw_features.py']
    for kind, target in (('ready', ready), ('features', books)):
        extra = 'extra_inputs.pkl' if kind == 'ready' else 'extra_features.pkl'
        for path in [ROOT / value for value in meta['input_paths'][kind]] + [ROOT / 'work/wave_v77/inputs' / extra]:
            target.update(load(path)); paths.append(path)
    rows = []
    for session in meta['sessions']:
        start, end = bounds(session)
        for symbol in ('TOPIX', 'NK225'):
            key = (session, symbol)
            r, b = ready[key], books[key]
            t = np.asarray(r['time_s'], dtype=float)
            bid, ask = np.asarray(b['bid'], dtype=float), np.asarray(b['ask'], dtype=float)
            bq, aq = np.asarray(b['bid_qty'], dtype=float), np.asarray(b['ask_qty'], dtype=float)
            valid = ((t >= start) & (t < end) & np.isfinite(bid) & np.isfinite(ask) & np.isfinite(bq) & np.isfinite(aq)
                     & (bid > 0) & (ask > bid) & (bq > 0) & (aq > 0))
            indices = np.flatnonzero(valid)
            assert len(indices) > 1, key
            first, last = int(indices[0]), int(indices[-1])
            begin_mid, end_mid = float((bid[first] + ask[first]) / 2), float((bid[last] + ask[last]) / 2)
            change = end_mid / begin_mid - 1
            regime = '上昇' if change >= THRESHOLD else '下落' if change <= -THRESHOLD else '横ばい'
            row = dict(session=session, symbol=symbol, start_mid=begin_mid, end_mid=end_mid, regime=regime,
                start_time=datetime.fromtimestamp(t[first], JST).isoformat(), end_time=datetime.fromtimestamp(t[last], JST).isoformat(),
                start_source_index=first, end_source_index=last, start_seq=int(r['seq'][first]), end_seq=int(r['seq'][last]),
                window_start=datetime.fromtimestamp(start, JST).isoformat(), window_end_exclusive=datetime.fromtimestamp(end, JST).isoformat())
            row['return'] = change
            rows.append(row)
    assert len(rows) == 60
    output = dict(rows=rows,
        definition='事後説明専用。該当場の最初と最後の保存有効最良気配中値を使用し、終中値/始中値−1が+0.1%以上なら上昇、−0.1%以下なら下落、その間なら横ばい。閾値は損益と無関係に固定。',
        threshold=THRESHOLD,
        observation_window='既存生板抽出と同じDay 08:45以上15:40未満、Night 17:00以上翌05:55未満（JST）。場外の気配を除く。夜間は開始日へ帰属。',
        quote_validity='最良買売価格・数量が有限かつ正、買値<売値。10段品質は要求しない。気配差拡大を方向分類の欠測理由にしない。',
        limitations=['正式な取引所始値・引値ではなく保存区間の端点。欠けた前後は補間しない。',
                     '横ばいは始終差で定義し、途中の大きな上下や最大値幅が小さかったとは意味しない。',
                     '同時計の原本順は維持し、各場の最初/最後の有効観測を使う。価格時計は受信時刻ではない。'],
        use_in_strategy=False, use_in_selection=False, profit_results_read=False,
        source_SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    target = HERE / '相場分類.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(保存=str(target), 口座数=len(rows), 商品別={symbol: {regime: sum(row['symbol'] == symbol and row['regime'] == regime for row in rows) for regime in ('上昇','下落','横ばい')} for symbol in ('TOPIX','NK225')}), ensure_ascii=False))


if __name__ == '__main__':
    main()
