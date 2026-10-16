"""保存入口分類だけから、未知原因・小標本・大勝ち依存と具体時刻を説明する。"""

from datetime import datetime, timedelta, timezone

import numpy as np

import analyze


def displayed(stamp: float | None) -> str | None:
    """
    機能: 保存価格代理時計を日本時間の短い日時へ変換する。
    引数: stamp(float|None)はUTC秒または不明。
    返り値: str|Noneは日本時間。受信時刻や注文到着時刻とは呼ばない。
    """
    return datetime.fromtimestamp(stamp, timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S') if stamp is not None else None


def run() -> None:
    """
    機能: 保存246親の分類から、全33静的安定性と結果群の真の分子分母を求める。
    引数: なし。
    返り値: None。旧巨大cache・原本・金融を読まず新しい短補足だけを作る。
    """
    source = analyze.HERE/'入口状態と保存損益の分類.json'; r = analyze.read(source)
    assert r['全合格']; entries=r['entries']; sessions=r['sessions']; stability={}; probabilities={}
    for stage in ('paper','fill'):
        stability[stage],probabilities[stage]={},{}
        for window in (10,30,60):
            for mode in ('N','P'):
                ident=mode+str(window); stability[stage][ident],probabilities[stage][ident]={},{}
                for symbol in analyze.SYMBOLS:
                    original=[e for e in entries if e['symbol']==symbol]
                    selected=[e for e in original if e['stages'][stage]['gates'][ident]['accepted']]
                    nets={s:sum(e['baseline_parent_net'] for e in selected if e['session']==s) for s in sessions}
                    ordered=sorted(nets.values(),reverse=True); positives=[v for v in nets.values() if v>0]
                    stat=stability[stage][ident][symbol]=dict(採用親=len(selected),採用場=len({e['session'] for e in selected}),
                        静的黒字場=sum(v>0 for v in nets.values()),静的赤字場=sum(v<0 for v in nets.values()),
                        静的採用ゼロ場=len(sessions)-len({e['session'] for e in selected}),
                        静的収支=sum(nets.values()),中央値=float(np.median(list(nets.values()))),
                        上位3利益場除外収支=sum(nets.values())-sum(ordered[:3]),
                        最大利益場の全利益場寄与=ordered[0]/sum(positives) if positives else None,
                        静的各場収支=nets)
                    assert stat['静的収支']==r['静的六条件'][stage][ident][symbol]['全33']['採用群']['収支']
                    groups=r['P1L8結果群の当時入口'][symbol]
                    good=groups['利益目標を得て黒字']['測定']['各活動場の最初の実入口'][stage][ident]
                    bad=groups['初期損失のまま赤字']['測定']['各活動場の最初の実入口'][stage][ident]
                    total=good['accepted']+bad['accepted']
                    probabilities[stage][ident][symbol]=dict(successes=good['accepted'],total=total,
                        value=good['accepted']/total if total else None,
                        分母='保存P1L8活動場のうち、最初の実入口の当時'+stage+'状態が当条件に該当した場',
                        事象='その元の未フィルタP1L8政策が最終黒字',
                        限界='フィルタ後の勝率ではない。後の建玉と停止時刻が変わる新政策は未再生。')
    reasons={}
    for stage in ('paper','fill'):
        reasons[stage]={}
        for symbol in analyze.SYMBOLS:
            reasons[stage][symbol]={}
            selected=[e for e in entries if e['symbol']==symbol]
            for window in (10,30,60):
                reasons[stage][symbol][str(window)]={}
                for market in ('own','peer'):
                    measured=[e['stages'][stage]['windows'][str(window)][market] for e in selected]
                    reasons[stage][symbol][str(window)][market]=dict(母数=len(measured),
                        UNKNOWN=sum(x['state']=='UNKNOWN' for x in measured),
                        AMBIGUOUS=sum(x['state']=='AMBIGUOUS' for x in measured),
                        同時に複数理由あり=True,
                        各未知理由={name:sum(x['unknown_reason'] is not None and bool(x['unknown_reason']&bit) for x in measured)
                            for bit,name in analyze.core.UNKNOWN_NAMES.items()},
                        公表選択不足又は鮮度超過=sum(bool(x['selection_unknown_reason']) for x in measured),
                        自己公表終点から実候補までの不正=sum(bool(x['own_tail_unknown']) for x in measured))
    wanted={('2026-10-08_Day','TOPIX'),('2026-10-05_Night','TOPIX'),('2026-10-02_Night','NK225'),
        ('2026-09-24_Night','NK225')}; examples=[]
    for entry in r['最初の入口の具体気配']:
        if (entry['session'],entry['symbol']) not in wanted:
            continue
        item={k:entry[k] for k in ('session','symbol','parent','side','baseline_parent_net')}; item['時点']={}
        for stage in ('paper','fill'):
            value=entry['stages'][stage]; market=value['windows']['30']
            simplified={}
            for name in ('own','peer'):
                obs=market[name]; simplified[name]=dict(state=obs['state'],
                    公表価格時計=displayed(obs['source']['price_time_s']) if obs['source'] else None,
                    公表気配=[obs['source']['bid'],obs['source']['ask']] if obs['source'] else None,
                    基準価格時計=displayed(obs['reference']['price_time_s']) if obs['reference'] else None,
                    基準気配=[obs['reference']['bid'],obs['reference']['ask']] if obs['reference'] else None,
                    bidask変化呼値=[obs['bid_change_ticks'],obs['ask_change_ticks']],
                    unknown_reason=obs['unknown_reason'],尾部不正=obs['own_tail_unknown'])
            item['時点'][stage]=dict(価格時計=displayed(value['time_s']),原seq=value['seq'],
                実当行気配=[value['current']['bid'],value['current']['ask']],
                三十秒観測=simplified,六分類=value['gates'])
        examples.append(item)
    analyze.write(analyze.HERE/'入口分類の短い原因整理.json',dict(全合格=True,
        入力SHA256=analyze.digest(source),静的全33安定性=stability,
        元政策結果に対する条件付き割合=probabilities,UNKNOWNの内訳=reasons,具体4場=examples,
        考察=['E01の有利指値は押し・戻りで到達する。紙上時点の方向支持とfill時点の順行要求は同じ仮説ではない。',
            '紙上P30の静的PFは両商品で上昇したが、10親/13親と少数であり、未知除外と大勝ち寄与を分ける必要がある。',
            '相手反対なしN30は支持ありを意味しない。未知による見送りは市場心理としての逆方向判定ではない。',
            '紙上支持を基準に指値を出す入口仮説はあるが、注文待機中の仮説破綻と場内目標の変化は次の因果再生で確認する。'],
        新金融再生=0,新注文=0,原本再読取=0,API=0))
    print('保存入口だけの安定性・未知原因・4場具体気配の補足を保存',flush=True)


if __name__=='__main__':
    run()
