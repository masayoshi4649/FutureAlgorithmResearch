"""独立会計と画面を確認し、参加停止再開の全場結果を公開する。"""

import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
FOLDER = '00085_仮想成績による参加停止と再開'
NAME = '仮想成績で停止再開する手法と全セッション損益.html'
OUT = ROOT/'アルゴリズム調査'/FOLDER


def read(path):
    """
    機能: 日本語JSONの検査証拠を読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 公開物と既存成果の内容指紋を計算する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 全81条件の独立検査後、最新の資料と入口を更新する。
    引数: なし。
    返り値: None。旧00084の全成果を保持する。
    """
    audits = [WORK/'audit/全81停止再開の公開根拠と全会計及び逆対照恒等式監査.json',
              WORK/'review/独立解釈と全親会計再検算及び逃した回復利益.json']
    for path in audits:
        assert read(path)['全合格']
    generation,display = read(HERE/'生成結果.json'),read(HERE/'表示の独立検査.json')
    assert generation['全合格'] and display['全合格'] and display['目視確認']
    assert sha(OUT/NAME)==generation['HTML_SHA256']==display['HTML_SHA256']
    for name,digest in generation['使用資料SHA256'].items():
        assert sha(ROOT/name)==digest,name
    old = ROOT/'アルゴリズム調査/00084_異なる戦略への配分と同時運転'
    old_hashes = {str(p.relative_to(ROOT)):sha(p) for p in old.iterdir() if p.is_file()}
    analysis_path = WORK/'analysis/比較結果.json'
    analysis = read(analysis_path)
    assert analysis['全合格'] and analysis['conditions']==81 and analysis['primary']=='B0622_C16_P60'
    (OUT/'公開会計.json').write_bytes(analysis_path.read_bytes())
    (OUT/'README.md').write_text(f'''# 仮想成績による参加停止と再開

最初に [{NAME}]({NAME}) を開いてください。独立仮想口座の過去成績に基づく81条件を全30場で検証しました。

1. 主HTML先頭の結論と同配分の常時参加との比較。
2. 選択欄で全81条件の全30場利益・損失・収支・新規／返済枚数。
3. 折畳で拒否した回復利益4親、損失回避と利益喪失、期間・源別損益・参加件数。
4. 再集計は [公開会計.json](公開会計.json)。再生・独立監査は `../../work/wave_v89`。

主は `B0622_C16_P60`：GU6・M3逆2・C032枚（NKは2倍）、最新16完了仮想親の金額利益割合60%以上の源だけ新規参加。
仮想口座は停止中も完走。過去成績だけをセッションへ持越し、建玉は全場返済します。判断時計より厳密に古い完了だけを参照します。
割合条件は4完了未満を許可。連敗条件は4完了を待たず停止できます。許可した親の途中管理は元の源どおりです。
通常60%以上と逆60%未満は、準備不足を除き採用集合が排反です。全親会計と全原板時価まで和の恒等式を独立検算しました。

**両銘柄の利益80%は未達。過去成績で停止再開する共通の改善策としては採用に至りませんでした。**
前16による参考選定も停止なしを選択。全期間は既知探索で、未知期間での保証ではありません。
価格はラージCurrentPriceの次有効観測、実契約の換算はTOPIXmini/NK225micro。各新規・返済注文へ立会手数料を計上。
全体片方向上限TOPIX10枚／NK20枚、拒否で空く枠を他源へ貸しません。仮想料金を実口座へ二重計上せず、含み損は全清算時価へ含めました。

再生成（プロジェクトルート）：

```text
python -X utf8 work/wave_v89/analysis/analyze.py
python -X utf8 work/wave_v89/report/build.py
python -X utf8 work/wave_v89/report/verify.py
```

再生は `python -X utf8 work/wave_v89/research.py --run`。固定内容と指紋を確認後に実行します。
新規条件の独立監査は人工5,832口座・実観測4,536切断、全81条件4,860実口座の会計と時計を照合しました。
旧00084は変更していません。現在API取得と実注文は0件。利益80%を目指す調査は継続中です。
''',encoding='utf-8')
    # ----------------------------------------
    # 入口だけを更新し、過去の各調査の本文と数値は保持する。
    path = ROOT/'README.md'
    text = path.read_text(encoding='utf-8')
    line = f'最新の調査は **[00085：仮想成績による参加停止と再開](アルゴリズム調査/{FOLDER}/{NAME})** です。停止中も紙上を動かす81条件を全30場で検証。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。利益80%への調査は継続中です。'
    text,count = re.subn(r'^最新の調査は .*$',line,text,count=1,flags=re.MULTILINE)
    assert count==1
    path.write_text(text,encoding='utf-8')
    path = ROOT/'アルゴリズム調査/README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00085案内開始-->.*?<!--00085案内終了-->\s*','',text,flags=re.DOTALL)
    text = text.replace('**最新は00084の','**00084の')
    first,rest = text.split('\n',1)
    block = f'''<!--00085案内開始-->
**最新は00085の[{NAME}]({FOLDER}/{NAME})。過去仮想成績による停止再開の81条件、全30場、損失回避と利益喪失の比較。**

[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。利益80%への調査は継続中です。
<!--00085案内終了-->

'''
    path.write_text(first+'\n\n'+block+rest.lstrip(),encoding='utf-8')
    path = ROOT/'アルゴリズム調査/index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00085開始-->.*?<!--00085終了-->\s*','',text,flags=re.DOTALL)
    text = text.replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
    text = re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00085：仮想成績で停止・再開する81条件を検証。避けた損失と逃した利益を元の親へ対応させて比較します。</p>',text,count=1,flags=re.DOTALL)
    article = f'''\n<!--00085開始--><article class="task latest"><div class="number">作業00085 <span class="badge">最新</span></div><h2>仮想成績による参加停止と再開</h2><p>過去の仮想成績で新規を停止し、紙上回復で再開する81条件。全30場と、回復の最初の利益を取り逃した実例を掲載。</p><a class="button" href="{FOLDER}/{NAME}">停止再開と全場損益</a> <a href="{FOLDER}/README.md">読む順序</a></article><!--00085終了-->\n'''
    assert '</header>' in text
    path.write_text(text.replace('</header>','</header>'+article,1),encoding='utf-8')
    for name,digest in old_hashes.items():
        assert sha(ROOT/name)==digest,name
    proof = dict(全合格=True,旧00084保持=old_hashes,独立監査SHA256={str(p.relative_to(ROOT)):sha(p) for p in audits},
        公開SHA256={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='公開指紋.json'})
    (OUT/'公開指紋.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('00085の資料と入口を公開、旧00084を保持。利益80%への調査は継続中。',flush=True)


if __name__=='__main__':
    main()
