"""保存会計を場単位で接続し、報告用の比較と全場明細を作る。"""

import common143 as shared
from analyze143 import summarize


def assemble(recipes):
    """
    機能: 結果を見て選んだ開発候補の昼夜規則を、保存済み全50場から接続する。
    引数: recipes(list[dict])はID・昼方式・夜方式・短い説明。
    返り値: dictはxlsx入力。新しい売買生成を行わず、事後選抜であることを保持する。
    """
    allrows, manifests = [], []
    for stage in ('第一巡', '第二巡', '第三巡'):
        path = shared.HERE/f'{stage}結果143.json'
        if path.exists():
            result = shared.read(path)
            allrows.extend(result['rows'])
            manifests.append(shared.prior.ref(path))
    lookup = {(r['method'],r['session']):r for r in allrows}
    assert len(lookup)==len(allrows)
    sessions = sorted({r['session'] for r in allrows})
    rows, selected = [], []
    for recipe in recipes:
        method = recipe['method']
        day = recipe.get('source_day',recipe['day_method'])
        night = recipe.get('source_night',recipe['night_method'])
        selected.append(dict(symbol='NK225', **recipe))
        for scene in sessions:
            source = day if scene.endswith('_Day') else night
            row = dict(lookup[source,scene], source_method=source, method=method)
            rows.append(row)
    summary, groups = summarize(rows)
    result = dict(selected=selected, rows=rows,
        selection_note='全50場を見て改修・選抜した開発比較です。売買中に未来の場方向は使いません。ラージの次正常気配を日経miniの約定代理とします。',
        source_note='00143三巡の保存約定会計、日経原板Last始終値照合。mini片道38.5円を注文別切捨て',
        methodology=dict(選抜='既知50場の事後開発選択', 商品='NK225mini', 片方向最大=10,
            利益損失='新規・追加・部分返済の全費用を含む完結親の純益と純損失',
            保有='03～06時除外の実保有時間の和集合、各場率の単純平均', 入力=manifests))
    shared.save(shared.HERE/'report_data143.json', result)
    shared.save(shared.HERE/'報告候補集計143.json',dict(summary=summary,groups=groups,recipes=recipes))
    for item in summary:
        print(item['method'],item['net'],round(item['pf'],4),item['losses'],round(item['mean_holding_ratio']*100,2))
    return result


if __name__=='__main__':
    assemble(shared.read(shared.HERE/'報告候補の組合せ143.json'))
