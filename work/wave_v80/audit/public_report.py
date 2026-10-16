"""公開二HTMLの埋込み会計・主張・最大損失例を保存原本へ照合する。"""

import json
import re
from datetime import datetime

import numpy as np

from accounts import HERE,WORK,study


def embedded(path) -> tuple:
    """機能: 単独HTMLから読取専用の公開会計データを取り出す。

    引数: path(Path)。返り値: HTML文字列と資料辞書(tuple)。
    """
    source=path.read_text(encoding='utf8')
    found=re.search(r'<script id="report-data" type="application/json">(.*?)</script>',source,re.S)
    assert found is not None
    assert not any(token in source for token in ['__DATA__','__STYLE__','__COMMON__','__SCRIPT__'])
    return source,json.loads(found.group(1))


def main() -> None:
    """機能: 二HTMLの全数値と説明用の価格・時計・損失を独立照合する。

    引数: なし。返り値: なし(None)。書込みは監査フォルダのみ。
    """
    public=study.ROOT/'アルゴリズム調査/00076_5秒発注遅延を含む秒スキャルピング'
    mainpath=public/'秒スキャルピングの改善と全セッション損益.html'
    allpath=public/'全330条件の前半比較.html'
    html,data=embedded(mainpath);allhtml,all_data=embedded(allpath)
    fixed=study.load(WORK/'初回事前固定.json');selection=study.load(WORK/'最終前半選定.json')
    assert data['sessions']==fixed['全30'] and data['front']==fixed['前16'] and data['back']==fixed['後14']
    assert data==study.load(WORK/'report/描画資料.json')
    configs={c['id']:c for c in selection['確認条件']}
    assert {m['id'] for m in data['methods']}==set(configs)
    for method in data['methods']:
        assert method['config']==configs[method['id']]
    accounts=0
    for delay in ['0','1','5']:
        assert set(data['final'][delay])==set(configs)
        for ident,packet in data['final'][delay].items():
            assert packet==study.load(WORK/'final'/f'delay{delay}'/'results'/f'{ident}.json')
            accounts+=len(packet['rows'])
    for ident,period in data['strict'].items():
        assert period==study.load(WORK/'quality_strict3/results'/f'{ident}.json')['periods']['対象']
    public_account=study.load(public/'公開会計.json')
    assert public_account['期間']==data['sessions'] and public_account['前半']==data['front'] and public_account['後半']==data['back']
    assert public_account['遅延別']==data['final']
    for ident,packet in public_account['厳格3秒鮮度'].items():
        assert packet==study.load(WORK/'quality_strict3/results'/f'{ident}.json')
        assert packet['periods']['対象']==data['strict'][ident]
    for name,record in public_account['監査'].items():
        assert record==study.load(HERE/f'{name}.json')
    public_fixed=study.load(public/'検証条件と固定記録.json')
    assert public_fixed['初回']==fixed and public_fixed['最終選定']==selection
    assert public_fixed['改修']==study.load(WORK/'改修事前固定.json')
    assert len(all_data['rows'])==330
    for row in all_data['rows']:
        folder='first' if row['stage']=='初回' else 'repair'
        packet=study.load(WORK/folder/'results'/f'{row["config"]["id"]}.json')
        assert row['config']==packet['config'] and row['metrics']==packet['periods']['前16']
    for path,wanted in data['audit']['入力'].items():
        assert study.digest(study.ROOT/path)==wanted
    assert '両商品の1組平均収支は悪化' in html
    assert '単一部品の因果効果ではありません' in html
    assert '同じ3取引' in html and '4つの独立した成功例ではありません' in html
    assert '実際の受信から5秒以内の成績を再現したものではありません' in html
    assert '指定10秒窓の実長は1～24秒' in html
    assert '指値全般が無効という証明ではありません' in html
    assert '全330条件を後半へ最適化した表ではありません' in allhtml
    review=study.load(WORK/'audit/最終数値の解釈と過剰断定の独立レビュー.json')
    assert review['合格']

    # ----------------------------------------
    # 約定後の大きな損失例を、元台帳と全連続原本の代理時計から再検算する。
    diagnosis=study.load(WORK/'diagnosis/最終代表の改善限界と遅延経路.json')
    example=diagnosis['最大損失の具体的経路']
    assert all(value==example[field] for field,value in data['loss_case'].items())
    key=example['セッション'],example['商品'];ident=example['手法'];cid=example['組']
    ledger=study.load(WORK/'final/delay5/ledgers'/f'{ident}.pkl')[key]
    t=ledger['trades'][cid];orders=ledger['orders'][ledger['orders'][:,2]==cid]
    ready,books,signals,maps=study.material();r,b=ready[key],books[key]
    assert t[10]==example['収支円']==-60836.
    assert t[5]==example['新規価格'] and t[6]==example['返済価格']
    for name,opened in [('新規',1),('返済',0)]:
        order=orders[orders[:,7]==opened][0]
        for field,col in [('判断',10),('到着予定',11),('約定',12)]:
            assert datetime.fromisoformat(example['注文時計'][name][field]).timestamp()==order[col]
    entry=orders[orders[:,7]==1][0];exit_order=orders[orders[:,7]==0][0]
    assert int(entry[3])==1 and int(entry[4])==10
    threshold=entry[5]-3*r['tick'];trigger=b['bid'][int(exit_order[1])];filled=exit_order[5]
    assert threshold==example['想定発動価格'] and trigger==example['実際返済判断bid'] and filled==example['返済待ち後bid']
    components=[(entry[5]-threshold)*10000.,(threshold-trigger)*10000.,(trigger-filled)*10000.,entry[8]+exit_order[8]]
    expected=[example['設定幅による価格損失円'],example['発動観測時点までの追加価格損失円'],example['返済判断後の追加価格損失円'],example['手数料円']]
    np.testing.assert_allclose(components,expected,atol=1e-6,rtol=0)
    assert sum(components)==-t[10]
    rawchecks=0
    for point in example['原本連続観測']:
        i=point['準備行']
        assert point['原本seq']==int(r['seq'][i])
        assert datetime.fromisoformat(point['代理時計']).timestamp()==r['time_s'][i]
        for field,rawfield in [('bid','bid'),('ask','ask'),('買数量','bid_qty'),('売数量','ask_qty')]:
            assert point[field]==b[rawfield][i]
        rawchecks+=1
    ei,xi=int(entry[0]),int(exit_order[0])
    maxgap=float(np.diff(r['time_s'][ei:xi+1]).max())
    assert maxgap==example['新規約定から返済約定までの最大代理時計間隔秒']==1.
    waiting=study.load(WORK/'final/delay5/ledgers/A6_P6_M0.pkl')
    for symbol in ['TOPIX','NK225']:
        all_orders=np.concatenate([v['orders'] for k,v in waiting.items() if k[1]==symbol])
        for name,opened in [('新規',1),('返済',0)]:
            selected_orders=all_orders[all_orders[:,7]==opened]
            waits=selected_orders[:,12]-selected_orders[:,10]
            saved=data['waits'][symbol][name]
            assert len(waits)==saved['件数']
            for percentile,label in [(50,'中央値秒'),(95,'百分位95秒'),(100,'最大秒')]:
                assert abs(float(np.percentile(waits,percentile))-saved[label])<1e-7
    result=dict(合格=True,公開主HTML_SHA256=study.digest(mainpath),公開全330HTML_SHA256=study.digest(allpath),
        公開方法数=11,遅延水準数=3,公開損益口座数=accounts,前半条件数=330,厳格鮮度条件数=len(data['strict']),
        最大損失例の独立照合行数=rawchecks,最大損失分解円=components,
        数値と公開元帳の完全一致=True,実待機分布の独立再計算=True,
        解釈='平均収支の悪化、代表同士と単一確認部品の比較、少数4設定の同一経路、代理時計と現実の遅延の区別は監査済み。最大損失例の実経過時間を代理時計から断定しない。')
    readme=public/'README.md'
    if readme.exists():
        text=readme.read_text(encoding='utf8')
        for required in ['942,860','285,040','1決済組あたりの平均収支は両商品とも初回成行より悪化','未知データによる検証とは呼びません','真の受信時計とミニ・マイクロ自身の板がなく']:
            assert required in text
        result['公開README_SHA256']=study.digest(readme)
    assert '後半の新しい再生結果では代表を選び直していない' in html
    assert '長い価格観測の空白としては現れていません' in html and '真の経過時間は不明' in html
    (HERE/'公開二HTMLと最大損失例の最終内容監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
