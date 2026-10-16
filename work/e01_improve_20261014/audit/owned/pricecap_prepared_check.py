"""公開価格制限の準備仮説と拡幅の別性を、保存43小資料と純人工で敵対確認する。"""

from collections import Counter
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import math


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SAVED = ROOT/'work/e01_cross_market_20261014/diagnosis/公開からD0新規への価格悪化と拡幅の43親小測定.json'
EXPECTED = '6e8dd984dcfb38d686a2520d0af8da5e9e8ffdd2be9f5285be71b141901b633a'


def publish(side: int, bid: float, ask: float, tick: float, allowance: int) -> dict:
    """
    機能: 公開時の片側 BBO と許容呼値だけから不変価格制限を作る純人工仕様を定義する。
    引数: side(int) は買1/売-1、bid/ask/tick(float) は公開気配と観測呼値、allowance(int) は0又は1。
    返り値: dict は予約状態と公開時制限。正式実装や将来の first quote は参照しない。
    """
    assert side in (-1,1) and allowance in (0,1) and 0 < bid < ask and tick > 0
    price = Decimal(str(ask if side==1 else bid))
    limit = price + side*allowance*Decimal(str(tick))
    return dict(side=side, limit=float(limit), status='待機', anchor_accepted=True,
                first_normal_row=None, fill_price=None, fee_orders=0)


def observe(state: dict, row: int, bid: float, ask: float, normal: bool) -> dict:
    """
    機能: 既公開後に到着した一行を処理し、最初の正常気配だけで全量成立又は失効する人工を定義する。
    引数: state(dict) は純人工予約、row(int) は公開後行、bid/ask(float) とnormal(bool) は当行気配。
    返り値: dict は一回消費後の状態。後続の有利気配で同予約を救済しない。
    """
    result=deepcopy(state)
    if result['status']!='待機' or not normal:
        return result
    assert row>0 and math.isfinite(bid) and math.isfinite(ask) and 0<bid<ask
    price=ask if result['side']==1 else bid
    result['first_normal_row']=row
    if result['side']*(price-result['limit'])<=0:
        result.update(status='成立',fill_price=price,fee_orders=1)
    else:
        result['status']='失効'
    assert result['anchor_accepted']
    return result


