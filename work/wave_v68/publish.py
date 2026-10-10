"""新作業00065を登録し、主結果・根拠へのリンクを検査する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

import report

HERE = Path(__file__).resolve().parent
INDEX = report.ROOT/'アルゴリズム調査/index.html'
README = INDEX.parent/'README.md'
FOLDER = report.OUT.name


def main() -> None:
    """機能: 会計・因果・気配感度完了を確認し、最新作業と読む順を登録する。

    引数: なし。返り値: なし(None)。
    """
    read = report.compare.read
    assert read(HERE/'audit/台帳独立会計_observed.json')['総口座数'] == 2128
    assert read(HERE/'review/気配価格置換の完了.json')['口座数'] == 2128
    visual = read(HERE/'HTML表示の独立検査.json')
    assert visual['全合格']
    assert visual['主HTML_SHA256'] == hashlib.sha256((report.OUT/'損失を減らす改修と全セッション損益.html').read_bytes()).hexdigest()
    results = '''# 損失低減の検証結果

損失対策として残す候補は **R01_P2T：手数料後2組連敗したら新規を30分休止**。その後、連敗数を0から数え直し元方式で再開する。1組は初回新規から全返済まで。TOPIXミニ初回5枚、NK225マイクロ初回10枚、増玉なし。入口と個々の建玉の出口はR01を維持する。

| 全28場・手数料後 | 元R01の負け組損失 | 改修後 | 削減 | 勝ち組利益の維持 | 元収支 | 改修収支 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| TOPIXミニ | 1,402,606円 | 1,261,511円 | 10.1% | 90.8% | +615,981円 | +570,992円 |
| NK225マイクロ | 632,980円 | 577,440円 | 8.8% | 96.1% | +235,140円 | +257,060円 |

元の282組中29入口を休止で見送り、共通253入口の収支は全て同じ。両銘柄とも全28場で取引を継続。取引総数はTOP139→121、NK143→132組。初回枚数を減らしただけの比較ではない。

**減らせたのは負けの回数・総額。1回の最大損失は不変**（TOP40,418円、NK14,220円）。平均負け組損失はTOP16,698→17,281円、NK7,535→7,499円。全期間の場内最大下落はTOP158,799→134,464円、NK84,095→74,875円。ただし後12ではTOP111,507→128,762円と増加し、全ての場面で資産下落を抑える改善ではない。

後12の収支はTOP+142,528→+117,283円、NK+44,940→+43,540円。休止は損失だけでなく回復の利益も逃す。10/05ナイトTOPでは回避した損失より逃した利益が大きく、場収支が28,749円悪化した。

## その他の改善候補

前16の事前基準による順位はE01_T05X、E01_P2T、R01_P2T。採否は各条件の元方式との銘柄別比較を行い、後12で選び直していない。

1位E01_T05Xは「5分以降、一度も0.5ATRへ伸びず、現在0.25ATR逆行なら全返済」。日経の全28損失を20.6%減らして収支も増やしたが、TOPでは回復する勝ちを切り、後12収支−148,070円。共通改修としては不採用。10/01日中TOP買いで元+95,084→−12,918円となり、後半の元勝ち26組中8組を負けへ変えた。

一律の0.5／0.375ATR損失枠、板中値逆行で半減・全返済、EMA失効撤退、5／10／15／30分失敗判定、2連敗で場終了、累積−2Rで場終了など、2基準＋36改修＝38条件を比較。数値と各条件の不合格理由は[全38条件の比較](全38条件の比較.html)。

## 執行と検証

買いを売り気配・売りを買い気配へ置換した固定注文感度では、R01_P2T全28収支はTOP+395,492円、NK+194,860円（元R01は+436,981／+167,740円）。E01_T05XのTOP全28は−1,629円へ崩れた。この感度は注文の発動条件や次の入口を再生成していない。

手数料は新規・返済ともTOPIXmini41.8円／枚、NK225micro11円／枚。1注文合計を1円未満切捨て。含み損益・全損失玉を含め、セッション末に全返済。

2,128口座・26,594注文・16,255決済の独立会計、全観測の含み時価・最大下落、38条件の途中切断／未来変更、人工経路23件を照合。判定に未来価格を用いていない。しかし全28場は既知で、後半の損失診断も仮説作りに使ったため、選定の過適合や将来利益を保証しない。

最初に見るファイルは[損失を減らす改修と全セッション損益](損失を減らす改修と全セッション損益.html)。元00064・App/E01は変更していない。現在API取得0、実注文0。
'''
    (report.OUT/'検証結果.md').write_text(results,encoding='utf8')
    source = INDEX.read_text(encoding='utf8')
    source = source.replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    source = re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00065：E01／R01の損失低減を38条件で比較。損失を削る効果と利益を逃す代償。</p>',source,count=1)
    block = f'''<!--00065開始--><article class="task latest"><div class="number">作業00065 <span class="badge">最新</span></div><h2>E01とR01の損失低減</h2><p>早期失敗整理・損失枠短縮・連敗休止。保存28場、同じ初回枚数、手数料後の損失／利益維持、全場・週の金額と枚数、売買図。</p><a class="button" href="{FOLDER}/損失を減らす改修と全セッション損益.html">損失を減らす改修と損益を開く →</a><p><a href="{FOLDER}/全38条件の比較.html">全38条件</a> · <a href="{FOLDER}/検証結果.md">短い検証結果</a> · <a href="{FOLDER}/README.md">資料案内</a></p></article><!--00065終了-->'''
    if '<!--00065開始-->' in source:
        source = re.sub(r'<!--00065開始-->.*?<!--00065終了-->',block,source,flags=re.S)
    else:
        source = source.replace('<!--00064開始-->',block+'\n<!--00064開始-->',1)
    INDEX.write_text(source,encoding='utf8')
    text = README.read_text(encoding='utf8').replace('**最新は00064','**00064')
    guide = f'''<!--00065案内開始-->
**最新は00065の[損失を減らす改修と全セッション損益]({FOLDER}/損失を減らす改修と全セッション損益.html)。38条件で損失低減と利益維持を比較。28場・手数料後、全場と週の損益・枚数、5分足売買図。**

[全38条件]({FOLDER}/全38条件の比較.html) · [短い検証結果]({FOLDER}/検証結果.md) · [資料案内]({FOLDER}/README.md)。
<!--00065案内終了-->
'''
    if '<!--00065案内開始-->' in text:
        text = re.sub(r'<!--00065案内開始-->.*?<!--00065案内終了-->\n?',guide,text,flags=re.S)
    else:
        text = text.replace('<!--00064案内開始-->',guide+'\n<!--00064案内開始-->',1)
    README.write_text(text,encoding='utf8')
    # ----------------------------------------
    # 新旧の全HTMLリンクとREADMEの相対パスを確認する。
    count = 0
    for path in (INDEX,report.OUT/'損失を減らす改修と全セッション損益.html',report.OUT/'全38条件の比較.html'):
        for tag in BeautifulSoup(path.read_text(encoding='utf8'),'html.parser').select('a[href]'):
            href = tag['href']
            if href.startswith(('http','#')):
                continue
            target = (path.parent/unquote(href.split('?',1)[0].split('#',1)[0])).resolve()
            assert target.exists(),target
            count += 1
    for path in (README,report.OUT/'README.md',report.OUT/'検証結果.md'):
        for href in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf8')):
            if href.startswith(('http','#')):
                continue
            target = (path.parent/unquote(href.split('?',1)[0].split('#',1)[0])).resolve()
            assert target.exists(),target
            count += 1
    (HERE/'公開リンク照合.json').write_text(json.dumps(dict(全合格=True,リンク数=count,
        最新作業='00065',公開先=str(report.OUT)),ensure_ascii=False,indent=2),encoding='utf8')
    print('00065を最新に登録、全リンク照合完了:',count)


if __name__ == '__main__':
    main()
