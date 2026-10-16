"""新小診断を公開済み会計と独立監査へ照合し、銘柄別事後候補を新成功と扱わない。"""

from pathlib import Path
import hashlib
import json
import math


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
DIAG=ROOT/'work/e01_improve_20261014/diagnosis'
OLD=ROOT/'work/e01_cross_market_20261014/audit'
READS={}
COUNT=0


def read(path: Path) -> dict:
    """
    機能: 新診断と公開済み小会計及び独立証跡だけを各一読する。
    引数: path(Path) は計画に列挙した小 JSON。
    返り値: dict は保存内容。金融結果原本・大型・台帳は開かない。
    """
    assert path.relative_to(ROOT).as_posix() not in READS and '/finance/' not in path.as_posix()
    saved=path.read_bytes();READS[path.relative_to(ROOT).as_posix()]=hashlib.sha256(saved).hexdigest()
    return json.loads(saved.decode('utf-8-sig'))


def same(a: object,b: object) -> None:
    """
    機能: 保存小値を未知・真偽付きで独立資料へ比較する。
    引数: a/b(object) は観測値と期待値。
    返り値: None。比較数を記録し不一致を例外にする。
    """
    global COUNT
    COUNT+=1
    if b is None or isinstance(b,(bool,str)):
        assert a==b,(a,b)
    else:
        assert a is not None and math.isclose(a,b,abs_tol=1e-5,rel_tol=1e-12),(a,b)


