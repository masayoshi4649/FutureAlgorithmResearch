"""結果前の起動ガードが集合欠落・未来参照・根拠偽装を拒否する人工検査。"""

from copy import deepcopy

import numpy as np

import run_verified as guard
import band_signal_audit as fixtures


def main() -> None:
    """機能: 人工入力の一箇所を壊し、未確認の実体を起動可としないことを調べる。

    引数: なし。返り値: なし (None)。実損益・API・保存ライブを使わない。
    """
    results = []
    def accepted(name: str) -> None:
        """機能: 合格した人工確認を記録する。

        引数: name (str)。返り値: なし (None)。
        """
        results.append(dict(検査=name, 一致=True))
    def rejected(name: str, call) -> None:
        """機能: 不正資料の拒否を確認する。

        引数: name (str)、call (callable)。返り値: なし (None)。
        """
        try:
            call()
        except (AssertionError, KeyError):
            accepted(name)
            return
        raise AssertionError('破損を受理: ' + name)
    fixed = dict(conditions=guard.runner.design.conditions(), supplementary_conditions=guard.runner.design.supplementary_conditions(),
        主仮説='Q034__V000', 全条件数=364, 主条件数=91, 診断条件数=273, 補助条件数=65)
    guard.verify_catalog(fixed); accepted('主364と別補助65の全集合')
    altered = deepcopy(fixed); altered['conditions'].pop()
    rejected('主条件不足拒否', lambda: guard.verify_catalog(altered))
    altered = deepcopy(fixed); altered['主仮説'] = 'Q079__V000'
    rejected('主仮説差替拒否', lambda: guard.verify_catalog(altered))
    altered = deepcopy(fixed); altered['supplementary_conditions'][0]['random_seed'] = 1
    rejected('seed重複欠落拒否', lambda: guard.verify_catalog(altered))
    altered = deepcopy(fixed); altered['supplementary_conditions'].pop()
    rejected('全反転不足拒否', lambda: guard.verify_catalog(altered))

    # ----------------------------------------
    # 出来高の素材・公開と気配維持を独立式で検査する。
    rows, features = guard.volume.fixture()
    events, _ = guard.volume.extract(rows, features, '2026-09-21_Day')
    guard.verify_event_frame(events, features); accepted('人工イベント素材と公開境界')
    for name, column, value in [('非隣接差分', 'prev_seq', -1), ('未来出来高', 'current_volume_time_s', 99999999999.),
        ('最良側偽装', 'side', -1), ('数量比偽装', 'volume_to_side_qty', 9.), ('気配維持偽装', 'stable', False),
        ('公開行偽装', 'release_seq', 9999)]:
        altered = events.copy(deep=True); altered.loc[0, column] = value
        rejected(name, lambda item=altered: guard.verify_event_frame(item, features))

    # ----------------------------------------
    # 保存された採用区間から、方向と根拠2列の接続を再展開する。
    inputs, features, events, spec = fixtures.fixture()
    spec['params']['peer_mode'] = 'none'
    output = fixtures.render(inputs, features, events, spec)
    key = '人工_Day', 'NK225'
    row, ready = output[key], inputs[key]
    def verify(value: dict) -> None:
        """機能: 人工信号一入力の全保存根拠を検査する。

        引数: value (dict)。返り値: なし (None)。
        """
        guard.verify_direction(value['direction'], value['source_row'], value['source_episode'],
            value['episodes'], ready, spec['params'])
    verify(row); accepted('保存episodeから方向と根拠を全展開')
    active = int(np.flatnonzero(row['direction'])[0])
    altered = deepcopy(row); altered['source_row'][active] += 1
    rejected('方向の未来根拠拒否', lambda: verify(altered))
    altered = deepcopy(row); altered['source_episode'][active] = 99
    rejected('存在しない準備ID拒否', lambda: verify(altered))
    altered = deepcopy(row); altered['direction'][active] *= -1
    rejected('根拠と逆の方向拒否', lambda: verify(altered))
    altered = deepcopy(row); altered['source_row'][0] = 0
    rejected('中立行の偽根拠拒否', lambda: verify(altered))
    altered = deepcopy(row); altered['episodes'][0]['accepted'] = False
    rejected('方向を残した不採用偽装拒否', lambda: verify(altered))
    altered = deepcopy(row); altered['episodes'][0]['stable_volume_score'] = 100.
    rejected('安定量が全出来高を超える偽装拒否', lambda: verify(altered))
    altered = deepcopy(row); altered['episodes'][0]['signal_expiry_time_s'] += 1.
    rejected('成立期限の延命拒否', lambda: verify(altered))
    altered = deepcopy(row); altered['episodes'][0]['confirmation_seq'] = altered['episodes'][0]['setup_seq']
    rejected('準備と同一行の成立拒否', lambda: verify(altered))
    altered = deepcopy(row); altered['episodes'][0]['confirmation_time_s'] = altered['episodes'][0]['expiry_time_s']
    rejected('期限到達と同時の成立拒否', lambda: verify(altered))
    value = dict(全検査合格=True, 検査数=len(results), 検査=results,
        採否条件変更=False, 新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False,
        ガード実装SHA256=guard.volume.digest(guard.HERE / 'run_verified.py'))
    guard.runner.save(guard.HERE / 'run_verified_test.json', value)
    print('起動ガード人工', len(results), '件合格。', flush=True)


if __name__ == '__main__':
    main()
