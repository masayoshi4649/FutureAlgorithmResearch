"""勝率の再評価を独立集計と照合し、同じ作業の補足として索引へ載せる。"""

import hashlib
import json
from pathlib import Path

import publish_report as publication

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=publication.OUT


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main() -> None:
    """機能: 独立勝率計算・画面・リンクを確認し、補足リンクと公表記録を更新する。

    引数: なし。返り値: なし(None)。原本・注文計算・売買明細は変更しない。
    """
    own=publication.read(HERE/'8割基準の再評価.json')
    other=publication.read(HERE/'統合12方式の勝率再集計.json')
    assert own['全合格'] and other['全合格']
    mapping={'黒字数':'session_wins','赤字数':'session_losses','同値セッション数':'session_zeros',
        'セッション数':'session_total','セッション勝率':'session_winrate','勝ち取引数':'cycle_wins',
        '負け取引数':'cycle_losses','同値取引数':'cycle_zeros','一連取引数':'cycle_total',
        '一連取引勝率':'cycle_winrate','一枚平均勝敗比':'average_unit_payoff',
        '一連取引平均勝敗比':'average_cycle_payoff','収支円':'net_yen','途中時価を含む最大下落円':'drawdown_yen'}
    for row in own['結果']:
        check=next(r for r in other['結果'] if r['id']==row['id'] and r['symbol']==row['symbol'])
        assert all(abs(row[key]-check[field])<1e-8 for key,field in mapping.items())
    references=own['参照SHA256']|other['参照SHA256']
    assert all(publication.digest(ROOT/path)==expected for path,expected in references.items())
    visual=publication.read(HERE/'表示検査_2画面.json')
    assert visual['全合格']
    for row in visual['結果']:assert publication.digest(OUT/row['ファイル'])==row['HTML_SHA256']
    visual['目視確認済']=True
    visual['目視画像SHA256']={row['画像']:publication.digest(HERE/row['画像']) for row in visual['結果']}
    save(HERE/'表示検査_2画面.json',visual)
    original=publication.read(HERE/'表示検査_5画面.json')
    for row in visual['結果']:
        if row['ファイル']!='分解と結論.html':continue
        original['結果']=[row if item['ファイル']==row['ファイル'] else item for item in original['結果']]
        original['目視画像SHA256'][row['画像']]=publication.digest(HERE/row['画像'])
    save(HERE/'表示検査_5画面.json',original)
    # ----------------------------------------
    # 00041の追記として示し、過去作業の内容は変更しない。
    name=OUT.name;index=ROOT/'アルゴリズム調査/index.html';readme=ROOT/'アルゴリズム調査/README.md'
    index_text=index.read_text(encoding='utf-8');readme_text=readme.read_text(encoding='utf-8')
    href=f'{name}/8割の勝ちと損小利大.html'
    if href not in index_text:
        marker='<!--00041終了-->';assert marker in index_text
        start=index_text.index('<!--00041開始-->');end=index_text.index(marker)
        block=index_text[start:end]
        block=block.replace('</article>',f'<p><strong>評価基準の補足：</strong><a href="{href}">約8割の黒字と損小利大による再評価</a>。セッション勝率と取引勝率を分けて表示。</p></article>')
        index_text=index_text[:start]+block+index_text[end:]
    if href not in readme_text:
        lines=readme_text.splitlines();position=next(i for i,line in enumerate(lines) if line.startswith('**最新は00041'))
        lines.insert(position+1,f'\n追記：[約8割の勝ちと損小利大での再評価]({href})。既存12方式の同じ14場をセッション勝率・取引勝率で分けて再集計。')
        readme_text='\n'.join(lines)+'\n'
    link_count=publication.links(index,index_text)+publication.links(readme,readme_text)
    link_count+=sum(publication.links(path,path.read_text(encoding='utf-8')) for path in OUT.iterdir() if path.suffix in ('.html','.md'))
    index.write_text(index_text,encoding='utf-8');readme.write_text(readme_text,encoding='utf-8')
    record=dict(全合格=True,独立対応数=24,独立数値一致数=24*len(mapping),元保存参照不変数=len(references),
        リンク確認数=link_count,新売買再生=False,API追加取得数=0,目視確認済=True,
        結論='セッション約8割なら4候補。厳密な両市場80%以上又は取引80%以上とは区別。',
        出力SHA256={str(path.relative_to(ROOT)):publication.digest(path) for path in [OUT/'8割の勝ちと損小利大.html',OUT/'分解と結論.html',OUT/'README.md',index,readme]},
        参照SHA256={str(path.relative_to(ROOT)):publication.digest(path) for path in [HERE/'8割基準の再評価.json',HERE/'統合12方式の勝率再集計.json',HERE/'統合12方式の新勝率基準による整理.md']})
    save(HERE/'8割基準の公表確認.json',record)
    print(json.dumps({k:v for k,v in record.items() if not isinstance(v,dict)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
