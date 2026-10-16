"""実接頭helperの切断・未来改変接口を、読取入力なしの人工だけで検査する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import prefix_preflight as preflight
import state_artificial as artificial
import states


HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 接頭helper自体の6未来変更と境界選定をC/R人工で確認する。
    引数: なし。
    返り値: None。実入力loader、金融、APIを呼ばず人工専用証跡を保存する。
    """
    target = HERE / '実接頭helperの人工接口検査.json'
    assert not target.exists()
    refs = [Path(__file__), HERE / 'prefix_preflight.py', HERE / 'states.py', HERE / 'state_artificial.py']
    beginning = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    counts = dict(思想=0, 境界=0, 切断局所=0, 切断pair=0, 未来局所=0, 未来pair=0)
    for family in ('C', 'R'):
        rows = artificial.basic_rows(family)
        rows += [dict(rows[-1], delta=0.) for _ in range(4)]
        own, peer = artificial.raw_fixture(rows), artificial.raw_fixture(rows)
        peer['price_time_s'] -= .1
        peer['volume_time_s'] -= .1
        config, item = artificial.config(family), dict(tick=1., start=0.)
        full_own, full_peer = states.run(own, item, config), states.run(peer, item, config)
        full = states.pulses(full_own, full_peer, own, peer)
        cuts, scope = preflight.cut_points(full_own, full, own, item)
        assert all(value['成立'] for value in scope.values())
        counts['思想'] += 1
        for cutoff in cuts:
            length = cutoff['length']
            public = states.publication(peer)
            before = public['rows'][public['times'] < own['price_time_s'][length - 1]]
            peer_length = int(before[-1]) + 1
            short_own, short_peer = preflight.prefix(own, length), preflight.prefix(peer, peer_length)
            past_own, past_peer = states.run(short_own, item, config), states.run(short_peer, item, config)
            preflight.assert_state(full_own, past_own, length)
            preflight.assert_pulse(full, states.pulses(past_own, past_peer, short_own, short_peer), length)
            counts['境界'] += 1
            counts['切断局所'] += 1
            counts['切断pair'] += 1
            for kind in range(6):
                future_own, future_peer = preflight.mutate(own, length, kind), preflight.mutate(peer, peer_length, kind)
                changed_own, changed_peer = states.run(future_own, item, config), states.run(future_peer, item, config)
                preflight.assert_state(full_own, changed_own, length)
                preflight.assert_pulse(full, states.pulses(changed_own, changed_peer, future_own, future_peer), length)
                counts['未来局所'] += 1
                counts['未来pair'] += 1
    ending = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    assert beginning == ending
    proof = dict(全合格=True, 人工専用=True, 検査件数=counts, 開始終端source一致=True,
                 開始SHA256=beginning, SHA256=ending, 入力loader呼出=0, 正式金融再生=0, API取得=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=counts, 証跡SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
