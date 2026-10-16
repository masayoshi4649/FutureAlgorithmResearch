"""実画像を確認した利確四比較の表示と導線を確定する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from finalize_sizing import Links


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'


def main() -> None:
    """
    機能: 目視した三画面を記録し、利確修正の最新文書と知見の参照を確認する。
    引数: なし。rootが1450/520と補足展開の実画像を見た後だけ実行する。
    返り値: None。金融・板・台帳・APIを利用しない。
    """
    proof_path=HERE/'goal_anchor_review/利確目標修正の全場と広狭表示確認.json'
    proof=json.loads(proof_path.read_text(encoding='utf-8'))
    assert proof['全合格'] and len(proof['画面'])==3
    for screen in proof['画面']:
        assert screen['全合格'] and screen['円枚数照合']==1360 and screen['概要照合']==88
        assert Path(screen['画像']).is_file()
    proof['根目視確認']=True
    proof['根目視内容']='広狭画面の暗色本文・概要・横スクロールと、旧比較/初回受理q及び目標/上位3場除外の展開画像を確認。'
    proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    # ----------------------------------------
    # 文書更新後の指紋と参照は、前段の証跡を上書きせず別に保存する。
    targets=[ROOT/'README.md',ROOT/'アルゴリズム調査/README.md',ROOT/'アルゴリズム調査/index.html',
        ROOT/'アルゴリズム調査/調査方針.md',PUBLIC/'README.md',
        PUBLIC/'枚数に合わせた利確修正と全セッション損益.html',PUBLIC/'数量変更で残った損失の具体例.md']
    targets.extend((ROOT/'アルゴリズム調査/共通/知見台帳').glob('*.md'))
    references=[];shas={}
    for source in targets:
        raw=source.read_bytes();text=raw.decode('utf-8-sig')
        shas[source.relative_to(ROOT).as_posix()]=hashlib.sha256(raw).hexdigest()
        if source.suffix=='.html':
            parser=Links();parser.feed(text);links=parser.references
        else:
            links=re.findall(r'\]\(([^)]+)\)',text)
        for link in links:
            link=link.strip().strip('<>')
            if not link or link.startswith(('https:','http:','mailto:','#')):
                continue
            relative=unquote(link.split('#',1)[0].split('?',1)[0])
            assert (source.parent/relative).resolve().is_file(),(source,link)
            references.append(dict(出典=source.relative_to(ROOT).as_posix(),参照先=link))
    result=dict(全合格=True,参照確認数=len(references),対象SHA256=shas,
        根目視資料=proof_path.relative_to(ROOT).as_posix(),参照=references,
        主評価条件数=365,今回追加金融条件=4,両商品最新三基準合格=0,
        追加金融=0,原板=0,NPZ=0,API=0)
    (HERE/'goal_anchor_review/利確修正の目視と最新導線確認.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(全合格=True,目視画像=3,参照確認数=len(references),両商品三基準合格=0),ensure_ascii=False))


if __name__=='__main__':
    main()
