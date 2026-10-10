"""次の反証計画と、直近の確定損益を一覧で区別する。"""

from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
FOLDER='00033_復元方式の自動選択と改善8条件の反証'
PREVIOUS='00032_悪化時の部分減量と回復後の数量復元'


def main() -> None:
    """機能: 過去リンクを保ちながら今回の段階を明示する。

    引数: なし。返り値: なし (None)。未実施の損益を掲載しない。
    """
    path=ROOT/'アルゴリズム調査/index.html'
    source=path.read_text(encoding='utf-8')
    source=re.sub(r'<!--00033開始-->.*?<!--00033終了-->','',source,flags=re.S)
    source=source.replace('task latest','task')
    source=re.sub(r' <span class="badge">最新[^<]*</span>','',source)
    source=re.sub(r'<p class="lead">.*?</p>',
        '<p class="lead">00033は974条件の反証を実行中。直近の確定結果は00032（427条件の検算完了）です。</p>',source,count=1)
    block=f'''<!--00033開始--><article class="task latest"><div class="number">作業00033 <span class="badge">最新・再生・独立検算中</span></div><h2>復元方式の自動選択と改善8条件の反証</h2><p>長い逆行の有無で回復待ち／時計復元を選ぶ一つの機械規則と、旧改善8条件を検証します。主206条件の実データ再生を開始しました。補助768条件と独立検算を続けます。</p><a class="button" href="{FOLDER}/比較計画.html">974条件の比較計画 →</a><a class="button" href="{PREVIOUS}/悪化時の部分減量と回復後の数量復元.html">直近の確定結果 →</a><a class="button" href="{PREVIOUS}/全条件損益.html">確定済み週・セッション損益 →</a><p><a href="{FOLDER}/README.md">資料案内</a></p></article><!--00033終了-->'''
    path.write_text(source.replace('</header>','</header>'+block,1),encoding='utf-8')
    path=ROOT/'アルゴリズム調査/README.md';source=path.read_text(encoding='utf-8')
    source=re.sub(r'\*\*最新は.*?\*\*',f'**最新は00033の[974条件の反証計画]({FOLDER}/比較計画.html)（再生・独立検算中）。直近の確定結果は[00032の比較]({PREVIOUS}/悪化時の部分減量と回復後の数量復元.html)。**',source,count=1)
    source=re.sub(r'^\| `00033_.*\n','',source,flags=re.M).replace('`（最新）','`')
    anchor='| --- | --- | --- | --- |'
    row=f'\n| `{FOLDER}`（最新） | 復元方式の自動選択・改善8条件の反証、再生・独立検算中 | [比較計画]({FOLDER}/比較計画.html) | [資料案内]({FOLDER}/README.md)・[確定済み比較]({PREVIOUS}/悪化時の部分減量と回復後の数量復元.html) |'
    path.write_text(source.replace(anchor,anchor+row,1),encoding='utf-8')
    print('00033の進行状況と00032の確定結果を一覧へ反映。')


if __name__=='__main__':main()
