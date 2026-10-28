"""事前に定めた独立枠の選択方法で合成し、全場の報告入力を作る。"""

import json
from pathlib import Path
import pickle
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGINE = ROOT / 'work/research145_engine'
RESIDUAL = ROOT / 'work/research145_residual'
sys.path[:0] = [str(ENGINE), str(ROOT/'work/research145_audit')]
import source145
import account145
from audit_results145 import verify


def read(path):
    """
    機能: 検算済みの保存結果を読む。
    引数: path(Path)。返り値: dict又はlistはJSON内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, data):
    """
    機能: 比較・選抜・報告の根拠を保存する。
    引数: path(Path)、data(dict又はlist)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def stats(rows):
    """
    機能: 当初指定に沿って、収支と赤字頻度・深さを集計する。
    引数: rows(list[dict])は同一条件の場会計。返り値: dictは比較指標。
    """
    nets = np.array([row['net'] for row in rows], float)
    profit = sum(row['profit'] for row in rows)
    loss = sum(row['loss'] for row in rows)
    red = -nets[nets < 0]
    black = nets[nets > 0]
    return dict(sessions=len(rows), profit=profit, loss=loss, net=float(nets.sum()),
        pf=profit/loss if loss else None, wins=len(black), reds=len(red),
        median=float(np.median(nets)), average=float(nets.mean()),
        mean_loss=float(red.mean()) if len(red) else 0.,
        median_loss=float(np.median(red)) if len(red) else 0.,
        max_loss=float(red.max()) if len(red) else 0.,
        ex3=float(nets.sum()-np.sort(black)[-3:].sum()),
        entries=sum(row['entries'] for row in rows),
        parents=sum(row['parent_count'] for row in rows),
        zero_entries=sum(row['entries']==0 for row in rows))


def rank(rows):
    """
    機能: 登録した順位規則をそのまま適用する。
    引数: rows(list[dict])。返り値: tupleは小さいほど上位の順位鍵。
    """
    value = stats(rows)
    return value['reds'], -value['median'], -value['net'], value['max_loss']


def choose(rows, methods, scenes):
    """
    機能: 指定期間だけで各担当の候補を順位付けする。
    引数: rows(list[dict])、methods(list[str])、scenes(set[str])。
    返り値: tuple[str,list[dict]]は選択IDと全順位。基準を排除しない。
    """
    ordered = sorted(methods, key=lambda method: (*rank([r for r in rows if r['method']==method and r['session'] in scenes]), method))
    return ordered[0], [dict(method=method, **stats([r for r in rows if r['method']==method and r['session'] in scenes])) for method in ordered]


