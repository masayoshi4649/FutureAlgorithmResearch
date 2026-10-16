"""押し回復と旧J2が重なるかを、新条件を追加せず結果後に独立切り分けする。"""

from collections import Counter
from pathlib import Path

import numpy as np

import 共通独立読取 as R
import 元候補対応と独立会計分解 as P
import 最悪3場の原板と政策休止及び門番の独立反証 as W


def bbo_check(key: tuple, state: dict, policy: str, material: dict) -> dict:
    """
    機能: 幾何成立点の両公開板と各anchorから源更新及び気配進行を独立検算する。
    引数: key(tuple[str,str])、state/material(dict)、policy(str:C0～C3)。
    返り値: dict。anchorの作成過程と政策40全行を独立復元したとは言わない。
    """
    own = material['prices'][key]
    peer_symbol = 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
    peer = material['prices'][key[0], peer_symbol]
    side, row, grid = int(state['side']), int(state['observed_own_index']), int(state['grid_index'])
    other = int(state['observed_peer_index'])
    assert int(own['seq'][row]) == int(state['observed_own_seq'])
    assert float(own['time_s'][row]) == state['observed_own_time']
    assert float(own['bid'][row]) == state['observed_own_bid']
    assert float(own['ask'][row]) == state['observed_own_ask']
    assert other >= 0 and grid >= 0
    assert int(peer['seq'][other]) == int(state['observed_peer_seq'])
    assert float(peer['time_s'][other]) == state['observed_peer_time']
    assert float(peer['bid'][other]) == state['observed_peer_bid']
    assert float(peer['ask'][other]) == state['observed_peer_ask']
    source = material['grids'][key[0]]['markets'][peer_symbol]['current']
    assert other == int(source['index'][grid])
    current_ok = bool(source['valid'][grid] and source.get('q_valid', source['valid'])[grid]
        and 0 < source['bid'][grid] < source['ask'][grid])
    own_ok = bool(0 < own['bid'][row] < own['ask'][row]
        and own['ask'][row] - own['bid'][row] <= 2 * own['tick'] + 1e-9)
    fresh_grid = bool(own['time_s'][row] - material['grids'][key[0]]['grid'][grid] <= 10. + 1e-8)
    finite = all(np.isfinite(state['observed_' + prefix + '_' + name])
        for prefix in ('own', 'peer') for name in ('index', 'seq', 'time', 'bid', 'ask'))
    pair = finite and own_ok and current_ok and fresh_grid and peer['time_s'][other] <= own['time_s'][row] + 1e-8
    assert pair == bool(state['pair_valid'])
    fresh = pair and state['anchor_valid'] != 0
    terms = {}
    for prefix in ('own', 'peer'):
        index = state['observed_' + prefix + '_index'] > state[prefix + '_anchor_index']
        seq = state['observed_' + prefix + '_seq'] > state[prefix + '_anchor_seq']
        stamp = state['observed_' + prefix + '_time']
        anchor = state[prefix + '_anchor_time']
        clock = stamp >= anchor if policy == 'C2' else stamp > anchor and stamp > state['phase_time']
        terms[prefix] = dict(index更新=bool(index), seq更新=bool(seq), 時計条件=bool(clock),
            現在時計=R.clock(stamp), anchor時計=R.clock(anchor) if np.isfinite(anchor) else None)
        fresh &= index and seq and clock
    progress = bool(fresh)
    changes = {}
    for prefix, tick in (('own', float(own['tick'])), ('peer', float(peer['tick']))):
        for quote in ('bid', 'ask'):
            value = side * (state['observed_' + prefix + '_' + quote] - state[prefix + '_anchor_' + quote])
            changes[prefix + '_' + quote] = dict(方向付き進行pt=float(value), 必要tick=tick)
            progress &= value >= tick - tick * 1e-8
    assert bool(fresh) == bool(state['fresh_sources'])
    assert bool(progress) == bool(state['quotes_progress'])
    return dict(両pair有効=bool(pair), 両源更新=bool(fresh), 両気配進行=bool(progress),
        源時計条件=terms, 各気配進行=changes, 独立局所照合=True)


