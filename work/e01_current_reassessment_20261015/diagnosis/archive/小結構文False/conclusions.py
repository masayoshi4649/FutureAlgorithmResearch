"""目的射影を再利用し、方向逆行と追尾未起動を勝ち反証付きで要約する。"""

from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean, median

import run

HERE=Path(__file__).resolve().parent
SUMMARY=HERE/'方向とコスト及び保護未起動の限定小結.json'
REPORT=HERE/'方向逆行とコスト及び次の一部品の小結.md'


def stats(parents: list[dict]) -> dict:
    """
    機能: 完結親分母を保ちながら支持更新・事後黒字・保有時間を合算する。
    引数: parents(list[dict]) は同商品同条件の実親集合。
    返り値: dict は金額、負け方向、保護起動前の分布。未保有の潜在波は含めない。
    """
    base=run.totals(parents)
    return dict(**base,support_updated_parents=sum(bool(p['support_events']) for p in parents),
                support_events=sum(len(p['support_events']) for p in parents),
                mean_holding_proxy_seconds=mean(p['holding_price_proxy_seconds'] for p in parents) if parents else None,
                median_holding_proxy_seconds=median(p['holding_price_proxy_seconds'] for p in parents) if parents else None,
                mean_friction_yen=mean(p['amounts']['crossing_disadvantage_yen']+p['fees_yen'] for p in parents) if parents else None,
                peak_reached_wide_arm=sum(p['best_parent_liquidation_yen']>=p['notional_yen']*.00125 for p in parents))


def compact(p: dict) -> dict:
    """
    機能: 一つの実親を公開・約定・極値・返済の必要最小限へ写す。
    引数: p(dict) は診断済み実親。
    返り値: dict は短い勝ち反証又は負け実例。相手板・真受信時計を補完しない。
    """
    def point(z: dict) -> dict:
        """
        機能: 原行・価格代理時計・BBO・当時両市場票を小射影する。
        引数: z(dict) は同観測点。
        返り値: dict は必要な既保存列のみ。
        """
        return {k:z[k] for k in ('normal_row','raw_seq','bid','ask','parent_liquidation_yen','support_line',
            'volume_known','volume_up','volume_down','volume_signed_balance','own_price_known','own_price_count',
            'own_price_balance','peer_price_known','peer_price_count','peer_price_balance','peer_raw_seq','peer_price_age_seconds')} | {'JST_price_proxy':run.jst(z['price_time_s'])}
    return dict(session=p['session'],symbol=p['symbol'],parent=p['parent'],side=p['side'],q=p['entry_quantity'],
                net=p['net_yen'],amounts=p['amounts'],peak=p['best_parent_liquidation_yen'],worst=p['worst_parent_liquidation_yen'],
                wide_arm=p['notional_yen']*.00125,cash_stop=p['parent_stop_yen'],
                support_updates=len(p['support_events']),publication=point(p['publication']),
                adverse_ticks=p['published_adverse_ticks'],entry=point(p['entry']['約定']),
                best=point(p['first_parent_liquidation_argmax']),worst_point=point(p['first_parent_liquidation_argmin']),
                exit_source=point(p['exits'][0]['判断']),exit_fill=point(p['exits'][0]['約定']),
                exit_reason=p['exits'][0]['reason_label'])


