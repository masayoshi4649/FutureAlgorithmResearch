"""抽出した板の観測量について保存則と測定可能範囲を集計する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent


def summarize(frames: list[pd.DataFrame]) -> dict:
    """機能: 全量保存と未知比率、公開遅延、値直し等の観測件数を集計する。

    引数: frames(list[DataFrame])。返り値: 将来収益を含まない品質要約(dict)。
    """
    frame = pd.concat(frames, ignore_index=True)
    volume = float(frame.source_volume_delta.sum())
    classified = frame.exec_buy + frame.exec_sell + frame.exec_unknown
    np.testing.assert_array_equal(classified, frame.source_volume_delta)
    for side in ('bid', 'ask'):
        for action in ('add', 'remove'):
            assert (frame[f'noexec_{side}_{action}'] <= frame[f'all_{side}_{action}']).all()
        assert (frame[f'refill_{side}_fixed_quote'] <= frame[f'refill_{side}']).all()
    assert (frame.source_last_seq < frame.seq).all()
    assert (frame.source_time_s < frame.time_s).all()
    assert (frame.volume_time_s <= frame.time_s).all()
    return dict(特徴行数=len(frame), 源有効板行数=int(frame.valid_events.sum()),
                出来高正増分=volume, 買い執行代理=float(frame.exec_buy.sum()),
                売り執行代理=float(frame.exec_sell.sum()), 未知数量=float(frame.exec_unknown.sum()),
                未知数量比率=float(frame.exec_unknown.sum() / volume) if volume else None,
                出来高正増分ゼロblock数=int((frame.source_volume_delta == 0).sum()),
                源時刻から公開まで秒分位={str(p): float(frame.source_age.quantile(p)) for p in (.25, .5, .75, .9, .99, 1.)},
                源時刻から60秒超block数=int((frame.source_age > 60).sum()),
                源時刻から60秒超block比率=float((frame.source_age > 60).mean()),
                源一block有効板行数分位={str(p): float(frame.valid_events.quantile(p)) for p in (.25, .5, .75, .9, 1.)},
                両最良気配上昇回数=int(frame.both_up.sum()), 両最良気配下落回数=int(frame.both_down.sum()),
                出来高差ゼロ板遷移数=int(frame.no_trade_events.sum()),
                出来高差正板遷移数=int(frame.trade_events.sum()),
                出来高欠測遷移数=int(frame.unavailable_volume_events.sum()),
                出来高リセット遷移数=int(frame.volume_resets.sum()),
                連続性切断数=int(frame.continuity_resets.sum()),
                十段正常行数=int(frame.depth_valid_events.sum()),
                十段欠測行数=int(frame.depth_incomplete_events.sum()),
                十段並び順不正行数=int(frame.depth_disordered_events.sum()),
                十段同価格重複行数=int(frame.depth_duplicate_events.sum()),
                十段不備を含むblock数=int((frame.depth_valid_events < frame.valid_events).sum()),
                数量保存一致=True, 源情報は公開行より前=True,
                注意='同一約定時刻内の複数板更新には個別受信時刻がない。速度・回復時間は約定時刻で測る代理値。')


def main() -> None:
    """機能: 完成した特徴だけを読み、銘柄別品質を保存する。

    引数: なし。返り値: なし(None)。価格の未来ラベルは作らない。
    """
    features = pickle.loads((HERE / 'features.pkl').read_bytes())
    result = {symbol: summarize([f for (session, sym), f in features.items() if sym == symbol])
              for symbol in ('TOPIX', 'NK225')}
    result['全体'] = summarize(list(features.values()))
    old_path = HERE / '監査_深板修正前.json'
    current_path = HERE / '監査.json'
    if old_path.exists() and current_path.exists():
        old = json.loads(old_path.read_text(encoding='utf8'))
        current = json.loads(current_path.read_text(encoding='utf8'))
        old_hash = {row['原本']: row['原本SHA256'] for row in old['原本別']}
        current_hash = {row['原本']: row['原本SHA256'] for row in current['原本別']}
        assert old_hash == current_hash
        result['再抽出時の原本不変'] = dict(一致原本数=len(old_hash), SHA256完全一致=True)
    (HERE / '観測品質.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
