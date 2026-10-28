"""第二段階の検証済み会計を、手法別xlsx用の入力へ加える。"""

from combine145 import HERE, ROOT, read, save, stats


def main():
    """
    機能: 全44条件の明細と比較集計を作り、第一段階を欠落させない。
    引数: なし。返り値: None。売買再生や入力会計の変更はしない。
    """
    report=read(HERE/'report145.json')
    directory=ROOT/'work/research145_roles'
    guard=read(directory/'ドテン確認の全場結果145.json')
    roles=read(directory/'役割分離の全場結果145.json')
    names={c['id'] for c in guard['configs']+roles['configs']}
    report['rows']=[r for r in report['rows'] if r['method'] not in names]+guard['rows']+roles['rows']
    report['methods']=[m for m in report['methods'] if m['id'] not in names]
    for cfg in guard['configs']:
        report['methods'].append(dict(id=cfg['id'],name=cfg['name'],description='V10のドテンだけに公開40分の支持を追加。通常の入口・数量・出口は同じ。'))
    for cfg in roles['configs']:
        text=' / '.join(f"{kind}: 主{cfg[kind]['CG']}・追加{cfg[kind]['A']}・別{cfg[kind]['CS']}" for kind in ['Day','Night'])
        report['methods'].append(dict(id=cfg['id'],name=cfg['name'],description=text+'。担当ごとの上限5・3・2枚を固定。'))
    assert len(report['methods'])==44 and len(report['rows'])==2200
    assert len({(r['method'],r['session']) for r in report['rows']})==2200
    scenes=sorted({r['session'] for r in report['rows']})
    summary=[]
    for method in report['methods']:
        chosen=[r for r in report['rows'] if r['method']==method['id']]
        assert len(chosen)==50
        for group in ['全50場','前半30場','後半20場','Day','Night','上昇','下落']:
            selected=[r for r in chosen if group=='全50場' or (group=='前半30場' and r['session'] in scenes[:30])
                    or (group=='後半20場' and r['session'] in scenes[30:]) or r['session'].endswith('_'+group) or r['direction']==group]
            if selected:summary.append(dict(method=method['id'],group=group,**stats(selected)))
    report['conclusion']='32改修・11組合せと基準を比較。全条件は既知50場の開発結果。費用0・最大10枚。'
    save(HERE/'report145.json',report)
    save(HERE/'全条件集計145.json',summary)
    for r in summary:
        if r['group']=='全50場' and r['method'] in names:
            print(r['method'],r['net'],r['pf'],r['reds'],r['mean_loss'],r['max_loss'],r['entries'])


if __name__=='__main__':main()
