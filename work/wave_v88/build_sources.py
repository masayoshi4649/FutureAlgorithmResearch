"""旧実装を改変せず、今回だけの観測約定と未来ラベルなし観測器を生成する。"""
from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def build():
    """
    機能: 変更箇所を限定した独立コピーと差分指紋を保存する。
    引数: なし。
    返り値: dict の生成仕様。旧ファイルへの書込みはない。
    """
    source=ROOT/'work/wave_v19/engine.py'
    text=source.read_text(encoding='utf-8')
    replacements=[
        ('us_open, par, detail, cap):','us_open, par, detail, cap, observed_fill):'),
        ('level=p if market_flags[z] else v','level=p if observed_fill or market_flags[z] else v'),
        ('anchor=pending_level;extreme=anchor','anchor=p if observed_fill else pending_level;extreme=anchor'),
        ('config: dict, detail: bool=False)', 'config: dict, detail: bool=False, observed_fill: bool=False)'),
        ("par,detail,config['audit_cap'])", "par,detail,config['audit_cap'],observed_fill)"),
        ('指定価格約定。主玉・カバー合計', 'observed_fill(bool)が真なら成立した観測価格、偽なら旧指定価格。主玉・カバー合計'),
    ]
    for before,after in replacements:
        assert text.count(before)==1,before
        text=text.replace(before,after)
    (HERE/'m3_engine.py').write_text(text,encoding='utf-8')
    # ----------------------------------------
    original=ROOT/'work/wave_v52/theory/analyze.py'
    raw=original.read_text(encoding='utf-8')
    start=raw.index('def build_account(')
    end=raw.index('        lab = dict(time_s=float(origin))',start)
    function=raw[start:end]
    function=function.replace(' -> tuple[pd.DataFrame, pd.DataFrame, dict]:',' -> tuple[pd.DataFrame, dict]:',1)
    function=function.replace('公開済み観測と将来ラベルを別々に作る。','旧観測品質を維持し、現在までの観測だけを作る。',1)
    function=function.replace('特徴・ラベル・品質集計(tuple)。','特徴・品質集計(tuple)。将来価格の読取を含まない。',1)
    function=function.replace('rows, labels = [], []','rows = []',1)
    function=function.replace("現在品質不良=0, 採用起点=0,\n                   未来ラベル不足={str(h): 0 for h in HORIZONS})",'現在品質不良=0, 採用起点=0)',1)
    function += '    return pd.DataFrame(rows), quality\n'
    helper=raw[raw.index('def imbalance('):start]
    (HERE/'c03_observe.py').write_text('"""旧52の観測採否を保持し、未来ラベル生成部分だけ除外した今回のコピー。"""\nimport numpy as np\nimport pandas as pd\n\n'+helper+function,encoding='utf-8')
    proof=dict(M3変更=replacements,M3元SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
        C03元SHA256=hashlib.sha256(original.read_bytes()).hexdigest(),
        C03変更='旧build_accountのrows.append(row)までを同一保持。未来ラベル作成の分岐と未来不足件数のみ除去。旧観測との全列一致を別検査。')
    (HERE/'生成仕様.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return proof


if __name__=='__main__':
    build()
