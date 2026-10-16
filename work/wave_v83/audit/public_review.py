"""公開HTMLに埋め込まれた全数値と、主張の対象範囲を検査する。"""
import re
from context import *
from accounts import load

PUBLIC=ROOT/'アルゴリズム調査/00079_方向予測を使わない注文手法の検証'


def embedded(path: Path) -> dict:
    """機能: HTML内の静的描画資料を抽出する。

    引数: path(Path)。返り値: 描画資料(dict)。
    """
    found=re.search(r'<script id="report-data" type="application/json">(.*?)</script>',path.read_text(encoding='utf8'),re.S)
    assert found
    return json.loads(found.group(1))


def main() -> None:
    """機能: 全埋込会計を元JSONへ完全照合し、範囲と留保の文面を保存する。

    引数: なし。返り値: なし(None)。
    """
    generated=load(WORK/'report/生成結果.json')
    selection=load(WORK/'前半選定.json');fixed=load(WORK/'results/事前固定.json')
    checked=0;names={};documents={}
    for filename,expected in generated['HTML'].items():
        path=PUBLIC/filename;assert digest(path)==expected
        d=embedded(path);documents[filename]=d;names[filename]=expected
        if 'methods' not in d:
            assert len(d['rows'])==288
            for row in d['rows']:
                raw=load(WORK/'train/results'/f'{row["config"]["id"]}.json')
                assert row['metrics']==raw['periods']['前16'] and row['config']==raw['config'];checked+=1
            continue
        assert len(d['sessions'])==30 and d['sessions']==fixed['全30']
        assert set(d['final'])=={'0'}
        for stage,column in [('final/delay0','final'),('ideal','ideal'),('ideal_fee','ideal_fee')]:
            collection=d[column]['0'] if column=='final' else d[column]
            for name,value in collection.items():
                assert value==load(WORK/stage/'results'/f'{name}.json');checked+=1
        assert d['sensitivity']==load(WORK/'sensitivity/無作為20種の比較.json')
        assert d['persistent_spec']==load(WORK/'persistent/固定条件.json')
        for row in d['persistent']:
            name=row['parent_id']
            assert row['result']==load(WORK/'persistent/results'/f'{name}.json')
            assert row['original']==load(WORK/'final/delay0/results'/f'{name}.json');checked+=2
        text=json.dumps(d,ensure_ascii=False)
        for wording in ['元の指値','仮説','待ち順位','現在値','未知']:
            assert wording in text
        assert d['conclusion']==load(WORK/'report/結論文.json')
    for filename,h in generated['入力SHA256'].items():assert digest(ROOT/filename)==h
    # ----------------------------------------
    allmain=[load(WORK/'final/delay0/results'/f'{name}.json') for name in selection['selected']]
    both=sum(all(r['periods']['対象'][s]['net']>0 for s in ['TOPIX','NK225']) for r in allmain)
    assert both==0
    virtual=load(WORK/'ideal_fee/results/O06_W08_V2.json')
    assert [virtual['periods']['対象'][s]['net'] for s in ['TOPIX','NK225']]==[3674796.,757560.]
    assert [virtual['periods']['対象'][s]['winning_sessions'] for s in ['TOPIX','NK225']]==[18,18]
    changed=load(WORK/'persistent/results/O06_W08_V2.json')
    assert [changed['periods']['対象'][s]['net'] for s in ['TOPIX','NK225']]==[1214120.,-457720.]
    findings=[
        '主13条件の全30場両商品共通黒字は0。全288条件を後14で確認したとは記載していない。',
        '金額利益割合は親組会計が主。個別脚へ切替えても最終収支は同じで、残りの赤字玉を捨てない。',
        '現在値必約定の2対照は実行可能性の証明ではなく、主損益への単なる費用足し戻しでも上界でもない。',
        '指値保持3条件は全30主結果閲覧後の仮説確認。保持と元指値約定モデルの変更を明記し、未知成功扱いしない。',
        '乱数20種は同じ30相場での入口感度で、20個の独立相場ではない。',
        '場末全返済と片方向上限、買い売り双方の手数料を含む。最大総玉と差引玉を区別する。',
        '主は追加発注遅延0。CurrentPriceTimeは受信時計でなく、ラージ気配で小型商品全量約定を仮定する制約が残る。',
        '全玉停止の発動は現在値による概算。報告時価は清算気配と返済料を使用し、停止閾値を最大損失保証としていない。',
        '理想的無ドリフトの注文対照を実相場の勝率の断定へ拡張していない。注文管理全般が不可能と証明したとは記載しない。']
    result=dict(合格=True,HTML_SHA256=names,埋込会計完全一致=checked,描画入力指紋一致=len(generated['入力SHA256']),
        文面解釈監査=findings,主固定全30両商品黒字条件数=both,留意='実ブラウザの見た目は別担当の検査。本監査は静的描画資料・計算・意味の照合。')
    save('公開HTMLの数値と解釈監査.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
