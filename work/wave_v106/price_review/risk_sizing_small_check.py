"""299小射影と代表10候補の同定・予定金額を独立算術で検算する。"""

from collections import Counter
from pathlib import Path
import hashlib
import json
import math

from risk_sizing_oracle import fee, sized_quantity, VALUE, CAP, LOSS


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def read(path: Path) -> dict:
    """
    機能: 保存小JSONをUTF-8で読取専用解析する。
    引数: path(Path)は小資料の位置。
    返り値: dictは保存値。大入力及び金融台帳は読まない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: 小JSON又はsourceのSHA256を求める。
    引数: path(Path)は小資料の位置。
    返り値: strは同bytesの指紋。大入力に適用しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def near(actual: float, expected: float) -> None:
    """
    機能: 独立算術と保存金額を小さい絶対誤差で比較する。
    引数: actual/expected(float)は有限金額。
    返り値: None。非有限値及び1e-8円以上の差は拒否する。
    """
    assert math.isfinite(actual) and math.isfinite(expected) and math.isclose(actual,expected,rel_tol=1e-13,abs_tol=1e-8)


def qualifies(base: dict, mode: str) -> bool:
    """
    機能: 母三条件の真偽を既知資格と厳密方向境界から独立計算する。
    引数: base(dict)は保存票、mode(str)はVETO/CONFIRM/KNOWN_VETO。
    返り値: boolは元公開採否。実busy又は後続予算を含めない。
    """
    if not base['known'] or base['direction_votes'] < 2:
        return mode=='VETO'
    return base['balance'] >= .25 if mode=='CONFIRM' else base['balance'] > -.25


def subset_check(rows: list[dict], saved: dict) -> None:
    """
    機能: 小射影の部分集合から可用性件数と数量分布を独立算出する。
    引数: rows(list[dict])は公開候補、saved(dict)は保存集計。
    返り値: None。無取引を勝ちと判定せず、集計の整合だけを確認する。
    """
    n=len(rows); known=sum(r['sizing']['known'] for r in rows)
    zero=sum(r['sizing']['known'] and r['sizing']['proposed_quantity']==0 for r in rows)
    distribution=Counter(str(r['sizing']['proposed_quantity']) for r in rows if r['sizing']['known'])
    assert (saved['公開分母'],saved['予定量既知'],saved['予定量未知'],saved['q0公開'],saved['正量公開'])==(n,known,n-known,zero,known-zero)
    assert saved['数量分布']==dict(distribution)
    assert saved['q0割合_全公開分母']==(zero/n if n else None)
    assert saved['q0割合_予定量既知分母']==(zero/known if known else None)


def main() -> None:
    """
    機能: 299小射影の予定q・各場集計と代表10候補の由来を独立検算する。
    引数: なし。小JSONと独立sourceだけを使用する。
    返り値: Noneは新証跡。新金融収支又は入口見送りの有効性を算出しない。
    """
    source=ROOT/'work/wave_v106/size_availability/公開299のATR両気配と予定数量可用性.json'
    cases=ROOT/'work/wave_v106/price_review/new_goal_causes/代表六赤字場と回復勝ちの初回予定数量.json'
    saved=read(source); scenes=read(cases)
    assert digest(source)=='67014ed5401371e86bcbf32f2e5bc94a5cb07e9c27954c8a133040574c3e74fa'
    assert saved['全合格'] and scenes['全合格'] and scenes['対応候補数']==10
    index={(r['symbol'],r['session'],r['publish_normal_row']):r for r in saved['witness']}
    assert len(index)==len(saved['witness'])==299
    measured={}; gates=0
    for key,r in index.items():
        symbol=r['symbol']; oracle=sized_quantity(r['ATR'],r['bid'],r['ask'],LOSS[symbol],symbol); owner=r['sizing']
        assert r['quote_valid'] and oracle['known']==owner['known'] and oracle['quantity']==owner['proposed_quantity']
        assert len(owner['risk_by_quantity'])==CAP[symbol]
        for q,(a,b) in enumerate(zip(oracle['amounts'],owner['risk_by_quantity']),1):
            assert b['quantity']==q and b['affordable']==(a<=LOSS[symbol]); near(a,b['planned_risk_yen'])
        for mode,gate in r['old_gate'].items():
            assert gate['allowed']==qualifies(r['W60'],mode); gates+=1
        measured[key]=oracle
    subsets=0
    for symbol,groups in saved['商品別'].items():
        rows=[r for r in index.values() if r['symbol']==symbol]
        for mode,target in groups.items():
            subset_check(rows if mode=='全公開' else [r for r in rows if qualifies(r['W60'],mode)],target); subsets+=1
    for session,symbols in saved['各場'].items():
        for symbol,groups in symbols.items():
            rows=[r for r in index.values() if (r['symbol'],r['session'])==(symbol,session)]
            for mode,target in groups.items():
                subset_check(rows if mode=='全公開' else [r for r in rows if qualifies(r['W60'],mode)],target); subsets+=1
    # ----------------------------------------
    # 代表を299の同当時行へ結び、旧結果参照の公開同定情報まで小資料同士で照合する。
    references={p:read(ROOT/p) for p in scenes['source'] if p!=source.relative_to(ROOT).as_posix()}
    for path,sha in scenes['source'].items(): assert digest(ROOT/path)==sha
    summaries=[]
    for scene in scenes['診断']:
        key=scene['symbol'],scene['session'],scene['公開normal_row']; r=index[key]; oracle=measured[key]; q=oracle['quantity']
        for key1,key2 in (('paper_parent','paper_parent'),('side','side'),('JST','JST'),('raw_row','raw_row'),
                         ('raw_seq','raw_seq'),('price_time_s','price_time_s'),('公開ATR','ATR'),
                         ('公開bid','bid'),('公開ask','ask'),('元初回枚数','original_qty')):
            assert scene[key1]==r[key2]
        assert scene['元W60']==r['W60'] and scene['三元公開採否']==r['old_gate'] and scene['初回予定q']==q
        assert scene['各整数量']==r['sizing']['risk_by_quantity']
        amount=oracle['amounts'][q-1] if q else 0.
        near(scene['予定q予約額'],amount); near(scene['最小一枚予定額'],oracle['amounts'][0]); near(scene['元枚数予定額'],oracle['amounts'][-1])
        near(scene['内訳']['ATR予約'],q*r['ATR']*VALUE[r['symbol']])
        near(scene['内訳']['気配差予約'],q*(r['ask']-r['bid'])*VALUE[r['symbol']])
        assert scene['内訳']['往復料予約']==2*fee(q,r['symbol'])
        near(scene['予約後予定余白'],LOSS[r['symbol']]-amount)
        assert scene['三元門と予定正量の両方を満たす']=={m:qualifies(r['W60'],m) and q>0 for m in r['old_gate']}
        ref=scene['保存由来']; evidence=references[ref['path']]
        if scene['種類']=='旧代表赤字の負け親':
            selected=[v for v in evidence[ref['場キー']] if v['session']==scene['session']]; assert len(selected)==1
            ps=[selected[0]['初負け']] if scene['symbol']=='TOPIX' else selected[0]['負け親']
            p=[v for v in ps if v['parent']==scene['paper_parent']]; assert len(p)==1; p=p[0]
            point=p['公開']; assert ('買い' if scene['side']==1 else '売り')==p['方向']
            assert scene['保存旧結果の参考']['旧親収支']==p['収支']
        elif scene['種類']=='旧回復勝ちの反証':
            selected=[v for v in evidence['具体例'] if v['id']==ref['具体例ID'] and v['session']==scene['session'] and v['symbol']==scene['symbol'] and v['種類']=='旧勝ち親を赤字化した最大例']; assert len(selected)==1
            p=selected[0]['基準P1L8親']; point=p['実注文'][0]['判断']
            assert p['親']['親']==scene['paper_parent'] and scene['保存旧結果の参考']['旧親収支']==p['親']['収支']
        else:
            selected=[v for v in evidence[ref['場キー']] if v['session']==scene['session'] and v['paper_parent']==scene['paper_parent']]; assert len(selected)==1; p=selected[0]
            point=dict(normal_row=p['normal_row'],raw_seq=p['candidate_raw_seq'],price_time_s=p['candidate_price_time_s'],JST=p['JST'])
            assert p['side']==scene['side'] and p['candidate_raw_row']==r['raw_row']
        assert (point['normal_row'],point['raw_seq'],point['price_time_s'],point['JST'])==(r['publish_normal_row'],r['raw_seq'],r['price_time_s'],r['JST'])
        summaries.append(dict(種類=scene['種類'],商品=scene['symbol'],場=scene['session'],当時時計=scene['JST'],親=scene['paper_parent'],初回予定q=q,最小予定額=oracle['amounts'][0]))
    assert len(summaries)==10
    proof=dict(全合格=True,種別='保存小射影の独立算術と同定確認。新金融ではない。',
        source_SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in [source,cases,Path(__file__),HERE/'risk_sizing_oracle.py']},
        独立再計算公開数=299,母採否確認数=gates,商品及び場別集計数=subsets,代表対応=summaries,
        結論='TOPIX旧赤字4親と旧回復勝ち2親のq0、日経旧赤字3親のq2/q2/q1は保存予定式と一致。悪い入口だけを除外する法則ではない。',
        未測定=['実busy・静観・期限・後続残予算を反映した取引集合','次正常気配の実約定と部分返済','新数量の実損益'],
        原入力=0,原板=0,NPZ=0,API=0,新金融=0,比例損益推定=0)
    output=HERE/'risk_sizing_全299と代表10公開の独立小算術確認.json'; assert not output.exists()
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,公開=299,代表=10,集計=subsets,SHA256=digest(output)),ensure_ascii=False))


if __name__=='__main__': main()
