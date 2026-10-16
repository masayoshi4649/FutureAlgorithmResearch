"""公開前HTMLの全セルを元会計へ照合し、無活動及び不採用の表示を確認する。"""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
WAVE = HERE.parents[1]
PREVIEW = WAVE / 'report' / 'preview_final'


def digest(path: Path) -> str:
    """
    機能: 小さな表示資料及び結果JSONの指紋を求める。
    引数: path(Path)はsource、HTML又はJSON。
    返り値: strはSHA256。巨大台帳及び原本は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 公開会計又は元会計のJSONを読む。
    引数: path(Path)は資料。
    返り値: dictは内容。金融再生を行わない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


# ----------------------------------------

class Tables(HTMLParser):
    """
    機能: 表示sourceのtbody/tfootセルを、details ID別に独立抽出する。
    引数: HTMLParserへ渡すUTF-8 HTML文字列。
    返り値: Tablesはtables(dict)と全本文を保持する解析器。
    """

    def __init__(self) -> None:
        """
        機能: 表とセルの解析状態を初期化する。
        引数: なし。
        返り値: None。
        """
        super().__init__(convert_charrefs=True)
        self.details = None
        self.current_table = None
        self.section = None
        self.cells = None
        self.text = None
        self.tables = {}
        self.body = []
        self.links = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str]]) -> None:
        """
        機能: 表、行、セルの開始と手法IDを保存する。
        引数: tag(str)、attrs(list[tuple[str,str]])はHTML要素。
        返り値: None。
        """
        attributes = dict(attrs)
        if tag == 'details':
            self.details = attributes.get('id')
        elif tag == 'table':
            self.current_table = self.details or '比較表'
            assert self.current_table not in self.tables
            self.tables[self.current_table] = dict(tbody=[], tfoot=[])
        elif tag in ('tbody', 'tfoot'):
            self.section = tag
        elif tag == 'tr' and self.section is not None:
            self.cells = []
        elif tag in ('th', 'td') and self.cells is not None:
            self.text = []
        elif tag == 'a':
            self.links.append(attributes.get('href'))

    def handle_endtag(self, tag: str) -> None:
        """
        機能: セル文字列と完成行を対応表へ追加する。
        引数: tag(str)は終了要素。
        返り値: None。
        """
        if tag in ('th', 'td') and self.text is not None:
            self.cells.append(''.join(self.text).strip())
            self.text = None
        elif tag == 'tr' and self.cells is not None:
            self.tables[self.current_table][self.section].append(self.cells)
            self.cells = None
        elif tag in ('tbody', 'tfoot'):
            self.section = None
        elif tag == 'table':
            self.current_table = None
        elif tag == 'details':
            self.details = None

    def handle_data(self, value: str) -> None:
        """
        機能: span内を含むセル文字と本文を保存する。
        引数: value(str)はHTML文字列。
        返り値: None。
        """
        self.body.append(value)
        if self.text is not None:
            self.text.append(value)


# ----------------------------------------

def yen(value: float) -> str:
    """
    機能: 元会計の整数円を表示仕様へ変換する。
    引数: value(float)は円額。
    返り値: strは三桁区切りと符号を持つ独立期待表示。
    """
    assert abs(value - round(value)) < 1e-5
    return format(round(value), ',')


def cells(row: dict) -> list[str]:
    """
    機能: 一商品の利益/損失/収支と決済勝負枚数を期待セルにする。
    引数: row(dict)は元会計行又は集計。
    返り値: list[str]は四つの表示セル。
    """
    return [yen(row['profit']), yen(row['loss']), yen(row['net']),
            str(row['winning_lots']) + '/' + str(row['losing_lots'])]


def main() -> None:
    """
    機能: 全19表×32場と全体footer、比較19行及び公開会計のsourceを照合する。
    引数: なし。
    返り値: None。小review証跡を新規保存。台帳再hash、金融再生及び公開は行わない。
    """
    destination = HERE / '公開前全19手法のHTMLと全32会計の独立照合.json'
    assert not destination.exists()
    html_path = PREVIEW / '板の定着と進行失敗の説明と全セッション損益.html'
    accounting_path = PREVIEW / '公開会計.json'
    public = read(accounting_path)
    final_path = WAVE / '金融全32の結果.json'
    final = read(final_path)
    audit_path = WAVE / 'review' / 'finance_audit' / '全19条件と全32セッションの独立金融監査.json'
    prefix_path = WAVE / 'engine' / '実金融の先頭4親と接頭不変.json'
    assert public['financial_SHA256'] == digest(final_path)
    assert public['independent_SHA256'] == digest(audit_path)
    assert public['financial_prefix_SHA256'] == digest(prefix_path)
    assert read(audit_path)['全合格'] and read(prefix_path)['全合格']
    assert public['sessions'] == final['sessions'] and len(public['sessions']) == 32
    assert public['条件数'] == 19 and len(public['条件別']) == 19
    assert public['安定候補'] == public['金額利益80両商品'] == []
    html = html_path.read_text(encoding='utf-8')
    parser = Tables()
    parser.feed(html)
    assert set(parser.tables) == set(public['条件別']) | {'比較表'}
    assert len(parser.tables['比較表']['tbody']) == 19
    summary_rows = {row[0]: row for row in parser.tables['比較表']['tbody']}
    count = 0
    for ident, published in public['条件別'].items():
        item = final['results'][ident]
        path = ROOT / item['path']
        assert digest(path) == item['SHA256']
        original = read(path)
        assert published == original, ident
        table = parser.tables[ident]
        assert len(table['tbody']) == 32 and len(table['tfoot']) == 1
        rows = {(row['session'], row['symbol']): row for row in original['rows']}
        assert len(rows) == 64
        for index, session in enumerate(public['sessions']):
            expected = [session.replace('_Day', ' デイ').replace('_Night', ' ナイト')]
            for symbol in ('TOPIX', 'NK225'):
                expected += cells(rows[session, symbol])
            assert table['tbody'][index] == expected, (ident, session)
            count += 8
        expected_foot = ['32場合計']
        for symbol in ('TOPIX', 'NK225'):
            expected_foot += cells(original['periods']['全32'][symbol])
        assert table['tfoot'][0] == expected_foot, (ident, '全体合計')
        count += 8
        expected_summary = [ident]
        for symbol in ('TOPIX', 'NK225'):
            total, stable = original['periods']['全32'][symbol], original['stability']['全32'][symbol]
            ratio = '—' if total['profit_share'] is None else format(total['profit_share'] * 100, '.1f') + '%'
            expected_summary += [yen(total['net']), str(stable['losing_sessions']) + '/' + str(stable['active_sessions']), ratio]
            if stable['active_sessions'] == 0:
                assert ratio == '—' and total['profit'] == total['loss'] == 0
        assert summary_rows[ident] == expected_summary, (ident, '比較行')
        count += 6
    text = ''.join(parser.body)
    assert '採用候補はありません' in text and '無取引は勝ちに含めません' in text
    assert 'R2の両商品100%は各1取引だけなので候補から除外' in text
    r2 = public['条件別']['R2']
    for symbol in ('TOPIX', 'NK225'):
        assert r2['periods']['全32'][symbol]['campaigns'] == 1
        assert r2['stability']['全32'][symbol]['active_sessions'] == 1
        assert not r2['stability']['全32'][symbol]['activity_adequate']
    assert 'color-scheme:dark' in html and 'overflow:auto' in html
    assert '#R2' in parser.links and '公開会計.json' in parser.links and 'README.md' in parser.links
    result = dict(全合格=True,
        scope='公開前preview_finalの全表示セルと公開会計を元finance/resultsへ照合。金融監査及び実prefixの指紋接続を確認。画像及び公開後相対リンクは根担当。',
        手法詳細表数=19, 各tbody場数=32, 詳細場行数=608, 商品会計掲載数=1216,
        商品footer合計数=38, 比較表行数=19, 表示数値照合セル数=count,
        公開会計全19条件が元結果完全同一=True, 無活動割合未定義記号=True,
        安定候補なし表示=True, R2各1回の活動不足で除外=True,
        財務監査と実prefix指紋接続=True, ダークと横スクロール指定=True,
        SHA256={str(path.relative_to(ROOT)): digest(path) for path in (
            Path(__file__), html_path, accounting_path, final_path, audit_path, prefix_path,
            WAVE / 'report.py', WAVE / 'report' / '生成結果_最終.json')},
        巨大台帳再hash=0, 原本読取=0, 金融再生=0, API取得=0, 公開操作=0)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 詳細場行数=608, 商品footer合計数=38,
                         表示数値照合セル数=count, SHA256=digest(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
