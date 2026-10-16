"""公開HTMLの数値・機械条件・既知検証の解釈を独立照合する。"""
import re
from context import *
from accounts import load

PUBLIC=ROOT/'アルゴリズム調査/00080_順行逆指値と反転売買の検証'


def embedded(path: Path) -> dict:
    """機能: 単体HTMLの埋込会計を抽出する。

    引数: path(Path)。返り値: 描画資料(dict)。
    """
    found=re.search(r'<script id="report-data" type="application/json">(.*?)</script>',path.read_text(encoding='utf8'),re.S)
    assert found
    return json.loads(found.group(1))


def main() -> None:
    """機能: 全公開数値と元結果を完全照合し、誤認しやすい結論を検査する。

    引数: なし。返り値: なし(None)。
    """
    generated=load(WORK/'report/生成結果.json');chosen=load(WORK/'前半選定.json')
    hashes={};checks=0
    for filename,h in generated['HTML'].items():
        path=PUBLIC/filename;assert digest(path)==h;hashes[filename]=h;d=embedded(path)
        if 'methods' not in d:
            assert len(d['rows'])==108
            for row in d['rows']:
                raw=load(WORK/'train/results'/f'{row["config"]["id"]}.json')
                assert row['config']==raw['config'] and row['metrics']==raw['periods']['前16'];checks+=1
            continue
        assert len(d['methods'])==14 and d['selection']==chosen and len(d['sessions'])==30
        for model,stage in [('main','final/delay0'),('ideal','ideal_fee')]:
            assert set(d['results'][model])==set(chosen['selected'])
            for name,result in d['results'][model].items():
                assert result==load(WORK/stage/'results'/f'{name}.json');checks+=1
        extra=d['supplement'];assert extra['fixed']==load(WORK/'supplement/追加固定.json')
        name=extra['method']['id'];assert name=='F3_W64_V1' and name not in d['results']['main']
        for model,stage in [('main','supplement/final'),('ideal','supplement/ideal_fee')]:
            assert extra['results'][model]==load(WORK/stage/'results'/f'{name}.json');checks+=1
        for method in d['methods']:
            if method['family']==5:
                assert '返済理由の名称だけでは決めない' in method['short']
                assert '損切りや同額決済なら' not in method['short']
        assert d['conclusion']==load(WORK/'report/結論文.json')
        assert all(not pair['selected_by_performance'] for pair in chosen['pairs'])
    for name,h in generated['入力SHA256'].items():assert digest(ROOT/name)==h
    # ----------------------------------------
    main_results=[load(WORK/'final/delay0/results'/f'{name}.json') for name in chosen['selected']]
    assert sum(all(r['periods']['対象'][s]['net']>0 for s in ['TOPIX','NK225']) for r in main_results)==0
    theory=load(WORK/'ideal_fee/results/F1_W32_V0.json')['periods']['対象']
    assert [theory[s]['net'] for s in ['TOPIX','NK225']]==[37364.,190080.]
    assert [theory[s]['winning_sessions'] for s in ['TOPIX','NK225']]==[14,14]
    immediate=load(WORK/'ideal_fee/results/F3_W08_V1.json')['periods']['対象']
    assert [immediate[s]['net'] for s in ['TOPIX','NK225']]==[-7789836.,-2475120.]
    notes=[
        '即ドテンの赤字という結論は入口・反転8呼値の比較に限定し、全幅や全ての反転法が不可能と断定していない。',
        '同幅0/1は入口方向だけ、同幅2/3/4/5は返済後の再入口を変えた対照。パラメータ以外の売買時刻が同一だとは主張しない。',
        '主14と追加参考1を分離。活動不足の前半両黒字条件を隠さず、主結果後の追加探索と明記する。',
        '現在値必約定で黒字のF1_W32_V0も示すが、売買気配での実行可能性や共通安定利益を証明したとは扱わない。',
        '価格条件としての損切りと実約定後の赤字を区別。F5は理由名でなく返済後の純損益で反転する説明へ訂正した。',
        '親約定前の子判定なし、返済実約定前の反対新規なし、反転時の両注文料、同一行最大1反転を説明と計算で確認。',
        '現在値と売買気配は違う価格系列。中値での同時刻損益分解と、現在値必約定の再生を区別する。',
        '全30は既知データ。代理時計、ラージ気配による小型商品代用、全量約定の仮定を明記。']
    result=dict(合格=True,HTML_SHA256=hashes,元結果と完全一致した埋込会計=checks,
        描画入力指紋一致=len(generated['入力SHA256']),文面監査=notes,
        留意='数値・意味の監査。実ブラウザでの表示確認は別担当の記録を参照。')
    save('公開HTMLの数値と解釈監査.json',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
