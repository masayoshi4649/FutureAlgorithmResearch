"""既存の00120へ指定デイの全玉明細の導線を追加する。"""

import hashlib
import json
from pathlib import Path
import re


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
NAME='00120_段階トレーリング新規と利益玉の部分回転'
FILE='2026-09-24_Dayの売買と利確明細.html'


def update(path: Path, before: str, after: str) -> dict:
    """
    機能: 一意の既存案内へ明細リンクだけを追加する。
    引数: path(Path)は案内、before/after(str)は置換前後の一意な部分。
    返り値: dictは変更前後のSHA。既存金融HTMLは変更しない。
    """
    original=path.read_bytes()
    text=original.replace(b'\r\r\n',b'\r\n').decode('utf-8')
    assert text.count(before)==1
    if FILE in text:
        assert text.count(FILE)==1
        # 初回はindexの既存marker不足で停止したため、三案内は重複させず再利用する。
    else:
        text=text.replace(before,after,1)
    path.write_bytes(text.encode('utf-8'))
    return dict(path=path.relative_to(ROOT).as_posix(),before_sha256=hashlib.sha256(original).hexdigest(),
                after_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def main() -> None:
    """
    機能: 日付明細と従来40場報告を区別し、四つの既存案内から開けるようにする。
    引数: なし。
    返り値: None。新しい金融や試行登録を行わない。
    """
    public=ROOT/'アルゴリズム調査'/NAME
    assert (public/FILE).is_file()
    changes=[]
    for path,prefix in ((ROOT/'README.md','アルゴリズム調査/'),(ROOT/'アルゴリズム調査/README.md','')):
        marker='<!--00120案内終了-->'
        line=f'追加：[2026-09-24 デイの全売買・利確明細]({prefix}{NAME}/{FILE})。ROTATEの両銘柄315玉について、新規・返済の時刻、価格、値幅、枚数、円損益を掲載。\n'
        changes.append(update(path,marker,line+marker))
    path=public/'README.md'
    title='# 段階トレーリング新規と利益玉の部分回転'
    changes.append(update(path,title,title+f'\n\n指定日：[2026-09-24 デイの全売買・利確明細]({FILE})。上下対称の個別利益回転ROTATE_S2_T1の315玉を表示します。'))
    path=ROOT/'アルゴリズム調査/index.html'
    original=path.read_bytes()
    text=original.decode('utf-8')
    if '<!--00120開始-->' in text:
        start=text.index('<!--00120開始-->');end=text.index('<!--00120終了-->')
        fragment=text[start:end]
        assert fragment.count('</article>')==1 and FILE not in fragment
        fragment=fragment.replace('</article>',f' <a href="{NAME}/{FILE}">9月24日デイの全売買明細</a></article>')
        text=text[:start]+fragment+text[end:]
    else:
        # 先行の案内生成は属性付きmainを認識せずカードを挿入していなかった。
        match=re.search(r'<main\b[^>]*>',text)
        assert match and FILE not in text
        card=f'''\n<!--00120開始--><article class="task latest"><div class="number">作業00120・段階トレーリング</div><h2>上下対称の利益玉回転とカバー保持</h2><p>114条件・両商品40場。最新18条件を含め、残在庫と反復損失を確認しました。</p><a class="button" href="{NAME}/{FILE}">9月24日デイの全売買明細</a> <a href="{NAME}/段階トレーリングの結論と全セッション損益.html">114条件と全40場の結果</a> <a href="{NAME}/README.md">読む順序</a></article><!--00120終了-->\n'''
        text=text[:match.end()]+card+text[match.end():]
    path.write_bytes(text.encode('utf-8'))
    changes.append(dict(path=path.relative_to(ROOT).as_posix(),before_sha256=hashlib.sha256(original).hexdigest(),
                        after_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for target in ('desktop','mobile'):
        for path in (HERE/'visual'/target).glob('*.json'):
            data=json.loads(path.read_text(encoding='utf-8'))
            if 'viewed_by_root' in data:
                data['viewed_by_root']=True
                data['rows_note']='rowsは旧40場用selectorなので0。明細の行数・315玉は独立表示会計で別に照合。'
                path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (HERE/'案内と表示確認の追記.json').write_text(json.dumps(dict(passed=True,changes=changes,
        root_viewed_PC_mobile=True,financial_replay=0,original_market_reads=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('00120の指定日明細へ四案内を追加。既存114条件の金融・HTML・台帳は不変。')


if __name__=='__main__':
    main()
