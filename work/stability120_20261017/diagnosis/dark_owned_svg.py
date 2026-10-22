"""所有SVGの配色だけを変更し、数値データを開かず暗色PNGへ描画する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


HERE=Path(__file__).resolve().parent/'formal_b'
ROOT=HERE.parents[3]
NAME='最悪場の確定損益と全玉清算時価及び長短枚数'
COLORS={'#ffffff':'#0b1120','#000000':'#dce6f2','#b0b0b0':'#64748b',
        '#cccccc':'#64748b','#17814d':'#6ee7b7','#c13d43':'#fb7185',
        '#cf6767':'#fb7185','#1974b8':'#60a5fa','#cb8c23':'#fbbf24','#7c8794':'#94a3b8'}


def structural(root: ET.Element) -> list[tuple]:
    """
    機能: 配色style以外のSVG要素と全属性を比較用に取り出す。
    引数: root(Element)はSVGルート。
    返り値: list[tuple]は全図形・文字経路・座標の不変確認用。
    """
    return [(node.tag,tuple((k,v) for k,v in node.attrib.items() if k!='style'),node.text,node.tail) for node in root.iter()]


def main() -> None:
    """
    機能: 白図を保持して暗色版を作り、正式MDの図参照だけを更新する。
    引数: なし。
    返り値: None。市場・結果JSON・NPZを読まず、金融を再生しない。
    """
    source=HERE/(NAME+'.svg');png=HERE/(NAME+'.png')
    svg=HERE/(NAME+'_暗色.svg');target=HERE/(NAME+'_暗色.png')
    md=HERE/'利益玉を回しても不利な在庫が少なくならなかった原因.md'
    archive=HERE/'archive/白図参照の完成版'
    assert not archive.exists() and not svg.exists() and not target.exists()
    archive.mkdir(parents=True)
    for path in (md,HERE/'正式bの利益回転と残在庫損失診断の完了証跡.json',HERE/'在庫図の担当目視確認.json'):
        (archive/path.name).write_bytes(path.read_bytes())
    before_svg=source.read_bytes();before_png_sha=hashlib.sha256(png.read_bytes()).hexdigest()
    original=ET.fromstring(before_svg); tree=ET.fromstring(before_svg)
    for node in tree.iter():
        if 'style' in node.attrib:
            style=node.attrib['style']
            for a,b in COLORS.items():style=style.replace(a,b)
            node.set('style',style)
    tree.set('style','fill: #dce6f2; color: #dce6f2')
    for group in tree.iter():
        if group.get('id','').startswith('legend_'):
            for node in group.iter():
                style=node.get('style','')
                if 'fill: #0b1120' in style:node.set('style',style.replace('fill: #0b1120','fill: #142137'))
    assert structural(original)==structural(tree)
    ET.register_namespace('','http://www.w3.org/2000/svg')
    ET.register_namespace('xlink','http://www.w3.org/1999/xlink')
    converted=ET.tostring(tree,encoding='unicode')
    assert '#ffffff' not in converted and '#000000' not in converted
    svg.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'+converted,encoding='utf8')
    # ----------------------------------------
    # ローカルSVGだけを一時HTMLへ埋め、隔離したheadless ChromeでPNGへ変換する。
    html=HERE/'暗色SVGをPNGへ変換する所有画面.html'
    html.write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><title>暗色在庫図</title>'
        '<style>html,body{margin:0;background:#0b1120;color:#dce6f2;width:1650px;height:1005px;overflow:hidden}'
        'svg{display:block;width:1650px;height:1005px}</style>'+converted+'</html>',encoding='utf8')
    chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    args=[str(chrome),'--headless=new','--disable-gpu','--hide-scrollbars','--disable-background-networking',
          '--no-first-run','--no-default-browser-check','--force-device-scale-factor=1',
          '--window-size=1650,1005','--user-data-dir='+str(HERE/'dark_render_profile'),
          '--screenshot='+str(target),html.as_uri()]
    run=subprocess.run(args,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=40)
    assert run.returncode==0 and target.is_file(),run.stderr[-1500:]
    from PIL import Image
    with Image.open(target) as result:
        assert result.size==(1650,1005)
        assert result.convert('RGB').getpixel((0,0))==(11,17,32)
    text=md.read_text(encoding='utf8')
    assert text.count(NAME+'.png')==1
    md.write_text(text.replace(NAME+'.png',NAME+'_暗色.png'),encoding='utf8')
    assert source.read_bytes()==before_svg and hashlib.sha256(png.read_bytes()).hexdigest()==before_png_sha
    files=(source,png,svg,target,md,archive/md.name,html,Path(__file__))
    evidence=dict(全合格=True,改訂='所有SVGの配色と正式MDの図参照だけ。白図を保持。',
        図形属性と全座標及び文字経路同一=True,背景='#0b1120',文字と軸='#dce6f2',凡例背景='#142137',
        描画終了コード=run.returncode,PNG画素=[1650,1005],PNG左上RGB=[11,17,32],
        数値データ読取=0,結果JSON読取=0,NPZ読取=0,原市場読取=0,金融再生=0,根目視=False,担当目視=False,
        outputs=[dict(path=p.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size) for p in files])
    proof=HERE/'暗色図と診断MD参照だけの表示改訂証跡.json'
    assert not proof.exists();proof.write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'全合格':True,'PNG':str(target.relative_to(ROOT)),'改訂証跡SHA256':hashlib.sha256(proof.read_bytes()).hexdigest(),
        'MD_SHA256':hashlib.sha256(md.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=='__main__':
    main()
