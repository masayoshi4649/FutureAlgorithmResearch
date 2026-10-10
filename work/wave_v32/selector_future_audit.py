"""選択器の未来足・未来影口座・価格反射を追加監査し、開始用証跡を結合する。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import pickle
import shutil
import socket
import sys
import urllib.request

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v23'
sys.path.insert(0, str(HERE))
import selector_signals as target
from selector_signal_audit import read, save, digest, original_hashes, reject_network, equal, array_hash


def copied_candles(inputs: dict, directory: Path, cutoffs: dict | None = None,
                   offsets: dict | None = None, delay_band: bool = False) -> None:
    """機能: 足を作業域へ複写し、公開後の未来部分又は上下反射だけを変形する。

    引数: inputs (dict)、directory (Path)、cutoffs/offsets (dict|None)、delay_band (bool)。
    返り値: なし (None)。原本には書き込まない。
    """
    for session, symbol in inputs:
        source = ROOT / 'candle_1min' / symbol / f'{session}.csv'
        path = directory / 'candle_1min' / symbol / f'{session}.csv'
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        frame = pd.read_csv(path)
        if offsets is not None:
            offset = offsets[session, symbol]
            old_high, old_low = frame.high.copy(), frame.low.copy()
            for field in ('open', 'close'):
                frame[field] = offset - frame[field]
            frame['high'], frame['low'] = offset - old_low, offset - old_high
        else:
            public = pd.to_datetime(frame.time).astype('int64').to_numpy(float)
            # pandasのdatetime精度をnsへ統一する。
            public = pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 120.
            cutoff = cutoffs[session]
            mask = (public + 60 > cutoff) & (public <= cutoff) if delay_band else public > cutoff
            for field in ('open', 'high', 'low', 'close'):
                frame.loc[mask, field] = frame.loc[mask, field] * 1.7 + 1234.
            frame.loc[mask, 'volume'] = 987654321.
        frame.to_csv(path, index=False)


def compare_prefix(base: dict, altered: dict, inputs: dict, cutoffs: dict) -> int:
    """機能: 各市場の共通時刻以前の原本行を値変更後と比較する。

    引数: base/altered/inputs/cutoffs (dict)。返り値: 比較区間数 (int)。
    """
    count = 0
    for key, ready in inputs.items():
        keep = ready['time_s'] <= cutoffs[key[0]]
        np.testing.assert_array_equal(base[key][keep], altered[key][keep])
        count += 1
    return count


def fake_shadows(inputs: dict) -> list[dict]:
    """機能: 実損益を読まず、実時計上の学習境界を試す人工影成績を作る。

    引数: inputs (dict)。返り値: 人工影口座行 (list[dict])。
    """
    output = []
    sessions = sorted({k[0] for k in inputs})
    for index, session in enumerate(sessions):
        risks = target.reference_r(inputs, session)
        for symbol in target.SYMBOLS:
            for branch in target.BRANCHES:
                output.append(dict(session=session, symbol=symbol, branch=branch,
                    net_yen=risks[symbol]['risk_yen'] * (((index % 4) - 1) * (1 if branch == 'T' else -1)),
                    completed_at=float(inputs[session, symbol]['time_s'][-1]), complete=True))
    return output


def past_future(inputs: dict) -> dict:
    """機能: Bの全近傍で未来影口座と当該両市場の削除・値変更を検査する。

    引数: inputs (dict)。返り値: 合成影口座による実時計検査件数 (dict)。
    """
    shadows = fake_shadows(inputs)
    specs = ((6, .25), (5, .25), (7, .25), (6, .20), (6, .30))
    checks = 0
    for window, gap in specs:
        base, logs = target.build_past_requests(inputs, shadows, window, gap)
        for session, start, _, _ in target._sessions(inputs):
            actual_inputs = {k: r for k, r in inputs.items() if r['start'] <= start}
            prior = [r for r in shadows if inputs[r['session'], r['symbol']]['start'] < start]
            short, short_logs = target.build_past_requests(actual_inputs, prior, window, gap)
            equal(short, {k: v for k, v in base.items() if k in actual_inputs})
            assert short_logs == [r for r in logs if r['timestamp'] <= start]
            changes = deepcopy(shadows)
            for row in changes:
                if inputs[row['session'], row['symbol']]['start'] >= start:
                    row['net_yen'] = 1e15 if row['branch'] == 'R' else -1e15
            altered, modified_logs = target.build_past_requests(inputs, changes, window, gap)
            equal({k: v for k, v in altered.items() if k in actual_inputs}, short)
            assert [r for r in modified_logs if r['timestamp'] <= start] == short_logs
            checks += 1
    return dict(B全近傍と13場初の未来影削除改変=checks, 使用影損益='人工値のみ。新損益不使用。')


def main() -> None:
    """機能: 第一段のprefix監査へ未来改変・価格反射を結合し全監査完了を保存する。

    引数: なし。返り値: なし (None)。売買再生・現在保存物・APIを使用しない。
    """
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    initial = read(HERE / 'selector_signal_audit.json')
    assert initial['構造監査合格']
    for relative, fingerprint in initial['参照SHA256'].items():
        assert digest(ROOT / relative) == fingerprint
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    features = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    with np.load(HERE / 'audited_entries.npz') as archive:
        base_entries = {branch: {key: archive[f'{branch}|{key[0]}|{key[1]}'] for key in inputs} for branch in target.BRANCHES}
    target.initialize(inputs, features)
    states = {window: target.build_state_requests(inputs, window) for window in (24, 30, 36)}
    for _, logs in states.values():
        for event in logs:
            for foot in event['foot_time'].values():
                assert foot is None or foot + 180. <= event['timestamp']
    cutoffs = {session: start + max(1, int((observed - start) * .55 // 1800)) * 1800.
               for session, start, limit, observed in target._sessions(inputs)}
    future_root, band_root, mirror_root = (HERE / 'audit_candles' / name for name in ('future', 'additional_delay', 'mirror'))
    copied_candles(inputs, future_root, cutoffs=cutoffs)
    copied_candles(inputs, band_root, cutoffs=cutoffs, delay_band=True)
    offsets = {key: 2 * np.ceil(np.max(r['last']) / r['tick']) * r['tick'] for key, r in inputs.items()}
    copied_candles(inputs, mirror_root, offsets=offsets)
    changed_features = {k: f.copy() for k, f in features.items()}
    changed_inputs = {k: dict(r, last=r['last'].copy(), atr=r['atr'].copy()) for k, r in inputs.items()}
    for key, frame in changed_features.items():
        future = frame.time_s > cutoffs[key[0]]
        frame.loc[future, 'source_mid_last'] = frame.loc[future, 'source_mid_last'] * 1.7 + 1234.
        frame.loc[future, 'ofi_signed'] *= -100
        future_rows = changed_inputs[key]['time_s'] > cutoffs[key[0]]
        changed_inputs[key]['last'][future_rows] *= 1.7
        changed_inputs[key]['atr'][future_rows] *= 2.3
    counts = {}
    try:
        target.set_root(future_root)
        changed_entries = target.build_entries(changed_inputs, changed_features)
        counts['T_R未来足板価格ATR改変'] = sum(compare_prefix(base_entries[b], changed_entries[b], inputs, cutoffs) for b in target.BRANCHES)
        counts['A未来足出来高価格改変'] = 0
        for window in states:
            changed, logs = target.build_state_requests(changed_inputs, window)
            counts['A未来足出来高価格改変'] += compare_prefix(states[window][0], changed, inputs, cutoffs)
            for session, cutoff in cutoffs.items():
                assert [r for r in logs if r['session'] == session and r['timestamp'] <= cutoff] == [r for r in states[window][1] if r['session'] == session and r['timestamp'] <= cutoff]
        target.set_root(band_root)
        counts['A追加60秒の未公開足変更'] = 0
        for window in states:
            changed, _ = target.build_state_requests(inputs, window)
            counts['A追加60秒の未公開足変更'] += compare_prefix(states[window][0], changed, inputs, cutoffs)
        # ----------------------------------------
        target.set_root(mirror_root)
        mirror_inputs = {k: dict(r, last=offsets[k] - r['last']) for k, r in inputs.items()}
        mirror_features = {k: f.copy() for k, f in features.items()}
        for key, frame in mirror_features.items():
            frame['source_mid_last'] = offsets[key] - frame['source_mid_last']
        mirrored = target.build_entries(mirror_inputs, mirror_features)
        for branch in target.BRANCHES:
            equal(mirrored[branch], {k: -v for k, v in base_entries[branch].items()})
        counts['T_R上下反射'] = 52
        for window in states:
            reflected, _ = target.build_state_requests(mirror_inputs, window)
            equal(reflected, states[window][0])
        counts['A上下反射で同じ要求'] = 78
        # ----------------------------------------
        target.set_root(ROOT)
        no_size = {k: f.copy() for k, f in features.items()}
        for frame in no_size.values():
            for field in frame.columns:
                if any(word in field for word in ('qty', 'ofi', 'imb', 'trade', 'added', 'removed', 'refill', 'pressure', 'dflow', 'micro_bias')):
                    frame[field] = 0.
        no_board = target.build_entries(inputs, no_size)
        equal(base_entries['R'], no_board['R'])
        counts['P02価格撤回版の数量OFI除去一致'] = 26
        counts.update(past_future(inputs))
    finally:
        target.set_root(ROOT)
    assert original_hashes() == initial['原本78SHA256']
    for relative, fingerprint in initial['参照SHA256'].items():
        assert digest(ROOT / relative) == fingerprint
    result = dict(追加監査合格=True, 検査件数=counts, API取得数=0, 売買再生実行=False,
                  新PnL参照=False, 現在データ使用=False, コードSHA256=digest(Path(__file__)))
    save(HERE / 'selector_future_audit.json', result)
    combined = dict(initial, 全監査完了=True, 追加監査=result)
    combined['参照SHA256'] = dict(initial['参照SHA256'])
    for path in (Path(__file__), HERE / 'selector_future_audit.json', HERE / 'selector_signal_audit.json', HERE / 'audited_entries.npz'):
        combined['参照SHA256'][path.relative_to(ROOT).as_posix()] = digest(path)
    save(HERE / 'selector_causality_before_pnl.json', combined)
    lines = ['# T/R入口と選択要求の損益前監査', '',
             '- Tは凍結H019を再生成し、旧26入力の方向と一致。Rは元P02の価格だけの撤回版を使用し、数量・OFIを消しても同じ26列。',
             '- 全13セッションでT/Rの2切断104区間、A24/30/36窓の2切断156区間が一致。',
             '- 未来足・板価格・ATRを改変しても過去T/R52区間、A78区間は一致。追加60秒待ち中の足変更78区間も不変。',
             '- 価格上下反射でT/Rは逆方向、Aは同じ要求。未確定足や未来出来高を選択に使わない。',
             '- Aは別公開足による同要求2回。新足なし・欠測・中間不一致で確認を解除し現要求を維持。最早切替は24窓60分、30/36窓90分。',
             '- Bは両市場両枝の完了後だけ学習し、当該両市場は除外。5仕様×13場初の未来影削除・改変が一致。厳密gap境界、欠損R除外、±3制限後の両市場最低平均を合成検査した。',
             '- 乱数A/B全64seedは共通時計・末尾長不変。入口/要求の1・5・15秒遅延は原本過去asof、0秒は同一行。',
             '', '新損益・現在保存物を参照せず、売買再生もAPI取得も行っていない。原本78ファイルは不変。これは選択規則の因果性を検査するもので、選択に予測力があることを証明しない。']
    (HERE / 'selector_signal_audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(result, flush=True)


if __name__ == '__main__':
    main()
