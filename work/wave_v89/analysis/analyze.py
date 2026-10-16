"""停止再開の損失削減と利益喪失を、元親との対応で分解する。"""

from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0,str(WORK))
import research


def ledger(identifier, result):
    """
    機能: 指紋一致した会計台帳を読む。
    引数: identifier(str)、result(dict)。
    返り値: dict。
    """
    path = WORK/'ledgers'/f'{identifier}.pkl'
    assert research.sha(path)==result['ledger_SHA256']
    with path.open('rb') as stream:
        return pickle.load(stream)


def select(results):
    """
    機能: 事前固定の前16場指標だけで参考条件を選ぶ。
    引数: results(dict)。
    返り値: tuple[str又はNone,list[dict]]。
    """
    proof = []
    for identifier,result in results.items():
        stats = result['periods']['前16']
        eligible = all(stats[s]['net']>0 and stats[s]['campaigns']>=20 and stats[s]['max_drawdown']>0 for s in ('TOPIX','NK225'))
        proof.append(dict(id=identifier,eligible=eligible,
            score=min(stats[s]['return_drawdown'] for s in ('TOPIX','NK225')) if eligible else None,
            tie_score=min(stats[s]['worst_session']/stats[s]['max_drawdown'] for s in ('TOPIX','NK225')) if eligible else None))
    ordered = sorted([p for p in proof if p['eligible']],key=lambda p:(-p['score'],-p['tie_score'],p['id']))
    return (ordered[0]['id'] if ordered else None),proof


def decompose(result, actual, baseline, fixed):
    """
    機能: 元親の採用・拒否を対応させ、収支差と源別利益損失を期間別に照合する。
    引数: result/actual/baseline/fixed(dict)。
    返り値: tuple[dict,dict,dict]。全差分・源別差分・実源別利益損失。
    """
    pairs = []
    for key in sorted(actual):
        chosen = {(p['source'],p['cid']):p for p in actual[key]['parents']}
        base = {(p['source'],p['cid']):p for p in baseline[key]['parents']}
        assert set(chosen)<=set(base)
        gates = {(g['source'],g['cid']):g for g in actual[key]['gate_trace'] if g['allocated_quantity']>0}
        for parent_key,parent in base.items():
            accepted = parent_key in chosen
            assert parent_key in gates and bool(gates[parent_key]['allowed'])==accepted
            if accepted:
                for field in ('net','fees','gross'):
                    assert abs(chosen[parent_key][field]-parent[field])<1e-7
            pairs.append(dict(session=key[0],symbol=key[1],source=parent_key[0],cid=parent_key[1],
                base_net=parent['net'],actual_net=chosen[parent_key]['net'] if accepted else 0.,accepted=accepted,
                warmed=not gates[parent_key]['warmup'],bootstrap=gates[parent_key]['warmup'] or gates[parent_key]['profit_share'] is None,
                past_share=gates[parent_key]['profit_share']))
    differences,source_differences,parts = {},{},{}
    for period in ('前16','後14','全30'):
        differences[period],source_differences[period],parts[period] = {},{},{}
        for symbol in ('TOPIX','NK225'):
            selected = [p for p in pairs if p['session'] in fixed[period] and p['symbol']==symbol]
            source_differences[period][symbol],parts[period][symbol] = {},{}
            for source in (None,'GU','M3','C03'):
                pool = [p for p in selected if source is None or p['source']==source]
                saved = -sum(p['base_net'] for p in pool if not p['accepted'] and p['base_net']<0)
                missed = sum(p['base_net'] for p in pool if not p['accepted'] and p['base_net']>0)
                base_net,actual_net = sum(p['base_net'] for p in pool),sum(p['actual_net'] for p in pool)
                assert abs(actual_net-base_net-saved+missed)<1e-7
                value = dict(base_net=base_net,actual_net=actual_net,saved_loss=saved,missed_profit=missed,delta=actual_net-base_net,
                    accepted=sum(p['accepted'] for p in pool),rejected=sum(not p['accepted'] for p in pool),cancelled=0)
                if source is None:
                    differences[period][symbol] = value
                    assert abs(actual_net-result['periods'][period][symbol]['net'])<1e-7
                else:
                    source_differences[period][symbol][source] = value
                    profit = sum(p['actual_net'] for p in pool if p['actual_net']>0)
                    loss = -sum(p['actual_net'] for p in pool if p['actual_net']<0)
                    parts[period][symbol][source] = dict(net=profit-loss,profit=profit,loss=loss,
                        campaigns=sum(p['accepted'] for p in pool),profit_share=profit/(profit+loss) if profit+loss else None)
    return differences,source_differences,parts


