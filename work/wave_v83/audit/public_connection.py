"""公開会計・固定記録・読む順序が監査済み原資料へ接続するか検査する。"""
import re
from urllib.parse import unquote,urlsplit
from html.parser import HTMLParser
from context import *
from accounts import load

PUBLIC=ROOT/'アルゴリズム調査/00079_方向予測を使わない注文手法の検証'


class Links(HTMLParser):
    """機能: 静的HTMLの実リンク属性だけを収集する。"""
    def __init__(self):
        """機能: リンク保持器を作る。

        引数: なし。返り値: なし(None)。
        """
        super().__init__();self.links=[]

    def handle_starttag(self, tag, attrs):
        """機能: 開始タグのhrefを収集する。

        引数: tag(str)、attrs(list)。返り値: なし(None)。
        """
        self.links.extend(value for name,value in attrs if name=='href' and value)


def main() -> None:
    """機能: 公開資料の完全一致・旧成果保持・導線を検査する。

    引数: なし。返り値: なし(None)。循環を避け公開会計自身のSHAは証跡へ含めない。
    """
    actual=load(PUBLIC/'公開会計.json');fixed=load(WORK/'results/事前固定.json')
    assert actual['期間']==fixed['全30']
    for column,stage in [('通常','final/delay0'),('論理対照','ideal'),('指定現在値約定と実手数料','ideal_fee'),('指値保持モデル','persistent')]:
        sources={p.stem:load(p) for p in (WORK/stage/'results').glob('*.json')}
        assert actual[column]==sources,column
    assert actual['無作為20種']==load(WORK/'sensitivity/無作為20種の比較.json')
    assert actual['表示検査']==load(WORK/'report/HTML表示の独立検査.json')
    for name,value in actual['監査'].items():
        if name!='公開接続監査.json':assert value==load(HERE/name),name
    assert actual['監査']['独立監査総括.json']==load(HERE/'独立監査総括.json')
    spec=load(PUBLIC/'検証条件と固定記録.json')
    sources={'事前固定':'results/事前固定.json','前半選定':'前半選定.json','入力照合':'prepared/価格入力の照合.json',
        '論理対照':'ideal/固定条件.json','指定現在値と実手数料':'ideal_fee/固定条件.json',
        '指値保持改修':'persistent/固定条件.json','損失診断':'diagnosis/12家族代表の損失構造.json'}
    for key,name in sources.items():assert spec[key]==load(WORK/name)
    fingerprints=load(PUBLIC/'公開指紋.json')
    for name,h in fingerprints['成果'].items():assert digest(PUBLIC/name)==h
    for name,h in spec['旧成果保持'].items():assert digest(ROOT/'アルゴリズム調査'/name)==h
    logic=load(PUBLIC/'注文手法の論理対照.json')
    assert logic['仮説']==load(WORK/'theory/注文管理だけで利益を生む仮説と10家族.json')
    assert logic['人工相場']==load(WORK/'theory/人工相場による注文手法の性質.json')
    # ----------------------------------------
    links=0
    for path in list(PUBLIC.glob('*.html'))+[PUBLIC/'README.md']:
        body=path.read_text(encoding='utf8')
        if path.suffix=='.html':
            parser=Links();parser.feed(body);targets=parser.links
        else:targets=re.findall(r'\[[^\]]*\]\(([^)]+)\)',body)
        for target in targets:
            parts=urlsplit(target)
            if parts.scheme or not parts.path:continue
            assert (path.parent/unquote(parts.path)).resolve().exists(),(path.name,target)
            links+=1
    for path in [ROOT/'README.md',ROOT/'アルゴリズム調査/README.md',ROOT/'アルゴリズム調査/index.html']:
        assert '00079_方向予測を使わない注文手法の検証' in path.read_text(encoding='utf8')
    readme=(PUBLIC/'README.md').read_text(encoding='utf8')
    for name in ['O06_W08_V2','O06_W08_V3']:
        row=actual['通常'][name]['periods']['対象']
        for symbol in ['TOPIX','NK225']:assert f'{row[symbol]["net"]:+,.0f}円' in readme
    assert 'その観測で子の返済条件を1回評価' in readme
    result=dict(合格=True,公開会計=['通常13','無費用論理対照13','実手数料論理対照13','指値保持3','乱数20','独立監査総括','最新表示検査'],
        固定記録照合=len(sources),旧公開保持=len(spec['旧成果保持']),有効な相対リンク=links,
        入口3ファイル=True,README主2条件収支=True,親約定前子発動なし説明=True,
        制約='公開指紋の全成果を照合した。自己参照を避け、この証跡に公開会計自身のSHAは保存しない。')
    save('公開接続監査.json',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
