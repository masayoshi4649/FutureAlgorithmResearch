"""前20の固定診断例を原資料の物理行へ接続する。新たな売買は生成しない。"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

from diagnose_early165 import ROOT, OUT, BASE, read, sha, clock


def selected_events(ledger: dict, parents: set[str]) -> list[dict]:
    """機能: 指定親の保存約定を選ぶ。引数: ledger(dict),parents(set[str])。返り値: list[dict]。"""
    return [e for e in ledger['Events'] if e['Order']['Parent'] in parents]


def raw_points(scene: dict, wanted: set[int], intervals: list[tuple[int,int]]) -> dict:
    """機能: 元読取条件で採番し指定原行と価格経路を取得する。引数: scene(dict),wanted(set[int]),intervals(list[tuple])。返り値: dict。"""
    path = Path(scene['books']['NK225'])
    expected = next(x['sha256'] for x in scene['fingerprints'] if x['path'].replace('\\','/') == str(path).replace('\\','/'))
    digest = hashlib.sha256()
    previous = scene['start']
    index = -1
    evidence, paths, normal_indices = {}, [], []
    old_price = None
    with path.open('rb') as stream:
        for line, block in enumerate(stream,1):
            digest.update(block)
            b = json.loads(block)
            if b.get('CurrentPriceTime') is None: continue
            try: at = dt.datetime.fromisoformat(b['CurrentPriceTime'].replace('Z','+00:00')).timestamp()
            except (ValueError,TypeError): continue
            last = b.get('CurrentPrice',0)
            if not isinstance(last,(int,float)) or not math.isfinite(last) or last <= 0: continue
            if at < scene['start'] or at > scene['end'] or (scene['cutoff'] > 0 and at >= scene['cutoff']) or at < previous: continue
            previous = at
            index += 1
            bid, ask = (b.get('Buy1') or {}).get('Price',0), (b.get('Sell1') or {}).get('Price',0)
            normal = isinstance(bid,(int,float)) and isinstance(ask,(int,float)) and math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask
            if normal: normal_indices.append(index)
            point = {'index':index,'line':line,'time':at,'jst':clock(at),'bid':bid,'ask':ask,'last':last,'normal':normal}
            if index in wanted:
                evidence[str(index)] = {**point,'raw':b}
            inside = any(lo<=index<=hi for lo,hi in intervals)
            price = (bid,ask)
            if inside and (price != old_price or index in wanted): paths.append(point)
            old_price = price
    actual = digest.hexdigest()
    assert actual == expected, ('原資料変更',str(path))
    assert set(map(int,evidence)) == wanted
    return {'path':str(path),'sha256':actual,'adopted_rows':index+1,'points':evidence,'price_paths':paths,'normal_indices':normal_indices}


def main() -> None:
    """機能: 3夜の具体例を原板で検査し保存する。引数: なし。返り値: None。"""
    source = OUT / '前20夜の独立入口と追撃抑制の分解165.json'
    report = read(source)
    proof = read(BASE / 'results/train_validation/再生完了165_train_validation.json')
    assert proof['completed'] and proof['returncode']==0 and proof['sources_unchanged']
    paths = {x['session']:x for x in proof['results']}
    plans = {
        '2026-09-22_Night': {'states':[480,538]},
        report['u04_effect']['best_parent']['session']: {'u04_parent':report['u04_effect']['best_parent']['parent']},
        report['u04_effect']['worst_parent']['session']: {'u04_parent':report['u04_effect']['worst_parent']['parent']},
    }
    output = []
    for session, plan in plans.items():
        p = ROOT / paths[session]['path']
        assert p.parent.name=='train_validation' and sha(p)==paths[session]['sha256']
        saved = read(p)
        assert saved['scene']['split'] in ('train','validation')
        cases = {c['config']['id'][-2:]:c for c in saved['cases']}
        wanted, events, traces, intervals = set(), [], [], []
        item = {'session':session,'result_sha256':paths[session]['sha256'],'plan':plan}
        if 'states' in plan:
            c = cases['10']
            rows = [r for r in report['trade_rows'] if r['session']==session and r['method']=='NK225_U165_10' and r['state_id'] in plan['states']]
            parents = {r['parent'] for r in rows}
            events = selected_events(c['actual'],parents)
            traces = [t for t in c['trigger_trace'] if t['Parent'] in parents]
            item['rows'] = rows
            for sid in plan['states']:
                rs = [r for r in rows if r['state_id']==sid]
                intervals.append((min(r['state_index'] for r in rs)-10,max(r['exit_index'] for r in rs)+1))
        else:
            parent = plan['u04_parent']
            c = cases['04']
            item['difference'] = next(x for x in report['u04_parents'] if x['session']==session and x['parent']==parent)
            item['old_events'] = selected_events(saved['control']['actual'],{parent})
            item['u04_events'] = selected_events(c['actual'],{parent})
            events = item['old_events'] + item['u04_events']
            traces = [t for t in c['trigger_trace'] if t['Parent']==parent]
            intervals = [(min(e['Order']['DecisionIndex'] for e in events),max(e['FillIndex'] for e in events))]
        for e in events:
            wanted.update((e['Order']['DecisionIndex'],e['FillIndex']))
        for t in traces:
            wanted.add(t['Index'])
            state = t['State']
            if state['Known']: wanted.add(state['Band']['StartIndex'])
            for key in ('Buy','Sell'):
                h = state[key]
                if h['ID']:
                    wanted.add(h['Index'])
                    if h['PressureIndex']>0: wanted.add(h['PressureIndex'])
                    for z in ('Barrier','Support'):
                        if h[z]['Known']: wanted.add(h[z]['Index'])
        raw = raw_points(saved['scene'],wanted,intervals)
        refs = {q['Index']:q for q in saved['reference']}
        checked = 0
        for idx in wanted:
            q = raw['points'][str(idx)]
            if idx in refs:
                a = refs[idx]
                assert all(q[b]==a[k] for b,k in [('time','Time'),('line','Line'),('bid','Bid'),('ask','Ask'),('last','Last'),('normal','Normal')])
                checked += 1
        import bisect
        for e in events:
            o = e['Order']
            j = bisect.bisect_right(raw['normal_indices'],o['DecisionIndex'])
            assert raw['normal_indices'][j]==e['FillIndex']
            q = raw['points'][str(e['FillIndex'])]
            assert q['time']==e['FillTime'] and q['bid']==e['Bid'] and q['ask']==e['Ask']
            assert e['Price']==(q['ask'] if o['Side']>0 else q['bid'])
        del raw['normal_indices']
        item.update({'events':events if 'states' in plan else [],'traces':traces,'raw':raw,'checked_saved_references':checked,'checked_next_normal_events':len(events)})
        output.append(item)
        print(session,'原板と次正常約定の一致',len(events),'件',flush=True)
    dest = OUT / '前20夜の具体原行診断165.json'
    dest.write_text(json.dumps({'passed':True,'financial_runs':0,'confirmation_results_read':0,'source_analysis_sha256':sha(source),'examples':output},ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(dest,flush=True)


if __name__=='__main__':
    main()