def complement(results, ledgers, refs):
    """
    機能: 通常60%と逆60%の集合・会計が基準と共通準備親に分解できるか確認する。
    引数: results/ledgers/refs(dict)。
    返り値: list[dict]。未来結果は診断専用。
    """
    proof = []
    for profile in research.catalog.PROFILES:
        base = refs[profile][1]
        for scope in ('S','C'):
            for window in (8,16):
                normal = ledgers[f'B{profile}_{scope}{window:02d}_P60']
                inverse = ledgers[f'B{profile}_{scope}{window:02d}_R60']
                for key in base:
                    b = {(p['source'],p['cid']):p for p in base[key]['parents']}
                    n = {(p['source'],p['cid']):p for p in normal[key]['parents']}
                    r = {(p['source'],p['cid']):p for p in inverse[key]['parents']}
                    assert (set(n)|set(r))==set(b)
                    overlap = set(n)&set(r)
                    gates = {(g['source'],g['cid']):g for g in normal[key]['gate_trace']}
                    expected = {pk for pk in b if gates[pk]['warmup'] or gates[pk]['profit_share'] is None}
                    assert overlap==expected
                    for field in ('net','fees','gross'):
                        assert abs(sum(p[field] for p in n.values())+sum(p[field] for p in r.values())-
                                   sum(p[field] for p in b.values())-sum(b[pk][field] for pk in overlap))<1e-6
                    proof.append(dict(profile=profile,scope=scope,window=window,session=key[0],symbol=key[1],
                                      bootstrap=len(overlap),親和会計一致=True))
    return proof


def main():
    """
    機能: 固定81条件を評価し、金額80%と期間安定性・採用効果を確認する。
    引数: なし。
    返り値: None。
    """
    fixed = research.read(research.FIXED)
    research.validate(fixed)
    results = {c['id']:research.read(WORK/'results'/f'{c["id"]}.json') for c in fixed['catalog']}
    assert len(results)==81
    ledgers = {identifier:ledger(identifier,result) for identifier,result in results.items()}
    refs = research.references()
    selected,selection_proof = select(results)
    differences,source_differences,source_contributions = {},{},{}
    improvements = []
    for identifier,result in results.items():
        d,ds,p = decompose(result,ledgers[identifier],refs[result['config']['profile_id']][1],fixed)
        differences[identifier],source_differences[identifier],source_contributions[identifier] = d,ds,p
        baseline = refs[result['config']['profile_id']][0]
        deltas = []
        for symbol in ('TOPIX','NK225'):
            a,b = result['periods']['全30'][symbol],baseline['periods']['全30'][symbol]
            deltas.extend([a['net']-b['net'],(a['profit_share'] or 0)-(b['profit_share'] or 0),
                           a['positive_sessions']-b['positive_sessions'],b['max_drawdown']-a['max_drawdown']])
        if min(deltas)>=-1e-7 and max(deltas)>1e-7:
            improvements.append(identifier)
    raw80 = [i for i,r in results.items() if all(r['periods']['全30'][s]['profit_share'] is not None and
                  r['periods']['全30'][s]['profit_share']>=.8 for s in ('TOPIX','NK225'))]
    targets = [i for i in raw80 if all(results[i]['periods']['全30'][s]['campaigns']>=20 for s in ('TOPIX','NK225'))]
    stable = [i for i,r in results.items() if all(r['periods'][p][s]['net']>0 for p in ('前16','後14') for s in ('TOPIX','NK225'))]
    conclusion = [
        '過去の仮想成績で停止・再開する81条件を試しましたが、両銘柄の利益80%は未達。前16場の選定も「停止なし」を選びました。',
        '主案は直近16親の利益割合60%以上だけ参加。収支はTOPIX551,608円・日経113,156円で、常時参加より568,237円・129,840円低下。避けた損失より逃した利益が大きく、日経の後14場も−73,440円でした。',
        '負けからの回復を仮想取引で確認した時には、最初の大勝ちは終わっていました。過去成績の回復だけを再開条件にする方式は、今回のデータでは共通の改善策になりませんでした。']
    output = dict(全合格=True,conditions=81,primary=research.catalog.PRIMARY,selected=selected,results=results,
        selection_proof=selection_proof,differences=differences,differences_source=source_differences,
        source_contributions=source_contributions,complement_proof=complement(results,ledgers,refs),
        both80=targets,raw_both80=raw80,both_positive_periods=stable,strict_both_improvements=improvements,
        conclusion=conclusion,全期間既知=True,結果SHA256={i:research.sha(WORK/'results'/f'{i}.json') for i in results})
    research.save(HERE/'比較結果.json',output)
    print(research.clean(dict(主=output['primary'],前半選定=selected,金額八割=targets,両期間黒字=stable,両銘柄四指標改善=improvements)),flush=True)


if __name__=='__main__':
    main()
