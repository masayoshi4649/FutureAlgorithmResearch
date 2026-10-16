"""全会計・安定性・独立監査・画面と旧成果の保持を検査して00090を公開する。"""

import ast
import hashlib
import json
from pathlib import Path
import re
import shutil


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]
RESEARCH=ROOT/'アルゴリズム調査'
FOLDER='00090_独立価格と現在確認によるセッション安定化'
OUT=RESEARCH/FOLDER
MAIN=OUT/'独立価格と現在確認の説明と全セッション損益.html'
PRIMARY='I3_G1_S0_T1'
FIXED_SHA='94969a99b2e7373cb2c34a8f8c7cc23ea234ce26d1b32904e175f1e440efbc6b'
SELECTED_SHA='ae9e460810faacf2d13e67f14ee8cbee05b6a5488fc6bfc23d7a5832499c2f3e'
ACCOUNT_SHA='8fd876ff1ee6500a37af2745597a398d0cf370c35040bbe1912cb9091388df67'


def read(path: Path) -> dict:
    """機能: 確定した日本語JSONを読む。

    引数: path(Path)。返り値: dictは資料内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """機能: 大きな公開会計も一定メモリーで指紋化する。

    引数: path(Path)。返り値: strはSHA256。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def check_hashes(values: dict) -> None:
    """機能: 根拠資料の指紋と現在内容の一致を検査する。

    引数: values(dict[str,str])はルート相対位置とSHA。返り値: Noneは一致確認。
    """
    for relative,expected in values.items():assert sha(ROOT/relative)==expected,relative


def prior_files() -> dict:
    """機能: 旧00089・00088・00087の全公開ファイルを指紋化する。

    引数: なし。返り値: dict[str,str]は全成果のSHA。
    """
    folders=('00089_予定リスクと中心利確及び失敗後再参加',
             '00088_回復確認と中心帰還による再参加','00087_待機基準の保持と二市場反対による返済')
    assert all((RESEARCH/folder).is_dir() for folder in folders)
    return {str(path.relative_to(ROOT)):sha(path) for folder in folders
            for path in sorted((RESEARCH/folder).rglob('*')) if path.is_file()}


def evidence(manifest: dict,name: str) -> tuple:
    """機能: 公開前に確定した根拠資料をそのSHAで検査する。

    引数: manifest(dict)、name(str)。返り値: tuple[Path,dict]は確認済み根拠。
    """
    item=manifest['資料'][name];expected=item['SHA256']
    assert isinstance(expected,str) and re.fullmatch('[0-9a-f]{64}',expected),name
    path=ROOT/item['path'];assert sha(path)==expected,name
    value=read(path);assert value.get('全合格') is True,name
    check_hashes(value.get('SHA256',{}))
    return path,value


