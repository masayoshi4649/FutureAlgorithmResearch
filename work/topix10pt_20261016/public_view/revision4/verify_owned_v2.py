"""正しい価格ptまで拒否した初版を保全し、同bytes私有複製だけから差分表示を閉じる。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
OUT=HERE/'render_v2'
HTML_SHA='bcb4ae475fc94583928dda86b60ee230c7ab42f95cf437ed53c4f103480545f0'
JSON_SHA='d2236e18866d94ce1872f3b0aca079297f3af8a98c770565727b91016471e3c2'
MD_SHA='12d32626b39c322b24ee0c99149e4875ddbf4e7c6a54cc985992d419c5ef2ee6'
ADDED='../../work/topix10pt_20261016/s03_review/S03の仮説と六割の信頼性を敵対的に確認.md'


def module():
    """
    機能: 初版検査器をsourceとして読み、誤った一行だけ私有注入から除く。
    引数: なし。
    返り値: module は同じrenderer。初版ファイルを変更しない。
    """
    spec=importlib.util.spec_from_file_location('保全した表示検査初版',HERE/'verify_delta.py')
    loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded)
    lines=loaded.PROBE.splitlines();removed=[line for line in lines if '率差のpt残り' in line]
    assert len(removed)==1
    loaded.PROBE='\n'.join(line for line in lines if '率差のpt残り' not in line)
    assert '率差五セル' in loaded.PROBE and '％ポイント単位' in loaded.PROBE
    loaded.HERE=OUT;return loaded


def write(name: str,value: dict) -> None:
    """
    機能: 初版と別位置へ証跡を新規保存する。
    引数: name(str)、value(dict) はv2出力。
    返り値: None。
    """
    OUT.mkdir(exist_ok=True);path=OUT/name;assert not path.exists();path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def prepare() -> None:
    """
    機能: 公開再読0のrenderer修正理由と私有複製の指紋を先に固定する。
    引数: なし。
    返り値: None。新市場読取を許可するものではない。
    """
    old=module()
    write('誤検知を分離した同bytes再表示の計画.json',dict(全合格=True,source_SHA256=old.sources(),
        v2source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        期待=dict(HTML=HTML_SHA,JSON=JSON_SHA,MD=MD_SHA),
        原因='初版の本文全体regexが価格の−2.5ptを率差残りと誤認。率差五セルの厳密期待は初版でも合格済み。',
        修正='本文全体のpt禁止だけ注入から除去。実際の率差五セルの％ポイント厳密照合は維持。',
        予定=dict(新公開追加読取=0,同bytes新HTML_JSON_MD=3,同bytes旧HTML_JSON=2,初版False=1,市場結果=0,prepared=0,金融=0,API=0),
        初版保全='revision4/verify_delta.py・False.json・開始.json・計画・ownedは全て不変更。'))


def run() -> None:
    """
    機能: 一読保全済みの三公開物だけを再利用し、差分と広狭PNGを確認する。
    引数: なし。
    返り値: None。新公開本文やリンク先本文は開かない。
    """
    old=module();plan=json.loads((OUT/'誤検知を分離した同bytes再表示の計画.json').read_bytes())
    assert plan['source_SHA256']==old.sources() and plan['v2source_SHA256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    failure=json.loads((HERE/'False.json').read_bytes());assert '率差のpt残り' in failure['例外']
    assert failure['読取計数']['新公開HTML']==failure['読取計数']['新公開JSON']==failure['読取計数']['新追補MD']==1
    raw_html=(HERE/'owned'/old.HTML_NAME).read_bytes();raw_json=(HERE/'owned'/old.JSON_NAME).read_bytes();raw_md=(HERE/'owned'/old.MD_NAME).read_bytes()
    assert old.sha(raw_html)==HTML_SHA and old.sha(raw_json)==JSON_SHA and old.sha(raw_md)==MD_SHA
    previous_html=(old.PREVIOUS/'owned'/('同bytes_'+old.HTML_NAME)).read_bytes();previous_json=(old.PREVIOUS/'owned'/('同bytes_'+old.JSON_NAME)).read_bytes()
    assert old.sha(previous_html)==old.OLD_HTML and old.sha(previous_json)==old.OLD_JSON
    data=json.loads(raw_json);assert data==json.loads(previous_json)
    soup=BeautifulSoup(raw_html.decode('utf-8'),'html.parser');before=old.tables(BeautifulSoup(previous_html.decode('utf-8'),'html.parser'));after=old.tables(soup)
    assert json.loads(soup.find('script',id='report-data').get_text())==data and set(before)==set(after)
    cells=0;units=0;headers=0
    for name,rows in before.items():
        assert len(rows)==len(after[name])
        for a,b in zip(rows,after[name]):
            assert len(a)==len(b)
            for x,y in zip(a,b):
                want='良い方との差（率）' if x=='良い方との差' else re.sub(r'([+−-]\d+(?:\.\d+)?)pt$',r'\1％ポイント',x)
                assert y==want,(name,x,y);cells+=1
                if x=='良い方との差':headers+=x!=y
                else:units+=x!=y
    assert units==5 and headers==2
    expected=dict(official=data['selection']['正式候補'],
        units=[x.get_text() for x in soup.select('#primary-table tbody tr td:nth-child(7),#posthoc-comparison-table tbody tr td:last-child')],added_link=ADDED)
    links=[]
    for label,hrefs in (('HTML',[x['href'] for x in soup.select('a[href]')]),('MD',re.findall(r'\[[^\]]*\]\(([^)]+)\)',raw_md.decode('utf-8')))):
        for href in hrefs:
            parsed=urlsplit(href);assert not parsed.scheme and not parsed.netloc
            target=(old.PUBLIC/unquote(parsed.path)).resolve() if parsed.path else old.PUBLIC/old.HTML_NAME
            assert target.is_relative_to(old.ROOT) and target.is_file(),str(target)
            links.append(dict(source=label,href=href,path=target.relative_to(old.ROOT).as_posix()))
    results=[old.render(raw_html.decode('utf-8'),expected,'PC1450',1450),old.render(raw_html.decode('utf-8'),expected,'モバイル520',520)]
    assert old.sources()==plan['source_SHA256']
    value=dict(全合格=True,目視確認=False,前QA_SHA256=old.OLD_PROOF,公開JSON全項目同値=True,正式選択不変=True,
        公開_SHA256=dict(HTML=HTML_SHA,JSON=JSON_SHA,MD=MD_SHA),静的表比較セル=cells,率差単位修正セル=units,率差見出し修正セル=headers,
        画面=results,リンク=links,初版False保全=True,修正理由=plan['原因'],読取=plan['予定'],
        初回公開一読の計数=failure['読取計数'],source_SHA256=plan['source_SHA256'],source始終一致=True)
    write('率差単位と反証リンクの独立差分表示検査_v2.json',value)
    print(json.dumps(dict(全合格=True,静的セル=cells,率差単位=units,見出し=headers,目視確認=False,
        SHA256=old.sha((OUT/'率差単位と反証リンクの独立差分表示検査_v2.json').read_bytes())),ensure_ascii=False))


def main() -> None:
    """
    機能: 私有再表示の計画と実行を分離する。
    引数: CLI --prepare又は--run。
    返り値: None。
    """
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--prepare',action='store_true');mode.add_argument('--run',action='store_true')
    args=parser.parse_args();prepare() if args.prepare else run()


if __name__=='__main__':main()
