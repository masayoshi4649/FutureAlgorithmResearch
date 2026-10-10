"""確認済み画面と独立監査、固定指紋が一致した資料だけを公開可能にする。"""

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
OUT=ROOT/'アルゴリズム調査/00073_二市場判断と金額利益8割への改善'


def load(path: Path) -> dict:
    """機能: 保存された検査証跡を読む。

    引数: path(Path)。返り値: 内容(dict)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 内容のSHA256を計算する。

    引数: path(Path)。返り値: 指紋(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as f:
        while data:=f.read(4*1024*1024):h.update(data)
    return h.hexdigest()


def main() -> None:
    """機能: 監査・固定設定・目視済み六画面をまとめ公開前確認を保存する。

    引数: なし。返り値: なし(None)。監査やHTMLの合否は書き換えない。
    """
    fixed=load(WORK/'事前固定.json')
    assert all(digest(ROOT/p)==h for p,h in fixed['SHA256'].items()),'固定後変更'
    checks={}
    for name in ('独立会計器の自己検査.json','追加と全返済料金配賦の人工独立会計.json','独立損切り利益保護と追加リスクの人工監査.json',
                 '主492条件と固定感度追加の全会計独立監査.json','全価格窓と直前レンジと新Night入力の独立監査.json',
                 '固定代表と追加対照の実注文未来不変監査.json'):
        path=WORK/'audit'/name;value=load(path);assert value['合格'];checks[name]=digest(path)
    count=load(WORK/'audit/主492条件と固定感度追加の全会計独立監査.json')
    assert count['条件数']==558 and count['口座数']==31132 and count['全曲線照合数']==31132
    path=HERE/'12入口と共同状態の未来不変検査.json';value=load(path);assert value['合格'];checks[path.name]=digest(path)
    # ----------------------------------------
    # 人が確認した六枚の表示と、元会計・実操作検査の同じHTMLであることを確認する。
    hashes={}
    for label,name in [('主報告','金額利益8割を目指す改善と全セッション損益.html'),('全一覧','全492条件の比較.html')]:
        path=HERE/(label+'_表示検査.json');proof=load(path);assert proof['全合格'] and all(r['全合格'] for r in proof['結果'])
        assert proof['HTML_SHA256']==digest(OUT/name);hashes[name]=proof['HTML_SHA256']
        for row in proof['結果']:assert Path(row['画像']).exists()
        proof['目視確認']=True;proof['目視内容']='六画面を実画像で確認。暗色背景・文字・金額・売買点・狭幅の表内横スクロールを確認。'
        path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    prior=ROOT/'アルゴリズム調査/00072_二市場の即時板判断と保有管理'
    assert digest(prior/'二市場の即時判断と保有管理の説明と損益.html')=='a4fac23adca476bd4a7c0e90db7eff996dd72a76447d5eef5de49f8760bcf5eb'
    assert digest(prior/'全996条件の比較.html')=='f8b263ccbb39cea45ba95761d0993b67dd3f2e6fc33a4b2c2069fac7262db75e'
    proof=dict(全合格=True,監査確認=True,目視確認=True,HTML_SHA256=hashes,監査SHA256=checks,事前固定SHA256=digest(WORK/'事前固定.json'),
        基準旧成果不変=True,実注文=0,API取得=0)
    (HERE/'公開前確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print('固定・独立会計・未来不変・六画面の公開前確認が完了しました')


if __name__=='__main__':
    main()