def main() -> None:
    """機能: 全3286口座・848商品期間・独立源・境界・表示の合格後だけ公開する。

    引数: なし。返り値: Noneは最新案内と確認済み公開資料の保存。
    未確定の指紋や未閲覧の正式結果を使って公開せず、旧成果を一切編集しない。
    """
    manifest_path=HERE/'公開確定指紋.json';manifest=read(manifest_path)
    assert manifest['確定済み'] is True,'正式会計・独立説明・根目視の確定前は公開しません'
    prior_path=HERE/'旧00089_00088_00087公開成果の保持.json';prior=read(prior_path)
    assert prior_files()==prior['全旧成果SHA256']
    fixed_path=WORK/'事前固定.json';fixed=read(fixed_path)
    assert sha(fixed_path)==FIXED_SHA and len(fixed['SHA256'])==181
    assert fixed['全31既知'] and fixed['新しい未見確認場数']==0
    assert len(fixed['条件'])==53 and fixed['主']==PRIMARY
    check_hashes(fixed['SHA256'])
    selected_path=WORK/'前16参考代表.json';selected=read(selected_path)
    assert sha(selected_path)==SELECTED_SHA
    assert selected['全合格'] and selected['selected']=='J8' and selected['後15正式損益前選定']
    assert selected['固定SHA256']==FIXED_SHA
    check_hashes(selected['結果SHA256'])
    # ----------------------------------------
    # 会計と安定性の完結全範囲を検査し、源別の相殺や未照合の集計を公開しない。
    account_path,account=evidence(manifest,'正式会計')
    assert sha(account_path)==ACCOUNT_SHA
    assert account['条件数']==53 and account['primary']==PRIMARY and account['selected']=='J8'
    assert account['全31既知'] and account['新未見確認場数']==0
    assert account['catalog']==fixed['条件'] and account['sessions']==fixed['全31']
    assert len(account['results'])==53 and sum(len(r['rows']) for r in account['results'].values())==3286
    assert sum(len(r['periods'])*2 for r in account['results'].values())==848
    assert sum(len(r['stability'])*2 for r in account['results'].values())==848
    policy=read(WORK/'セッション安定性の事前評価.json')
    assert account['セッション安定性の事前評価']==policy
    check_hashes(account['正式結果SHA256'])
    full_path,full=evidence(manifest,'全範囲独立検算')
    assert full['検査件数']['口座']==3286 and full['検査件数']['商品期間集計']==848
    assert full['固定先行コード変更']==full['新損益による監査条件選別']==0
    assert full['SHA256'][str(account_path.relative_to(ROOT))]==sha(account_path)
    identity_path,identity=evidence(manifest,'実行手順同一性')
    assert identity['全53条件省略なし'] and identity['元main前後前提及び後段省略なし']
    assert identity['凍結検算関数変更']==identity['凍結監査ファイル変更']==identity['固定181依存変更']==0
    assert identity['新損益による監査条件選別']==0 and identity['事前固定SHA256']==FIXED_SHA
    assert identity['worker数']==3 and all(worker['全完了'] for worker in identity['worker完了'])
    completed=[ident for worker in identity['worker完了'] for ident in worker['完了条件']]
    assert len(completed)==53 and set(completed)=={config['id'] for config in fixed['条件']}
    assert len(identity['全53チェックポイントSHA256'])==53
    check_hashes(identity['読取監査SHA256'])
    check_hashes(identity['全53チェックポイントSHA256'])
    check_hashes(identity['証跡SHA256'])
    assert identity['証跡SHA256'][str(full_path.relative_to(ROOT))]==sha(full_path)
    assert identity['検査件数']==full['検査件数']
    old_full=WORK/'audit/full.py'
    assert sha(old_full)==identity['凍結fullSHA256']
    tree=ast.parse(old_full.read_text(encoding='utf-8'))
    old_main=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main')
    ast_text=ast.dump(ast.Module(body=old_main.body,type_ignores=[]),include_attributes=False)
    ast_digest=hashlib.sha256(ast_text.encode('utf-8')).hexdigest()
    same_ast=identity['構文木同一性']
    assert same_ast['元main文数']==same_ast['再結合文数']==len(old_main.body)==26
    assert same_ast['元main全体構文木SHA256']==same_ast['分割再結合構文木SHA256']==ast_digest
    interrupted_item=manifest['資料']['元中断記録'];interrupted_path=ROOT/interrupted_item['path']
    assert sha(interrupted_path)==interrupted_item['SHA256']
    interrupted=read(interrupted_path)
    assert interrupted['正式最終合格'] is False and '全合格' not in interrupted
    assert interrupted['数学検算基準変更']==interrupted['正式PL変更']==0
    assert interrupted['固定full原本変更']==interrupted['凍結181依存変更']==0
    assert interrupted['潜在例外が実際に発生したとの主張'] is False
    check_hashes(interrupted['SHA256'])
    projection_path,projection=evidence(manifest,'配分源別')
    assert len(projection['検査'])==124 and projection['源間相殺']==projection['枠貸出']==0
    assert all(row['全原板源時価一致'] for row in projection['検査'])
    selection_path,selection=evidence(manifest,'独立参考選定')
    assert selection['参考代表']=='J8'
    assert selection['選定に後15正式損益使用']==selection['当段階後15損益閲覧']==0
    assert selection['SHA256'][str(selected_path.relative_to(ROOT))]==SELECTED_SHA
    boundary_path,boundary=evidence(manifest,'立会境界')
    assert boundary['口座数']==3286 and boundary['全注文数']==full['検査件数']['注文']
    assert boundary['連続立会末以降約定']==boundary['立会末以降約定']==boundary['立会開始以前約定']==0
    assert boundary['全注文数']==11320 and full['検査件数']['決済親']==5660
    # ----------------------------------------
    # 独立説明と生成・表示・根担当の目視を同じHTMLと同じ根拠へ結ぶ。
    supplement_item=manifest['資料']['説明補足'];supplement_path=ROOT/supplement_item['path']
    assert sha(supplement_path)==supplement_item['SHA256']
    supplement=read(supplement_path)
    assert supplement['根集計SHA256']==sha(account_path) and supplement['売買及び会計の変更']==0
    assert supplement['全合格'] and len(supplement['根拠SHA256'])==11
    check_hashes(supplement['根拠SHA256'])
    for path in (full_path,identity_path,interrupted_path):
        assert supplement['根拠SHA256'][str(path.relative_to(ROOT))]==sha(path)
    j8_review=WORK/'review/J8旧イベントの前決済と連続損失及び既知市場開始の前後分類.json'
    assert supplement['根拠SHA256'][str(j8_review.relative_to(ROOT))]==sha(j8_review)
    assert read(j8_review)['全合格']
    display=read(HERE/'表示の独立検査.json');generated=read(HERE/'生成結果.json')
    assert display['全合格'] and display['目視確認']
    assert display['保存結果一致数']==53 and display['保存会計口座数']==3286
    assert generated['条件数']==53 and generated['口座数']==3286
    assert display['HTML_SHA256']==generated['HTML_SHA256']==sha(MAIN)
    assert len(display['画面'])==5
    assert all(view['全合格'] and view['条件切替数']==53 and view['セッション口座表示数']==3286
               and view['JavaScriptエラー']==0 for view in display['画面'])
    check_hashes(generated['使用資料SHA256'])
    assert generated['使用資料SHA256'][str(supplement_path.relative_to(ROOT))]==sha(supplement_path)
    for path,expected in supplement['根拠SHA256'].items():assert generated['使用資料SHA256'][path]==expected
    check_hashes(display['画像SHA256']);check_hashes(display['検査実装SHA256'])
    root_visual=read(HERE/'根担当の五画面目視.json')
    assert root_visual['全合格'] and root_visual['HTML_SHA256']==sha(MAIN)
    assert len(root_visual['確認画像SHA256'])==5
    assert root_visual['確認画像SHA256']==display['画像SHA256']
    check_hashes(root_visual['確認画像SHA256'])
    # ----------------------------------------
    # 確認済みの新成果だけ保存し、旧案内はリンクを残したまま最新印だけを移す。
    shutil.copyfile(account_path,OUT/'公開会計.json');assert sha(OUT/'公開会計.json')==sha(account_path)
    template=(HERE/'README.template.md').read_text(encoding='utf-8')
    summary='\n\n'.join(supplement['conclusion'][:3])
    guide=template.replace('__SUMMARY__',summary)
    assert '__SUMMARY__' not in guide
    (OUT/'README.md').write_text(guide,encoding='utf-8')
    root_readme=ROOT/'README.md';text=root_readme.read_text(encoding='utf-8')
    line=(f'最新の調査は **[00090：独立価格と現在確認によるセッション安定化]'
          f'(アルゴリズム調査/{FOLDER}/{MAIN.name})** です。53条件・全31既知場の平均赤字・最大赤字・'
          f'活動黒字率と全場損益を比較。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。'
          '両銘柄の安定収益と金額利益80%への調査は継続中です。')
    text,count=re.subn(r'^最新の調査は .*$',lambda match:line,text,count=1,flags=re.M);assert count==1
    root_readme.write_text(text,encoding='utf-8')
    research_readme=RESEARCH/'README.md';text=research_readme.read_text(encoding='utf-8')
    if '<!--00090案内開始-->' not in text:
        block=(f'<!--00090案内開始-->\n**最新は00090の[{MAIN.name}]({FOLDER}/{MAIN.name})。'
               '独立価格と現在入口の53条件。各セッションの赤字と安定性を優先し、全31場の損益を掲載。**\n\n'
               f'[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。'
               '既知データの比較であり、将来の収益成功とは扱いません。\n<!--00090案内終了-->\n\n')
        assert '<!--00089案内開始-->' in text
        text=text.replace('**最新は00089の','**00089の',1)
        text=text.replace('<!--00089案内開始-->',block+'<!--00089案内開始-->',1)
    research_readme.write_text(text,encoding='utf-8')
    index=RESEARCH/'index.html';text=index.read_text(encoding='utf-8')
    if '<!--00090開始-->' not in text:
        text=text.replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
        article=(f'<!--00090開始--><article class="task latest"><div class="number">作業00090 '
                 '<span class="badge">最新</span></div><h2>独立価格と現在確認によるセッション安定化</h2>'
                 '<p>53条件・全31既知場。平均赤字・最大赤字・活動黒字率を優先し、'
                 '価格と執行源を分けた手法及び全場損益を比較します。</p>'
                 f'<a class="button" href="{FOLDER}/{MAIN.name}">説明と全場損益</a> '
                 f'<a href="{FOLDER}/README.md">読む順序</a></article><!--00090終了-->\n')
        assert '<!--00089開始-->' in text;text=text.replace('<!--00089開始-->',article+'<!--00089開始-->',1)
    text,count=re.subn(r'<p class="lead">最新000(?:89|90)：.*?</p>',
        '<p class="lead">最新00090：最大利益より赤字場の安定性。53条件・全31既知場の損益を掲載します。</p>',text,count=1)
    assert count==1;index.write_text(text,encoding='utf-8')
    assert prior_files()==prior['全旧成果SHA256']
    outputs=[MAIN,OUT/'README.md',OUT/'公開会計.json',root_readme,research_readme,index]
    proof=dict(全合格=True,HTML_SHA256=sha(MAIN),全口座=3286,商品期間集計=848,
               全31既知=True,新未見確認場数=0,根担当五画面目視確認=True,
               旧00089と00088と00087全成果不変=True,旧成果指紋=prior['全旧成果SHA256'],
               公開指紋={str(path.relative_to(ROOT)):sha(path) for path in outputs},
               公開確定指紋SHA256=sha(manifest_path),監査SHA256=sha(full_path),
               源別独立SHA256=sha(projection_path),立会内清算SHA256=sha(boundary_path),
               独立参考選定SHA256=sha(selection_path),説明補足SHA256=sha(supplement_path),
               凍結全手順同一性SHA256=sha(identity_path),元中断記録SHA256=sha(interrupted_path),
               条件及び参考の差替え=False,API取得=0,実注文=0)
    (HERE/'公開結果.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in proof.items() if key!='旧成果指紋'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
