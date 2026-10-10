"""入口候補と状況別選択が未来に依存しないか独立検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK))
from signals import FAMILIES, candidates, make_decisions, mode, confirmed


def main() -> None:
    """機能: 十二入口・確認有無・自動選択の切断と未来改変を比較する。

    引数: なし。返り値: なし(None)。損益による条件選択は行わない。
    """
    features = pickle.loads((TASK/'特徴.pkl').read_bytes())
    keys = sorted(features)
    audits = []
    families = [x[0] for x in FAMILIES]+['AUTO']
    for key in [keys[i] for i in (0,1,22,23,44,45)]:
        frame = features[key]
        full, rows = candidates(frame)
        decisions = {(family, check): make_decisions(frame, full, rows, family, check)[0]
                     for family in families for check in (False, True)}
        for fraction in (.35,.7):
            cut = int(len(frame)*fraction)
            part = frame.iloc[:cut].copy()
            limited, short_rows = candidates(part)
            changed = frame.copy()
            for name in ('close','prev_close','open','high','low','vwap_proxy','ema8','ema21','prior20_high','prior20_low'):
                changed.loc[changed.index[cut:], name] *= 1.7
            for name in ('execution','recovery','repricing','supply'):
                changed.loc[changed.index[cut:], name] *= -1.
            other, changed_rows = candidates(changed)
            for family in full:
                np.testing.assert_array_equal(limited[family], full[family][:cut])
                np.testing.assert_array_equal(other[family][:cut], full[family][:cut])
            for family in families:
                for check in (False,True):
                    actual = make_decisions(part, limited, short_rows, family, check)[0]
                    modified = make_decisions(changed, other, changed_rows, family, check)[0]
                    expected = decisions[family,check][:cut]
                    np.testing.assert_array_equal(actual, expected)
                    np.testing.assert_array_equal(modified[:cut], expected)
                    audits.append(dict(セッション=key[0], 銘柄=key[1], 手法=family, 確認=check,
                                       切断比率=fraction, 一致判断数=cut))
    r = SimpleNamespace(er15=.5, ema8=102., ema21=100., atr5=2., vwap_proxy=100., close=103.,
                        prev_close=102., peer_ema8=98., peer_ema21=100., peer_atr5=2., peer_er15=.5,
                        peer_can_trade=1, board_valid=1, execution=.5, unknown_fraction=0., repricing=.5,
                        supply=.5, recovery=.5)
    assert mode(r) == (1,1)
    assert not confirmed(r, 1, '追従', 1,1)
    r.peer_can_trade = 0
    assert confirmed(r, 1, '追従', 1,1)
    r.unknown_fraction, r.execution, r.repricing = 1.,0.,np.nan
    assert not confirmed(r, 1, '追従', 1,1)
    r.er15 = .2
    assert mode(r) == (2,0)
    r.er15 = np.nan
    assert mode(r) == (0,0)
    output = dict(合格=True, 実データ比較数=len(audits), 比較=audits,
                  合成確認=['相手の明確な逆方向は新規見送り','相手不明は一致扱いせず拒否もしない',
                            '全量不明の執行ゼロは順張り確認に使わない','状況不明を追従や反復へ断定しない'],
                  実装SHA256=hashlib.sha256((TASK/'signals.py').read_bytes()).hexdigest())
    (HERE/'入口と選択の独立検査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf8')
    print('入口と選択合格', len(audits), flush=True)


if __name__ == '__main__':
    main()
