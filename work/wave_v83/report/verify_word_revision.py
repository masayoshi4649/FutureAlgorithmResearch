"""全数値検査後の監視順序の文言だけの変更を確認し、最終HTML指紋を追記する。"""
import copy
import hashlib
import json
from pathlib import Path
from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
OUT = HERE.parents[2] / 'アルゴリズム調査/00079_方向予測を使わない注文手法の検証'


def normalized_structure(soup):
    """
    機能: 隔離検査が付けた要素とスクリプト内容を除き、DOM構造を列挙する。
    引数: soup (BeautifulSoup)。
    返り値: list[tuple] のタグ名・属性の順序付き一覧。
    """
    replica = BeautifulSoup(str(soup), 'html.parser')
    for tag in replica.select('base, script, meta[http-equiv="Content-Security-Policy"]'):
        tag.decompose()
    return [(tag.name, dict(tag.attrs)) for tag in replica.find_all()]


def check_revision(path, previous):
    """
    機能: 旧描画資料に対しデータ全体・JS・CSS・構造が保全されたことを調べる。
    引数: path (Path) は最終公開HTML、previous (Path) は検査済み旧複製HTML。
    返り値: dict の変更箇所と照合結果。
    """
    current = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
    old = BeautifulSoup(previous.read_text(encoding='utf-8'), 'html.parser')
    first = json.loads(old.select_one('#report-data').string)
    second = json.loads(current.select_one('#report-data').string)
    preserved = copy.deepcopy(second)
    preserved['persistent_description'] = first['persistent_description']
    preserved['text']['execution-assumptions'] = first['text']['execution-assumptions']
    assert preserved == first, '許容した2文以外の埋込み資料変更'
    js = [s.string for s in current.select('script:not([type="application/json"])')]
    old_js = [s.string for s in old.select('script:not([type="application/json"])')]
    assert len(js) == 2 and js == old_js[1:3], 'JavaScript変更'
    assert [s.string for s in current.select('style')] == [s.string for s in old.select('style')], 'CSS変更'
    assert normalized_structure(current) == normalized_structure(old), 'DOM構造変更'
    old_p = [p.get_text() for p in old.select('p')]
    new_p = [p.get_text() for p in current.select('p')]
    assert len(old_p) == len(new_p)
    changes = [(a, b) for a, b in zip(old_p, new_p) if a != b]
    assert len(changes) == 1 and '行末の即時新規約定' in changes[0][1]
    assert 'その観測で子条件を1回監視' in second['text']['execution-assumptions']
    assert 'その観測の現在値で返済条件を1回監視' in second['persistent_description']
    return dict(HTML=path.name, 数値とその他資料不変=True, JavaScript不変=True, CSS不変=True,
                DOM構造不変=True, 静的段落変更数=1,
                変更='行末の即時新規の子監視は次観測、待機新規が後続行頭で約定した子監視は同観測で1回と明確化。',
                HTML_SHA256=hashlib.sha256(path.read_bytes()).hexdigest())


# ----------------------------------------
def main():
    """
    機能: 文言修正だけであることを確かめ、既存の全数値検査証拠へ追記する。
    引数: なし。
    返り値: None。公開ファイルと売買結果は変更しない。
    """
    proof_path = HERE / 'HTML表示の独立検査.json'
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    records = [check_revision(OUT / name, HERE / 'visual' / source) for name, source in [
        ('予測を使わない注文手法と全セッション損益.html', '主全体広幅.html'),
        ('家族別12手法の説明と全セッション損益.html', '家族別広幅.html')]]
    all_name = '全288条件の前半比較.html'
    all_hash = hashlib.sha256((OUT / all_name).read_bytes()).hexdigest()
    assert all_hash == proof['HTML_SHA256'][all_name]
    proof['全操作検査時_HTML_SHA256'] = proof['HTML_SHA256'].copy()
    proof['HTML_SHA256'] = {**{r['HTML']: r['HTML_SHA256'] for r in records}, all_name: all_hash}
    proof['文言修正後の簡易確認'] = dict(全合格=True, 内容=records, 全288不変=True,
        検査方針='既存350ファイルと全操作の再試験は繰り返さず、文以外の全データ・JS・CSS・DOM構造の同一性を確認。',
        画像='9画像は全操作検査時の版。最終版の文言3箇所は差分確認のみで、再描画したとは扱わない。')
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof['文言修正後の簡易確認'], ensure_ascii=False))


if __name__ == '__main__':
    main()
