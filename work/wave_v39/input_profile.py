"""次の独立仮説のために、公開済み板特徴の粒度だけを確認する。"""

from pathlib import Path
import hashlib
import json
import pickle
import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'wave_v23/features_depth.pkl'


def main() -> None:
    """機能: 損益を計算せず、公開間隔と素材区間の品質を記録する。

    引数: なし。返り値: なし (None)。原本・既存特徴は読み取りのみ。
    """
    payload = SOURCE.read_bytes()
    frames = pickle.loads(payload)
    rows = []
    for (session, symbol), frame in sorted(frames.items()):
        release = frame.time_s.to_numpy(float)
        source = frame.source_time_s.to_numpy(float)
        interval = np.diff(release)
        row = dict(セッション=session, 銘柄=symbol, 特徴行数=len(frame),
            公開間隔秒分位=np.quantile(interval, [0, .1, .5, .9, 1]).tolist(),
            公開時素材遅れ秒分位=np.quantile(release-source, [0, .5, .9, 1]).tolist(),
            同一素材時刻数=int(np.sum(np.diff(source)==0)),
            連続性リセット数=int(frame.continuity_reset_count.sum()),
            全素材先行=bool((frame.source_last_seq < frame.seq).all()),
            全公開行増加=bool((np.diff(frame.seq)>0).all()),
            全素材時刻非減少=bool((np.diff(source)>=0).all()),
            公開素材一分例=frame[['time_s','source_time_s','source_first_seq',
                'source_last_seq','seq','ofi_signed','ofi_abs','bid_qty','ask_qty']].head(4).to_dict('records'))
        rows.append(row)
    result = dict(段階='粒度確認だけ・売買未実施', 元特徴SHA256=hashlib.sha256(payload).hexdigest(),
        入力数=len(rows), 特徴列=list(next(iter(frames.values())).columns), 入力=rows,
        API取得数=0, 現在保存物使用=False)
    (HERE/'入力粒度確認.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(入力数=len(rows), 全特徴行数=sum(r['特徴行数'] for r in rows),
        各入力中央値秒=[r['公開間隔秒分位'][2] for r in rows]), ensure_ascii=False))


if __name__ == '__main__':
    main()
