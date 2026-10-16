"""配分検証の独立会計と表示検査を確認し、新しい作業の入口を公開する。"""

import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE.parent
FOLDER = '00084_異なる戦略への配分と同時運転'
NAME = '異なる3手法の配分と全セッション損益.html'
OUT = ROOT/'アルゴリズム調査'/FOLDER


def sha(path):
    """
    機能: 公開物と過去成果の内容指紋を計算する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    """
    機能: 日本語UTF-8の証拠を読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    """
    機能: 全独立検査と画面確認後、README・索引・公開会計を更新する。
    引数: なし。
    返り値: None。旧00083の全成果を保持する。
    """
    audits = [WORK/'audit/全22配分の公開注文と独立全会計監査.json',
              WORK/'review/配分効果と結論の独立再検算.json']
    for path in audits:
        assert read(path)['全合格']
    generation, display = read(HERE/'生成結果.json'), read(HERE/'表示の独立検査.json')
    assert generation['全合格'] and display['全合格'] and display['目視確認']
    assert sha(OUT/NAME)==generation['HTML_SHA256']==display['HTML_SHA256']
    for name, digest in generation['使用資料SHA256'].items():
        assert sha(ROOT/name)==digest, name
    old = ROOT/'アルゴリズム調査/00083_再参加の損失原因と改善の反復検証'
    old_hashes = {str(p.relative_to(ROOT)):sha(p) for p in old.iterdir() if p.is_file()}
    analysis_path = WORK/'analysis/比較結果.json'
    analysis = read(analysis_path)
    assert analysis['全合格'] and analysis['conditions']==22
    (OUT/'公開会計.json').write_bytes(analysis_path.read_bytes())
    (OUT/'README.md').write_text(f'''# 異なる戦略への配分と同時運転

最初に [{NAME}]({NAME}) を開いてください。3手法への22配分を、同じ30セッション・料金・約定条件で比較しました。

1. 主HTML先頭の短い結論と主要比較。
2. 配分選択で全30場の利益・損失・収支・新規／返済枚数。
3. 折畳で手法説明、源別損益、期間、同枚数対照と補完性。
4. 再集計資料は [公開会計.json](公開会計.json)。売買再生と監査は `../../work/wave_v88`。

事前主案はGU6・M3逆2・C032枚（NKは2倍）。参考GU8・M3逆2は全30閲覧後の比較で、事前選定の成功ではありません。
総利益80%・総損失20%、全日安定は未達です。既知データ内の研究であり、未知期間の保証ではありません。
価格はラージのCurrentPrice、数量と倍率はTOPIXmini/NK225micro。源の公開注文後の次有効観測で約定し、新規・返済の実注文ごとに立会手数料を計上します。
合計片方向上限TOPIX10枚／NK20枚。各源に固定枠を持たせ、他源へ空き枠を貸さず、全源を場内で返済します。
親を源間でまとめて負けを消さず、源別の親利益・親損失と、全体の清算時価を別に検算しました。

再生成（プロジェクトルート）：

```text
python -X utf8 work/wave_v88/analysis/analyze.py
python -X utf8 work/wave_v88/report/build.py
python -X utf8 work/wave_v88/report/verify.py
```

売買再生は `python -X utf8 work/wave_v88/research.py --run`。`事前固定.json` と依存指紋を照合してから実行します。
保存済み30セッションを固定した試験です。追加データへ適用する時は、新しい入力と試験期間を別途固定します。
現在API取得と実注文は0件。旧00083の本文・データは変更していません。
''',encoding='utf-8')
    # ----------------------------------------
    # 最新の案内だけを変更し、各既存調査の本文は保存する。
    root_readme = ROOT/'README.md'
    content = root_readme.read_text(encoding='utf-8')
    line = f'最新の調査は **[00084：異なる戦略への配分と同時運転](アルゴリズム調査/{FOLDER}/{NAME})** です。追従・中期逆張り・短期反転への22配分を、全30場で検証。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。利益80%を目指す調査は継続中です。'
    content, count = re.subn(r'^最新の調査は .*$',line,content,count=1,flags=re.MULTILINE)
    assert count==1
    root_readme.write_text(content,encoding='utf-8')
    research_readme = ROOT/'アルゴリズム調査/README.md'
    text = research_readme.read_text(encoding='utf-8')
    text = re.sub(r'<!--00084案内開始-->.*?<!--00084案内終了-->\s*','',text,flags=re.DOTALL)
    text = text.replace('**最新は00083の','**00083の')
    first, rest = text.split('\n',1)
    block = f'''<!--00084案内開始-->
**最新は00084の[{NAME}]({FOLDER}/{NAME})。異なる3手法への22配分・源別損益・全30セッション収支。**

[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。利益80%への調査は継続中です。
<!--00084案内終了-->

'''
    research_readme.write_text(first+'\n\n'+block+rest.lstrip(),encoding='utf-8')
    index = ROOT/'アルゴリズム調査/index.html'
    text = index.read_text(encoding='utf-8')
    text = re.sub(r'<!--00084開始-->.*?<!--00084終了-->\s*','',text,flags=re.DOTALL)
    text = text.replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
    text = re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00084：異なる3手法への固定配分を全30セッションで検証。源別損益と全体時価の両方で安定性を評価します。</p>',text,count=1,flags=re.DOTALL)
    article = f'''\n<!--00084開始--><article class="task latest"><div class="number">作業00084 <span class="badge">最新</span></div><h2>異なる戦略への配分と同時運転</h2><p>追従・中期逆張り・短期反転への22配分。手数料と合計保有上限を守り、親別損益・全時価・全セッション収支を比較。</p><a class="button" href="{FOLDER}/{NAME}">配分と全セッション損益</a> <a href="{FOLDER}/README.md">読む順序</a></article><!--00084終了-->\n'''
    assert '</header>' in text
    index.write_text(text.replace('</header>','</header>'+article,1),encoding='utf-8')
    for name, digest in old_hashes.items():
        assert sha(ROOT/name)==digest
    proof = dict(全合格=True,旧00083保持=old_hashes,独立監査SHA256={str(p.relative_to(ROOT)):sha(p) for p in audits},
        公開SHA256={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='公開指紋.json'})
    (OUT/'公開指紋.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('00084の資料と入口を公開。旧00083を保持。利益80%への調査は継続中。',flush=True)


if __name__=='__main__':
    main()
