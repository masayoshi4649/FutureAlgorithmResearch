"""市場を読まず、得点・異家族一致・連続判定・接頭不変を人工で検査する。"""

from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

import selector119 as S

HERE=Path(__file__).resolve().parent
COUNT=Counter()


def check(value: bool,label: str) -> None:
    """
    機能: 人工の不一致をその場で拒否し、検査数を種類別に数える。
    引数: value(bool)は独立な期待条件、label(str)は検査名。
    返り値: None。不一致はAssertionErrorを送出する。
    """
    assert value,label
    COUNT[label]+=1


def build(equity: np.ndarray,position: np.ndarray|None=None,width: np.ndarray|None=None,
          families: list[str]|None=None,fee: float=1.) -> dict:
    """
    機能: 人工だけの資産から純関数を呼び、入力不変と出力の型を確認する。
    引数: equity(float[B,N])、position(int8[B,N]|None)、width(float[N]|None)、
        families(list[str]|None)、fee(float)は人工入力。市場データは受け取らない。
    返り値: dictは六つの選択信号。
    """
    b,n=equity.shape
    p=np.ones((b,n),dtype=np.int8) if position is None else position
    w=np.full(n,10.) if width is None else width
    fam=[str(i) for i in range(b)] if families is None else families
    before=[v.copy() for v in (equity,p,w)];names=list(fam)
    out=S.build_selectors(equity,p,w,fam,fee)
    for a,z in zip((equity,p,w),before):
        np.testing.assert_array_equal(a,z);check(True,'入力改変なし')
    check(fam==names and len(out['specs'])==6,'仕様と家族不変')
    for key,dtype in [('entry',np.int8),('exit_long',np.bool_),('exit_short',np.bool_),('width',np.float64),('valid',np.bool_)]:
        check(out[key].shape==(6,n) and out[key].dtype==dtype,'寸法と型')
    check(not np.any(out['exit_long']&out['exit_short']),'両方向退出の同時成立なし')
    return out


def expect_rejected(call: object,label: str) -> None:
    """
    機能: 不正な接口入力が静かに救済されず拒否されることを調べる。
    引数: call(Callable[[],object])は人工呼出、label(str)は理由。
    返り値: None。期待したValueErrorが出ない場合は失敗する。
    """
    try:
        call()
    except ValueError:
        check(True,label)
    else:
        raise AssertionError(label)


