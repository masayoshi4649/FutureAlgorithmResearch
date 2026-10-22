"""旧終端数量nullと旧完了保証への委譲を、実測なしに分離検査する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import report_fixture_h as F
import report_v6h as R


def main() -> None:
    """
    機能: 前150合成を保持し、終了委譲と中央値の判定だけを追加確認する。
    引数: なし。
    返り値: None。実結果・市場・旧曲線を読まず、小証跡を保存する。
    """
    here = Path(__file__).resolve().parent
    out = here / 'report_fixture_h'
    target = out / '旧終端委譲と直接数量null及び中央値零の純表示補足.json'
    assert not target.exists()
    data = F.fixture()
    basis = dict(verified_flat=True, path='完全合成/旧終了SOURCE確認.json', SHA256='d' * 64)
    g = R.generate(data, out / 'public_v2', 'e' * 64, '完全合成/少額固定設定.json', True, basis)
    public = json.loads((out / 'public_v2/data.json').read_text(encoding='utf8'))
    checks = 0
    for s in R.SYMBOLS:
        m = public['cases'][R.METHOD]['metrics'][s]
        assert m['verified_flat'] and m['unclosed_unknown_sessions'] == 33
        checks += 1
        assert sum(r['unclosed'] is None for r in public['cases'][R.METHOD]['rows'] if r['symbol'] == s) == 33
        checks += 1
    assert public['qualification_count'] == 0 and public['cases'][R.METHOD]['metrics']['TOPIX']['median'] == 0
    checks += 1
    green = deepcopy(data)
    for r in green['rows']:
        r.update(profit=100, loss=0, net=100, campaigns=1, winning_campaigns=1, losing_campaigns=0,
                 winning_lots=1, losing_lots=0, fees=41)
    _, p, _ = R.render(green, 'f' * 64, '完全合成', basis)
    assert p['qualification_count'] == 1
    checks += 1
    _, no_basis, _ = R.render(green, 'f' * 64, '完全合成')
    assert no_basis['qualification_count'] == 0
    checks += 1
    green['rows'][-1]['unclosed'] = 1
    _, pending, _ = R.render(green, 'f' * 64, '完全合成', basis)
    assert pending['qualification_count'] == 0
    checks += 1
    text = (out / 'public_v2' / R.HTML_NAME).read_text(encoding='utf8')
    assert 'verified_flat=True' in text and '今回旧全曲線を再監査した意味ではありません' in text
    checks += 1
    evidence = dict(passed=True, checks=checks, scope='前150合成に対し表示の終了委譲だけ追補。実測を読まない。', generation=g,
        source_SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (here / 'report_v6h.py', Path(__file__))},
        old_fixture=dict(path='report_fixture_h/商品別固定一組と旧引用及び追加七場の純表示検査.json',
                         SHA256=hashlib.sha256((out / '商品別固定一組と旧引用及び追加七場の純表示検査.json').read_bytes()).hexdigest()),
        actual_result_reads=0, market_reads=0, financial_replay=0, API=0)
    target.write_bytes(R.encoded(evidence))
    print(json.dumps(dict(passed=True, checks=checks, SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
                         report_SHA256=evidence['source_SHA256']['report_v6h.py']), ensure_ascii=False))


if __name__ == '__main__':
    main()
