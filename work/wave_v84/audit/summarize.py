"""各独立検査の範囲と確かめられなかった点を集約する。"""
from context import *
from accounts import load


def main() -> None:
    """機能: 証跡と固定指紋を検査して監査総括とREADMEを保存する。

    引数: なし。返り値: なし(None)。旧成果と原本は変更しない。
    """
    stages=['train','final_delay0','ideal_fee','supplement_final','supplement_ideal_fee']
    fields=['条件数','口座数','注文数','決済脚数','全玉終了組数','会計照合項目','期間会計数',
        '予約イベント独立照合口座','予約イベント数','全行清算時価SHA一致口座']
    totals={k:0 for k in fields};details={};fingerprints={}
    fixed=load(WORK/'results/事前固定.json')
    assert digest(WORK.parent/'wave_v83/prepared/inputs.pkl')==fixed['input_SHA256']
    for directory,key in [(WORK,'code_SHA256'),(WORK.parent/'wave_v83','legacy_code_SHA256')]:
        for name,h in fixed[key].items():assert digest(directory/name)==h
    for stage in stages:
        p=HERE/f'{stage}の独立会計監査.json';d=load(p);assert d['合格']
        details[stage]={k:d[k] for k in fields};fingerprints[p.name]=digest(p)
        for k in fields:totals[k]+=d[k]
        for name,h in d['結果SHA256'].items():
            path=WORK/name;assert digest(path)==h
            run=load(path)['run']
            assert run['input_SHA256']==fixed['input_SHA256']
            assert run['code_SHA256']==fixed['code_SHA256']
            assert run['legacy_code_SHA256']==fixed['legacy_code_SHA256']
    for name in ['ドテン人工境界と独立会計.json','全家族人工未来切断監査.json',
        '前半選定と最終前半再生の独立照合.json','全代表の実原本未来切断監査.json',
        '少数取引追加の実原本未来切断監査.json','全代表の入口極値とドテン判断監査.json',
        '公開損失診断と理由名の独立照合.json']:
        p=HERE/name;assert load(p)['合格'];fingerprints[name]=digest(p)
    review=HERE/'公開HTMLの数値と解釈監査.json'
    if review.exists():assert load(review)['合格'];fingerprints[review.name]=digest(review)
    limits=[
        '条件数と口座数は、同じ原本の条件・約定モデル別の延べ再生数であり、独立相場の数ではない。',
        '初回前16の予約イベントは未保存。実約定・全玉会計・全行時価は全件照合し、予約は人工境界及び最終代表の全イベントで検査した。',
        '主選定14は前16だけで固定。少数取引追加1は主結果閲覧後の探索であり、両者を分けている。いずれも全30場は既知で未知検証ではない。',
        'CurrentPriceTimeと保存行順に対する因果性の監査であり、実受信時刻・小型商品の独自板・注文到着・待ち順位・部分約定は保証しない。',
        '現在値必約定と売買気配約定は、価格とその後の保有経路が異なる。対照間の差を気配差だけの費用足し戻しと解釈しない。',
        '会計・因果性の合格は、利益の持続性や実売買での再現性を証明しない。']
    result=dict(合格=True,延べ独立会計=totals,段階別=details,証跡SHA256=fingerprints,
        事前固定SHA256=digest(WORK/'results/事前固定.json'),主選定SHA256=digest(WORK/'前半選定.json'),
        追加固定SHA256=digest(WORK/'supplement/追加固定.json'),限界=limits)
    save('独立監査総括.json',result)
    body=['# 00080 の独立監査','',
        'ドテン時の返済と反対新規を別注文として照合し、全玉会計・保有上限・極値と最初の発動行・未来不変の検査に合格した。','',
        '| 段階 | 条件実行 | 口座 | 注文 | 決済 |',
        '|---|---:|---:|---:|---:|']
    for stage,row in details.items():body.append('| '+stage+' | '+' | '.join(f'{row[k]:,}' for k in ['条件数','口座数','注文数','決済脚数'])+' |')
    body+=['','合成216ケースと60人工経路919未来切断を確認した。実原本の途中切断は主107口座1,296地点、追加7口座42地点。',
        '保存注文と現在値の区間演算から、入口・極値・最初の返済条件を独立再計算した。通常・理論・追加の1,800口座で59,804入口、20,451即ドテン、58,703通常返済が一致した。',
        '主再生の前16は448口座、追加は32口座で初回台帳と完全一致した。','',
        '詳細は [独立監査総括.json](独立監査総括.json) と各監査JSONを参照。','']
    body+=['- '+v for v in limits]
    (HERE/'README.md').write_text('\n'.join(body)+'\n',encoding='utf8')
    print(json.dumps(totals,ensure_ascii=False))


if __name__=='__main__':main()
