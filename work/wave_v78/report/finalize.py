"""固定した検証と表示・目視の証跡を一つの公開前確認へまとめる。"""

import argparse
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
OUT=ROOT/'アルゴリズム調査/00074_歴代手法の再評価と二市場統合'


def load(path: Path) -> dict:
    """機能: 検査証跡を読む。

    引数: path(Path)。返り値: 内容(dict)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: ファイル内容のSHA256を計算する。

    引数: path(Path)。返り値: 指紋(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as f:
        while data:=f.read(4*1024*1024):h.update(data)
    return h.hexdigest()


def main() -> None:
    """機能: 独立監査、固定指紋、目視を終えた同じHTMLを検査する。

    引数: CLI --viewed(bool) は確認担当が画像を実際に閲覧した後だけ指定する。
    返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--viewed',action='store_true');args=parser.parse_args()
    assert args.viewed,'画面を実際に閲覧してから実行してください'
    fixed=load(WORK/'事前固定.json')
    assert all(digest(ROOT/p)==h for p,h in fixed['SHA256'].items()),'固定後変更'
    evidence={}
    for name in ('独立会計器の自己検査.json','統合管理の人工経路と独立会計監査.json',
                 '全162条件と固定感度の独立会計監査.json','固定代表と管理部品の実注文未来不変監査.json'):
        path=WORK/'audit'/name;value=load(path);assert value['合格'];evidence[name]=digest(path)
        if 'engine_SHA256' in value:assert value['engine_SHA256']==digest(WORK/'engine.py')
        if '固定SHA256' in value:assert value['固定SHA256']==digest(WORK/'事前固定.json')
    count=load(WORK/'audit/全162条件と固定感度の独立会計監査.json')
    assert count['条件数']==210 and count['口座数']==12600 and count['全行清算時価照合数']==12600
    assert count['選定SHA256']==digest(WORK/'前半選定.json')
    for delay in (1,5,15):
        path=WORK/'prepared'/f'信号照合_delay{delay}.json';value=load(path)
        assert value['場数']==30 and value['既往FD15完全一致場数']==29 and value['旧common及び価格有効性完全一致場数']==30 and value['途中切断一致数']==90
        evidence[path.name]=digest(path)
        path=(WORK if delay==5 else WORK/'sensitivity'/f'delay{delay}')/'旧3基準の完全一致.json';assert load(path)['合格'];evidence[str(path.relative_to(WORK))]=digest(path)
    # ----------------------------------------
    # 目視した画像と、元会計を全照合したHTMLの指紋を一致させる。
    display=load(HERE/'表示検査.json')
    assert display['全合格'] and display['元結果一致口座数']==9720
    assert all(r['全合格'] and Path(r['画像']).exists() for r in display['実画面'])
    hashes=display['HTML_SHA256']
    assert all(digest(OUT/name)==h for name,h in hashes.items())
    published=load(OUT/'公開会計.json');assert hashes==published['公開SHA256'] and published['表示集計一致']
    prior=ROOT/'アルゴリズム調査/00073_二市場判断と金額利益8割への改善'
    assert digest(prior/'金額利益8割を目指す改善と全セッション損益.html')=='776a04576d4eb04b3e6d5cf0b3a0cc2b3f4e535af437ec3684633e9b94c2c37b'
    assert digest(prior/'全492条件の比較.html')=='e91e11b5b7ddf75a457aad5ddd6fda6b250b81c1b3b48686929c6f6fd198ffab'
    display['目視確認']=True
    display['目視内容']='最終HTMLの広幅・狭幅・全条件・売買図を画像で閲覧し、暗色背景・金額・注文・表内横スクロールを確認。'
    (HERE/'表示検査.json').write_text(json.dumps(display,ensure_ascii=False,indent=2),encoding='utf8')
    proof=dict(全合格=True,監査確認=True,目視確認=True,HTML_SHA256=hashes,監査SHA256=evidence,
        事前固定SHA256=digest(WORK/'事前固定.json'),旧成果不変=True,API取得=0,実注文=0)
    (HERE/'公開前確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print('固定・独立監査・画面検査を確認しました')


if __name__=='__main__':
    main()
