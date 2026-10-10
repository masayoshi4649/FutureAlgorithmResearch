"""板の過去学習が同一セッションの未来ラベルを使わないことを検査する。"""

from __future__ import annotations

import copy
import json
import pickle
from pathlib import Path

import numpy as np
import learned_flow as model

OUT = Path(__file__).resolve().parent


def trim(ready: dict, end: int) -> dict:
    """機能: 原本観測行を指定位置までに切り、境界情報は維持する。

    引数: ready (dict)、end (int)。返り値: 切断した入力 (dict)。
    """
    count = len(ready['time_s'])
    return {key: (value[:end].copy() if isinstance(value, np.ndarray) and len(value) == count else value)
            for key, value in ready.items()}


def generate(inputs: dict, frames: dict, name: str) -> tuple[dict, list]:
    """機能: 本番の学習記録を上書きせず候補方向と係数記録を作る。

    引数: inputs/frames (dict)、name (str)。返り値: 方向辞書と記録 (tuple[dict,list])。
    """
    old = model.OUT
    destination = OUT / 'learned_audit' / name
    destination.mkdir(parents=True, exist_ok=True)
    model.OUT = destination
    try:
        _, result = model.build_all(inputs, frames)
        audit = json.loads((destination / '学習の時系列記録.json').read_text(encoding='utf-8'))
        return result, audit
    finally:
        model.OUT = old


