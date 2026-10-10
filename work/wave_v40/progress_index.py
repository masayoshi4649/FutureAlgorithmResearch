"""新しい研究計画への入口を、前回の確定結果と区別して追加する。"""

from pathlib import Path
import re


def main() -> None:
    """機能: 00035準備中の案内と00034確定結果を共通一覧へ保存する。

    引数: なし。返り値: なし (None)。過去作業の内容は変更しない。
    """
    root=Path(__file__).resolve().parents[2]/'アルゴリズム調査'
    folder='00035_同じ価格帯の防御変化と突破'
    assert (root/folder/'比較計画.html').exists()
    text=(root/'index.html').read_text(encoding='utf-8')
    text=re.sub(r'<!--00035開始-->.*?<!--00035終了-->','',text,flags=re.S)
    text=text.replace('task latest','task')
    text=re.sub(r' <span class="badge">最新[^<]*</span>','',text)
    text=re.sub(r'<p class="lead">.*?</p>', '<p class="lead">00035：同じ価格帯の防御変化を準備・検証中。直近の確定結果は00034です。</p>',text,count=1)
    block=f'''<!--00035開始--><article class="task latest"><div class="number">作業00035 <span class="badge">最新・検証中</span></div><h2>同じ価格帯の防御変化と突破</h2><p>固定価格への二試行で板数量の回復が弱まるか。価格だけ・最後の板・順序なし・逆・乱数を比較します。</p><a class="button" href="{folder}/比較計画.html">比較計画 →</a><p><a href="{folder}/README.md">資料案内</a> ／ <a href="00034_予想外の板圧力と独立価格対照/予想外の板圧力と独立価格対照.html">直近の確定結果</a></p></article><!--00035終了-->'''
    (root/'index.html').write_text(text.replace('</header>','</header>'+block,1),encoding='utf-8')
    text=(root/'README.md').read_text(encoding='utf-8')
    text=re.sub(r'\*\*最新は.*?\*\*',f'**最新は00035の[同じ価格帯の防御変化]({folder}/比較計画.html)（準備・検証中）。直近の確定結果は[00034](00034_予想外の板圧力と独立価格対照/予想外の板圧力と独立価格対照.html)です。**',text,count=1)
    text=re.sub(r'^\| `00035_.*\n','',text,flags=re.M).replace('`（最新）','`')
    row=f'\n| `{folder}`（最新） | 固定価格帯の二試行と板履歴、281条件を準備・検証中 | [比較計画]({folder}/比較計画.html) | [資料案内]({folder}/README.md) |'
    (root/'README.md').write_text(text.replace('| --- | --- | --- | --- |','| --- | --- | --- | --- |'+row,1),encoding='utf-8')


if __name__=='__main__':main()
