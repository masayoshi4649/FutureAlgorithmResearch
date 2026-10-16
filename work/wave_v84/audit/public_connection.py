"""公開会計・読む順序・固定資料と元結果の接続を確認する。"""
import re
from html.parser import HTMLParser
from urllib.parse import unquote,urlsplit
from context import *
from accounts import load

PUBLIC=ROOT/'アルゴリズム調査/00080_順行逆指値と反転売買の検証'


class Links(HTMLParser):
    """機能: 静的HTMLの実リンクを収集する。"""
    def __init__(self):
        """機能: 保持器を作成する。

        引数: なし。返り値: なし(None)。
        """
        super().__init__();self.links=[]

    def handle_starttag(self,tag,attrs):
        """機能: リンク先属性を抽出する。

        引数: tag(str)、attrs(list)。返り値: なし(None)。
        """
        self.links.extend(v for k,v in attrs if k=='href' and v)


def main() -> None:
    """機能: 公開コピーの一致とローカルリンクを検査する。

    引数: なし。返り値: なし(None)。循環を避け公開会計自身の指紋は保存しない。
    """
    payload=load(PUBLIC/'公開会計.json');fixed=load(WORK/'results/事前固定.json')
    assert payload['全30']==fixed['全30']
    for column,stage in [('通常気配','final/delay0'),('現在値必約定と実手数料','ideal_fee')]:
        assert payload[column]=={p.stem:load(p) for p in (WORK/stage/'results').glob('*.json')}
    for name in ['final','ideal_fee']:
        assert payload['少数取引の探索的参考'][name]=={p.stem:load(p) for p in (WORK/'supplement'/name/'results').glob('*.json')}
    for name,value in payload['独立監査'].items():
        if name!='公開接続監査.json':assert value==load(HERE/name),name
    for name,value in payload['表示検査'].items():assert value==load(WORK/'report'/name)
    specs=load(PUBLIC/'検証条件と固定記録.json')
    for column,path in [('事前固定','results/事前固定.json'),('前半選定','前半選定.json'),
        ('現在値必約定の条件','ideal_fee/固定条件.json'),('探索的参考の追加固定','supplement/追加固定.json')]:
        assert specs[column]==load(WORK/path)
    assert specs['入力照合']==load(WORK.parent/'wave_v83/prepared/価格入力の照合.json')
    for path,value in specs['損失診断'].items():assert value==load(WORK/path)
    for name,h in specs['旧成果保持'].items():assert digest(ROOT/'アルゴリズム調査'/name)==h
    public_hashes=load(PUBLIC/'公開指紋.json')
    for name,h in public_hashes['成果'].items():assert digest(PUBLIC/name)==h
    # ----------------------------------------
    count=0
    for path in list(PUBLIC.glob('*.html'))+[PUBLIC/'README.md']:
        body=path.read_text(encoding='utf8')
        if path.suffix=='.html':
            parser=Links();parser.feed(body);targets=parser.links
        else:targets=re.findall(r'\[[^\]]*\]\(([^)]+)\)',body)
        for target in targets:
            parts=urlsplit(target)
            if parts.scheme or not parts.path:continue
            assert (path.parent/unquote(parts.path)).resolve().exists();count+=1
    for path in [ROOT/'README.md',ROOT/'アルゴリズム調査/README.md',ROOT/'アルゴリズム調査/index.html']:
        assert '00080_順行逆指値と反転売買の検証' in path.read_text(encoding='utf8')
    text=(PUBLIC/'README.md').read_text(encoding='utf8').replace('−','-')
    for family in range(6):
        name=f'F{family}_W08_V1';row=payload['現在値必約定と実手数料'][name]['periods']['対象']
        for symbol in ['TOPIX','NK225']:assert f'{row[symbol]["net"]:+,.0f}円' in text
    for snippet in ['実際にこの価格で全量約定できるという意味ではありません','主選定は変更していません','未知データでの証明ではありません']:
        assert snippet in text
    result=dict(合格=True,公開会計=['通常14','実手数料理論14','追加参考1の両モデル','独立監査','表示検査'],
        固定資料と診断完全一致=True,旧成果保持=len(specs['旧成果保持']),有効な相対リンク=count,
        README同幅6理論数値一致=True,入口3ファイル=True,
        制約='表示検査は検査時点の保存資料へ一致。HTMLの描画そのものは別担当の証跡。自己参照を避け公開会計自身のSHAを保存しない。')
    save('公開接続監査.json',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
