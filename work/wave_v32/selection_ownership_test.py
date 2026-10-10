"""独立所有監査が意図した破損を拒否するかを合成相場だけで確認する。"""

from copy import deepcopy
import hashlib
from pathlib import Path

import numpy as np

import episode_audit as audit
import engine_selector_audit as fixtures


def main() -> None:
    """機能: 正常な取消付き経路と改変した所有・取消・源・集計を検査する。

    引数: なし。返り値: なし (None)。実相場の新しい方式や損益は試さない。
    """
    audit.deny_network()
    ready, states, requests, config = fixtures.fixture([100., 100., 103., 104., 114., 100.], [1, 2, 2, 2, 1, 1])
    result = audit.engine.run(ready, states, requests, config, True)
    specification = dict(source_override=0)
    owners, sources, checked = audit.owner_audit(ready, states, requests, result, specification)
    assert checked['取消要求確認数'] == 1 and checked['所有検査新規数'] == 1
    selection, _ = audit.summarize(ready, result, owners, sources, config['point_value'])
    audit.equal(selection, audit.runner.selection_summary(result, ready, config['point_value']))
    mutations = []
    value = deepcopy(result)
    held = int(np.flatnonzero(owners)[0])
    value['selection_curve'][held, audit.S['position_owner_id']] = 1
    mutations.append(('保有所有者の改変', value))
    value = deepcopy(result)
    value['selection_curve'][held, audit.S['position_entry_source_id']] = 1
    mutations.append(('実入口源の改変', value))
    value = deepcopy(result)
    value['selection_curve'][1, audit.S['pending_level']] += 1
    mutations.append(('取消待ちで旧注文価格を変更', value))
    value = deepcopy(result)
    row = np.flatnonzero(value['selection_events'][:, audit.E['event']] == 3)[0]
    value['selection_events'][row, audit.E['row']] += 1
    mutations.append(('取消確認を翌々行へ変更', value))
    value = deepcopy(result)
    value['selection_curve'][0, audit.S['request_id']] = 2
    mutations.append(('要求列の改変', value))
    checks = []
    for name, value in mutations:
        try:
            audit.owner_audit(ready, states, requests, value, specification)
        except AssertionError:
            checks.append({'破損': name, '拒否': True})
        else:
            raise AssertionError(name + 'を見逃した')
    modified = deepcopy(selection)
    modified['branch_net_yen']['R'] += 1000
    try:
        audit.equal(modified, selection)
    except AssertionError:
        checks.append({'破損': '枝別収支の改変', '拒否': True})
    else:
        raise AssertionError('枝別収支の改変を見逃した')
    audit.runner.save(Path(__file__).with_suffix('.json'), {'全合格': True, '正常経路一致': True, '破損拒否件数': len(checks),
        '検査': checks, 'API取得数': 0, '実相場再生': False,
        '監査実装SHA256': hashlib.sha256((audit.HERE / 'episode_audit.py').read_bytes()).hexdigest()})
    print('正常経路と6破損拒否を合成で確認。')


if __name__ == '__main__':
    main()
