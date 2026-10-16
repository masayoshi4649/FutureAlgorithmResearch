"""ユーザー訂正後の全場平均10万円を、親平均と分離した純算術で固定する。"""

from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OLD=ROOT/'work/e01_adaptive_price_20261014/audit/owned/旧00106の実容量使用と一取引10万円床の独立算術.json'


def metric(nets: list[float], parent_count: int, floor: float|None) -> dict:
    """
    機能: 全場平均を損失・無取引0込みで求め、旧親平均と別に保存する。
    引数: nets(list[float]) は全33場net、parent_count(int) は完結親数、floor(float|None) は商品別円床。
    返り値: dict は場平均・親平均・主経済床。NK円床NoneをTOPから代用しない。
    """
    assert len(nets)==33 and parent_count>=0
    total=sum(nets);mean=total/33
    return dict(total=total,session_count=33,mean_session_net=mean,
        mean_parent_net=total/parent_count if parent_count else None,
        floor=floor,economic_pass=None if floor is None else mean>=floor)


def main() -> None:
    """
    機能: 旧公開会計の新目標再評価と全場分母/境界の独立人工を保存する。
    引数: なし。旧経済証跡一読と純数値だけで計算する。
    返り値: None。金融・入力・台帳・API や旧証跡を変更しない。
    """
    target=HERE/'目標訂正後の全33場平均十万円と旧32条件の独立算術.json'
    assert not target.exists()
    raw=OLD.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    assert sha=='74bdcae31ce9f0693876aa3b9c42d97d9eecca5a333030ca6c12fd26f5e4bada'
    old=json.loads(raw.decode('utf-8-sig'));assert old['全合格']
    cases=[([100000.]*33,33,True),([100000.]*32+[99999.],33,False),
        ([100000.]+[0.]*32,1,False),([1100000.]*3+[0.]*30,3,True),([0.]*33,0,False),
        ([200000.]*17+[-20000.]*5+[0.]*11,22,True),([200000.]*16+[-20000.]*6+[0.]*11,22,False)]
    observations=[]
    for nets,parents,expected in cases:
        result=metric(nets,parents,100000.)
        assert result['economic_pass']==expected
        observations.append(dict(**result,positive=sum(n>0 for n in nets),negative=sum(n<0 for n in nets),zero=sum(n==0 for n in nets)))
    assert metric([0.]*33,0,None)['economic_pass'] is None
    assert metric([0.]*33,0,None)['mean_session_net']==0 and metric([0.]*33,0,None)['mean_parent_net'] is None
    revised={cid:dict(total=v['費用後収支'],session_count=33,mean_session_net=v['費用後収支']/33,
                     parent_count=v['親数'],mean_parent_net=v['全親平均net円'],session_floor_pass=v['費用後収支']/33>=100000)
             for cid,v in old['公開32条件のTOPIX全親平均'].items()}
    assert len(revised)==32 and not any(v['session_floor_pass'] for v in revised.values())
    current=old['商品別容量と平均']['TOPIX']
    assert current['収支円']==8260 and current['全33平均収支円']==8260/33
    fixed_total=current['旧価格固定全量net合計'];assert fixed_total==78312
    output=dict(全合格=True,新目標='TOPIX全33セッションの手数料後net平均>=100000円。損失/無取引0を全33分母へ含む。',
        必要総net円=3300000,親平均は参考=True,NK円額床未指定=True,従来三基準を維持=True,
        全場平均の独立人工=observations,旧32条件の新目標判定=revised,
        旧選択=dict(total=8260,session_count=33,mean_session_net=8260/33,parent_count=8,mean_parent_net=8260/8,
            新主経済床未達=True,旧価格固定全量事後total=fixed_total,旧価格固定全量事後mean_session_net=fixed_total/33,
            旧価格固定全量事後mean_parent_net=9789.,事後算術は新金融ではない=True),
        trimの定義='上位最大3正net場を除いて残場数で割る。平均親netや全33分母をtrimへ代用しない。従来頑健性と経済床は別flag。',
        表現訂正='以前の『固定10miniなら平均生値幅10.0836pt必要』は旧一取引10万円目標の条件付き算術。現目標は一場容量換算net10ptであり、その場の複数取引合計や可変数量なので一取引の生値幅へ置換しない。',
        範囲='売買係数/退出/数量は未変更。純/core既合格の再実行はせず、評価とそのsource署名を別更新する。',
        旧証跡SHA256=sha,独立sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        金融result再読=0,旧金融再生=0,新金融=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,旧源又は共有変更=0)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
