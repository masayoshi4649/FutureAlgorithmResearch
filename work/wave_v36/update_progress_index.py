"""結果の確定段階を隠さず、新作業と直近比較への入口を表示する。"""

from pathlib import Path
import re
import json

ROOT = Path(__file__).resolve().parents[2]
FOLDER = '00031_出来高通過と気配維持からの方向判定'
PREVIOUS = '00030_板と両市場による条件付き追跡短縮'


def main() -> None:
    """機能: 既存リンクを保ち、00031の設計段階と00030の検算状態を示す。

    引数: なし。返り値: なし (None)。成績の確定や成功を宣言しない。
    """
    folder = ROOT / 'アルゴリズム調査'
    previous_proof = ROOT / 'work/wave_v35/完備監査.json'
    previous_complete = previous_proof.exists() and json.loads(previous_proof.read_text(encoding='utf-8'))['検証完了']
    status = '確定報告' if previous_complete else '独立検算中の暫定報告'
    started = (ROOT / 'work/wave_v36/起動実行の証跡.json').exists()
    finished = (ROOT / 'work/wave_v36/supplementary/主再生の完了.json').exists()
    proof_path = ROOT / 'work/wave_v36/完備監査.json'
    verified = proof_path.exists() and json.loads(proof_path.read_text(encoding='utf-8'))['検証完了']
    stage = '確定報告' if verified else '独立検算中' if finished else '売買再生中' if started else '準備中'
    target = '出来高通過と気配維持からの方向判定.html' if verified else 'README.md'
    message = '全364条件と補助65の比較・独立検算を確定しました。' if verified else '全364条件と補助65の再生を終え、独立検算を進めています。' if finished else (
        '結果前に条件と検査を固定し、364条件と補助65を再生しています。' if started else '新手法の損益はまだ未計算です。')
    path = folder / 'index.html'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'<!--00031開始-->.*?<!--00031終了-->', '', source, flags=re.S)
    source = source.replace('task latest', 'task').replace(' <span class="badge">最新</span>', '')
    source = re.sub(r'<p class="lead">.*?</p>', f'<p class="lead">最新作業は00031：出来高通過と気配維持。{message}</p>', source, count=1)
    block = f'''<!--00031開始--><article class="task latest"><div class="number">作業00031 <span class="badge">最新・{stage}</span></div><h2>出来高通過と気配維持からの方向判定</h2><p>{message} 方向判定90種類と価格だけ・全出来高・旧方式を比較。</p><a class="button" href="{FOLDER}/{target}">比較と資料案内 →</a><p><a href="{FOLDER}/全条件損益.html">全条件損益</a> ／ <a href="{FOLDER}/５分足と売買.html">売買図</a></p><p>直前の比較：<a href="{PREVIOUS}/板と両市場による条件付き追跡短縮.html">00030・条件付き追跡短縮（{status}）</a></p></article><!--00031終了-->'''
    source = source.replace('</header>', '</header>' + block, 1)
    path.write_text(source, encoding='utf-8')
    path = folder / 'README.md'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00031の[出来高と気配維持]({FOLDER}/{target})（{stage}）。**', source, count=1)
    source = re.sub(r'^\| `00031_.*\n', '', source, flags=re.M).replace('`（最新）', '`')
    anchor = '| --- | --- | --- | --- |'
    row = f'\n| `{FOLDER}`（最新） | 気配維持と出来高の追加価値・{stage} | [比較・資料]({FOLDER}/{target}) | [損益]({FOLDER}/全条件損益.html)・[資料案内]({FOLDER}/README.md) |'
    source = source.replace(anchor, anchor + row, 1)
    path.write_text(source, encoding='utf-8')
    print('00031の進捗と00030の検算状態を一覧へ反映。')


if __name__ == '__main__':
    main()