def main():
    """
    機能: 独立枠の固定合成を行い、同時数量と独立現金会計を検査する。
    引数: なし。返り値: None。各場の結果で選択を変更しない。
    """
    receipt = read(HERE/'会計修正登録受領145.json')
    assert receipt['returncode']==0
    left = read(ENGINE/'結果145.json')
    right = read(RESIDUAL/'残玉と部分利確後の全場結果145.json')
    rows = left['rows'] + right['rows']
    scenes = sorted({row['session'] for row in rows})
    assert len(scenes)==50 and len(rows)==1600
    assert len({(r['session'],r['method']) for r in rows})==1600
    v_methods = sorted({r['method'] for r in left['rows']})
    r_methods = sorted({r['method'] for r in right['rows']})
    selections = []
    for code, stages in [('C01', {'全場':scenes[:30]}),
                         ('C02', {'Day':[s for s in scenes[:30] if s.endswith('_Day')],
                                  'Night':[s for s in scenes[:30] if s.endswith('_Night')]}),
                         ('C03', {'全場':scenes})]:
        for kind, chosen_scenes in stages.items():
            v, vr = choose(rows,v_methods,set(chosen_scenes))
            r, rr = choose(rows,r_methods,set(chosen_scenes))
            selections.append(dict(method=code,kind=kind,addon=v,residual=r,
                selected_using=chosen_scenes, addon_ranking=vr,residual_ranking=rr))
    save(HERE/'固定組合せの選択145.json', selections)
    combined, audits = [], []
    target = HERE/'combined_orders'
    target.mkdir(exist_ok=True)
    for scene in scenes:
        with (ENGINE/'cache'/f'{scene}.pkl').open('rb') as stream:
            packet,data,_,_,label = pickle.load(stream)
        arrays = {}
        with np.load(ENGINE/'measurement'/f'NK225_{scene}.npz') as va, np.load(RESIDUAL/'orders'/f'{scene}.npz') as ra:
            np.testing.assert_array_equal(va['V00'],ra['R00'])
            for code in ('C01','C02','C03'):
                selection = next(x for x in selections if x['method']==code and (x['kind']=='全場' or scene.endswith('_'+x['kind'])))
                v,r = selection['addon'],selection['residual']
                orders = source145.shared.merge(ra['CG_'+r],va['A_'+v],ra['CS_'+r])
                result = account145.account(orders,packet,code,label)
                result['components']=dict(addon=v,residual=r)
                result['selection_period']='全50場の事後選抜' if code=='C03' else '前半30場で固定・後半20場で比較'
                result['period']='前半30場' if scene in scenes[:30] else '後半20場'
                audits.append(verify(orders,data['ready'],data['quotes'],result))
                combined.append(result)
                arrays[code]=orders
        np.savez_compressed(target/f'{scene}.npz',**arrays)
    save(HERE/'組合せ結果145.json',dict(rows=combined,selections=selections,audits=audits,all_passed=True))
    # ----------------------------------------
    # 重複基準R00を省き、TG04の費用0再生を先頭に置く。
    report_rows=[]
    for row in rows+combined:
        if row['method']=='R00':
            continue
        copy=dict(row)
        if copy['method']=='V00':
            copy['method']='TG04Z'
        report_rows.append(copy)
    metadata = [dict(id='TG04Z',name='TG04基準・手数料0で再生',description='基本5枚・追加3枚・別入口2枚。元の売買条件を費用0で再生した比較基準。')]
    for config in left['configs']:
        if config['id']=='V00':
            continue
        metadata.append(dict(id=config['id'],name=config['name'],description='追加担当だけを変更。'+config['name']+'。基本担当と別入口は基準と同じ。'))
    for config in right['configs']:
        if config['id']=='R00':
            continue
        description='基本担当の部分利確後だけを変更。' if config['id'].startswith('P') else '基本・別入口の残り1枚の扱いを変更。'
        metadata.append(dict(id=config['id'],name=config['name'],description=description+config['name']+'。追加担当は基準と同じ。'))
    for code,name in [('C01','前半30場で固定した組合せ'),('C02','昼夜別に前半30場で固定した組合せ'),('C03','全50場から選んだ開発用組合せ')]:
        text=' / '.join(f"{s['kind']} {s['residual']}＋{s['addon']}" for s in selections if s['method']==code)
        metadata.append(dict(id=code,name=name,description=text+'。同じ期間の事後選抜を新しい期間の実績と混同しない。'))
    assert len(metadata)==34
    summaries=[]
    for method in metadata:
        chosen=[r for r in report_rows if r['method']==method['id']]
        for group in ['全50場','前半30場','後半20場','Day','Night','上昇','下落']:
            subset=[r for r in chosen if group=='全50場' or (group=='前半30場' and r['session'] in scenes[:30])
                    or (group=='後半20場' and r['session'] in scenes[30:]) or r['session'].endswith('_'+group) or r['direction']==group]
            if subset:
                summaries.append(dict(method=method['id'],group=group,**stats(subset)))
    save(HERE/'全条件集計145.json',summaries)
    save(HERE/'report145.json',dict(methods=metadata,rows=report_rows,conclusion='各手法の収支・赤字頻度・損失の深さを比較。全34条件は既知50場の開発比較。'))
    print(json.dumps(selections,ensure_ascii=False)[:2000])
    print('34手法・各50場の組合せと会計確認が完了しました。')


if __name__=='__main__':
    main()
