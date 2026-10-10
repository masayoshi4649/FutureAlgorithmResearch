"""新規見送り指標の切断・未来変更・上下反射と注文許可を検査する。"""

from __future__ import annotations

import numpy as np
import gate_replay as run


def transformed_model(key: tuple, mode: str, cutoff: float) -> dict:
    """機能: 原本を変更せず指標素材を切断又は変形する。

    引数: key(tuple)、mode(str)、cutoff(float)。返り値: 再生成モデル(dict)。
    """
    bars = run.replay.entry.HIERARCHY.LEGACY._bars(run.INPUTS[key])
    values = {name: np.asarray(bars[name]).copy() for name in ('time_s', 'close', 'atr')}
    if mode == 'cut':
        valid = values['time_s'] < cutoff
        values = {name: value[valid] for name, value in values.items()}
    elif mode == 'future':
        future = values['time_s'] >= cutoff
        values['close'][future] += 10000 + np.arange(np.sum(future))*100
        values['atr'][future] *= 3
    else:
        values['close'] = 2*np.max(values['close'])-values['close']
    return run.model_from_bars(values)


def check_signals() -> None:
    """機能: 全32入力×13条件の因果性と売買対称性を確認する。

    引数: なし。返り値: なし(None)。
    """
    records = []
    for session in sorted({key[0] for key in run.INPUTS}):
        keys = [(session, symbol) for symbol in ('TOPIX', 'NK225')]
        start = max(run.INPUTS[key]['start'] for key in keys)
        end = min(run.INPUTS[key]['time_s'][-1] for key in keys)
        cutoff = start+(end-start)*.63
        alternatives = {mode: {key: transformed_model(key, mode, cutoff) for key in keys}
                        for mode in ('cut', 'future', 'reflection')}
        for key in keys:
            ready = run.INPUTS[key]
            state = run.replay.MID['entry'][key]
            own, peer = run.expanded(key, run.MODELS, ready['time_s'])
            count = int(np.searchsorted(ready['time_s'], cutoff, side='left'))
            for gate in run.catalog():
                mask = run.gate_mask(gate, state, own, peer)
                for mode, models in alternatives.items():
                    limit = len(state) if mode == 'reflection' else count
                    a, b = run.expanded(key, models, ready['time_s'][:limit])
                    other = run.gate_mask(gate, -state[:limit] if mode == 'reflection' else state[:limit], a, b)
                    np.testing.assert_array_equal(mask[:limit], other, err_msg=str((key, gate['id'], mode)))
                tied = np.flatnonzero(np.diff(ready['time_s']) == 0)+1
                same = int(tied[np.argmin(abs(tied-int(len(state)*.73)))]) if len(tied) else count
                a, b = run.expanded(key, run.MODELS, ready['time_s'][:same])
                np.testing.assert_array_equal(mask[:same], run.gate_mask(gate, state[:same], a, b))
                records.append(dict(session=key[0], symbol=key[1], gate=gate['id'], 切断=True, 未来変更=True, 上下反射=True, 同秒順=True))
    run.save(run.HERE/'新規見送り信号の因果監査.json', dict(全合格=True, 入力条件数=len(records), 結果=records,
        元信号='元入口/B00/B01は既存v47/v48因果監査済み。今回監査は追加した見送り用確定足変換と可否判定。',
        API取得数=0, 実装SHA256=run.sha(run.HERE/'gate_replay.py')))


def check_orders() -> None:
    """機能: 保存済み新規注文が直前の有効原本行で許可されていたか検査する。

    引数: なし。返り値: なし(None)。
    """
    gates = {g['id']: g for g in run.catalog()}
    records = []
    for path in sorted((run.HERE/'ledgers').glob('*.json.gz')):
        gate = gates[path.name.split('__')[-1].split('.')[0]]
        total, changed = 0, 0
        for ledger in run.read(path):
            key = ledger['session'], ledger['symbol']
            ready = run.INPUTS[key]
            state = run.replay.MID['entry'][key]
            own, peer = run.expanded(key, run.MODELS, ready['time_s'])
            mask = run.gate_mask(gate, state, own, peer)
            gated = np.where(mask, state, 0)
            valid_rows = np.flatnonzero(np.isfinite(ready['last']) & (ready['last'] > 0))
            for order in ledger['orders']:
                if order[7] != 1 or order[6] != 20:
                    continue
                fill, source, side = int(order[0]), int(order[1]), int(order[3])
                previous = int(valid_rows[np.searchsorted(valid_rows, fill)-1])
                assert gated[previous] == side and gated[source] == side
                changed += int(gated[fill] != side)
                total += 1
        records.append(dict(id=path.name.removesuffix('.json.gz'), 初回件数=total, 成熟計画源の許可全一致=True,
                            取消観測と既発注約定が同じ行だった件数=changed))
    run.save(run.HERE/'新規約定直前の許可監査.json', dict(全合格=True, 結果=records))


if __name__ == '__main__':
    run.initialize()
    check_signals()
    check_orders()
    print('見送り信号416組の切断・未来変更・反射・同秒順と保存注文を確認', flush=True)
