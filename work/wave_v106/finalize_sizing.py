"""目視した数量四比較の表示証跡と、最新文書の参照を確定する。"""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'


class Links(HTMLParser):
    """HTMLの参照先だけを集める表示確認用パーサ。"""

    def __init__(self) -> None:
        """
        機能: 参照先の格納先を初期化する。
        引数: なし。
        返り値: None。外部接続をしない。
        """
        super().__init__()
        self.references=[]

    def handle_starttag(self,tag: str,attrs: list[tuple[str,str|None]]) -> None:
        """
        機能: HTMLリンクの相対先を保存する。
        引数: tag(str)は要素名、attrs(list[tuple[str,str|None]])は属性。
        返り値: None。リンク先はまだ読まない。
        """
        if tag=='a':
            self.references.extend(v for k,v in attrs if k=='href' and v)


def main() -> None:
    """
    機能: 実際に確認した3画像を記録し、変更文書のローカルリンクを確認する。
    引数: なし。rootが広狭及び損失二例を目視した後だけ実行する。
    返り値: None。金融・原板・台帳・APIを利用しない。
    """
    proof_path=HERE/'risk_sizing_review/予定リスク数量の四切替全33場と広狭確認.json'
    proof=json.loads(proof_path.read_text(encoding='utf-8'))
    assert proof['全合格'] and len(proof['画面'])==3
    for screen in proof['画面']:
        assert screen['全合格'] and screen['円枚数照合']==1360 and screen['損失例表示照合']==10
        assert Path(screen['画像']).is_file()
    proof['根目視確認']=True
    proof['根目視内容']='1450/520の暗色本文と横スクロール、4比較概要、監査二例の展開表示を実画像で確認。'
    proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    # ----------------------------------------
    # 変更した導線と共通知見の参照を、同じ保存時点の指紋へ束縛する。
    targets=[ROOT/'README.md',ROOT/'アルゴリズム調査/README.md',ROOT/'アルゴリズム調査/index.html',
        ROOT/'アルゴリズム調査/調査方針.md',PUBLIC/'README.md',
        PUBLIC/'予定リスクで枚数を変える4比較と全セッション損益.html',PUBLIC/'数量変更で残った損失の具体例.md']
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
        主評価条件数=361,追加金融条件=4,両商品最新三基準合格=0,
        追加金融=0,原板=0,NPZ=0,API=0)
    (HERE/'risk_sizing_review/数量四比較の目視と全導線確認.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(全合格=True,目視画像=3,参照確認数=len(references),両商品三基準合格=0),ensure_ascii=False))


if __name__=='__main__':
    main()