def main() -> None:
    """
    機能: 旧価格資格・少票・昼夜・B四条件・一日増益・銘柄別静的候補を小資料だけで監査する。
    引数: なし。新金融又は原金融再読を行わない。
    返り値: None。自所有の新監査 JSON だけを保存する。
    """
    target=HERE/'旧小診断の43価格15票及び銘柄別保存候補の独立確認.json'
    assert not target.exists()
    diag=read(DIAG/'旧小事実と銘柄別候補及び次十八対照の因果順序.json')
    plan=read(DIAG/'小資料だけの原因再整理計画.json')
    finance=read(OLD/'十六対照1056小会計と128期間及び受理円尺度の独立監査_v2.json')
    entry=read(OLD/'実公開票と全返済小価格からの独立算術監査.json')
    price=read(HERE/'公開一回FAKの反例と旧制限差及び43小価格の独立確認.json')
    pub=read(ROOT/'アルゴリズム調査/00104_E01の銘柄差の原因と修正検証/E01の銘柄差と固定16対照の公開会計.json')
    assert all(v['全合格'] for v in (diag,plan,finance,entry,price,pub))
    assert READS[(DIAG/'旧小事実と銘柄別候補及び次十八対照の因果順序.json').relative_to(ROOT).as_posix()]=='3dfa13e8e081acc166fe1336e21fe8aba702d52465698cd23cd2cc9ffbb745cf'
    assert diag['計画SHA256']==READS[(DIAG/'小資料だけの原因再整理計画.json').relative_to(ROOT).as_posix()]
    assert hashlib.sha256((DIAG/'review.py').read_bytes()).hexdigest()==diag['source_SHA256']==plan['source_SHA256']
    assert diag['小本文一読']==3
    for key in ('新金融','API','入力','台帳','原板','NPZ','旧公開編集','共有編集'):
        assert diag[key]==0
    for symbol in ('TOPIX','NK225'):
        for tag in ('勝ち','負け'):
            own=diag['旧執行資格集計'][symbol][tag]
            expected=price['独立再集計'][symbol][tag]
            same(own['分母'],expected['分母'])
            mapping={'不利':'新規側不利価格変化','拡幅':'気配幅拡大','拡幅だけ':'拡幅のみ',
                     'cap0価格不成立':'FAK0価格条件不成立','cap1価格不成立':'FAK1価格条件不成立'}
            for a,b in mapping.items():same(own[a],expected['条件数'][b])
        group=diag['B03母数と昼夜'][symbol]
        evidence=entry['商品別小射影再集計']['E01_CROSS_B03|'+symbol]
        same(group['実親'],evidence['実親数'])
        same(group['二票'],evidence['direction_vote_counts']['2'])
        same(group['二又は三票'],sum(n for key,n in evidence['direction_vote_counts'].items() if int(key)<4))
        same(group['Night'],evidence['ナイト親数']);same(group['Day'],evidence['デイ親数'])
        same(group['最大事後清算逆行'],evidence['費用後最大逆行円'])
    for cid,symbols in diag['保存B四条件'].items():
        case=pub['cases'][cid]
        for symbol,data in symbols.items():
            expected=finance['商品と期間'][cid][symbol]['期間']
            for key,val in expected['全33']['金額'].items():same(data['symbols'][key],val)
            assert data['stability']==expected['全33']['基準']
            assert data['direction']==finance['方向副表'][cid][symbol]
            for a,b in (('上位三除外','上位3正収支場除外'),('前十六','前16'),('後十七','後17')):
                for key,val in expected[b]['金額'].items():same(data[a]['aggregate'][key],val)
                assert data[a]['stability']==expected[b]['基準']
            own=[r for r in case['rows'] if r['symbol']==symbol]
            for tag in ('Day','Night'):
                rows=[r for r in own if r['session'].endswith('_'+tag)]
                stage=dict(全場=len(rows),活動=sum(r['campaigns']>0 for r in rows),
                    黒字=sum(r['net']>0 for r in rows),赤字=sum(r['net']<0 for r in rows),
                    無取引=sum(r['campaigns']==0 for r in rows),収支=sum(r['net'] for r in rows))
                assert data['昼夜'][tag]==stage
            none={r['session'] for r in own if r['campaigns']==0}
            boundaries=[b for b in case['boundary'] if b['symbol']==symbol and b['session'] in none]
            assert len(boundaries)==len(none)
            same(data['無取引受理']['受理なし'],sum(not b['anchor']['成立'] for b in boundaries))
            same(data['無取引受理']['受理あり実親なし'],sum(b['anchor']['成立'] for b in boundaries))
            same(data['名目損失枠対平均黒字場'],(5000 if symbol=='TOPIX' else 2000)/data['stability']['mean_positive_session_net_yen'])
    for pair,settings in diag['銘柄設定差の保存候補'].items():
        top='E01_CROSS_B03' if pair=='入口だけ銘柄差' else 'E01_CROSS_B04'
        assert settings['TOPIX']==diag['保存B四条件'][top]['TOPIX']
        assert settings['NK225']==diag['保存B四条件']['E01_CROSS_B01']['NK225']
        assert '事後組合せ' in settings['地位'] or 'パラメータ差' in settings['地位']
    a={(r['session'],r['symbol']):r for r in pub['cases']['E01_CROSS_B03']['rows']}
    b={(r['session'],r['symbol']):r for r in pub['cases']['E01_CROSS_B04']['rows']}
    changes=[dict(session=s,symbol=k,旧P1収支=a[s,k]['net'],ATR四分の一収支=b[s,k]['net'],差=b[s,k]['net']-a[s,k]['net'])
        for s,k in a if k=='TOPIX' and b[s,k]['net']!=a[s,k]['net']]
    assert changes==diag['TOP_B03対B04変更場']
    assert len(changes)==1 and changes[0]['session']=='2026-10-02_Night' and changes[0]['差']==1000
    output=dict(全合格=True,照合小値=COUNT,小資料一読SHA256=READS,
        B03二又は三票={s:diag['B03母数と昼夜'][s]['二又は三票'] for s in ('TOPIX','NK225')},
        確認='旧価格資格と拡幅は既独立再集計に一致。B03min4対象外はTOP4/7・NK6/8。TOP B04増益1000は10/2Night一場のみ。昼17/夜16、受理なし無取引の母数も一致。',
        留保='TOP B03/NK B01という商品別選択は、元の保存会計を静的に選んだ既知内候補。新再生・未知成功・共有資金/相関検証ではない。最低活動率を新たな合格基準へ足さず無取引を勝ちにしない。',
        新金融=0,金融原本再読=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,共有編集=0,
        独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,照合=COUNT,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
