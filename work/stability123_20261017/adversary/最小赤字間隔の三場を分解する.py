"""指定された最小累計赤字政策の赤字三場を、保存約定だけから分解する。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from io import BytesIO
import hashlib
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
EXPECTED='91475e3757d4a9462f1ecc9405c43e76145967693b0802c56e73068dd0db416c'
METHOD='I3_G10'
CHOSEN=['2026-10-01_Night','2026-10-13_Day','2026-09-29_Day']
JST=timezone(timedelta(hours=9))


def sha(payload: bytes) -> str:
    """
    機能: 一読済みbytesから指紋を算出する。
    引数: payload(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def stamp(epoch: float) -> str:
    """
    機能: 実epoch秒を日本時間で表示する。
    引数: epoch(float)。
    返り値: strは日付付きJST。
    """
    return datetime.fromtimestamp(float(epoch),JST).isoformat()


def save(path: Path, value: dict) -> None:
    """
    機能: 原本と区別した新規の小資料を保存する。
    引数: path(Path)、value(dict)。
    返り値: None。既存成果を上書きしない。
    """
    assert not path.exists(),path
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def decompose(o: np.ndarray,p: np.ndarray,q: dict,summary: dict) -> dict:
    """
    機能: 玉ごとの新規時Last・実BBO・終端BBOを突き合わせて損益を独立分解する。
    引数: o/p(ndarray)は当該政策の注文と代理玉、q(dict)は保存五列、summary(dict)。
    返り値: dictは各玉・方向別・全体の分解。将来値を新規へ渡す再生は行わない。
    """
    assert len(o)==len(p) and np.all(o[:,1]==1)
    assert len(set(o[:,0]))==len(o)
    mapping={int(v):i for i,v in enumerate(q['row'])}
    lookup={int(v[0]):v for v in p}
    fee=int(Decimal('41.8').to_integral_value(rounding=ROUND_FLOOR))
    multiplier=1000.
    entries=[]
    for order in o:
        uid=int(order[0]);side=int(order[2]);proxy=lookup[uid]
        i=mapping[int(order[4])];end=mapping[int(proxy[7])]
        assert order[13]==q['last'][i] and order[14]==q['bid'][i] and order[15]==q['ask'][i]
        assert proxy[8]==q['time'][end] and proxy[14]==q['last'][end]
        assert proxy[15]==q['bid'][end] and proxy[16]==q['ask'][end]
        entry_bbo=q['ask'][i] if side==1 else q['bid'][i]
        exit_bbo=q['bid'][end] if side==1 else q['ask'][end]
        assert order[7]==entry_bbo and proxy[6]==entry_bbo and proxy[9]==exit_bbo
        last_move=side*(q['last'][end]-q['last'][i])*multiplier
        entry_last_cost=side*(entry_bbo-q['last'][i])*multiplier
        exit_last_cost=side*(q['last'][end]-exit_bbo)*multiplier
        entry_mid=(q['bid'][i]+q['ask'][i])/2
        exit_mid=(q['bid'][end]+q['ask'][end])/2
        midpoint_move=side*(exit_mid-entry_mid)*multiplier
        entry_half_spread=(q['ask'][i]-q['bid'][i])*multiplier/2
        exit_half_spread=(q['ask'][end]-q['bid'][end])*multiplier/2
        net=side*(exit_bbo-entry_bbo)*multiplier-2*fee
        assert net==last_move-entry_last_cost-exit_last_cost-2*fee==proxy[12]
        assert net==midpoint_move-entry_half_spread-exit_half_spread-2*fee
        entries.append(dict(uid=uid,side=side,方向='買い' if side==1 else '売り',rank=int(order[10]),
                            判断原行=int(order[3]),判断JST=stamp(order[5]),
                            新規原行=int(order[4]),新規JST=stamp(order[6]),
                            発火線=float(order[17]),新規Last=float(q['last'][i]),新規bid=float(q['bid'][i]),
                            新規ask=float(q['ask'][i]),建値=float(entry_bbo),
                            代理原行=int(proxy[7]),代理JST=stamp(proxy[8]),予定引けJST=stamp(proxy[13]),
                            代理Last=float(q['last'][end]),代理bid=float(q['bid'][end]),代理ask=float(q['ask'][end]),
                            代理返済価格=float(exit_bbo),Last移動損益=float(last_move),
                            新規Last差_正は不利=float(entry_last_cost),終端Last差_正は不利=float(exit_last_cost),
                            中値移動損益=float(midpoint_move),新規半気配差=float(entry_half_spread),
                            終端半気配差=float(exit_half_spread),往復手数料=2*fee,純損益=float(net)))
    keys=['Last移動損益','新規Last差_正は不利','終端Last差_正は不利','中値移動損益',
          '新規半気配差','終端半気配差','往復手数料','純損益']
    sides={}
    for side,name in [(1,'買い'),(-1,'売り')]:
        chosen=[x for x in entries if x['side']==side]
        sides[name]=dict(枚数=len(chosen),最初の新規JST=chosen[0]['新規JST'] if chosen else None,
                         最後の新規JST=chosen[-1]['新規JST'] if chosen else None,
                         平均建値=sum(x['建値'] for x in chosen)/len(chosen) if chosen else None,
                         最低建値=min(x['建値'] for x in chosen) if chosen else None,
                         最高建値=max(x['建値'] for x in chosen) if chosen else None,
                         **{key:sum(x[key] for x in chosen) for key in keys})
    total={key:sum(x[key] for x in entries) for key in keys}
    assert total['純損益']==summary['net'] and total['往復手数料']==summary['fees']
    assert total['純損益']==total['Last移動損益']-total['新規Last差_正は不利']-total['終端Last差_正は不利']-total['往復手数料']
    assert total['純損益']==total['中値移動損益']-total['新規半気配差']-total['終端半気配差']-total['往復手数料']
    endpoint=entries[-1] if entries else None
    lock=None
    if sides['買い']['枚数'] and sides['買い']['枚数']==sides['売り']['枚数']:
        count=sides['買い']['枚数']
        gap=sides['売り']['平均建値']-sides['買い']['平均建値']
        spread=endpoint['代理ask']-endpoint['代理bid']
        expected=count*(gap-spread)*multiplier-total['往復手数料']
        assert np.isclose(expected,total['純損益'],rtol=0,atol=1e-6)
        lock=dict(片方向枚数=count,買平均に対する売平均の差pt=gap,
                  終端気配差pt=spread,式='枚数×(売平均−買平均−終端気配差)×1000−全往復手数料',
                  計算純損益=expected,留保='保有が両方向同数になった後は、気配差が同じならLastや中値の平行移動では回復しない。')
    return dict(summary=summary,終端=dict(参照JST=endpoint['代理JST'],予定引けJST=endpoint['予定引けJST'],
                Last=endpoint['代理Last'],bid=endpoint['代理bid'],ask=endpoint['代理ask']),
                sides=sides,total=total,両側赤字=all(sides[n]['純損益']<0 for n in ('買い','売り')),
                同数両建て式=lock,entries=entries)


def main() -> None:
    """
    機能: 先に固定された赤字上位三場の保存注文を一読保全して診断する。
    引数: なし。
    返り値: None。金融SOURCE・原板・API・台帳を変更しない。
    """
    out=HERE/'formal_gap10_loss'
    assert not out.exists(),'同じ実結果を再読しません'
    out.mkdir()
    save(out/'診断前の固定.json',dict(method=METHOD,sessions=CHOSEN,
        selection='全40小会計でI3_G10の赤字額上位三場。根担当が結果後に指定した原因診断。',
        result_sha256=EXPECTED,金融再生=0,API=0,原板読取=0))
    source=BASE=HERE.parent/'途中利確なしの十九間隔と全四十場.json'
    raw=source.read_bytes();assert sha(raw)==EXPECTED
    (out/'指定完成結果の同bytes保全.json').write_bytes(raw)
    result=json.loads(raw);del raw
    specs=result['specs'];index=next(i for i,s in enumerate(specs) if s['id']==METHOD)
    rows=[r for r in result['runs'] if r['method']==METHOD]
    assert [r['session'] for r in sorted(rows,key=lambda x:x['net'])[:3]]==CHOSEN
    refs={x['session']:x for x in result['cache']}
    cases={};reads=[]
    for session in CHOSEN:
        ref=refs[session]
        payload=(ROOT/ref['path']).read_bytes();assert sha(payload)==ref['sha256']
        with np.load(BytesIO(payload),allow_pickle=False) as archive:
            orders=archive[f'{index}__orders'].copy();proxy=archive[f'{index}__proxy_lots'].copy()
            quotes={key:archive['quotes__'+key].copy() for key in ('row','time','last','bid','ask')}
        del payload
        memory=BytesIO()
        np.savez_compressed(memory,orders=orders,proxy_lots=proxy,
                            **{'quotes__'+key:value for key,value in quotes.items()})
        local=memory.getvalue();name=out/(session+'_owned.npz');name.write_bytes(local)
        reads.append(dict(source=ref['path'],source_sha256=ref['sha256'],reads=1,
                          arrays=[f'{index}__orders',f'{index}__proxy_lots']+['quotes__'+k for k in quotes],
                          owned=name.relative_to(ROOT).as_posix(),owned_sha256=sha(local)))
        summary=next(x for x in rows if x['session']==session)
        cases[session]=decompose(orders,proxy,quotes,summary)
    save(out/'I3_G10赤字上位三場の注文と値動き及び費用分解.json',dict(
        passed=True,scope='既知40場のI3_G10赤字上位3だけの事後原因診断。選別前予測確率ではない。',
        method=METHOD,policy_index=index,source=dict(path=source.relative_to(ROOT).as_posix(),sha256=EXPECTED,reads=1),
        cache_reads=reads,cases=cases,
        Last分解='純損益=符号×(終端Last−新規時Last)×倍率−新規Last差−終端Last差−往復手数料。Last差の正は不利、負は有利。',
        中値分解='純損益=符号×(終端中値−新規時中値)×倍率−新規半気配差−終端半気配差−往復手数料。',
        留保=['Last基準の差は必ず正の取引コストではない。価格時計の停滞でLastが実BBOから離れることがある。',
              '終端は予定引けそのものの実約定ではなく、直前六分以内の保存済み正常BBO代理。',
              'この三場の赤字を見て、当時避けられた条件や閾値を事後に作らない。'],
        original_result_reads=1,measurement_npz_reads=3,金融再生=0,source変更=0,API=0,原板読取=0))
    lines=['# 10pt間隔でも残った損失', '',
           '初回3pt・以後10pt、途中利確なしの固定条件。累計赤字が最小だった条件の、赤字上位3セッションを事後に調べた。これを新しい予測法則の証拠にはしない。', '',
           '| セッション | 買い枚数／平均建値 | 売り枚数／平均建値 | 終端bid / ask | 買い収支 | 売り収支 | 合計 |',
           '| --- | --- | --- | --- | ---: | ---: | ---: |']
    for session,case in cases.items():
        b,a=case['sides']['買い'],case['sides']['売り'];end=case['終端']
        lines.append(f"| {session} | {b['枚数']} / {b['平均建値']:.2f} | {a['枚数']} / {a['平均建値']:.2f} | {end['bid']} / {end['ask']} | {b['純損益']:+,.0f}円 | {a['純損益']:+,.0f}円 | {case['total']['純損益']:+,.0f}円 |")
    lines += ['', '## 何が減らしたか', '',
              'Lastの移動だけを見た損益から、実新規BBOと当時Lastとの差、終端Lastと実返済BBOとの差、手数料を分けた。差額は正なら不利、負なら有利であり、Last差の全てをスプレッド損と呼ばない。', '',
              '| セッション | Last移動損益 | 新規Last差 | 終端Last差 | 手数料 | 最終収支 |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for session,case in cases.items():
        x=case['total']
        lines.append(f"| {session} | {x['Last移動損益']:+,.0f} | {x['新規Last差_正は不利']:+,.0f} | {x['終端Last差_正は不利']:+,.0f} | {x['往復手数料']:,.0f} | {x['純損益']:+,.0f} |")
    lines += ['', '通常の中値基準で分けた新規・終端の半気配差はJSONに別記した。新規判定時Lastと実新規BBOがずれるため、Lastの上下だけで約定の有利不利を決められない。', '',
              '## なぜ買いも売りも負けるか', '',
              '買い平均が売り平均より高い状態で両側同数を持つと、建値の差を含み損として固定する。終端の価格が買い平均より低く、売り平均より高ければ、買いも売りも赤字になる。両側同数になった後の単純な上昇・下落では、この差は取り返せず、最後の気配差と手数料も残る。', '',
              'ただし、この三場は買4／売6、買4／売5、買2／売6で、どちらも片側10枚に達していない。上限ロックが今回の赤字原因ではない。逆側の枚数は追い越したが、安い位置で増やした売りもその後の回復で赤字となり、高い買いの損も残った。両建てするだけでは元の不利な建値を回収したことにならない。', '',
              '例えば9/29は09:04:34の買い4089.5が終端4062.5で−27082円、14:35:14の売り4037が終端4063.5で−26582円。局所的な反発・反落を追って入ることと、引けまでその方向が有利なことは別である。この三場だけを見て、当時どちらを見送れたかは決められない。']
    for session,case in cases.items():
        lines += ['', f'## {session}の実新規', '',
                  f"引け代理は{case['終端']['参照JST']}、予定引けは{case['終端']['予定引けJST']}。", '',
                  '| 実新規JST | 方向・UID | 段数 | 発火線 | 建値BBO | 新規Last | 終端純損益 |',
                  '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
        for e in case['entries']:
            lines.append(f"| {e['新規JST']} | {e['方向']} {e['uid']} | {e['rank']} | {e['発火線']} | {e['建値']} | {e['新規Last']} | {e['純損益']:+,.0f}円 |")
    lines += ['', '[分解の正本JSON](I3_G10赤字上位三場の注文と値動き及び費用分解.json)']
    (out/'十ポイント間隔の損失原因.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,method=METHOD,
                          cases={k:dict(sides=v['sides'],total=v['total'],lock=v['同数両建て式'],terminal=v['終端']) for k,v in cases.items()},
                          proof_sha256=sha((out/'I3_G10赤字上位三場の注文と値動き及び費用分解.json').read_bytes()),
                          md_sha256=sha((out/'十ポイント間隔の損失原因.md').read_bytes())),ensure_ascii=False))


if __name__=='__main__':
    main()