def main() -> None:
    """
    機能: 全六条件を純人工で検査し、市場未読の証跡だけを保存する。
    引数: なし。
    返り値: None。金融成績・成功確率を作成しない。
    """
    target=HERE/'全玉清算教師の選択と接頭不変の純人工.json'
    check(not target.exists(),'人工の上書き禁止')
    n=300;t=np.arange(n,dtype=float)
    e=np.vstack([t*3,t*2]);p=np.ones((2,n),dtype=np.int8)
    out=build(e,p)
    for pair,h in enumerate((20,60,120)):
        for k in (2*pair,2*pair+1):
            check(not out['valid'][k,:h].any(),'最初H分は未準備')
            check(out['valid'][k,h] and out['entry'][k,h]==0,'最初の有効観測だけでは新規なし')
            check(out['entry'][k,h+1]==1 and not out['exit_short'][k,h+1],'二列連続で新規')
            check(out['exit_short'][k,h+2] and not out['exit_long'][k,h+2],'三列反対で保有側退出')
    # ----------------------------------------
    # 価格差だけなら優位な教師が、途中の大きい下落で劣後する反例。
    a=np.r_[np.arange(11)*10.,100.-np.arange(1,n-10)*5.]
    d=np.vstack([a,t*2]);pd=np.vstack([np.ones(n,dtype=np.int8),-np.ones(n,dtype=np.int8)])
    manual_score_a=50.-.5*(100.-50.)
    check(manual_score_a==25. and 40.>manual_score_a,'独立算数の時価下落罰')
    dd=build(d,pd)
    check(dd['entry'][0,21]==-1,'含み下落で最高教師が変わる')
    # 窓より前の高値は、その後も窓内の最大時価下落へ残さない。
    old=np.r_[10000.,np.zeros(9),np.arange(n-10)*2.]
    roll=build(np.vstack([old,t]),pd)
    check(roll['entry'][0,35]==1,'窓外ピークは下落に使わない')
    # ----------------------------------------
    # 同家族を二票へ水増しせず、相手が中立なら新規へ差替えない。
    ep=np.vstack([t*5,t*4,t*3]);pp=np.vstack([np.ones(n,dtype=np.int8),np.ones(n,dtype=np.int8),-np.ones(n,dtype=np.int8)])
    fam=build(ep,pp,families=['同じ入口','同じ入口','別の入口'])
    check(fam['entry'][0,22]==1 and fam['valid'][1,22] and fam['entry'][1,22]==0,'上位二人でも異家族を選ぶ')
    one=build(e,p,families=['同じ入口','同じ入口'])
    check(one['valid'][0,22] and not one['valid'][1].any(),'一つの家族だけでは二家族なし')
    pp[2]=0;neutral=build(ep,pp,families=['A','A','B'])
    check(neutral['valid'][1,22] and neutral['entry'][1,22]==0,'二家族の一方中立は一致なし')
    flat=p.copy();flat[0]=0;flat[1]=1;fl=build(e,flat)
    check(fl['valid'][0,22] and fl['entry'][0,22]==0,'最高教師が中立でも次位へ差替えなし')
    tie=build(np.vstack([t,t]),pd)
    check(tie['entry'][0,22]==1 and tie['entry'][1,22]==0,'同点は固定入力順')
    # ----------------------------------------
    # 料金境界は厳密超過。連続する中立は退出条件でなく確認の切断。
    hurdle=build(np.vstack([t*.5,t*.5]),p,fee=5.)
    check(not hurdle['valid'][0,20] and hurdle['entry'][0,20]==0,'料金二倍ちょうどは不参加')
    above=build(np.vstack([t*.5001,t*.5001]),p,fee=5.)
    check(above['valid'][0,20] and above['entry'][0,21]==1,'料金二倍より上だけ参加')
    flip=p.copy();flip[:,22:25]=-1;flip[:,25]=0;flip[:,26:29]=-1
    change=build(e,flip)
    check(not change['exit_long'][0,22:24].any() and change['exit_long'][0,24],'反対二列は退出しない')
    check(change['entry'][0,25]==0 and not change['exit_long'][0,25] and not change['exit_short'][0,25],'中立は退出でない')
    check(not change['exit_long'][0,26:28].any() and change['exit_long'][0,28],'中立後は反対の連続をやり直す')
    # ----------------------------------------
    # 一教師の欠測も、共通比較の履歴を切る。不正な幅も同様。
    gap=e.copy();gap[1,25]=np.nan;wg=np.full(n,10.);wg[30]=0.
    go=build(gap,p,wg)
    check(not go['valid'][:,25].any() and not go['valid'][:,30].any(),'欠測と幅不正は全選択を停止')
    check(not go['valid'][0,31:51].any() and go['valid'][0,51],'gap後H分の履歴を再準備')
    check(go['entry'][0,51]==0 and go['entry'][0,52]==1,'gap前の新規連続は持越しなし')
    rawwidth=np.linspace(10.,20.,n);wo=build(e,p,rawwidth)
    for k in range(6):np.testing.assert_array_equal(wo['width'][k],rawwidth);check(True,'現在幅を全選択へ接続')
    er=e.copy();pr=p.copy();wr=rawwidth.copy()
    for a0 in (er,pr,wr):a0.setflags(write=False)
    build(er,pr,wr)
    # ----------------------------------------
    # 未来の得点・方向・幅を破壊しても、既知接頭の全配列を変えない。
    rng=np.random.default_rng(119)
    eq=np.cumsum(rng.normal(1.,2.,size=(5,n)),axis=1)
    pos=np.asarray(rng.integers(-1,2,size=(5,n)),dtype=np.int8)
    wid=np.linspace(2.,8.,n);eq[1,40]=np.nan;wid[143]=np.nan
    families=['A','A','B','C','C'];full=build(eq,pos,wid,families)
    cuts=(0,1,19,20,21,22,59,60,61,62,119,120,121,142,143,144,264,265,299,300)
    fields=('entry','exit_long','exit_short','width','valid')
    for cut in cuts:
        pre=build(eq[:,:cut],pos[:,:cut],wid[:cut],families)
        check(pre['specs']==full['specs'],'仕様は未来長非依存')
        for name in fields:
            np.testing.assert_array_equal(pre[name],full[name][:,:cut]);check(True,'短い接頭と全入力が一致')
        for variant in range(3):
            x=eq.copy();y=pos.copy();z=wid.copy()
            if variant==0:x[:,cut:]=rng.normal(1000.,10000.,size=x[:,cut:].shape);y[:,cut:]=-1;z[cut:]=1000.
            elif variant==1:x[:,cut:]=np.nan;y[:,cut:]=0;z[cut:]=np.nan
            else:x[:,cut:]=-1e8;y[:,cut:]=1;z[cut:]=0.
            changed=build(x,y,z,families)
            for name in fields:
                np.testing.assert_array_equal(changed[name][:,:cut],full[name][:,:cut]);check(True,'未来三種類破壊で接頭不変')
    expect_rejected(lambda:S.build_selectors(e,p.astype(np.int64),np.ones(n),['A','B'],1.),'方向の型不正を拒否')
    bad=p.copy();bad[0,0]=2
    expect_rejected(lambda:S.build_selectors(e,bad,np.ones(n),['A','B'],1.),'方向の符号不正を拒否')
    expect_rejected(lambda:S.build_selectors(e,p,np.ones(n-1),['A','B'],1.),'幅の寸法不正を拒否')
    expect_rejected(lambda:S.build_selectors(e,p,np.ones(n),['A'],1.),'家族の寸法不正を拒否')
    expect_rejected(lambda:S.build_selectors(e,p,np.ones(n),['A',''],1.),'家族の空文字を拒否')
    expect_rejected(lambda:S.build_selectors(e,p,np.ones(n),['A','B'],-1.),'料金の不正を拒否')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'selector119.py',Path(__file__))}
    proof=dict(全合格=True,scope='市場未読の六選択器純人工。未返済時価/料金足切り/異家族/二列新規/三列反対退出/gap/未来接頭。収益有効性の試験ではない。',
        固定六条件=full['specs'],検査数=dict(COUNT),検査合計=sum(COUNT.values()),未来切断点数=len(cuts),未来変更数=len(cuts)*3,
        source_SHA256=hashes,入力契約='一分格子。欠落列はNaNを保持。圧縮された実時間gapはこの純函数から検出不可。',
        未検証=['同商品同qtyでの教師資産生成・直前BBOの因果性は呼出側へ委譲。','全open時価と返済料を使う点が旧完了親ゲートとの差。将来の勝率又は利益保証ではない。','根の20分幅を実entry起点のstopへ接続する経済エンジンは対象外。','実保有の有無を見ず退出述語を返す。実long/shortにだけ適用する責任は呼出側。'],
        市場読取=0,新金融再生=0,原入力=0,大型台帳=0,API=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print('純人工合格',sum(COUNT.values()),hashlib.sha256(target.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':
    main()
