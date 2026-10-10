"""完了セッションだけで次セッションの方向アルゴリズムを選ぶ機械的選択器。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np

import signals
import learned_flow
from research import aggregate

OUT = Path(__file__).resolve().parent
RESULTS_PATH = OUT / '全条件セッション集計.json'


def catalog() -> list[dict]:
    """機能: 性能再計算前に固定する８種類の過去成績による選択を返す。

    引数: なし。返り値: 比較候補 (list[dict])。
    """
    choices = [
        ('P00','過去全体・自銘柄PF',0,'own','pf',1),
        ('P01','直近３区間・自銘柄PF',3,'own','pf',1),
        ('P02','直近５区間・自銘柄収支DD',5,'own','risk',1),
        ('P03','過去全体・両銘柄弱い側PF',0,'both','pf',1),
        ('P04','直近３区間・両銘柄弱い側収支DD',3,'both','risk',1),
        ('P05','直近５区間・両銘柄弱い側PF',5,'both','pf',1),
        ('P06','直近５区間・自銘柄上位２つの合議',5,'own','risk',2),
        ('P07','過去全体・両銘柄上位３つの合議',0,'both','pf',3),
    ]
    return [{'id':code,'name':name,'family':'過去成績による機械的手法選択',
             'description':'完了区間のG00固定１枚成績だけで次区間の方向手法を選ぶ。選んだ方向列を共通出口で新たに再生する。',
             'params':{'window':window,'scope':scope,'metric':metric,'top':top,
                       'min_past_sessions':2,'min_cycles':2,'fallback':'F32','vote_threshold':.25}}
            for code,name,window,scope,metric,top in choices]


def source_ids() -> list[str]:
    """機能: 選択の対象を元の価格・板・過去学習５８信号に限定する。

    引数: なし。返り値: 元信号 ID (list[str])。選択器自体を候補に混ぜない。
    """
    return sorted(spec['id'] for spec in signals.catalog()+learned_flow.catalog())


def freeze() -> None:
    """機能: 選択条件を成績の読み込みより先に別の凍結記録へ保存する。

    引数: なし。返り値: なし (None)。元探索の凍結ファイルは変更しない。
    """
    payload = {'catalog':catalog(),'source_ids':source_ids(),'比較管理':'G00固定１枚',
               'PF順位':'金額PF（損失なし利益ありは５、５で上限）→収支/時価DD→１組平均NetR',
               '収支DD順位':'収支/時価DD→１組平均NetR→金額PF',
               '両銘柄順位':'それぞれ無次元化した指標の小さい側を各順位軸に使用',
               '同点順位':'元信号IDの昇順',
               '重み':'1+clip(順位の第１指標,-0.9,4)、合計１へ正規化',
               '合議':'重み付き方向和が+0.25以上で買い、-0.25以下で売り、それ以外中立',
               'fallback':'最初２区間と有効候補なしはF32。学習区間内で取引組が２未満の銘柄は順位対象外。',
               '事後設計':'既知１３セッションを使う設計の再現。未見期間として扱わない。'}
    path = OUT/'selector_past_fixed.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        if old['固定内容'] != payload:
            raise ValueError('既存の選択条件凍結と一致しません')
    else:
        path.write_text(json.dumps({'固定時刻':datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),'固定内容':payload},
                                   ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def metrics(rows: list[dict], min_cycles: int) -> tuple[float,float,float] | None:
    """機能: 過去区間の同銘柄成績を無次元の順位指標へ変換する。

    引数: rows (list[dict])、min_cycles (int)。返り値: PF・収支/DD・平均NetR、または不足時 None。
    """
    value = aggregate(rows)
    if value['cycles'] < min_cycles:
        return None
    loss, profit = value['gross_loss_yen'], value['gross_profit_yen']
    pf = min(5.,profit/loss) if loss>1e-8 else (5. if profit>0 else 0.)
    risk = value['net_yen']/max(1.,value['drawdown_yen'])
    mean_r = value['net_r']/value['cycles']
    return pf,risk,mean_r


def choose(spec: dict, previous: list[str], symbol: str, table: dict) -> tuple[list[str],list[float],list[str],str]:
    """機能: 現在区間を含まない過去区間だけから採用信号と重みを決定する。

    引数: spec (dict)、previous (list[str])、symbol (str)、table (dict)。
    返り値: 採用ID・重み・使用区間・不足理由 (tuple[list,list,list,str])。
    """
    params = spec['params']
    used = previous[-params['window']:] if params['window'] else list(previous)
    if len(previous)<params['min_past_sessions']:
        return [params['fallback']],[1.],used,'過去２区間未満'
    scopes = ('TOPIX','NK225') if params['scope']=='both' else (symbol,)
    ranked = []
    for signal_id in source_ids():
        values = []
        for target in scopes:
            rows = [table[(signal_id,target,session)] for session in used]
            value = metrics(rows,params['min_cycles'])
            if value is None:
                break
            values.append(value)
        if len(values)!=len(scopes):
            continue
        pf,risk,mean_r = tuple(min(v[i] for v in values) for i in range(3))
        score = (pf,risk,mean_r) if params['metric']=='pf' else (risk,mean_r,pf)
        ranked.append((signal_id,score))
    if not ranked:
        return [params['fallback']],[1.],used,'必要取引組数を満たす候補なし'
    ranked.sort(key=lambda row:(-row[1][0],-row[1][1],-row[1][2],row[0]))
    selected = ranked[:params['top']]
    raw_weights = [1.+float(np.clip(row[1][0],-.9,4.)) for row in selected]
    total = sum(raw_weights)
    return [row[0] for row in selected],[w/total for w in raw_weights],used,''


def build_all(inputs: dict, features: dict, directions: dict) -> tuple[list[dict],dict,list[dict]]:
    """機能: 過去結果だけで手法を選び、実際に再生する原本行ごとの方向列を作る。

    引数: inputs/features/directions (dict)。features は未使用。directions は元５８信号。
    返り値: 候補一覧・方向列・区間開始時選択記録 (tuple[list,dict,list])。
    """
    freeze()
    rows = json.loads(RESULTS_PATH.read_text(encoding='utf-8'))
    allowed = set(source_ids())
    table = {}
    for row in rows:
        identifier = row['id']
        if identifier.endswith('_G00') and identifier[:-4] in allowed:
            key = (identifier[:-4],row['symbol'],row['session'])
            if key in table:
                raise ValueError('元信号の成績行が重複しています')
            table[key] = row
    sessions = sorted({key[0] for key in inputs})
    outputs, events = {}, []
    for spec in catalog():
        by_key = {}
        for i, session in enumerate(sessions):
            previous = sessions[:i]
            for symbol in ('TOPIX','NK225'):
                key = (session,symbol)
                ready = inputs[key]
                selected,weights,used,reason = choose(spec,previous,symbol,table)
                if used:
                    latest = max(inputs[(old,peer)]['time_s'][-1] for old in used for peer in ('TOPIX','NK225'))
                    if latest >= ready['time_s'][0]:
                        raise ValueError('前セッションが現在セッション開始前に完了していません')
                if len(selected)==1:
                    state = np.asarray(directions[selected[0]][key],dtype=np.int8).copy()
                else:
                    vote = np.zeros(len(ready['time_s']))
                    for signal_id,weight in zip(selected,weights):
                        vote += directions[signal_id][key]*weight
                    threshold = spec['params']['vote_threshold']
                    state = np.where(vote>=threshold,1,np.where(vote<=-threshold,-1,0)).astype(np.int8)
                if len(state)!=len(ready['time_s']):
                    raise ValueError('原本と方向の行数が一致しません')
                by_key[key] = state
                events.append({'selector_id':spec['id'],'適用セッション':session,'symbol':symbol,
                               '判断時刻':float(ready['time_s'][0]),'学習末尾':used[-1] if used else None,
                               '学習区間':used,'selected_ids':selected,'weights':weights,'fallback理由':reason,
                               '方向更新':'区間開始で採用手法を固定、採用手法の原本行方向は区間内で更新',
                               '過去成績管理':'G00','現在セッション結果参照':False})
        outputs[spec['id']] = by_key
    return catalog(),outputs,events


def main() -> None:
    """機能: 別凍結の後に選択方向を生成し、根拠と原本方向を保存する。

    引数: なし。返り値: なし (None)。本スクリプトでは売買成績の再評価をしない。
    """
    freeze()
    inputs = pickle.loads((OUT/'inputs.pkl').read_bytes())
    directions = pickle.loads((OUT/'directions.pkl').read_bytes())
    specs,outputs,events = build_all(inputs,{},directions)
    (OUT/'selector_past_specs.json').write_text(json.dumps(specs,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'selection_events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
    with (OUT/'selector_past_directions.pkl').open('wb') as stream:
        pickle.dump(outputs,stream,pickle.HIGHEST_PROTOCOL)
    print(json.dumps({'選択条件数':len(specs),'区間銘柄ごとの選択件数':len(events),
                      '選択元信号数':len(source_ids()),'現在セッション成績参照':False},ensure_ascii=False))


if __name__=='__main__':
    main()
