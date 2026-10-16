"""数量四条件の全264小会計と最新基準を独立再集計し、抽出読取計画を固定する。"""

from pathlib import Path
import hashlib
import json
import math


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_risk_sizing'
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の数量/出口差','新たな入口の収支')


def read(path: Path) -> dict:
    """
    機能: 保存小JSONを読取専用で取得する。
    引数: path(Path)は小資料の位置。
    返り値: dictは保存値。大型cache、旧台帳、金融を実行しない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: 小JSON又はsourceの指紋を取得する。
    引数: path(Path)は小資料の位置。
    返り値: strはSHA256。抽出計画前に大型bytesを読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def near(a: float|None, b: float|None) -> None:
    """
    機能: 同じ定義の独立指標を有限性と誤差で比較する。
    引数: a/b(float|None)は二指標。
    返り値: None。未定義と0又は非有限の取り違えを拒否する。
    """
    if a is None or b is None: assert a is b; return
    assert math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-7),(a,b)


def goal(rows: list[dict]) -> dict:
    """
    機能: 完結親金額比、全場赤字率、平均黒字補填を独立集計する。
    引数: rows(list[dict])は同商品・同条件の保存小会計。
    返り値: dictは最新65/20/平均補填と活動参考。無取引を勝ちに数えない。
    """
    gain=sum(r['利益'] for r in rows); loss=sum(r['損失'] for r in rows)
    green=[r for r in rows if r['収支']>0]; red=[r for r in rows if r['収支']<0]; active=[r for r in rows if r['親数']]
    average=sum(r['収支'] for r in green)/len(green) if green else None
    maximum=max([0.]+[-r['収支'] for r in red]); share=gain/(gain+loss) if gain+loss else None
    simple=[r['利益']/(r['利益']+r['損失']) for r in active if r['利益']+r['損失']]
    ratio=len(red)/len(rows) if rows else None
    criteria=dict(金額65=share is not None and share>=.65,赤字20=ratio is not None and ratio<=.2,
        平均黒字補填=average is not None and maximum<=average)
    return dict(利益=gain,損失=loss,収支=gain-loss,金額利益割合=share,PF=gain/loss if loss else None,
        全場=len(rows),活動=len(active),黒字=len(green),赤字=len(red),無取引=len(rows)-len(active),
        赤字率全場=ratio,赤字率活動=len(red)/len(active) if active else None,平均黒字=average,最大赤字=maximum,
        最大赤字平均黒字比=maximum/average if average else None,活動場比率単純平均=sum(simple)/len(simple) if simple else None,
        基準=criteria,全基準合格=all(criteria.values()))


def main() -> None:
    """
    機能: 264保存小会計、五寄与、最新全場/上位3除外を点検し、少数抽出を先に固定する。
    引数: なし。保存resultと固定metadataだけを読む。
    返り値: Noneは会計監査と抽出計画。金融の再生を行わない。
    """
    path=SOURCE/'finance/結果.json'; result=read(path); fixed=read(SOURCE/'金融事前固定.json')
    assert digest(path)=='2f6d414138c37e53887b0b893a50f7cea360c69695eda6a4e1cf9990a17b5beb'
    assert result['全合格'] and result['source開始終端一致'] and result['source_SHA256']==fixed['source_SHA256']
    assert result['sessions']==fixed['sessions'] and len(result['sessions'])==33
    assert result['counts']=={'既input一読':33,'新GUengine':132,'旧基準台帳一読':528,'新政策会計':264}
    for name,sha in result['source_SHA256'].items(): assert digest(ROOT/name)==sha
    checked=0; equations=0; indicators={}; row_index={}
    for cid,data in result['results'].items():
        assert len(data['rows'])==len(data['ledgers'])==66
        original={(r['session'],r['symbol']):r for r in data['rows']}; assert len(original)==66
        assert set(original)=={(s,p) for s in result['sessions'] for p in ('TOPIX','NK225')}
        for row in original.values():
            assert row['全会計合格'] and row['利益']>=0 and row['損失']>=0
            near(row['利益']-row['損失'],row['収支'])
            assert row['勝ち親']+row['負け親']+row['零親']==row['親数']
            assert row['勝ち枚数']+row['負け枚数']+row['零枚数']==row['新規枚数']
            cap=5 if row['symbol']=='TOPIX' else 10
            assert 0<=row['最大買枚数']<=cap and 0<=row['最大売枚数']<=cap
            assert row['費用']>=0 and row['費用']==int(row['費用'])
            near(row['利益割合'],row['利益']/(row['利益']+row['損失']) if row['利益']+row['損失'] else None)
            near(row['PF'],row['利益']/row['損失'] if row['損失'] else None)
            near(row['平均利益'],row['利益']/row['勝ち親'] if row['勝ち親'] else None)
            near(row['平均損失'],row['損失']/row['負け親'] if row['負け親'] else None)
            if row['親数']==0: assert row['新規枚数']==row['費用']==row['収支']==row['注文件数']==0
            row_index[cid,row['session'],row['symbol']]=row; checked+=1
        indicators[cid]={}
        for symbol in ('TOPIX','NK225'):
            rows=[original[s,symbol] for s in result['sessions']]; full=goal(rows)
            top=sorted([r for r in rows if r['収支']>0],key=lambda r:r['収支'],reverse=True)[:3]
            removed={r['session'] for r in top}; tail=goal([r for r in rows if r['session'] not in removed])
            indicators[cid][symbol]=dict(全場=full,上位3除外=tail,除外場=[r['session'] for r in top])
            saved=data['symbols'][symbol]
            for human,new in (('利益','利益'),('損失','損失'),('収支','収支'),('利益割合','金額利益割合'),('PF','PF'),
                ('全場','全場'),('活動場','活動'),('黒字場','黒字'),('赤字場','赤字'),('無取引場','無取引'),('最大場損失','最大赤字')):
                near(saved[human],full[new])
            near(saved['上位3利益場除外収支'],tail['収支'])
            for field in ('親数','勝ち親','負け親','零親','費用','新規枚数','勝ち枚数','負け枚数','零枚数'):
                assert saved[field]==sum(r[field] for r in rows)
            leg=data['actual_leg_symbols'][symbol]
            near(leg['利益']-leg['損失'],full['収支']); near(leg['収支'],full['収支'])
            assert leg['実決済玉数']==leg['親数'] and leg['勝ち親']+leg['負け親']+leg['零親']==leg['親数']
            assert leg['実決済玉数']<=saved['新規枚数']
        # 全264の5寄与は旧保存rowとの差と恒等式。真の親対応は次の抽出台帳で別検査する。
        for scene in result['各場寄与'][cid]:
            key=scene['session']+'|'+scene['symbol']; current=original[scene['session'],scene['symbol']]
            for name,d in scene['比較別'].items():
                before=fixed['comparisons'][cid][name]; old=[r for r in before['rows'] if r['session']==scene['session'] and r['symbol']==scene['symbol']]
                assert len(old)==1 and d['baseline_id']==before['id']
                near(d['収支変化'],current['収支']-old[0]['収支'])
                near(d['収支変化'],d['避けた基準損失']-d['失った基準利益']+d['共通入口の数量/出口差']+d['新たな入口の収支'])
                assert d['避けた基準損失']>=0 and d['失った基準利益']>=0
                assert all(t['old_net']>0 and t['new_net']<0 for t in d['元勝ち親が赤字化']); equations+=1
        for symbol in ('TOPIX','NK225'):
            for name,d in result['diagnosis'][cid][symbol].items():
                selected=[r['比較別'][name] for r in result['各場寄与'][cid] if r['symbol']==symbol]
                for f in FIELDS: near(d[f],sum(r[f] for r in selected))
                assert d['元勝ち親が赤字化']==sum(len(r['元勝ち親が赤字化']) for r in selected)
    assert checked==264 and equations==792
    assert not any(v['全場']['全基準合格'] for products in indicators.values() for v in products.values())
    # ----------------------------------------
    # Q3の実政策部分返済は小表にない。GU診断と人工へ限定し、実Q2部分を別に抽出する。
    partial=[dict(id=cid,**r) for cid,data in result['results'].items() for r in data['rows'] if r['注文件数']>2*r['親数']]
    assert len(partial)==2 and all(max(r['最大買枚数'],r['最大売枚数'])==2 for r in partial)
    specs=[
        ('E01_SIZE_W60_VETO_D0_P2_L2_A1','2026-10-05_Night','TOPIX','q0で元入口を拒否した後の新参加', '同額固定数量L2'),
        ('E01_SIZE_W60_VETO_D0_P2_L2_A1','2026-10-05_Night','NK225','実Q3公開とGU診断、停止prefix',''),
        ('E01_SIZE_W60_CONFIRM_D0_P2_L2_A1','2026-09-25_Night','TOPIX','全条件TOP最大赤字と旧勝ち赤字化','旧P1L8'),
        ('E01_SIZE_W60_CONFIRM_D0_P2_L2_A1','2026-09-22_Day','NK225','全条件NK最大赤字と旧勝ち赤字化','旧P1L8'),
        ('E01_SIZE_W60_CONFIRM_D0_P2_L2_A1','2026-10-12_Day','TOPIX','実Q2部分返済と注文別floor料','')]
    new=[]; old=[]; sessions=[]
    for cid,session,symbol,purpose,comparison in specs:
        item=[r for r in result['results'][cid]['ledgers'] if r['session']==session and r['symbol']==symbol]; assert len(item)==1
        new.append(dict(id=cid,purpose=purpose,**item[0])); sessions.append(session)
        if comparison:
            ref=fixed['comparisons'][cid][comparison]
            old.append(dict(id=ref['id'],comparison=comparison,new_id=cid,**ref['ledgers'][session+'|'+symbol]))
    packets={s:fixed['input_cache'][s] for s in dict.fromkeys(sessions)}
    assert len(new)==5 and len(old)==3 and len(packets)==4
    plan=dict(全合格=True,目的='小会計監査後に少数の実注文・次正常気配・実料金・停止接頭を独立確認する。金融再実行は行わない。',
        financial_result_path=path.relative_to(ROOT).as_posix(),financial_result_SHA256=digest(path),
        新台帳=new,旧台帳=old,一読packet=packets,新台帳読取上限=5,旧台帳読取上限=3,packet読取上限=4,
        Q3留保='全264小表の実政策部分返済2口座はともに最大Q2。実Q3部分返済は本番発生を捏造せず、保存GU診断にあればその影経路として検査する。',
        抽出の選択='q0後参加、Q3、最大赤字と旧勝ち赤字化、実Q2部分料を重複場へまとめる。新旧5寄与の親対応は抽出3組に限定。',
        実行条件='この小計画をrootへ送付後に、列挙した新旧台帳及びpacketを各一回だけ読む。',
        予定金融再実行=0,原板=0,NPZ=0,API=0,全33input再読=0,現時点大型読取=0)
    plan_path=HERE/'risk_sizing_金融抽出5新3旧4packetの事前固定.json'; assert not plan_path.exists()
    plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    proof=dict(全合格=True,source_SHA256={path.relative_to(ROOT).as_posix():digest(path),
        (SOURCE/'金融事前固定.json').relative_to(ROOT).as_posix():digest(SOURCE/'金融事前固定.json')},
        独立source_SHA256=digest(Path(__file__)),小会計=checked,五寄与式及び旧row差=equations,
        新基準=indicators,実部分返済の小表=partial,抽出計画SHA256=digest(plan_path),
        結論='四条件の各商品最新三基準合格0。日経の各全場合計は正だがTOPIXは負、全条件の両商品合計も負。',
        限界='全264の会計整合と5寄与代数を確認。全親の新旧対応・実気配・数量はここでは再読しておらず次の抽出だけで確認する。',
        新金融=0,原入力=0,旧台帳=0,原板=0,NPZ=0,API=0)
    output=HERE/'risk_sizing_全264小会計と792寄与及び最新三基準の独立検算.json'; assert not output.exists()
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,小会計=checked,寄与式=equations,監査SHA256=digest(output),計画SHA256=digest(plan_path)),ensure_ascii=False))


if __name__=='__main__': main()