def overlap(ident: str, ledgers: dict, material: dict, wanted: dict) -> dict:
    """
    機能: TOPIX押し回復成立点とJ2の独立条件を重ね、別門番を具体化する。
    引数: ident(str)、ledgers/material/wanted(dict)。
    返り値: dict。件数は保存watch変化点であり全政策状態の独立再生ではない。
    """
    reasons, patterns, candidates, evidence = Counter(), Counter(), set(), {}
    geometric = simultaneous = all_bbo = checked = 0
    for key, ledger in ledgers.items():
        if key[1] != 'TOPIX':
            continue
        columns = {name: i + 1 for i, name in enumerate(ledger['watch_state_columns'])}
        values = ledger['watch_state_changes']
        rows = values[values[:, columns['active']] == 1]
        record = material['prices'][key]
        positions = rows[:, 0].astype(np.int64)
        sides = rows[:, columns['side']]
        quote = np.where(sides == 1, record['ask'][positions], record['bid'][positions])
        ready = ((rows[:, columns['phase']] == 2)
            & (sides * (quote - rows[:, columns['opposite_extreme']])
                >= rows[:, columns['recovery_width']] - record['tick'] * 1e-8))
        assert np.array_equal(ready, rows[:, columns['price_ready']] == 1), ident
        checked += len(rows)
        for row in rows:
            pattern = tuple(int(row[columns[name]]) for name in ('price_ready', 'j2_allowed', 'quotes_progress', 'pair_valid'))
            patterns[pattern] += 1
        for row in rows[ready]:
            state = {name: float(row[position]) for name, position in columns.items()}
            grid, side = int(state['grid_index']), int(state['side'])
            j2 = W.j2_facts(key, grid, side, material)
            assert j2['旧J2許可'] == bool(state['j2_allowed'])
            bbo = bbo_check(key, state, ident.split('_')[0], material)
            geometric += 1
            simultaneous += int(j2['旧J2許可'])
            all_bbo += int(bbo['両気配進行'])
            candidate = int(state['candidate_id'])
            candidates.add((key[0], candidate))
            group = '|'.join(j2['拒否根拠']) or 'J2成立'
            reasons[group] += 1
            if group not in evidence:
                position = int(row[0])
                mapped = R.published_grid(record, material['grids'][key[0]]['grid'])
                evidence[group] = dict(場=key[0], 元候補ID=candidate, 方向=side,
                    回復成立原板=R.point(key, position, material, mapped, wanted),
                    元候補原板=R.point(key, int(state['candidate_row']), material, mapped, wanted),
                    不利極値及び位相基準原板=R.point(key, int(state['phase_row']), material, mapped, wanted),
                    判定幅W=state['width'], 回復必要幅=state['recovery_width'],
                    回復実幅=side * (quote[np.searchsorted(positions, position)] - state['opposite_extreme']),
                    旧J2独立判定=j2, 両板源独立局所照合=bbo,
                    保存watch状態=state, 最終取消消費保存記録=P.exclusion_evidence(ledger, int(state['candidate_row']), side),
                    政策保存経過と源照合=W.policy_evidence(key, ledger, candidate, material, wanted))
    return dict(保存active変化点の価格幾何照合数=checked, 押し回復成立変化点=geometric,
        押し回復成立の異なる候補数=len(candidates), 回復とJ2の同時成立変化点=simultaneous,
        回復と両気配進行の同時成立変化点=all_bbo,
        成立組合せ=[dict(price_ready=k[0], j2_allowed=k[1], quotes_progress=k[2], pair_valid=k[3], 件数=v)
            for k, v in patterns.items()], 回復成立時のJ2拒否根拠変化点件数=dict(reasons), 具体原板=evidence,
        scope='保存watchの位相・極値を所与として全変化点の価格幾何を原価格から検算。回復成立点では旧J2及び両BBOの局所条件を別式で照合。40政策状態の全行生成過程は再現していない。')


def main() -> None:
    """
    機能: 四政策同A7X3の追加原因を既存三レビューを変更せず別資料へ保存する。
    引数: --根許可後(bool)は全31正式完了後に必須。
    返り値: None。新条件、API、仮想受信時計、主差替えは作らない。
    """
    R.permission()
    fixed, assembled = R.validate()
    material, wanted, answer = R.material(), {}, {}
    for policy in ('C0', 'C1', 'C2', 'C3'):
        ident = policy + '_A7_X3'
        answer[ident] = overlap(ident, R.load_ledgers(ident), material, wanted)
    raw = R.attach_raw(wanted)
    original = R.HERE / '主と参考及びC0即時の最悪3場原板と政策休止及び門番の独立反証.json'
    R.save('主TOPIXの押し回復と旧J2が重ならない具体的独立原因.json', dict(
        全合格=True, 主=fixed['主'], 主変更=False, 四政策局所反証=answer, 原本同seq照合=raw,
        既存第三レビューSHA256=R.digest(original), 計算コードSHA256=R.digest(Path(__file__)),
        注意=['押し回復が成立した後は必ず儲かるとは限らない。既に起きた回復は新規前の動き。',
            '門番を外した策略の成績はこの診断から算出できない。活動を増やす改変は未検証。',
            '原本の価格時計差とseq連続から真受信断裂又は共通受信順を証明しない。'], **R.provenance()))


if __name__ == '__main__':
    main()
