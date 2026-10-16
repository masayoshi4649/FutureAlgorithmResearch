"""広trail、長い保有、候補消費、未来変更を現104sourceの別人工証跡へ結ぶ。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

import artificial
import interface


HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 初回人工とは別に、広trailの実発動と時間非依存・再参加の境界を確認する。
    引数: なし。
    返り値: None。現source不変更、正式金融/原本/API0。
    """
    target = HERE / '広追尾と長い保有及び未来不変の追加人工.json'
    assert not target.exists()
    refs = [Path(__file__), HERE / 'artificial.py', HERE / 'core.py', HERE / 'interface.py']
    beginning = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    checks = dict(広trail発動及び次quote返済=0, 120秒超保有の固定支持維持=0, 保有中候補消費=0,
                  返済後30秒境界=0, 未来変更の過去物理及び全時価不変=0)
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            p, c = artificial.fixture(symbol, side)
            entry = p['record']['ask'][331] if side == 1 else p['record']['bid'][331]
            tick, width = p['record']['tick'], p['signal']['trend_width']
            artificial.quote_from(p, 340, entry + side * (width + 2. * tick), side)
            artificial.quote_from(p, 344, entry + side * 2. * tick, side)
            output = artificial.run(p, c, 'B2')
            assert output['orders'][1, 1] == 344 and output['orders'][1, 0] == 345 and output['orders'][1, 8] == 3
            assert int(output['judgments'][output['judgments'][:, 0] == 340][0, 18]) & 4
            checks['広trail発動及び次quote返済'] += 1
            p, c = artificial.fixture(symbol, side)
            c['event'][600] = -side
            c['support_price'][600] = c['support_price'][330] + side * 20. * tick
            artificial.refresh(c, p['record'])
            output = artificial.run(p, c, 'B2')
            assert output['orders'][1, 0] == 1140 and np.all(output['judgments'][:, 8] == c['support_price'][330])
            checks['120秒超保有の固定支持維持'] += 1
            assert len(output['orders']) == 2 and np.any((output['candidate_diagnostics'][:, 0] == 600) & (output['candidate_diagnostics'][:, 8] == 0))
            checks['保有中候補消費'] += 1
            p, c = artificial.fixture(symbol, side)
            artificial.quote_from(p, 335, c['support_price'][330] - side * 2. * tick, side)
            for row in (350, 366):
                c['event'][row] = side
                c['support_price'][row] = c['support_price'][330] - side * 4. * tick
            artificial.refresh(c, p['record'])
            output = artificial.run(p, c, 'B2')
            entries = output['orders'][output['orders'][:, 7] == 1]
            assert np.array_equal(entries[:, 1], [330., 366.]) and np.array_equal(entries[:, 0], [331., 367.])
            checks['返済後30秒境界'] += 1
            p, c = artificial.fixture(symbol, side)
            original = artificial.run(p, c, 'T2')
            altered_p, altered_c = deepcopy(p), deepcopy(c)
            artificial.quote_from(altered_p, 500, c['support_price'][330] - side * 8. * tick, side)
            altered_c['entry_quality'][500:550] = False
            altered_c['entry_reset'][500:550] = True
            altered_p['record']['quote_valid'][500:505] = False
            changed = artificial.run(altered_p, altered_c, 'T2')
            length = 400
            for name in ('curve', 'source_curve', 'target_trace', 'stale_equity'):
                np.testing.assert_array_equal(original[name][:length], changed[name][:length])
            for name in ('orders', 'events', 'judgments', 'candidate_diagnostics'):
                np.testing.assert_array_equal(original[name][original[name][:, 0] < length], changed[name][changed[name][:, 0] < length])
            assert original['raw_entry_diagnostics'] == changed['raw_entry_diagnostics']
            checks['未来変更の過去物理及び全時価不変'] += 1
    ending = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    assert beginning == ending
    proof = dict(全合格=True, 人工専用=True, 検査件数=checks, 開始終端source一致=True, 開始SHA256=beginning, SHA256=ending,
        初回人工の確認範囲補足='初回の量/期限支持不交換確認は短い予約悪化例だった。120秒超の保有及び保有中別支持候補をこの別証跡で明示検査。',
        新104正式金融=0, 原本読取=0, API取得=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=checks, 証跡SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
