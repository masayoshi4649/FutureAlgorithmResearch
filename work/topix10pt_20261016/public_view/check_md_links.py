"""一読保全済みの追補MDだけから追加のローカルリンクを確認する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote,urlsplit


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PUBLIC=ROOT/'アルゴリズム調査/00118_TOPIX十ポイントの予兆と多尺度方向予測'


def main() -> None:
    """
    機能: 公開MDの同bytes私有保全だけからリンク実在を検査する。
    引数: なし。
    返り値: None。市場本文・リンク先本文・公開MDの再読は行わない。
    """
    body=(HERE/'owned/同bytes_事後に残った予兆候補S03.md').read_bytes()
    assert hashlib.sha256(body).hexdigest()=='0a6fce26d2af7f89e6a230f41ec4e6469ea0f17369cfe2434cdde3cb3d4fe2d7'
    text=body.decode('utf-8');links=[]
    for href in re.findall(r'\[[^\]]*\]\(([^)]+)\)',text):
        parts=urlsplit(href);assert not parts.scheme and not parts.netloc
        target=(PUBLIC/unquote(parts.path)).resolve();assert target.is_relative_to(ROOT) and target.is_file(),str(target)
        links.append(dict(href=href,path=target.relative_to(ROOT).as_posix()))
    assert len(links)>=2
    path=HERE/'同bytes追補MDのリンク実在の追加検査.json';assert not path.exists()
    value=dict(全合格=True,公開MD_SHA256=hashlib.sha256(body).hexdigest(),リンク=links,
        読取=dict(同bytes私有MD=1,公開追加読取=0,リンク先本文=0,市場結果=0,prepared=0,金融=0,API=0))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,リンク数=len(links),SHA256=hashlib.sha256(path.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
