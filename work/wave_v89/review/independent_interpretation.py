"""完成済み81条件を変更せず、源別親会計と取り逃した回復利益を独立再検算する。"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SOURCES = ('GU', 'M3', 'C03')
SYMBOLS = ('TOPIX', 'NK225')
PROFILE_IDS = {'0622':'A0622', '0820':'A0820', 'HALF':'GU_HALF'}


def sha(path):
    """
    機能: 成果と旧基準を変更せず内容指紋を取得する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    """
    機能: 保存済みの日本語JSONを読み取る。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def clean(value):
    """
    機能: NumPyの値を同じ値のJSON標準型へ揃える。
    引数: value(object)。
    返り値: object。
    """
    if isinstance(value, dict):
        return {key:clean(item) for key,item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def load_ledger(path, expected):
    """
    機能: 指紋が一致する保存済み台帳だけを読み取る。
    引数: path(Path)、expected(str)。
    返り値: dict。
    """
    assert sha(path) == expected, str(path)
    with path.open('rb') as stream:
        return pickle.load(stream)


def iso(value):
    """
    機能: 保存代理時計を日本時間の表示へ変換する。
    引数: value(float)。
    返り値: str。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo('Asia/Tokyo')).isoformat()


def money_account(ledger, symbol):
    """
    機能: 実注文だけから親利益損失、料金、残枚数と片方向上限を再計算する。
    引数: ledger(dict)、symbol(str)。
    返り値: tuple[dict,dict]の場会計と親会計。取引エンジンを呼ばない。
    """
    value, fee10, cap = (1000,418,10) if symbol == 'TOPIX' else (10,110,20)
    parents, entries, remaining = {}, {}, {}
    position = np.zeros(3, dtype=np.int64)
    long_max = short_max = 0
    fees, new_lots, close_lots = 0, 0, 0
    for index, order in enumerate(ledger['orders']):
        row, decision, source, cid, side, qty, price, reason, new, uid = order
        row, decision, source, cid, side, qty, reason, new, uid = map(int, (row,decision,source,cid,side,qty,reason,new,uid))
        assert qty > 0 and side in (-1,1) and (decision < row or reason == 99)
        fee = qty * fee10 // 10
        assert fee == ledger['fees'][index]
        fees += fee
        key = SOURCES[source], cid
        parent = parents.setdefault(key, dict(net=0.,gross=0.,fees=0,initial_qty=0,entry_row=None,exit_row=None))
        parent['fees'] += fee
        position[source] += side * qty
        long_max = max(long_max, int(np.maximum(position, 0).sum()))
        short_max = max(short_max, int(np.maximum(-position, 0).sum()))
        assert long_max <= cap and short_max <= cap
        if new:
            assert uid not in entries
            entries[uid] = key, side, qty, price
            remaining[uid] = qty
            new_lots += qty
            parent.update(initial_qty=qty, entry_row=row)
        else:
            pk, ps, pq, pp = entries[uid]
            assert pk == key and side == -ps and qty <= remaining[uid]
            remaining[uid] -= qty
            close_lots += qty
            parent['gross'] += ps * qty * (price - pp) * value
            parent['exit_row'] = row
    assert not position.any() and all(qty == 0 for qty in remaining.values())
    assert new_lots == close_lots
    saved = {(p['source'],p['cid']):p for p in ledger['parents']}
    assert set(saved) == set(parents)
    for key, parent in parents.items():
        parent['net'] = parent['gross'] - parent['fees']
        for field in parent:
            assert abs(parent[field] - saved[key][field]) < 1e-7
    nets = [p['net'] for p in parents.values()]
    profit = sum(max(net,0.) for net in nets)
    loss = sum(max(-net,0.) for net in nets)
    row = dict(net=profit-loss,profit=profit,loss=loss,fees=fees,campaigns=len(parents),
               wins=sum(net>0 for net in nets),losses=sum(net<0 for net in nets),
               new_lots=new_lots,closed_lots=close_lots,max_long=long_max,max_short=short_max)
    return row, parents


# ----------------------------------------