def main() -> None:
    """
    機能: 一読診断の保存射影だけから限定小結と改善仮説を作る。
    引数: なし。
    返り値: None。元金融結果・台帳・cache・API・経済sourceを読取変更しない。
    """
    assert not SUMMARY.exists() and not REPORT.exists()
    source=run.sources()
    p=json.loads(run.PROJECTION.read_text(encoding='utf-8'))
    a=json.loads(run.OUTPUT.read_text(encoding='utf-8'))
    assert p['出典SHA256']==a['出典SHA256']==run.EXPECTED_SHA
    assert source==p['source_SHA256']
    maincase=p['cases'][run.MAIN]
    group={};wins={};examples={}
    for symbol in run.CAP:
        pp=[v for v in maincase['parents'] if v['symbol']==symbol]
        def volume_group(v: dict) -> str:
            """
            機能: 公開当時の既知出来高代理票数を事前の固定区分へ分ける。
            引数: v(dict) は実親。
            返り値: str は票数帯。実親の勝率以外へ分母を置換しない。
            """
            z=v['publication'];assert z['volume_known']
            n=z['volume_up']+z['volume_down']
            return '2票' if n==2 else '3–4票' if n<=4 else '5–9票' if n<=9 else '10票以上'
        def balance_group(v: dict) -> str:
            """
            機能: 公開時の既signed出来高代理釣合いを固定区分へ分ける。
            引数: v(dict) は実親。
            返り値: str は既知釣合い区分。符号を二度掛けない。
            """
            b=v['publication']['volume_signed_balance']
            return '.25以上.5未満' if b<.5 else '.5以上.75未満' if b<.75 else '.75以上1未満' if b<1 else '1'
        groups={'全親':pp,'負親':[v for v in pp if v['net_yen']<0],
                '負親かつ一度も黒字なし':[v for v in pp if v['net_yen']<0 and v['best_parent_liquidation_yen']<=0],
                '負親かつ途中黒字あり':[v for v in pp if v['net_yen']<0 and v['best_parent_liquidation_yen']>0]}
        group[symbol]={k:stats(v) for k,v in groups.items()}
        group[symbol]['公開代理票数別']={tag:stats([v for v in pp if volume_group(v)==tag]) for tag in ('2票','3–4票','5–9票','10票以上')}
        group[symbol]['公開代理釣合い別']={tag:stats([v for v in pp if balance_group(v)==tag]) for tag in ('.25以上.5未満','.5以上.75未満','.75以上1未満','1')}
        group[symbol]['返済理由別']={str(code):stats([v for v in pp if v['exits'][0]['reason']==code]) for code in sorted({v['exits'][0]['reason'] for v in pp})}
        winners=sorted((v for v in pp if v['net_yen']>0),key=lambda v:(-v['net_yen'],v['session'],v['parent']))
        wins[symbol]=[compact(v) for v in winners[:2]]
        examples[symbol]=[]
        for e in a['主③WIDE赤字上位3場の最大負親'][symbol]:
            match=next(v for v in pp if v['session']==e['session'] and v['parent']==e['parent'])
            examples[symbol].append(compact(match)|{'session_net':e['session_net_yen']})
    summary=dict(全合格=True,出典結果SHA256=run.EXPECTED_SHA,source_SHA256=source,
        診断sourceSHA256=run.sha(Path(__file__)),元射影SHA256=run.sha(run.PROJECTION),元検算SHA256=run.sha(run.OUTPUT),
        全九条件の全親と負親={cid:{s:{k:z[k] for k in ('all_parents','negative_parents')} for s,z in vv.items()} for cid,vv in a['aggregated'].items()},
        主③WIDEの詳細=group,赤字六例=examples,同条件の勝ち反証最大2例=wins,
        再金融=0,元金融本文追加読=0,台帳=0,cache=0,API=0,
        解釈='中値変化は同じ実入口/返済時点の恒等式。逆側に売買すれば利益になるという証明又は別約定モデルではない。',
        未測=['全normalの保有経路は再読していない。','peer BBO未保存。','支持更新行時計は一部未保存。'],
        次の一部品候補='方向逆行と反応認定後の継続失敗を先に対照。入口直後の追加追随の再検査等は未測で、係数の事後最適化をしない。')
    raw=json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    SUMMARY.write_text(raw,encoding='utf-8')
    lines=['両商品の赤字は、**中値方向の損益が負であることと、繰返す気配横断の両方**から生じた。手数料だけの問題ではない。全9条件すべてで両商品の中値損益も負だった。',
        '',f"[一読結果](../root_review/公開用の同bytes結果.json) SHA `{run.EXPECTED_SHA}`。[全9検算](九条件の方向損益と売買コスト及び反応WIDE六例.json)／[限定小結](方向とコスト及び保護未起動の限定小結.json)。同じ実入口・返済時点の金額分解で、中値約定や逆売買の利益を示さない。",'',
        '|③WIDE|全親数|中値変化|気配横断|実料|純損益|負け親の中値逆行|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for s in run.CAP:
        z=group[s]['全親'];n=group[s]['負親']
        lines.append(f"|{s}|{z['parent_count']}|{z['mid_direction_yen']:,.0f}円|{z['crossing_disadvantage_yen']:,.0f}円|{z['actual_fee_yen']:,.0f}円|{z['actual_net_yen']:,.0f}円|{n['mid_reverse_count']}/{n['parent_count']}|")
    lines += ['','負け親だけに限定しても、純損失を「負の中値変化−正の中値変化＋横断＋実料」に分解できる。順行した小幅親と真に逆行した親を混ぜて費用だけと断定しない。','']
    for s in run.CAP:
        z=group[s]['負親'];allz=group[s]['全親']
        lines += [f"- {s}の負け{z['parent_count']}親：中値変化合計{z['mid_direction_yen']:,.0f}円、横断{z['crossing_disadvantage_yen']:,.0f}円、料{z['actual_fee_yen']:,.0f}円、純損失{z['actual_net_yen']:,.0f}円。非逆行でも負けた親は{z['nonnegative_mid_but_net_loss']}。途中費用後黒字あり{z['once_positive_liquidation_count']}、黒字なし{z['never_positive_liquidation_count']}。WIDE起動線到達は負け{z['peak_reached_wide_arm']}親。全親の支持更新あり{allz['support_updated_parents']}/{allz['parent_count']}。"]
    lines += ['','赤字上位3場の最大負け親は各商品で次の3件。時刻は価格代理時計、seqは原列。六親すべて親純損失停止で、支持線更新は0件だった。','']
    for s in run.CAP:
        for e in examples[s]:
            en,ex,be=e['entry'],e['exit_fill'],e['best'];pub=e['publication']
            n=pub['volume_up']+pub['volume_down']
            lines += [f"- {s} {e['session']} 親{e['parent']}：{'買' if e['side']==1 else '売'}{e['q']}枚。公開{pub['JST_price_proxy']}（seq{pub['raw_seq']}）、出来高代理{n}票・釣合い{pub['volume_signed_balance']:.3g}、自己/相手価格票{pub['own_price_count']}/{pub['peer_price_count']}・釣合い{pub['own_price_balance']:.3g}/{pub['peer_price_balance']:.3g}。FAK{e['adverse_ticks']}T。入口{en['JST_price_proxy']} BBO{en['bid']:g}/{en['ask']:g} → 返済{ex['JST_price_proxy']} BBO{ex['bid']:g}/{ex['ask']:g}、親net{e['net']:,.0f}円。最良は{be['JST_price_proxy']} BBO{be['bid']:g}/{be['ask']:g}・局所{e['peak']:,.0f}円、WIDE arm{e['wide_arm']:,.0f}円に未到達。"]
    lines += ['','**次は入口後の継続失敗と、保護線が作れない過程を切り分ける余地がある。** 現在の「反対代理票の増加＋逆進行しない＋2T再進行」は方向継続を保証しなかった。上の六例は費用後黒字がない3親と、小黒字後に逆行した3親に分かれるため、利確だけの変更では前者を救えると推定しない。保護armを低くする案も、回復する勝ちを切る反証を伴う。','',
              '勝ち反証として、同じ③WIDEの上位2黒字親を各商品から保存した。強さ区分や票数だけを負け例に合わせて除外しない。']
    for s in run.CAP:
        for w in wins[s]:
            v=w['publication'];n=v['volume_up']+v['volume_down']
            lines += [f"- {s} {w['session']} 親{w['parent']}：net{w['net']:,.0f}円、公開出来高代理{n}票・釣合い{v['volume_signed_balance']:.3g}、自己/相手価格釣合い{v['own_price_balance']:.3g}/{v['peer_price_balance']:.3g}、支持更新{w['support_updates']}件。"]
    lines += ['','改善は未検証。初期spreadを見て未来の拡幅を予測したとは扱わず、未保存peer板・更新時計・心理を補完しない。原結果コピーの一目的1読以外に、元金融・台帳・cache・API・追加金融は0。']
    REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    assert source==run.sources()
    print(json.dumps(dict(全合格=True,小結bytes=len(raw.encode('utf-8')),小結SHA256=run.sha(SUMMARY),MD_SHA256=run.sha(REPORT)),ensure_ascii=False))


if __name__=='__main__':
    main()