def main() -> None:
    """機能: 完了セッション順序、未来切断、将来改変、同時セッション分離を検算する。

    引数: なし。返り値: なし (None)。結果は learned_flow_audit.json へ記録する。
    """
    inputs = pickle.loads((OUT / 'inputs.pkl').read_bytes())
    feature_path = OUT / 'features_depth.pkl'
    if not feature_path.exists():
        feature_path = OUT / 'features.pkl'
    frames = pickle.loads(feature_path.read_bytes())
    sessions = sorted({key[0] for key in inputs})
    checks, selection_rows, peer_rows = [], 0, 0
    built = {}
    for key, ready in inputs.items():
        frame = frames[key]
        assert np.all(np.diff(ready['time_s']) >= 0)
        assert np.all(np.diff(frame.time_s.to_numpy()) >= 0)
        assert np.all(np.diff(frame.seq.to_numpy()) >= 0)
        assert ready['time_s'][-1] > ready['limit']
        event = model.events(ready, frame)
        built[key] = event
        selected = np.searchsorted(frame.seq.to_numpy(), ready['seq'][event['indices']], side='right')-1
        valid = selected >= 0
        assert np.all(frame.seq.to_numpy()[selected[valid]] <= ready['seq'][event['indices'][valid]])
        assert np.all(frame.time_s.to_numpy()[selected[valid]] <= event['time_s'][valid])
        if 'source_last_seq' in frame:
            assert np.all(frame.source_last_seq.to_numpy()[selected[valid]] < frame.seq.to_numpy()[selected[valid]])
        selection_rows += int(valid.sum())
        for duration in (1800, 3600, 7200):
            cut = int(np.searchsorted(ready['time_s'], ready['start']+duration, side='left'))+1
            short = model.events(trim(ready, cut), frame)
            past = event['indices'] < cut
            np.testing.assert_array_equal(short['indices'], event['indices'][past])
            np.testing.assert_allclose(short['X'], event['X'][past], atol=1e-12)
    checks.append('全２６入力の観測順序・板解放行・解放時刻・３地点の特徴prefixが一致')
    for key, event in built.items():
        peer = built[(key[0], 'TOPIX' if key[1]=='NK225' else 'NK225')]
        lookup = np.searchsorted(peer['time_s']+60, event['time_s'], side='right')-1
        valid = lookup >= 0
        assert np.all(peer['time_s'][lookup[valid]]+60 <= event['time_s'][valid])
        peer_rows += int(valid.sum())
    for i, session in enumerate(sessions[1:],1):
        latest_past = max(inputs[(s,'TOPIX')]['time_s'][-1] for s in sessions[:i])
        latest_past = max(latest_past,max(inputs[(s,'NK225')]['time_s'][-1] for s in sessions[:i]))
        current_start = min(inputs[(session,symbol)]['time_s'][0] for symbol in ('TOPIX','NK225'))
        assert latest_past < current_start
    checks.append('学習用の過去セッションは両銘柄とも現在セッション開始前に完了、相手特徴は６０秒以上遅延')

    # ----------------------------------------
    # 全履歴の係数と、各セッションの出力が未来セッションの有無に依存しない。
    original, audit = generate(inputs, frames, '全履歴')
    first = {key: value for key,value in inputs.items() if key[0] in sessions[:3]}
    first_result, first_audit = generate(first, frames, '最初３セッション')
    for spec in model.catalog():
        code = spec['id']
        for key in first:
            np.testing.assert_array_equal(original[code][key], first_result[code][key])
            if key[0] in sessions[:2]:
                assert np.count_nonzero(original[code][key]) == 0
    for record in audit:
        position = sessions.index(record['適用セッション'])
        assert position >= 2
        assert record['学習末尾'] == sessions[position-1]
    checks.append('４候補とも最初２セッションは学習専用、未来１０セッションを削除しても最初３セッションの出力不変')

    # ----------------------------------------
    # 直近セッションの後半価格・板を大幅変更しても過去信号は不変。
    current = sessions[-1]
    cutoff = min(inputs[(current,symbol)]['start'] for symbol in ('TOPIX','NK225'))+7200
    changed_inputs = dict(inputs)
    changed_frames = dict(frames)
    for symbol in ('TOPIX','NK225'):
        key = (current,symbol)
        ready = dict(inputs[key])
        ready['last'] = ready['last'].copy()
        ready['atr'] = ready['atr'].copy()
        future = ready['time_s'] > cutoff
        ready['last'][future] = ready['last'][future]*1.4+100
        ready['atr'][future] *= 3
        changed_inputs[key] = ready
        frame = frames[key].copy()
        future_rows = frame.time_s > cutoff
        for name in ['ofi_signed','ofi_abs','trade_pos','trade_neg','added_bid','removed_bid','added_ask','removed_ask',
                     'imb1','imb5','imb10','micro_bias','pressure_near','pressure_far','dflow_near','dflow_far','refill_bid','refill_ask']:
            if name in frame:
                frame.loc[future_rows,name] = frame.loc[future_rows,name]*(-5 if name.endswith('signed') else 9)+3
        changed_frames[key] = frame
    changed, changed_audit = generate(changed_inputs, changed_frames, '現在の未来改変')
    for spec in model.catalog():
        for key, ready in inputs.items():
            mask = ready['time_s'] <= cutoff if key[0]==current else np.ones(len(ready['time_s']), dtype=bool)
            np.testing.assert_array_equal(original[spec['id']][key][mask],changed[spec['id']][key][mask])
    assert audit == changed_audit
    checks.append('直近セッションの未来価格・ATR・板数量を改変しても過去信号と適用係数は完全一致')

    # ----------------------------------------
    # 最新セッションを毎分境界で切断しても最後の観測行まで方向が一致。
    prefix_inputs = dict(inputs)
    for symbol in ('TOPIX','NK225'):
        key = (current,symbol)
        cut = int(np.searchsorted(inputs[key]['time_s'],cutoff,side='right'))
        prefix_inputs[key] = trim(inputs[key],cut)
    prefix, _ = generate(prefix_inputs,frames,'直近の２時間切断')
    for spec in model.catalog():
        for symbol in ('TOPIX','NK225'):
            key = (current,symbol)
            np.testing.assert_array_equal(prefix[spec['id']][key], original[spec['id']][key][:len(prefix_inputs[key]['time_s'])])
    checks.append('直近セッションの毎分境界での未来切断も最後の原本行まで一致')

    # ----------------------------------------
    # 特徴を固定し、現在セッションのラベルだけを極端に変えて同時学習混入を検出。
    label_inputs = dict(first)
    third = sessions[2]
    for symbol in ('TOPIX','NK225'):
        key = (third,symbol)
        ready = dict(first[key])
        ready['last'] = ready['last']*10+100000
        label_inputs[key] = ready
    original_events = model.events
    def frozen_events(ready: dict, frame) -> dict:
        """機能: ラベル経路のみ改変する監査用に価格特徴を固定する。

        引数: ready (dict)、frame (DataFrame)。返り値: 元のイベント (dict)。
        """
        return copy.deepcopy(built[(ready['session'],ready['symbol'])])
    model.events = frozen_events
    try:
        changed_labels, label_audit = generate(label_inputs, frames, '現在ラベルだけ改変')
    finally:
        model.events = original_events
    for spec in model.catalog():
        for symbol in ('TOPIX','NK225'):
            key = (third,symbol)
            np.testing.assert_array_equal(first_result[spec['id']][key],changed_labels[spec['id']][key])
    assert first_audit == label_audit
    checks.append('同一セッションの両銘柄ラベルだけを改変しても両銘柄の予測・係数不変')
    report = {'合格': True, '特徴ファイル': feature_path.name, '候補数': len(model.catalog()),
              'セッション数': len(sessions), '板参照検査数': selection_rows, '相手遅延検査数': peer_rows,
              '確認': checks, '修正': '毎分境界が入力末尾の場合のイベント欠落を修正。予測時間・閾値・正則化・学習開始数は変更なし。',
              '注意': '因果性と同一セッション分離の検査であり、予測性能の評価ではない。'}
    (OUT/'learned_flow_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