def case(key, parent, gate, ledger, gates, baselines):
    """
    機能: 拒否された元利益親と当時窓、確定後の次回採否を具体的にまとめる。
    引数: key(tuple)、parent/gate(dict)、ledger(dict)、gates(list)、baselines(dict)。
    返り値: dict。未来の元利益は診断専用で新規採否に渡さない。
    """
    completion = next(c for c in ledger[key]['completion_records']
                      if (c['source'],c['cid']) == (parent['source'],parent['cid']))
    selected = gate['selected']
    following = [(k,g) for k,g in gates if k[1] == key[1] and g['source'] == parent['source']
                 and g['time'] > completion['publish_time']]
    next_proof = []
    for k,g in following[:3]:
        base = next(p for p in baselines[k]['parents'] if (p['source'],p['cid']) == (g['source'],g['cid']))
        next_proof.append(dict(session=k[0],clock=iso(g['time']),cid=g['cid'],past_share=g['profit_share'],
                               accepted=g['allowed'],base_net=base['net']))
    last = selected[-1] if selected else None
    return dict(session=key[0],symbol=key[1],source=parent['source'],cid=parent['cid'],
        direction='買い' if gate['side'] == 1 else '売り',decision=iso(gate['time']),decision_row=gate['row'],
        base_net=parent['net'],base_gross=parent['gross'],fees=parent['fees'],quantity=parent['initial_qty'],
        base_entry_row=parent['entry_row'],base_exit_row=parent['exit_row'],
        accepted=gate['allowed'],reason=gate['reason'],past_share=gate['profit_share'],
        past_profit=gate['profit'],past_loss=gate['loss'],past_loss_streak=gate['loss_streak'],
        history_count=gate['available'],window_count=len(selected),history=selected,
        previous_completed_net=last['net'] if last else None,
        first_win_after_past_losses=last is not None and last['net'] < 0 and parent['net'] > 0,
        completed_clock=iso(completion['publish_time']),following=next_proof,
        注='元の親利益と後続親利益は事後診断。新規判断が当時参照したのはhistory内の厳密に古い完了だけ。')


