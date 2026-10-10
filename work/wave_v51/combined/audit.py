"""組合せ9条件の注文会計・事前選択・新規許可の時間順を独立確認する。"""
from __future__ import annotations

from copy import deepcopy
import gzip
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('組合せ監査対象', HERE.parent / 'combine.py')
target = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = target
_spec.loader.exec_module(target)


def read(path: Path) -> object:
    """機能: JSONを読む。

    引数: path(Path)。返り値: 保存値(object)。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def independent_decisions(candidate: dict, ready: dict, ledger: dict) -> list[dict]:
    """機能: 既に返済した実組の約定損益だけから許可を再計算する。

    引数: candidate/ready/ledger(dict)。返り値: 独立した許可記録(list[dict])。
    """
    total_r, losses, until, previous_end = 0., 0, 0., -1
    rows = []
    for cycle in ledger['cycles']:
        cid = int(cycle[0])
        opening = next(o for o in ledger['orders'] if o[2] == cid and o[7] == 1)
        origin, fill = int(opening[1]), int(opening[0])
        assert previous_end < origin < fill
        at = float(ready['time_s'][origin])
        mode = candidate['risk']
        accepted = not ((mode == 'day2R' and total_r <= -2)
            or (mode == 'loss2stop' and losses >= 2) or (mode == 'loss2pause45' and at < until))
        rows.append(dict(cycle=cid, origin=origin, fill=fill, accepted=accepted, past_r=total_r))
        if accepted:
            pnl = sum(t[2]*t[3]*(t[5]-t[4]) for t in ledger['trades'] if int(t[0]) == cid)
            assert abs(pnl-cycle[3]) < 1e-7
            total_r += pnl/(ledger['config']['initial_qty']*cycle[5])
            losses = losses+1 if pnl < 0 else 0
            if mode == 'loss2pause45' and losses >= 2:
                until = ready['time_s'][int(cycle[2])] + 45*60
                losses = 0
        previous_end = int(cycle[2])
    return rows


def main() -> None:
    """機能: 全414口座の独立会計と許可判断を検査する。

    引数: なし。返り値: なし(None)。
    """
    result, fixed = read(HERE / '結果.json'), read(HERE / '事前固定.json')
    assert [r['spec'] for r in result['候補']] == fixed['候補']
    inputs, _ = target.overlay.load()
    models = {key: target.overlay.bar_model(key) for key in inputs}
    names = sorted({key[0] for key in inputs})
    groups = dict(開発10=names[:10], 検証9=names[10:19], 既知追加4=names[19:], 全23=names)
    assert result['選択対象'] == names[:10]
    ranked = sorted((r for r in result['候補'] if r['eligible']), key=lambda r: (-r['score'], r['spec']['id']))
    assert ranked[0]['spec'] == result['選択']
    assert [r['spec']['id'] for r in ranked] == result['選抜順位']
    counts = dict(会計口座=0, 許可判断=0, 未来損益変更=0, 切断=0, 時価DD=0)
    proofs = []
    for candidate in result['候補']:
        spec = candidate['spec']
        old = {(r['session'], r['symbol']): r for r in read(HERE.parent / 'clock_search/ledgers' / (spec['clock']+'.json.gz'))}
        saved = read(HERE / 'ledgers' / (spec['id']+'.json.gz'))
        summaries = {(r['session'], r['symbol']): r for r in candidate['sessions']}
        assert len(saved) == len(old) == len(summaries) == 46
        curves = {}
        for ledger in saved:
            key = ledger['session'], ledger['symbol']
            ready, source, summary = inputs[key], old[key], summaries[key]
            decisions = independent_decisions(spec, ready, source)
            assert decisions == ledger['decisions']
            kept = {d['cycle'] for d in decisions if d['accepted']}
            assert ledger['orders'] == [o for o in source['orders'] if int(o[2]) in kept]
            assert ledger['trades'] == [t for t in source['trades'] if int(t[0]) in kept]
            trades = np.asarray(ledger['trades'], float).reshape((-1, 11))
            mult = 1000 if key[1] == 'TOPIX' else 10
            pnl = trades[:,2]*trades[:,3]*(trades[:,5]-trades[:,4])*mult
            values = dict(net_yen=float(pnl.sum()), gross_profit_yen=float(pnl[pnl>0].sum()), gross_loss_yen=float(-pnl[pnl<0].sum()),
                profit_units=int(trades[pnl>0,3].sum()), loss_units=int(trades[pnl<0,3].sum()), zero_units=int(trades[pnl==0,3].sum()))
            for field, value in values.items():
                assert abs(value-summary[field]) < 1e-6
            cash, position = np.zeros(len(ready['last'])), np.zeros(len(ready['last']))
            for order in ledger['orders']:
                fill, origin = int(order[0]), int(order[1])
                assert 0 <= origin < fill < len(position)
                assert order[4] == int(order[4]) and order[4] > 0
                cash[fill] -= order[3]*order[4]*order[5]
                position[fill] += order[3]*order[4]
                assert ready['time_s'][fill] < ready.get('session_close', ready['limit']+600)
            position = np.cumsum(position)
            assert position[-1] == 0 and np.abs(position).max() <= source['config']['initial_qty'] <= source['config']['audit_cap']
            curve = (np.cumsum(cash)+position*ready['last'])*mult
            curves[key] = curve
            assert abs(curve[-1]-summary['net_yen']) < 1e-6
            dd = np.max(np.maximum.accumulate(np.r_[0.,curve])[1:]-curve)
            assert abs(dd-summary['drawdown_yen']) < 1e-6
            # ----------------------------------------
            # 前半組に対する許可は、後半組の将来損益を書き替えても変わらない。
            cut = len(source['cycles'])//2
            if cut:
                changed = deepcopy(source)
                for c in changed['cycles'][cut:]:
                    c[3] = -100*c[3]-777
                future = target.overlay.evaluate(spec, ready, changed, models, True)
                assert future['decisions'][:cut] == ledger['decisions'][:cut]
                clipped = deepcopy(source)
                ids = {int(c[0]) for c in source['cycles'][:cut]}
                clipped['cycles'] = clipped['cycles'][:cut]
                for field in ('orders', 'trades'):
                    clipped[field] = [r for r in clipped[field] if int(r[2 if field=='orders' else 0]) in ids]
                prefix = target.overlay.evaluate(spec, ready, clipped, models, True)
                assert prefix['decisions'] == ledger['decisions'][:cut]
                counts['未来損益変更'] += 1
                counts['切断'] += 1
            counts['会計口座'] += 1
            counts['許可判断'] += len(decisions)
        for label, selected in groups.items():
            for symbol in ('TOPIX', 'NK225'):
                previous, high, worst = 0., 0., 0.
                for session in selected:
                    path = curves[session,symbol]+previous
                    high_line = np.maximum.accumulate(np.r_[high,path])[1:]
                    worst = max(worst,float(np.max(high_line-path)))
                    high = max(high,float(path.max()))
                    previous = float(path[-1])
                assert abs(worst-candidate['periods'][label][symbol]['drawdown_yen']) < 1e-6
                counts['時価DD'] += 1
        train = candidate['periods']['開発10']
        assert candidate['eligible'] == all(train[s]['active_sessions']>=7 and train[s]['cycles']>=20 for s in ('TOPIX','NK225'))
        assert candidate['score'] == min(train[s]['r'] for s in ('TOPIX','NK225'))
        proofs.append(dict(id=spec['id'], 独立会計=True, 全組の許可一致=True, 上限内=True, 場内返済=True, 末尾フラット=True, DD一致=True))
    output = dict(全合格=True, 件数=counts, 証跡=proofs, 選択先頭10のみ=True, 利益による組の事後選別なし=True,
        因果範囲='元時計の価格再生はclock_searchの各46口座因果監査を継承。本監査は組合せ許可の独立再計算と後半損益入力改変・組列切断を検査。', API取得数=0)
    (HERE / '独立確認.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
