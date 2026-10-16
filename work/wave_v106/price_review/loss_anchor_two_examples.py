"""二つの損切りと旧実利確を、気配・実料・原行時計の小保存値だけで独立確認する。"""

from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
import hashlib
import json
import math


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 授権された診断及び自所有の既監査小JSONだけを取得する。
    引数: path(Path)は小JSON。
    返り値: tuple[dict,str]は保存値と同読取SHA256。大台帳・packetは読まない。
    """
    assert path.suffix=='.json'
    saved=path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')),hashlib.sha256(saved).hexdigest()


def order_fee(quantity: int, symbol: str) -> int:
    """
    機能: ユーザー指定の片道注文料を整数円へ独立切り捨てする。
    引数: quantity(int)、symbol(str)は実枚数と商品。
    返り値: intは注文一つの実料。親単位の概算を使わない。
    """
    unit=Decimal('41.8') if symbol=='TOPIX' else Decimal('11')
    return int((unit*quantity).to_integral_value(rounding=ROUND_FLOOR))


def net(side: int, quantity: int, entry: float, exit: float, symbol: str) -> Decimal:
    """
    機能: 同一親・部分無しの新規と返済から実料後損益を独立算出する。
    引数: side/quantity(int)、entry/exit(float)、symbol(str)は実注文の保存値。
    返り値: Decimalは実料後net。最高値又は事後救済価格を使わない。
    """
    multiplier=Decimal(1000 if symbol=='TOPIX' else 10)
    return side*quantity*(Decimal(str(exit))-Decimal(str(entry)))*multiplier-2*order_fee(quantity,symbol)


def quote_check(row: dict) -> None:
    """
    機能: 保存した価格代理時計・原seq・通常行及び正BBO資格を確認する。
    引数: row(dict)は小保存気配。
    返り値: None。不観測の受信時刻又は厚みを追加しない。
    """
    assert row['quote_valid'] and 0<row['bid']<row['ask']
    for key in ('last','bid','ask','price_time_s'):assert math.isfinite(row[key])
    for key in ('normal_row','raw_seq'):assert type(row[key]) is int and row[key]>=0
    parsed=datetime.fromisoformat(row['価格代理JST'])
    assert parsed.utcoffset().total_seconds()==9*3600 and parsed.timestamp()==row['price_time_s']


# ----------------------------------------
def main() -> None:
    """
    機能: 二実例の損益・原行順序・旧実利確・必要呼値を純算術で確認する。
    引数: なし。根の完了通知に記載された診断指紋だけを受理する。
    返り値: Noneは自所有小監査。金融再生・大資料追加読取を行わない。
    """
    path=ROOT/'work/wave_v106/loss_stop_diagnosis/同一初回の比例損切りと旧回復実利確の二例.json'
    data,sha=read(path);assert sha=='6cc4f5569713938282e01d8ffb0d3ca39743d4c177b5ec259330d704af0e9139'
    old_path=HERE/'goal_anchor_全264小会計と寄与境界及び最新三基準の独立確認.json'
    new_path=HERE/'loss_anchor_全264小会計と比例境界及び最新三基準の独立確認.json'
    old,old_sha=read(old_path);new,new_sha=read(new_path)
    assert old['全合格'] and new['全合格'] and data['全合格'] and data['source開始終端一致']
    assert data['台帳一読']==4 and data['input一読']==2
    assert data['金融再生']==data['原板読取']==data['NPZ読取']==data['API']==0
    assert len(data['results'])==2
    proofs=[]
    for case in data['results']:
        symbol=case['symbol'];entry=case['初回実新規'];published=case['公開']
        judgment=case['比例損失判断'];new_exit=case['次正常返済'];prior=case['旧後続の実返済'];control=case['旧停止判断']
        assert len(prior)==1 and len(new_exit['実返済注文'])==1 and all(case['単純数式の前提'].values())
        before=prior[0];side=entry['side'];quantity=entry['quantity'];price=entry['entry_price']
        for row in (published,entry,judgment,new_exit,before):quote_check(row)
        assert side in (1,-1) and 0<quantity<=(5 if symbol=='TOPIX' else 10)
        assert price==entry['ask' if side==1 else 'bid']
        assert entry['normal_row']==published['normal_row']+1 and entry['raw_seq']==published['raw_seq']+1
        assert published['price_time_s']<=entry['price_time_s']<=judgment['price_time_s']<=new_exit['price_time_s']<before['price_time_s']
        assert published['raw_seq']<entry['raw_seq']<judgment['raw_seq']<new_exit['raw_seq']<before['raw_seq']
        assert new_exit['normal_row']==judgment['normal_row']+1 and new_exit['raw_seq']==judgment['raw_seq']+1
        order=new_exit['実返済注文'][0];old_order=before['注文']
        for observed,order_row,source,parent,reason in ((order,new_exit['normal_row'],judgment['normal_row'],case['parent'],95),
                (old_order,before['normal_row'],control['判断行'],case['parent'],94)):
            assert observed[:5]==[order_row,source,parent,-side,quantity]
            assert observed[6:]==[reason,0]
        assert order[5]==new_exit['ask' if -side==1 else 'bid']
        assert old_order[5]==before['ask' if -side==1 else 'bid']
        initial_quote=entry['bid' if side==1 else 'ask'];judge_quote=judgment['bid' if side==1 else 'ask']
        initial_net=net(side,quantity,price,initial_quote,symbol)
        judgment_net=net(side,quantity,price,judge_quote,symbol)
        new_net=net(side,quantity,price,order[5],symbol);old_net=net(side,quantity,price,old_order[5],symbol)
        assert initial_net==Decimal(str(entry['費用後初期清算円']))
        assert judgment_net==Decimal(str(judgment['清算利益円']))
        assert new_net==Decimal(str(case['新損失'])) and old_net==Decimal(str(case['旧利益']))
        assert new_net<0<old_net and judgment_net<=-Decimal(str(judgment['損失線円']))
        assert control['種別']=='利益目標' and control['発動'] and control['以後新規なし'] and not control['未来返済テンプレート参照']
        assert control['判断行']+1==control['返済行']==before['normal_row']
        assert control['判断原seq']+1==control['返済原seq']==before['raw_seq']
        assert control['判断価格時計']<=control['返済価格時計']==before['price_time_s']
        assert control['判断時清算利益']>=control['目標'] and control['実返済後収支']==float(old_net)
        assert control['判断から返済の悪化']==float(old_net)-control['判断時清算利益']
        full=5 if symbol=='TOPIX' else 10;budget=5000 if symbol=='TOPIX' else 2000
        assert control['損失予算']==budget and judgment['損失線円']==budget*quantity/full
        formula=case['単純数式'];multiplier=Decimal(1000 if symbol=='TOPIX' else 10)
        tick=Decimal('.5') if symbol=='TOPIX' else Decimal('10')
        spread=Decimal(str(entry['ask']))-Decimal(str(entry['bid']))
        cost=2*order_fee(quantity,symbol);loss=Decimal(str(formula['損失線円']));profit=Decimal(str(formula['利益線円']))
        adverse=(loss-quantity*spread*multiplier-cost)/(quantity*multiplier)
        favorable=(profit+quantity*spread*multiplier+cost)/(quantity*multiplier)
        assert adverse>0 and favorable>0
        assert formula['初期清算気配']==initial_quote and formula['初期気配差']==float(spread)
        assert formula['往復注文料']==cost and formula['初期費用後清算']==float(initial_net)
        assert formula['初期清算気配から必要逆行幅']==float(adverse)
        assert formula['初期清算気配から必要順行幅']==float(favorable)
        adverse_ticks=int((adverse/tick).to_integral_value(rounding=ROUND_CEILING))
        favorable_ticks=int((favorable/tick).to_integral_value(rounding=ROUND_CEILING))
        assert formula['必要逆行の観測呼値数']==adverse_ticks==1
        assert formula['必要順行の観測呼値数']==favorable_ticks==3
        # 呼値一つ前は境界未到達、切上げ先では到達。予測確率又は救済利益を追加しない。
        adverse_before=initial_net-quantity*(adverse_ticks-1)*tick*multiplier
        adverse_at=initial_net-quantity*adverse_ticks*tick*multiplier
        favorable_before=initial_net+quantity*(favorable_ticks-1)*tick*multiplier
        favorable_at=initial_net+quantity*favorable_ticks*tick*multiplier
        assert adverse_before>-loss>=adverse_at and favorable_before<profit<=favorable_at
        vote=case['W60公開票'];assert vote['known'] and vote['accepted'] and vote['direction_votes']>=2
        assert vote['candidate_raw_seq']==published['raw_seq'] and vote['candidate_price_time_s']==published['price_time_s']
        assert vote['cutoff_price_time_s']==published['price_time_s']-60
        assert vote['first_vote_raw_row']<=vote['last_vote_raw_row']<=vote['candidate_raw_row']
        assert vote['direction_votes']==vote['up_votes']+vote['down_votes']
        expected_balance=side*(vote['up_votes']-vote['down_votes'])/vote['direction_votes']
        assert math.isclose(vote['balance'],expected_balance,abs_tol=1e-15)
        assert vote['balance']>=.25
        # 既監査小境界に保存された受理q・行・線・場netの同値へ接続する。
        compatible=[]
        for cid,rows in new['初回受理境界確認'].items():
            boundary=next(r for r in rows if r['session']==case['session'] and r['symbol']==symbol)
            if (boundary['成立'] and boundary['受理q']==quantity and boundary['受理行']==published['normal_row']
                    and boundary['目標円']==float(profit) and boundary['損失停止線円']==float(loss)):
                assert boundary['初実数量']==quantity and not boundary['受理と初実差'] and boundary['停止']
                assert boundary['比例損失線超過']==max(0.,-float(new_net)-float(loss));compatible.append(cid)
        assert compatible
        proofs.append(dict(session=case['session'],商品=symbol,親=case['parent'],初回数量=quantity,
            方向='買い' if side==1 else '売り',片道料=order_fee(quantity,symbol),往復料=cost,
            初期清算=float(initial_net),新判断清算=float(judgment_net),新実収支=float(new_net),旧実収支=float(old_net),
            旧実との差=float(new_net-old_net),逆行余地=float(adverse),順行必要幅=float(favorable),
            逆行呼値=adverse_ticks,順行呼値=favorable_ticks,
            新判断まで価格時計秒=judgment['price_time_s']-entry['price_time_s'],
            旧実返済まで価格時計秒=before['price_time_s']-entry['price_time_s'],
            次normal隣接=True,原seq因果順=True,当時票算術同値=True,既監査境界と同値の条件ID=compatible))
    result=dict(全合格=True,診断SHA256=sha,診断source_SHA256=data['source_SHA256'],
        既独立goal監査SHA256=old_sha,既独立loss監査SHA256=new_sha,
        既監査金融metadata_SHA256=dict(旧goal=old['source_SHA256'],新loss=new['source_SHA256']),
        二実例独立算術=proofs,
        留保=['元小診断JSONは新旧条件ID・台帳/input個別SHAを直接保存していない。既監査境界との数値同値を確認した範囲に限定。',
              'NK例はCONFIRM_P1とVETO_P1の保存境界が同値で、この小JSONだけでは母条件を一意選択できない。',
              '次normalの隣接原行番号・正BBOは保存された元reader値に依拠する。packetの正常性分類を再測定したとは扱わない。',
              '価格代理時計が同じでも原seqは前進する。真の注文到着時刻・秒遅延は測定していない。',
              '板厚み・補充・真の方向反転・原因の発生確率は未測定。事後ピークで救済したPLは算出しない。'],
        大台帳追加読取=0,packet追加読取=0,原板=0,NPZ=0,API=0,金融=0)
    target=HERE/'loss_anchor_二実例気配損益と必要呼値の独立算術.json';assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,二実例=proofs,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