def main():
    """
    機能: 全81完成成果の独立会計、選定と反例を今回review内へ保存する。
    引数: なし。
    返り値: None。新条件又は新P/Lを作らず、凍結成果と既存分析を上書きしない。
    """
    comparison_path = WORK/'analysis/比較結果.json'
    analysis = read(comparison_path)
    reviewed_analysis_sha = sha(comparison_path)
    assert analysis['conditions'] == 81 and len(analysis['results']) == 81
    results = analysis['results']
    fixed = read(WORK/'事前固定.json')
    fixed_sha = sha(WORK/'事前固定.json')
    assert len(fixed['catalog']) == 81
    for name, expected in fixed['code_SHA256'].items():
        assert sha(ROOT/name) == expected, name
    refs = {}
    reference_results = {}
    hashes = {str(comparison_path.relative_to(ROOT)):reviewed_analysis_sha,
              str((WORK/'事前固定.json').relative_to(ROOT)):fixed_sha,
              str(Path(__file__).relative_to(ROOT)):sha(Path(__file__))}
    for profile, identifier in PROFILE_IDS.items():
        path = ROOT/'work/wave_v88/results'/(identifier+'.json')
        old = read(path)
        ledger_path = ROOT/'work/wave_v88/ledgers'/(identifier+'.pkl')
        refs[profile] = load_ledger(ledger_path, old['ledger_SHA256'])
        reference_results[profile] = old
        hashes[str(path.relative_to(ROOT))] = sha(path)
        hashes[str(ledger_path.relative_to(ROOT))] = old['ledger_SHA256']
    proofs = []
    primary_ledger = None
    all_parent_count = all_order_count = all_gate_count = 0
    for identifier, result in results.items():
        path = WORK/'results'/(identifier+'.json')
        assert sha(path) == analysis['結果SHA256'][identifier]
        assert read(path) == result
        ledger_path = WORK/'ledgers'/(identifier+'.pkl')
        ledgers = load_ledger(ledger_path, result['ledger_SHA256'])
        hashes[str(path.relative_to(ROOT))] = sha(path)
        hashes[str(ledger_path.relative_to(ROOT))] = result['ledger_SHA256']
        baseline = refs[result['config']['profile_id']]
        rows = {(r['session'],r['symbol']):r for r in result['rows']}
        independent = {}
        recovered = defaultdict(lambda: dict(saved=0.,missed=0.,delta=0.))
        for key, ledger in ledgers.items():
            row, parents = money_account(ledger,key[1])
            independent[key] = row
            for field in row:
                assert abs(row[field] - rows[key][field]) < 1e-7
            base = {(p['source'],p['cid']):p for p in baseline[key]['parents']}
            gate_map = {(g['source'],g['cid']):g for g in ledger['gate_trace'] if g['allocated_quantity']}
            assert set(parents) <= set(base)
            for pk, bp in base.items():
                gate = gate_map[pk]
                assert gate['allowed'] == (pk in parents)
                selected = gate['selected']
                assert all(p['source'] == pk[0] and p['symbol'] == key[1]
                           and p['publish_time'] < gate['time'] for p in selected)
                profit = sum(max(p['net'],0.) for p in selected)
                loss = sum(max(-p['net'],0.) for p in selected)
                assert profit == gate['profit'] and loss == gate['loss']
                if gate['mode'] == 'share' and not gate['warmup'] and profit+loss:
                    normal = 100*profit >= round(gate['threshold']*100)*(profit+loss)
                    assert gate['allowed'] == (not normal if gate['reverse'] else normal)
                if pk in parents:
                    for field in parents[pk]:
                        assert abs(parents[pk][field]-bp[field]) < 1e-7
                    source_index = SOURCES.index(pk[0])
                    actual = ledger['orders'][(ledger['orders'][:,2]==source_index)&(ledger['orders'][:,3]==pk[1])]
                    original = baseline[key]['orders'][(baseline[key]['orders'][:,2]==source_index)&(baseline[key]['orders'][:,3]==pk[1])]
                    np.testing.assert_array_equal(actual[:,:9],original[:,:9])
                else:
                    recovered[key[1]]['saved'] += max(-bp['net'],0.)
                    recovered[key[1]]['missed'] += max(bp['net'],0.)
            all_parent_count += len(parents)
            all_order_count += len(ledger['orders'])
            all_gate_count += len(gate_map)
        for symbol in SYMBOLS:
            pool = [r for key,r in independent.items() if key[1] == symbol]
            total = result['periods']['全30'][symbol]
            for field in ('net','profit','loss','fees','campaigns','wins','losses','new_lots','closed_lots'):
                assert abs(sum(row[field] for row in pool)-total[field]) < 1e-7
            assert sum(row['net']>0 for row in pool) == total['positive_sessions']
            assert sum(row['campaigns']==0 for row in pool) == total['no_trade_sessions']
            change = total['net'] - reference_results[result['config']['profile_id']]['periods']['全30'][symbol]['net']
            assert abs(change-recovered[symbol]['saved']+recovered[symbol]['missed']) < 1e-7
            recovered[symbol]['delta'] = change
            original = analysis['differences'][identifier]['全30'][symbol]
            for lhs,rhs in (('saved','saved_loss'),('missed','missed_profit'),('delta','delta')):
                assert abs(recovered[symbol][lhs]-original[rhs]) < 1e-7
        proofs.append(dict(id=identifier,口座数=len(ledgers),親会計利益損失と費用一致=True,
                           採用親の全注文元基準一致=True,source商品分離=True,全収支差=recovered))
        if identifier == analysis['primary']:
            primary_ledger = ledgers
    assert len(proofs) == 81 and all(p['口座数']==60 for p in proofs)
    selected = []
    for identifier, result in results.items():
        stats = result['periods']['前16']
        if all(stats[s]['net']>0 and stats[s]['campaigns']>=20 and stats[s]['max_drawdown']>0 for s in SYMBOLS):
            score = min(stats[s]['net']/stats[s]['max_drawdown'] for s in SYMBOLS)
            tie = min(stats[s]['worst_session']/stats[s]['max_drawdown'] for s in SYMBOLS)
            selected.append((score,tie,identifier))
    selected.sort(key=lambda p:(-p[0],-p[1],p[2]))
    assert selected[0][2] == analysis['selected'] == 'B0622_ALL'
    assert not analysis['both80'] and not analysis['raw_both80'] and not analysis['strict_both_improvements']
    gates = sorted([(key,g) for key,l in primary_ledger.items() for g in l['gate_trace'] if g['allocated_quantity']],
                   key=lambda item:(item[1]['time'],item[1]['row']))
    baseline = refs['0622']
    missed = {symbol:[] for symbol in SYMBOLS}
    for key,l in baseline.items():
        gs = {(g['source'],g['cid']):g for k,g in gates if k == key}
        for parent in l['parents']:
            g = gs[parent['source'],parent['cid']]
            if not g['allowed'] and parent['net']>0:
                missed[key[1]].append((key,parent,g))
    largest = {symbol:[case(key,parent,gate,primary_ledger,gates,baseline)
                       for key,parent,gate in sorted(missed[symbol],key=lambda p:-p[1]['net'])[:5]]
               for symbol in SYMBOLS}
    chosen = []
    for key, cid in ((('2026-09-28_Day','TOPIX'),1),(('2026-09-28_Day','NK225'),1),
                     (('2026-10-01_Day','NK225'),1)):
        parent = next(p for p in baseline[key]['parents'] if (p['source'],p['cid']) == ('GU',cid))
        gate = next(g for k,g in gates if k == key and (g['source'],g['cid']) == ('GU',cid))
        evidence = case(key,parent,gate,primary_ledger,gates,baseline)
        assert evidence['first_win_after_past_losses'] and not evidence['accepted']
        chosen.append(evidence)
    assert chosen[0]['following'][0]['accepted'] and chosen[1]['following'][0]['accepted']
    assert all(e['past_share'] < .6 and e['following'][0]['past_share'] >= .6 for e in chosen[:2])
    ranking = sorted([(min(r['periods']['全30'][s]['profit_share'] or 0 for s in SYMBOLS),identifier)
                      for identifier,r in results.items()], key=lambda p:(-p[0],p[1]))
    assert ranking[0][1] == 'BHALF_C16_P80'
    full20 = [item for item in ranking if all(results[item[1]]['periods']['全30'][s]['campaigns']>=20 for s in SYMBOLS)]
    assert full20[0][1] == 'B0820_C08_P80'
    output = dict(
        全合格=True, 対象='v89完成済み81条件の独立解釈と源親実会計',
        実行範囲='既存の実注文と固定結果を再検算した。新条件、新戦略P/L、売買エンジンの再運転は0。全原板時価の再生監査はaudit/full.pyの別担当に依存する。',
        全期間既知=True, 主=analysis['primary'],前16の独立選定=selected[0][2],
        会計再検算=dict(条件数=81,口座数=4860,実注文数=all_order_count,実親数=all_parent_count,
                        有配分ゲート数=all_gate_count,各条件=proofs),
        主の差額=analysis['differences'][analysis['primary']],
        主の源別利益損失=analysis['source_contributions'][analysis['primary']],
        拒否した利益上位5=largest, 回復の最初の利益を拒否した具体3件=chosen,
        候補限界=dict(全81最大の最低商品金額利益割合=ranking[0],
            各商品20実親以上で最大=full20[0],
            HALF80='BHALF_C16_P80は全30の実親7/9、無取引27/25場。後14は両商品とも実親0・無取引14場で、全日安定の根拠にならない。',
            配分80='B0820_C08_P80は全30利益割合64.83%/65.50%。無取引17/18場、後14は4/2親のみで、NKは全2親が負け・収支-6176円。',
            両商品80=analysis['both80'],両商品四指標改善=analysis['strict_both_improvements']),
        結論=[
            '過去の好調だけを参加条件にする主は、回避した損失より取り逃した利益が大きく、全30収支は両商品とも停止なしより悪化した。NKの後14は-73440円。',
            '9/28デイは直前の負けでGUを止め、TOPIX+142000円・NK+60336円を逃した。その紙上利益が完了履歴へ入った後のナイトから参加を再開しており、回復の最初の利益を休んでしまう反例が両商品で成立する。',
            '81条件に両商品80%又は両商品の収支・利益割合・黒字場数・最大下落を同時改善するものはなく、前16の固定選定も停止なしを選んだ。過去好調の持続を単独の参加根拠にする有用性は確認できない。',
        ],
        隠れた損失を防ぐ保証='各源親の料金後netの正負で利益と損失を個別計上し、異なる源の損失を先に同日相殺して利益割合にしていない。全注文ごとの料金と片方向上限、場末残0を本レビューでも再計算した。最大下落は源別親損益の和とは別の原板時価監査に依存する。',
        成果SHA256=hashes,
    )
    assert sha(WORK/'事前固定.json') == fixed_sha
    current = read(comparison_path)
    assert current['results'] == analysis['results'] and current['differences'] == analysis['differences']
    target = HERE/'独立解釈と全親会計再検算及び逃した回復利益.json'
    target.write_text(json.dumps(clean(output),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('全81条件・4860口座の実親会計を独立照合しました。回復の最初の利益の拒否3件を保存しました。',flush=True)


if __name__ == '__main__':
    main()
