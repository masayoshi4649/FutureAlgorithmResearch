"""同じ昼夜の過去完了会計だけで、次のセッションの運転政策を決める。"""

from policies142 import online_config


def choose_method(past, candidates):
    """
    機能: 各候補の過去10同種場だけから安定性順の政策を一つ選ぶ。
    引数: past(list[dict])は完了した同銘柄同昼夜場、candidates(list[str])は固定候補。
    返り値: tuple[str,dict]は選択IDと各候補の採点。今場の情報を受け取らない。
    """
    config=online_config()
    scenes=sorted({r['session'] for r in past})[-config['window']:]
    if len(scenes)<config['warmup']:
        return 'B5',{}
    scores={}
    for candidate in candidates:
        subset=[r for r in past if r['method']==candidate and r['session'] in scenes]
        assert len(subset)==len(scenes)
        losses=[-r['net'] for r in subset if r['net']<0]
        scores[candidate]=[sum(r['entries']==0 for r in subset),len(losses),sum(losses)/len(losses) if losses else 0.,-sum(r['net'] for r in subset)]
    chosen=min(candidates,key=lambda c:(*scores[c],c))
    return chosen,scores


def replay_selection(rows):
    """
    機能: セッション開始前に選び、終了済みの実行可能な候補会計だけを順に蓄積する。
    引数: rows(list[dict])は候補全場の保存会計。各時点の選択関数には過去だけを渡す。
    返り値: tuple[list,list]はW01会計と再現可能な選択記録。
    """
    config=online_config();out=[];notes=[]
    for symbol in ('NK225','TOPIX'):
        for kind in ('Day','Night'):
            relevant=[r for r in rows if r['symbol']==symbol and r['kind']==kind and r['method'] in config['candidates']]
            past=[]
            for scene in sorted({r['session'] for r in relevant}):
                chosen,scores=choose_method(past,config['candidates'])
                current=[r for r in relevant if r['session']==scene]
                selected=next(r for r in current if r['method']==chosen)
                out.append(dict(selected,method='W01',component_method=chosen))
                notes.append(dict(symbol=symbol,session=scene,chosen=chosen,completed_sessions=sorted({r['session'] for r in past}),scores=scores))
                past.extend(current)
    return out,notes
