"""ブラウザが描画した全場表と、保存会計・資料リンクの一致を確認する。"""

import json
from urllib.parse import unquote
from bs4 import BeautifulSoup
from common139 import HERE,PUBLIC,read,ref


def main():
    """
    機能: 静的データ全146条件とブラウザ初期表示47場を検査する。
    引数: なし。
    返り値: None。金融再生を行わずQA証跡だけを保存する。
    """
    path=PUBLIC/'段階投入と早期参加の全セッション損益.html';source=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
    data=json.loads(source.select_one('#data').string);assert len(data['rows'])==146
    for method,pair in data['rows'].items():
        for symbol,rows in pair.items():
            assert len(rows)==47 and len({r[0] for r in rows})==47
            s=data['summary'][symbol][method]['全47場'];assert sum(r[1] for r in rows)==s['profit'] and sum(r[2] for r in rows)==s['loss']
            assert sum(r[3] for r in rows)==s['net']
            assert all(r[1]-r[2]==r[3] and r[1]>=0 and r[2]>=0 for r in rows)
    links=[]
    for node in source.select('a[href],img[src]'):
        target=node.get('href',node.get('src'))
        if target.startswith(('https:','http:','#')):continue
        local=(PUBLIC/unquote(target.split('#')[0])).resolve();assert local.is_file(),str(local);links.append(str(local))
    rendered=BeautifulSoup((HERE/'rendered139.html').read_text(encoding='utf-8'),'html.parser')
    assert len(rendered.select('#sessions tbody tr'))==47
    footer=rendered.select_one('#sessions tfoot').get_text()
    for symbol in ('NK225','TOPIX'):
        net=data['summary'][symbol]['P07']['全47場']['net'];assert f'{net:,.0f}' in footer
    assert len(rendered.select('#method option'))==146
    assert '初回2枚' in rendered.select_one('#description').get_text()
    result=dict(passed=True,conditions=146,accounts=13724,rendered_rows=47,local_links=len(links),
        report=ref(path),screenshot=ref(HERE/'preview139.png'),financial_replays=0,
        scope='Chromiumの初期選択P07と全データ・資料リンク。スクリーンショットを目視。')
    (HERE/'表示確認.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
