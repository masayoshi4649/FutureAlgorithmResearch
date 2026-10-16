"""重複する一部検査を除き、独立監査の範囲と限界を集約する。"""
from context import *
from accounts import load


def main() -> None:
    """機能: 各段階の証跡を確認して総括JSONと監査READMEを作る。

    引数: なし。返り値: なし(None)。既存エンジン・実績は変更しない。
    """
    stages=['train','final_delay0','sensitivity','ideal','ideal_fee','persistent']
    keys=['条件数','口座数','注文数','決済脚数','全玉終了組数','会計照合項目','期間会計数',
          '予約イベント独立照合口座','予約イベント数','全行清算時価SHA一致口座']
    total={k:0 for k in keys};details={};fingerprints={}
    fixed=load(WORK/'results/事前固定.json')
    assert digest(WORK/'prepared/inputs.pkl')==fixed['input_SHA256']
    code_hashes={}
    for stage in stages:
        p=HERE/f'{stage}の独立会計監査.json';d=load(p);assert d['合格']
        details[stage]={k:d[k] for k in keys}
        for k in keys:total[k]+=d[k]
        for name,h in d['結果SHA256'].items():
            path=WORK/name
            if not path.exists():
                stagepath='final/delay0' if stage=='final_delay0' else stage
                path=WORK/stagepath/'results'/name
            assert digest(path)==h
            run=load(path)['run'];source=run.get('input_SHA256',run.get('source_SHA256'))
            assert source==fixed['input_SHA256']
            for code,expected in run['code_SHA256'].items():
                assert digest(WORK/code)==expected;code_hashes[code]=expected
        fingerprints[p.name]=digest(p)
    audits=['人工境界と全玉会計監査.json','全家族人工未来切断監査.json',
        '前半選定と最終前半再生の独立照合.json','全代表の実原本未来切断監査.json',
        '持続指値の人工境界監査.json','持続指値の実原本未来切断監査.json','公開HTMLの数値と解釈監査.json']
    for name in audits:
        p=HERE/name;d=load(p);assert d['合格'];fingerprints[name]=digest(p)
    limitations=[
        '条件数・口座数は段階をまたぐ延べ実行数。350個の独立戦略や12,936個の独立相場を検証したという意味ではない。',
        '前半288の全量と乱数感度は予約イベント未保存。注文・全玉会計・全行時価は全検査、予約最大値は保存統計と人工境界を参照。',
        '固定代表と全追加対照は予約・取消・約定イベントも全件検査した。',
        '主は追加発注遅延0。人工互換検査にある5秒ケースは主成績・採用判断に使用していない。',
        '保存済み全30場は既知。前半で固定し後半で選び直していない主実験と、全30閲覧後の追加仮説確認を区別する。',
        '因果検査は保存されたCurrentPriceTimeと原本順に対する不変性。実受信時計・秒内経過・取引所の待ち順位・部分約定・小型商品板の再現ではない。',
        '現在値必約定の対照は実行可能な成績ではない。持続指値も対向気配による代理約定で、取引所GTCの実現可能性を証明しない。']
    result=dict(合格=True,延べ独立会計=total,段階別=details,証跡SHA256=fingerprints,
        元入力SHA256=fixed['input_SHA256'],実装指紋一致=code_hashes,限界=limitations)
    save('独立監査総括.json',result)
    body=['# 00079 の独立監査','',
        '全玉会計、注文順、片方向予約上限、因果順、公開数値の監査は合格。合格は実装と会計の整合性を示し、将来利益を保証しない。','',
        '| 段階 | 条件実行 | 口座 | 注文 | 決済脚 | 親組 |',
        '|---|---:|---:|---:|---:|---:|']
    for stage,d in details.items():
        body.append('| '+stage+' | '+' | '.join(f'{d[k]:,}' for k in ['条件数','口座数','注文数','決済脚数','全玉終了組数'])+' |')
    body+=['','全行の清算時価は現金・保有枚数・買い売り気配・返済料から独立再構成し、保存SHAと照合。親組と各脚の総収支、通常手数料、最大保有、期末残玉ゼロを確認した。',
        '持続指値では、元指値の予約から最初の実行可能気配、元指値での約定、期限・全玉停止時の取消まで全イベントを照合した。','',
        '凍結前にIFD初回監視の欠測後脱落と多段グリッドの記録容量不足を検出し、修正を再検査した。実績閲覧後に主エンジンを変更していない。','',
        '実原本の未来切断は主13代表95口座1,041地点、持続指値3対照23口座449地点。後者は未約定予約中237地点を含む。未来価格変更でも過去の注文・決済・時価・イベントが一致した。','',
        '監査の詳細は [独立監査総括.json](独立監査総括.json)、[公開HTMLの数値と解釈監査.json](公開HTMLの数値と解釈監査.json) を参照。','']
    body+=['- '+item for item in limitations]
    (HERE/'README.md').write_text('\n'.join(body)+'\n',encoding='utf8')
    print(json.dumps(total,ensure_ascii=False))


if __name__=='__main__':main()
