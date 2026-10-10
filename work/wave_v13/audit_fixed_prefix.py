"""凍結後の保存データで新旧通知と固定16条件の未来打切り不変性を確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_new_signals import compare_events
from audit_exact import close_equal
import data
import exact_engine
import new_signals
import research

OUT = Path(__file__).resolve().parent


def main() -> None:
    """機能: 旧24・新18通知と定刻通知を打切り、固定方式の過去売買を照合する。

    引数: なし。返り値: None: 打切り監査JSONを保存。通信・選択変更なし。
    """
    frozen = json.loads((OUT/'現在照合_凍結記録.json').read_text(encoding='utf-8'))
    base = data.signals_module(allow_holdout=True)
    base.CANDLE_OVERRIDES[frozen['session']] = OUT/'live'
    base.FEATURE_OVERRIDES[frozen['session']] = OUT/'live/features'
    new_signals.configure(base)
    records, trade_checks, closed_checks = [], 0, 0
    for session in [data.HOLDOUT, frozen['session']]:
        folder = base.feature_root(session)
        frames = {s: pd.read_csv(folder/f'{s}_{session}.csv') for s in data.SYMBOLS}
        for symbol in data.SYMBOLS:
            frame = frames[symbol]
            peer = frames[data.SYMBOLS[1-data.SYMBOLS.index(symbol)]]
            old_full, _ = base.build_events(session, symbol, frame, peer)
            new_full, _ = new_signals.build_events(session, symbol, frame, peer)
            tape = dict(np.load(folder/f'約定系列_{symbol}_{session}.npz', allow_pickle=False))
            tape['atr'] = base.atr_at(session, symbol, tape['time_s'])
            clock_full = research.clock_events(tape, session, symbol)
            events = pd.concat([old_full, new_full, clock_full], ignore_index=True).sort_values(['seq', 'family']).reset_index(drop=True)
            state = base.state_at(tape, frame, base.price_grid(session, symbol, float(tape['time_s'][-1])))
            ready = exact_engine.prepare(tape, events, session, symbol, state=state)
            full_results = {cfg['id']:exact_engine.simulate(ready, cfg['family'], cfg, detail=True) for cfg in frozen['selected_configs']}
            for fraction in [.3537, .7137]:
                index = int(len(frame)*fraction)
                stamp = float(frame.time_s.iloc[index])
                last_seq = int(frame.seq.iloc[index])
                own_cut = frame.loc[frame.seq <= last_seq]
                peer_cut = peer.loc[peer.time_s+60 <= stamp]
                old_cut, _ = base.build_events(session, symbol, own_cut, peer_cut, cutoff=stamp)
                new_cut, _ = new_signals.build_events(session, symbol, own_cut, peer_cut, cutoff=stamp)
                old_count = compare_events(old_full, old_cut, stamp)
                new_count = compare_events(new_full, new_cut, stamp)
                mask = tape['seq'] <= last_seq
                cut_tape = {k:v[mask] if np.ndim(v) and len(v) == len(mask) else v for k, v in tape.items()}
                cut_tape['atr'] = base.atr_at(session, symbol, cut_tape['time_s'], cutoff=stamp)
                close_equal(tape['atr'][mask], cut_tape['atr'])
                clock_cut = research.clock_events(cut_tape, session, symbol)
                pd.testing.assert_frame_equal(clock_full.loc[clock_full.seq <= last_seq].reset_index(drop=True), clock_cut.reset_index(drop=True), check_dtype=False)
                cut_state = base.state_at(cut_tape, own_cut, base.price_grid(session, symbol, stamp))
                for key in cut_state:
                    close_equal(state[key][mask], cut_state[key])
                cut_events = pd.concat([old_cut, new_cut, clock_cut], ignore_index=True).sort_values(['seq', 'family']).reset_index(drop=True)
                cut_ready = exact_engine.prepare(cut_tape, cut_events, session, symbol, state=cut_state)
                for cfg in frozen['selected_configs']:
                    full = full_results[cfg['id']]
                    cut = exact_engine.simulate(cut_ready, cfg['family'], cfg, detail=True)
                    expect = full['raw'][(full['raw'][:, 14] == 1) & (full['raw'][:, 21] <= last_seq)]
                    actual = cut['raw'][cut['raw'][:, 14] == 1]
                    close_equal(expect, actual)
                    for row in cut['equity']:
                        match = full['equity'][full['equity'][:, 1] == row[1]]
                        if len(match):
                            close_equal(row, match[0])
                    trade_checks += 1
                    closed_checks += len(actual)
                records.append(dict(セッション=session, 銘柄=symbol, 打切り原本行=last_seq,
                                    打切り時刻=stamp, 旧通知比較数=old_count, 新通知比較数=new_count))
    result = dict(成功=True, 通知系統数=42, 固定条件数=len(frozen['selected_ids']),
                  打切り箇所数=len(records), 固定条件打切り比較数=trade_checks,
                  確定脚比較数=closed_checks, 記録=records, API取得回数=0, 再選択=False,
                  ソースSHA256={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest()
                               for name in ['exact_engine.py', 'research.py', 'new_signals.py']})
    (OUT/'固定照合_未来打切り独立監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['記録', 'ソースSHA256']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