def main() -> None:
    """
    機能: 保存43親の価格不利/拡幅を独立再集計し、公開固定・最初の正常・未来 suffix の人工反例を記録する。
    引数: なし。保存小資料と旧公開制限 source のみを使う。
    返り値: None。所有領域の未存在 scope と準備監査を保存。金融・入力・台帳・API は0。
    """
    scope=HERE/'公開FAKと少数票及び保護の準備監査計画.json'
    target=HERE/'公開一回FAKの反例と旧制限差及び43小価格の独立確認.json'
    assert not scope.exists() and not target.exists()
    scope.write_text(json.dumps(dict(目的='正式経済部品の実装前に、公開固定価格と将来約定判定を分離し反証を整理。',
        小資料各一読=[SAVED.relative_to(ROOT).as_posix()],
        旧重複候補='00096の実装源はwave_v100。判断価格上限と今回の注文価格制限を別部品として比較。',
        新政策='preparedのみ。18新政策＝4入口×2FAK許容×2目標＋min4成行×2目標。新GU9×66=594、政策18×66=1188。',
        主基準='65%・全33赤字20%以下・最大赤字<=平均黒字net。未指定の最低活動率は追加しない。0行を勝ちとはしない。',
        大型入力=0,台帳=0,原板=0,NPZ=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    saved=SAVED.read_bytes()
    assert hashlib.sha256(saved).hexdigest()==EXPECTED
    value=json.loads(saved.decode('utf-8-sig'))
    assert value['全合格'] and len(value['実親'])==43
    groups={}
    examples=[]
    for symbol in ('TOPIX','NK225'):
        tick=.5 if symbol=='TOPIX' else 10.
        groups[symbol]={}
        for outcome in ('勝ち','負け','全親'):
            parents=[p for p in value['実親'] if p['symbol']==symbol and (outcome=='全親' or p['元勝敗']==outcome)]
            count=Counter()
            for p in parents:
                side=p['side'];pub=p['公開'];fill=p['実新規']
                price=pub['ask' if side==1 else 'bid']
                current=fill['ask' if side==1 else 'bid']
                unfavorable=side*(current-price)
                spread=fill['ask']-fill['bid']>pub['ask']-pub['bid']
                assert p['公開新規側価格']==price and p['実fill新規側価格']==current
                assert p['新規側不利価格変化']==(unfavorable>0)
                assert math.isclose(p['不利価格変化呼値'],unfavorable/tick)
                assert p['気配幅拡大']==spread
                assert p['両条件AND']==(unfavorable>0 and spread)
                assert p['どちらかOR']==(unfavorable>0 or spread)
                count['新規側不利価格変化']+=unfavorable>0
                count['気配幅拡大']+=spread
                count['両条件AND']+=unfavorable>0 and spread
                count['どちらかOR']+=unfavorable>0 or spread
                count['価格不利のみ']+=unfavorable>0 and not spread
                count['拡幅のみ']+=unfavorable<=0 and spread
                count['FAK0価格条件不成立']+=unfavorable>0
                count['FAK1価格条件不成立']+=unfavorable>tick
                if outcome=='負け' and symbol=='TOPIX':
                    examples.append(dict(session=p['session'],paper_parent=p['paper_parent'],side=side,
                        公開原seq=pub['raw_seq'],fill原seq=fill['raw_seq'],公開新規側=price,実新規側=current,
                        不利観測呼値=unfavorable/tick,公開気配幅=pub['ask']-pub['bid'],実fill気配幅=fill['ask']-fill['bid'],
                        価格条件FAK0=(unfavorable<=0),価格条件FAK1=(unfavorable<=tick),拡幅=spread,
                        留保='旧実親の二端点に対する価格条件のみ。新FAKの約定・後参加・損益とは呼ばない。'))
            expected=value['集計'][symbol][outcome]
            assert expected['分母']==len(parents)
            for key,n in expected['counts'].items():
                assert count[key]==n and math.isclose(expected['rates'][key],n/len(parents))
            groups[symbol][outcome]=dict(分母=len(parents),条件数=dict(count))
    assert groups['TOPIX']['負け']['条件数']['拡幅のみ']==2
    assert groups['NK225']['負け']['条件数']['新規側不利価格変化']==2
    # ----------------------------------------
    # 価格上限と幅を別にする買売対称の純反例。oldsourceの挙動とは混ぜない。
    artificial=[]
    cases=[('同価格の拡幅',99.,101.,True),('同幅の不利価格',101.,102.,False),
           ('価格も幅も不利',100.,102.,False),('同価格同幅',100.,101.,True),
           ('有利価格で下方向へ進行',99.,100.,True)]
    for side in (1,-1):
        for name,bid,ask,allowed0 in cases:
            # 201を中心に鏡映し、買のprice差・支持側差を売へ完全対称にする。
            pub_bid,pub_ask=100.,101.
            if side==-1:
                bid,ask=201.-ask,201.-bid
            for allowance in (0,1):
                state=publish(side,pub_bid,pub_ask,1.,allowance)
                prefix=observe(state,1,0.,0.,False)
                assert prefix==state and prefix['status']=='待機'
                end=observe(prefix,2,bid,ask,True)
                price=ask if side==1 else bid
                expected=side*(price-(101. if side==1 else 100.))<=allowance
                assert (end['status']=='成立')==expected
                assert end['anchor_accepted'] and end['first_normal_row']==2
                if allowance==0:
                    assert expected==allowed0
                for next_bid,next_ask in ((70.,71.),(130.,131.)):
                    suffix=observe(end,3,next_bid,next_ask,True)
                    assert suffix==end
                artificial.append(dict(事例=name,side=side,許容呼値=allowance,公開制限=state['limit'],
                    次正常bid=bid,次正常ask=ask,結果=end['status'],未来suffix不変=True,
                    失効でも初受理保持=end['anchor_accepted']))
    assert len(artificial)==20
    # 公開状態は将来初気配が変わっても同じ。成立状態が変わるのはその気配観測後だけ。
    for side in (1,-1):
        state=publish(side,100.,101.,1.,0)
        opposite=deepcopy(state)
        good=observe(state,1,100.,101.,True)
        bad=observe(opposite,1,102.,103.,True) if side==1 else observe(opposite,1,98.,99.,True)
        assert state==opposite and good['status']=='成立' and bad['status']=='失効'
    # old00096のトレンド新規は判断上限を越す将来fillを取り消していない。
    old_files=[ROOT/'アルゴリズム調査/00096_元候補からの入口価格上限と安定性/README.md',
        ROOT/'work/wave_v100/catalog.py',ROOT/'work/wave_v100/engine.py',
        ROOT/'work/wave_v100/analysis/assemble.py']
    old_sources={}
    for path in old_files:
        saved=path.read_bytes();old_sources[path.relative_to(ROOT).as_posix()]=hashlib.sha256(saved).hexdigest()
        source=saved.decode('utf-8-sig')
        if path.name=='engine.py':
            assert '上限は候補価格からの判断だけに作用し、予約後の成行約定は変更しない' in source
            assert 'if is_entry and source == 1 and not recovery_market' in source
            assert 'fill = asks[i] if action == 1 else bids[i]' in source
        if path.name=='catalog.py':
            assert "CAPS = (('P0', None), ('P05', .5), ('P1', 1.), ('P2', 2.))" in source
            assert "value['range_budget'] == 0" in source
    hypotheses=[
        dict(部品='公開価格固定のFAK0/1',論理='当時の入口価格だけを固定するので未来価格を公開maskへ渡さず、不利な第一正常価格では注文が成立しない。',
            反証='同値で反対側気配だけ不利になる拡幅は成立する。全ての方向誤り、初期清算損失、損切りギャップは防がない。',
            必須実装=['価格条件はpending実新規だけ。仮想paperの約定や既実新規を事後削除しない。',
                '第一normalを一回消費し、不成立後の第二有利normalへ待ち続けない。',
                '正常気配がまだない未完成prefixでは予約を保持。完成場のquiet/期限取消順位は元経済を維持し人工で照合する。',
                '失効実新規に実料・実UID返済を作らない。保有予約を解放して後の全feedを再参加させる。',
                '未約定でも初受理q/R/目標アンカーは保持。q0・元入口拒否・busy拒否を初受理へ置換しない。']),
        dict(部品='G50N4',論理='釣合い0.5で2票だけの不安定な比率を避ける単独対照。成行版を分けてFAK効果と票数効果を分離する。',
            反証='旧B01の敗戦は20票で釣合い0.7。min4だけでは既敗戦を拒否できない。B0315勝のうち7が2票なので、min4は旧勝ちも減らし得る。',
            必須実装=['票数の変更は公開の既知方向票だけ。事後勝敗やfirstfillの価格差は入口へ渡さない。',
                '4更新は独立4注文又は攻撃数量を保証しない。結果は全feed再参加を含めて判定する。']),
        dict(部品='途中利益保護',論理='費用後清算が正に進んだ後の戻しを逐次止める余地はある。',
            反証='元TOP7敗中6敗/NK2敗中2敗は一度も費用後黒字なし。利益保護の始動前に損失が出る原因には効かない。B03の途中逆行も利確前なので出口だけで消せるとは言えない。',
            必須実装=['事後peak/MAEを閾値へ流用せず、当時までの清算高水準だけを使う。',
                'floor0の判定でも次normalの実価格は0円利益を保証しない。',
                'FAK/票数と一度に保護を改修して帰属を曖昧にしない。現18条件では途中管理を維持する。'])]
    output=dict(全合格=True,状態='準備の仮説と純人工が合格。新正式源・新金融の有効性は未測定。',
        小43価格資料SHA256=EXPECTED,旧00096source_SHA256=old_sources,
        独立再集計=groups,旧TOP敗親の価格条件=examples,純人工20反例=artificial,
        未指定基準='最低活動率やデイ成功数を新たな合格条件へ足さない。活動/無取引/夜間偏りは参考として明示し0行を勝ちにしない。',
        次18案=dict(新GU予定=594,新政策予定=1188,保存成行政策比較=6,金融実行=0,
            観測呼値=dict(TOPIX=.5,NK225=10.),
            呼値表現='今回の許容1観測呼値は親が定めたラージ観測刻み。mini/micro商品2呼値であり、商品1呼値とは呼ばない。',
            母ごと対照='G25/G50/G75のP1/.25Rは旧同一政策を再利用。G50N4だけ新成行の単独対照を作る。'),
        仮説と反証=hypotheses,
        重複確認の範囲='00096公式READMEとwave_v100の直接catalog/engine/assembleを静的照合。母戦略/31場/数量8-16/候補判断上限と新E01/33場/可変q/公開FAK失効は異なる。過去全試行の完全一致判定をこの4源だけで保証しない。正式八部品とregistryの照合は別途必要。',
        留保=['43は旧完結実親の端点比較で全公開候補ではない。旧親の見送りを新収支へ置換しない。',
            '公開時の幅審査と第一気配での幅審査を混同しない。注文済み成行を同じfill行の拡幅で事後取消する模型は採らない。',
            '真のFAK到達時刻、mini/micro板厚み、部分成立、待ち順位は未観測。正常ラージ片側気配で全量又は零の代理を使う範囲を明示する。',
            '公開制限内で有利なfillでも、価格が戦略と逆に動くため有利約定になった場合がある。価格capは方向の正しさとは別。'],
        独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        新金融=0,金融結果読取=0,大型入力=0,台帳=0,原板=0,NPZ=0,API=0,共有及び旧source変更=0)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,純反例=20,旧小親=43,SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
        TOP負親=groups['TOPIX']['負け'],NK負親=groups['NK225']['負け']),ensure_ascii=False))


if __name__=='__main__':
    main()
