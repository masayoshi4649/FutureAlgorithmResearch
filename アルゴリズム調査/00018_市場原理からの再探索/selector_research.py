"""手法の機械的選択から返済までを、一つの口座状態で再生する追加検証。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import time
from zoneinfo import ZoneInfo

import research
import managers
import selector_signals
import selector_past

OUT = Path(__file__).resolve().parent


def save(name: str, value: object) -> None:
    """機能: 追加検証の結果を既存探索と別の名前で保存する。

    引数: name (str)、value (object)。返り値: なし (None)。
    """
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def init_worker() -> None:
    """機能: 各処理へ原本入力と選択後の方向列を設定する。

    引数: なし。返り値: なし (None)。
    """
    research.INPUTS = pickle.loads((OUT/'inputs.pkl').read_bytes())
    research.DIRECTIONS = pickle.loads((OUT/'selector_directions.pkl').read_bytes())


def main() -> None:
    """機能: 選択ルールを固定し、全注文管理との一体損益を比較する。

    引数: なし。返り値: なし (None)。既存候補の損益の継ぎ足しは行わない。
    """
    specs = selector_signals.catalog()+selector_past.catalog()
    management = managers.manager_catalog()
    save('選択統合の探索前固定.json',dict(時刻=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
         選択則数=len(specs),管理数=len(management),全条件数=len(specs)*len(management),
         全13セッション既読=True,現在データの追加取得なし=True,
         実行='選択後の方向を一つのengineへ渡し、建玉・待機・連敗・損失予算を引き継いで再生。',
         候補比較='元探索の資格と順位式を変更せず使用。選択ルール自体の事後最適化は残る。',
         SHA256={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ['selector_research.py','selector_signals.py','selector_past.py','engine.py','managers.py']}))
    inputs=pickle.loads((OUT/'inputs.pkl').read_bytes())
    features=pickle.loads((OUT/'features_depth.pkl').read_bytes())
    directions=pickle.loads((OUT/'directions.pkl').read_bytes())
    one, values, events = selector_signals.build_all(inputs,features,directions)
    two, other, past_events = selector_past.build_all(inputs,features,directions)
    values.update(other)
    assert {s['id'] for s in specs}==set(values)
    (OUT/'selector_directions.pkl').write_bytes(pickle.dumps(values,pickle.HIGHEST_PROTOCOL))
    save('手法選択の履歴.json',dict(相場状態から選択=events,過去確定成績から選択=past_events))
    items=[dict(id=s['id']+'_'+m['id'],signal_id=s['id'],manager_id=m['id'],family=s['family'],
                name=s['name']+'＋'+m['name'],signal=s,manager=m) for s in specs for m in management]
    save('選択統合の全条件.json',items)
    del inputs,features,directions,values,other
    started=time.monotonic()
    rows=[]
    with ProcessPoolExecutor(max_workers=3,initializer=init_worker) as pool:
        for i,result in enumerate(pool.map(research.evaluate,[(s['id'],m) for s in specs for m in management]),1):
            rows.extend(result)
            if i%40==0: print(f'{i}/{len(items)}条件完了、{time.monotonic()-started:.0f}秒',flush=True)
    save('選択統合のセッション集計.json',rows)
    sessions=sorted({r['session'] for r in rows})
    grouped={i['id']:[] for i in items}
    for r in rows: grouped[r['id']].append(r)
    ranking=[]
    for item in items:
        symbols={s:research.aggregate([r for r in grouped[item['id']] if r['symbol']==s]) for s in research.SYMBOLS}
        ranking.append(dict(item,symbols=symbols,qualified=research.eligibility(symbols,len(sessions)),score=list(research.score(symbols,len(sessions)))))
    ranking.sort(key=lambda r:(tuple(r['score']),r['id']),reverse=True)
    save('選択統合の期間集計.json',ranking)
    folds,walk_rows=[],[]
    for i in range(6,len(sessions)):
        candidates=[]
        for item in items:
            result={s:research.aggregate([r for r in grouped[item['id']] if r['symbol']==s and r['session'] in sessions[:i]]) for s in research.SYMBOLS}
            candidates.append((research.score(result,i),item['id']))
        _,identifier=max(candidates)
        test=[r for r in grouped[identifier] if r['session']==sessions[i]]
        walk_rows.extend(test)
        folds.append(dict(過去末尾=sessions[i-1],評価=sessions[i],採用ID=identifier,結果=test))
    save('選択統合の逐次選択.json',dict(位置付け='追加選択ルール自体を過去だけで選ぶ二段階目の時系列再現。全データ既読。',folds=folds,
        symbols={s:research.aggregate([r for r in walk_rows if r['symbol']==s]) for s in research.SYMBOLS}))
    finalists=[]
    seen=set()
    for item in ranking:
        if item['signal_id'] not in seen:
            finalists.append(item['id']);seen.add(item['signal_id'])
        if len(finalists)==5: break
    result=dict(primary=ranking[0]['id'],finalists=finalists,qualified_count=sum(r['qualified'] for r in ranking),
                count=len(items),selector_count=len(specs),sessions=sessions)
    save('選択統合の結果.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
