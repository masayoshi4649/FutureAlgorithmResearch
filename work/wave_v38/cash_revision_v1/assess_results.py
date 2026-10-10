"""全固定条件を読み、監査未完了の暫定経済判定を保存する。"""

from __future__ import annotations

import adaptive_runner as runner
import adaptive_assessment as assessment


def collect() -> tuple:
    """機能: 主206と補助768の全期間集計・全26明細を集める。

    引数: なし。返り値: index/sessions/固定設計 (tuple[dict,...])。
    """
    fixed = runner.prepare()
    index, sessions = {}, {}
    for destination, specs in (('', fixed['conditions']), ('supplementary', fixed['supplementary_conditions'])):
        done = runner.read(runner.HERE/destination/'主再生の完了.json')
        assert done['全条件数'] == len(specs) and done['全入力数'] == 26*len(specs)
        assert done['探索固定SHA256'] == runner.digest(runner.HERE/'探索条件の固定.json')
        values = runner.read(runner.HERE/destination/'全条件の期間集計.json.gz')
        assert len(values) == len(specs) and {r['id'] for r in values} == {s['id'] for s in specs}
        for value in values:
            identifier = value['id']
            assert identifier not in index
            index[identifier] = value
            sessions[identifier] = runner.read(runner.HERE/destination/'sessions'/(identifier+'.json.gz'))
    return index, sessions, fixed


def main() -> None:
    """機能: 経済条件を集計するが、独立監査完了や採用を宣言しない。

    引数: なし。返り値: なし (None)。
    """
    index, sessions, fixed = collect()
    ledgers = {identifier:runner.read(runner.HERE/'ledgers'/(identifier+'.json.gz')) for identifier in assessment.PAIRED_IDS}
    value = assessment.assess(index, sessions, fixed['全セッション'], ledgers, verification=False)
    runner.save(runner.HERE/'暫定判定.json', value)
    print('全974条件の暫定経済判定を保存。独立監査完了扱いにはしない。', flush=True)


if __name__ == '__main__':
    main()
