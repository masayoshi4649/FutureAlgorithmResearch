"""保存済みの順位・理由を別HTMLへまとめる。売買再計算や通信は行わない。"""
import argparse
import json
from pathlib import Path
import re
import shutil

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]
FOLDER = '00012_状態切替と柔軟な建玉管理'
OUT = ROOT / 'アルゴリズム調査' / FOLDER
PAGE = '週収支ランキングと両銘柄共通手法.html'


def read(path):
    """JSONファイルを読む。

    引数: path (Path) はファイル。返り値: 内容 (dict | list)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def normalize(data, reasons):
    """順位の元データを表示用の同一形式へ変換する。

    引数: data/reasons (dict) は順位と理由。返り値: 表示データ (dict)。
    """
    methods = {}
    for mid, original in data['methods'].items():
        explanation = reasons['reasons'][mid]
        methods[mid] = dict(id=mid, name=original['name'], description=original['description'],
                            rows={s: original['stocks'][s]['week'] for s in ['NK225', 'TOPIX']},
                            diagnostics={s: dict(without_best=original['stocks'][s]['best_session_removed_net'], atr_pf=original['stocks'][s]['atr']['atr_pf']) for s in ['NK225', 'TOPIX']},
                            reason_title=explanation['reason_title'], reason=explanation['reason'])
    single = {s: [dict(methods[r['id']]) for r in data['individual'][s]] for s in ['NK225', 'TOPIX']}
    common = [dict(methods[r['id']], score=r['score'], stable=r['stable']) for r in data['common']]
    ids = list(dict.fromkeys([r['id'] for s in ['NK225', 'TOPIX'] for r in single[s]] + [r['id'] for r in common]))
    assert len(common) == 5 and all(len(single[s]) == 5 for s in single)
    assert [r['id'] for r in common] == ['M3_逆_A03', 'M3_逆_A00', 'M2_逆_A00', 'M2_逆_A01', 'M1_逆_A03']
    assert common[4]['stable'] is False
    return dict(single=single, common=common, comparisons=[methods[mid] for mid in ids], examples=reasons['examples'], notes=reasons['notes'])


def guide():
    """00012のREADMEへ追加ランキングの入口と再現手順を記載する。

    引数: なし。返り値: なし。従来HTMLと生成コードは変更しない。
    """
    path = OUT / 'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\n<!--ランキング案内開始-->.*?<!--ランキング案内終了-->\n', '\n', text, flags=re.S)
    note = f'''\n<!--ランキング案内開始-->
最初に [{PAGE}]({PAGE}) を開いてください。読む順序は次のとおりです。

1. 新ランキングHTML：NK225／TOPIXの週収支上位５件、両銘柄共通の損小利大上位５件。「比較の理由」で相手銘柄との差を確認。
2. [全180条件・セッション別成績](状態切替と柔軟な建玉管理.html)：銘柄・手法ごとの10セッション。元の初期２候補一覧は [検証結果.md](検証結果.md)。
3. [資料/ランキング](資料/ランキング/)：順位の元集計・診断・監査。[資料](資料/) には元の売買再現資料も保存。

順位の元集計・診断・独立監査は [資料/ランキング](資料/ランキング/) です。再現はプロジェクトルートで次の順序です。

1. `python work/wave_v17/rankings/ranking_analysis.py` で保存済み集計から順位を生成。
2. `python work/wave_v17/rankings/report_rankings.py --publish` で別HTMLと案内を生成。
3. `node work/wave_v17/rankings/check_rankings.js` で順位・表示の金額と枚数を照合。

既存の主HTML・売買結果は変更しません。元ページを `report.py --publish` で再生成した場合は、README・索引の追加リンクを戻すため、その後に `report_rankings.py --publish` を実行してください。
<!--ランキング案内終了-->
'''
    rest = text[text.index('３信号 ×'):].replace('## 再現', '## 元の主ページの再現', 1)
    path.write_text('# 00012 状態切替と柔軟な建玉管理\n'+note+'\n'+rest, encoding='utf-8')


def indexes():
    """全体一覧の最新作業に追加HTMLのリンクを置く。

    引数: なし。返り値: なし。
    """
    base = OUT.parent
    path = base / 'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\n<!--ランキングリンク開始-->.*?<!--ランキングリンク終了-->\n', '\n', text, flags=re.S)
    link = f'\n<!--ランキングリンク開始-->\n追加：[週収支ランキングと両銘柄共通手法]({FOLDER}/{PAGE}) — 銘柄別上位５件と共通の損小利大上位５件。\n<!--ランキングリンク終了-->\n'
    index = text.index('\n\n| 作業フォルダ')
    path.write_text(text[:index]+link+text[index:], encoding='utf-8')
    path = base / 'index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--ランキングリンク開始-->.*?<!--ランキングリンク終了-->', '', text, flags=re.S)
    link = f'<!--ランキングリンク開始--><p><a href="{FOLDER}/{PAGE}">週収支ランキングと両銘柄共通手法 →</a></p><!--ランキングリンク終了-->'
    start = text.index('<!--00012開始-->')
    end = text.index('<!--00012終了-->', start)
    block = text[start:end].replace('</article>', link+'</article>')
    path.write_text(text[:start]+block+text[end:], encoding='utf-8')


def main():
    """元順位と短い説明からHTMLを生成し、必要時だけ案内を更新する。

    引数: --publish (bool) は一覧更新、--reasons (str) は理由JSON。
    返り値: なし。
    """
    parser = argparse.ArgumentParser(description='保存済みランキングの表示だけを生成')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--reasons', default='銘柄差の短文.json')
    args = parser.parse_args()
    data, reasons = read(WORK/'ranking_data.json'), read(WORK/args.reasons)
    payload = normalize(data, reasons)
    serialized = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    source = (WORK/'ranking_template.html').read_text(encoding='utf-8').replace('__PAYLOAD__', serialized)
    (OUT/PAGE).write_text(source, encoding='utf-8')
    target = OUT/'資料/ランキング'
    target.mkdir(parents=True, exist_ok=True)
    for file in WORK.iterdir():
        if file.is_file() and file.suffix in ['.py', '.html', '.js', '.md', '.json']:
            shutil.copy2(file, target/file.name)
    if args.publish:
        guide()
        indexes()
    print(json.dumps({'HTML': str(OUT/PAGE), '銘柄別件数': {s: len(payload['single'][s]) for s in payload['single']}, '共通件数': len(payload['common']), '比較ID数': len(payload['comparisons'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
