"""旧照合を保持し、気配差込み予算と保存基準の表示へ別版を接続する。"""

from pathlib import Path


HERE=Path(__file__).resolve().parent
BASE=HERE.parent.parent


def main() -> None:
    """
    機能: 既存の純表示監査源から、v9専用の独立照合源を新規保存する。
    引数: なし。旧sourceだけを読み、金融結果は読まない。
    返り値: None。旧source、既存証跡、金融sourceは変更しない。
    """
    source=(BASE/'v8/report_fixture/正式組と準備系譜及び脚表示の照合.py').read_text(encoding='utf8')
    source=source.replace('V8=HERE.parent','V9=HERE.parent').replace('BASE=V8.parent','BASE=V9.parent').replace('V8/','V9/')
    source=source.replace('privatev8','privatev9').replace('engine_v8.py','engine_v9.py').replace('run_v8.py','run_v9.py').replace('plan_v8.py','plan_v9.py')
    source=source.replace('正式320組とp46及びprep21の実表示照合.json','正式320組と旧八基準及び気配差予算の実表示照合.json')
    source=source.replace('八条件の小集計と相対共通費用分解.json','八条件の新旧差と相対共通費用分解.json')
    source=source.replace('相対乖離の復帰確認と残差追尾の全セッション損益.html','相対復帰の初期気配差込み予算と残差追尾の全セッション損益.html')
    source=source.replace('相対乖離の実際の復帰確認と全四十場.json','相対復帰の初期気配差込み予算と全四十場.json')
    for old,new in (
        ('45a10846c384cb66ef6d55b381308748180a679d6b22da57dcf246fbea04675f','534d13ad7e5afa80e3e926fe68e61dc0104624715be6b7a26083e3d51d5ec406'),
        ('05f3d543d693441106718d3b40e6ec6eb0d2148cebc84d9493eb029d7148710e','e54a4b4cbe4e79c2395e76330847badcb2aba59677af579f110e0f7e0ed70bda'),
        ('499d00b4fd88418ee1e3a6894d64eb31fe95b25479403e8f9bb106a51d07b1fc','c6da10245a2157d684e362b04bc5b6d4afde927693be82acbad129f5d22b0314')):
        source=source.replace(old,new)
    source=source.replace("check(near(prep[pi['cash_loss_budget']],sgn*(extreme-delta)*nominal+fees),'正の極値幅元本と明示往復料だけのcash予算')", "check(near(prep[pi['cash_loss_budget']],sgn*(extreme-delta)*nominal+prep[pi['estimated_roundtrip_cost']]) and prep[pi['estimated_roundtrip_cost']]>=fees,'正の極値幅元本と予約時推定往復料及び気配差のcash予算')")
    insertion='''
def check_baseline(retained: dict, public: dict, page: BeautifulSoup, metrics: dict, scenes: list) -> list:
    """
    機能: 同bytes保全copy内の保存旧320行と公開8対応の差額を独立足算する。
    引数: retained/public(dict)、page(BeautifulSoup)、metrics(dict)、scenes(list[str])。
    返り値: list[dict]は旧新の小比較。旧結果の再読又は再売買はしない。
    """
    reference=retained['baseline_reference']
    check(reference['sha256']=='2f7c15e27d7c0e20b6b14de8ab682ac62d49a55b6ba35d2079b6245d9699dcf4','保存v8完成SHAの結合')
    check(reference==public['baseline_reference'] and reference['saved_rows']==320 and reference['financial_replay']==retained['baseline_financial_rerun']==0,'旧基準再生零と由来を保つ')
    oldrows={(r['method'],r['session']):r for r in retained['baseline_runs']}
    specs=retained['specs'];check(len(oldrows)==len(retained['baseline_runs'])==320 and len(specs)==8,'保存旧320組と8対応の一意性')
    records=[];expected_rows={}
    for spec in specs:
        ident=spec['id'];oldid=spec['baseline_id'];check(ident==oldid+'_CB','同じモデル退出の予算因子だけを対照')
        rr=[oldrows[oldid,s] for s in scenes];publicold=public['baseline_cases'][oldid]
        check(publicold['rows']==rr,'旧全40場を元保存会計から改変せず転載')
        net=[r['net'] for r in rr];positive=[r['net'] for r in rr if r['fills'] and not r['unclosed'] and r['net']>1e-7]
        om=dict(net=sum(net),profit=sum(r['profit'] for r in rr),loss=sum(r['loss'] for r in rr),fees=sum(r['fees'] for r in rr),parents=sum(r['parents'] for r in rr),
            black=len(positive),red=sum(r['fills'] and not r['unclosed'] and r['net']<-1e-7 for r in rr),inactive=sum(not r['fills'] and not r['unclosed'] for r in rr),
            median=statistics.median(net),worst=min(net),top3_removed=sum(net)-sum(sorted(positive,reverse=True)[:3]),reserved_preparations=sum(r['reserved_preparations'] for r in rr))
        for k,v in om.items():check(near(v,publicold['metrics']['PAIR'][k]),'保存旧会計の全40場安定指標を独立足算')
        for symbol in ('NK225','TOPIX'):
            for k in ('gross','fees','net','realized','entry_quantity','closed_quantity'):
                check(near(sum(r['legs'][symbol][k] for r in rr),publicold['legs'][symbol][k]),'保存旧両脚会計の合計を独立足算')
        nm=metrics[ident]
        expected_rows[ident]=[ident,fmt(om['net'],True),fmt(nm['net'],True),fmt(nm['net']-om['net'],True),
            f"{om['black']}/{om['red']}/{om['inactive']} → {nm['black']}/{nm['red']}/{nm['inactive']}",
            f"{om['parents']} → {nm['parents']}",f"{om['reserved_preparations']} → {nm['reserved_preparations']}",fmt(om['fees']),fmt(nm['fees'])]
        records.append(dict(id=ident,baseline_id=oldid,old=om,new={k:nm[k] for k in om},net_change=nm['net']-om['net']))
    trs=page.select('table.comparison tbody tr');check(len(trs)==8,'8対応の差額表を全て掲載')
    for tr in trs:check([td.get_text(strip=True) for td in tr.select('td')]==expected_rows[tr['data-method']],'旧新収支と差額及び勝敗予約費用の実表示')
    text=page.get_text(' ',strip=True)
    check('その後の保有・再参加の変化も含みます' in text and '会計バグの修正とは呼びません' in text,'予算一因子の経路差を会計バグ又は単純利益移転と呼ばない')
    check('相対極値の価格撤回線はv8と同じ' in text and '実料金との二重課金はしません' in text,'価格極値不変と予算の費用二重課金なし')
    check('毎セッションの安定黒字は未達です' in text and public['qualification_count']==0,'赤字8対照を安定収益として採用しない')
    return records


'''
    source=source.replace('def main() -> None:',insertion+'def main() -> None:',1)
    source=source.replace("small=dict(scope=", "comparisons=check_baseline(retained,data,page,metrics,scenes)\n    small=dict(baseline_comparisons=comparisons,scope=")
    source=source.replace("pair_sessions=320,source_SHA256=", "pair_sessions=320,reused_baseline_rows=320,baseline_comparisons=8,source_SHA256=")
    source=source.replace('金融エンジンの実会計監査ではない。','保存実注文の独立算数を含むが、元quote価格や推定spread自体の再取得はしていない。')
    target=HERE/'正式組と気配差予算及び脚表示の照合.py'
    assert not target.exists()
    target.write_text(source,encoding='utf8')


if __name__=='__main__':
    main()
