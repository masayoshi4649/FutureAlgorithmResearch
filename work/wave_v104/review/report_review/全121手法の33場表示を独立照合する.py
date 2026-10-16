"""全121手法の公開表示を検算済み小会計から独立再合計する。"""

from collections import Counter
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WAVE = HERE.parents[1]
ROOT = WAVE.parents[1]
COUNTS = Counter()


class Node:
    """
    機能: 数値セルと説明文をタグの位置を保って保存する小さいHTML構造。
    引数: tag(str)、attrs(dict)はタグ名と属性。
    返り値: Nodeは子要素及び本文を持つ構造。
    """
    def __init__(self, tag: str, attrs: dict) -> None:
        """
        機能: タグの内容を文字列とは別に保持する。
        引数: tag(str)、attrs(dict)はタグ名と属性。
        返り値: None。
        """
        self.tag, self.attrs, self.children = tag, attrs, []

    def text(self) -> str:
        """
        機能: タグの表示文字を子要素から再帰的に抽出する。
        引数: なし。
        返り値: strは空白を整えた表示文字。scriptやstyleは抽出しない。
        """
        if self.tag in ('script', 'style'):
            return ''
        if self.tag == 'br':
            return ' '
        return ''.join(value.text() if isinstance(value, Node) else value for value in self.children).strip()

    def find(self, tag: str) -> list:
        """
        機能: 子孫の指定タグを文書順で抽出する。
        引数: tag(str)はタグ名。
        返り値: list[Node]は該当する全要素。
        """
        values = []
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    values.append(child)
                values.extend(child.find(tag))
        return values


class Parser(HTMLParser):
    """
    機能: 外部描画や通信なしで公開HTMLの表・説明を構造化する。
    引数: なし。
    返り値: Parserは文書のNode根と解析器。
    """
    def __init__(self) -> None:
        """
        機能: 公開HTMLの解析を初期化する。
        引数: なし。
        返り値: None。
        """
        super().__init__(convert_charrefs=True)
        self.root = Node('document', {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """
        機能: 開始タグとその属性を文書へ追加する。
        引数: tag(str)、attrs(list[tuple])は解析入力。
        返り値: None。空要素はスタックへ積まない。
        """
        value = Node(tag, dict(attrs))
        self.stack[-1].children.append(value)
        if tag not in ('meta', 'br', 'link', 'input', 'img', 'hr', 'source', 'wbr'):
            self.stack.append(value)
        elif tag == 'br':
            value.children.append(' ')

    def handle_endtag(self, tag: str) -> None:
        """
        機能: 対応する開始タグへ解析位置を戻す。
        引数: tag(str)は閉じタグ。
        返り値: None。省略タグを数値データとして解釈しない。
        """
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                return

    def handle_data(self, data: str) -> None:
        """
        機能: 表示文字を現在の要素へ保存する。
        引数: data(str)は本文。
        返り値: None。
        """
        self.stack[-1].children.append(data)


def read(path: Path) -> dict:
    """
    機能: 小さい公開及び既検算の会計JSONだけを読む。
    引数: path(Path)はJSON。
    返り値: dictは保存値。台帳、raw、NPZ及び金融再生は行わない。
    """
    assert path.suffix == '.json'
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 公開物及び小さい証跡のSHA256を求める。
    引数: path(Path)は小ファイル。
    返り値: strは内容指紋。巨大台帳や原本を再hashしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def yen(value: float) -> str:
    """
    機能: 元数値からHTMLの整数円表示を独立に求める。
    引数: value(float)は円額。
    返り値: strは三桁区切りの表示。微小誤差は0表示。
    """
    return '0' if abs(value) < .5 else format(round(value), ',')


def ratio(value: float | None) -> str:
    """
    機能: 金額割合の表示を独立に求める。
    引数: value(float|None)は割合。
    返り値: strは百分率又は未定義。無取引を利益に変換しない。
    """
    return '—' if value is None else format(value*100, '.1f')+'%'


def cells(row: Node) -> list:
    """
    機能: 一行の直属見出し/データセルを順序通り取得する。
    引数: row(Node)はtr。
    返り値: list[Node]はセル。入れ子の表を重複抽出しない。
    """
    return [value for value in row.children if isinstance(value, Node) and value.tag in ('th', 'td')]


def check_cells(actual: list, expected: list, label: object) -> None:
    """
    機能: 日本語セッション名、全金額、勝負零枚数の表示を元会計と比較する。
    引数: actual(list[Node])、expected(list[str])、label(object)は比較位置。
    返り値: None。不一致を拒否し、検査セル数を数える。
    """
    assert [value.text() for value in actual] == expected, label
    COUNTS['表示セル'] += len(expected)


def row_cells(label: str, rows: dict) -> list:
    """
    機能: TOPIX/NKの相殺前金額と決済枚数を独立に表の列へ並べる。
    引数: label(str)、rows(dict[symbol,dict])は行名と両商品会計。
    返り値: list[str]は全9表示セル。
    """
    result = [label]
    for symbol in ('TOPIX', 'NK225'):
        row = rows[symbol]
        result.extend([yen(row[key]) for key in ('profit', 'loss', 'net')])
        result.append('/'.join(str(row[key]) for key in ('winning_lots', 'losing_lots', 'flat_lots')))
    return result


def summed(rows: list) -> dict:
    """
    機能: 商品内の利益、損失、収支と勝負零枚数を独立再合計する。
    引数: rows(list[dict])は同じ商品の全場会計。
    返り値: dictは6項目。両商品間の倍率差を相殺しない。
    """
    return {name: sum(value[name] for value in rows) for name in
        ('profit', 'loss', 'net', 'winning_lots', 'losing_lots', 'flat_lots')}


def explanation(node: Node, config: dict, value: dict) -> None:
    """
    機能: 説明の枚数、入口仮説、相手確認及び出口幅を固定configと照合する。
    引数: node(Node)、config/value(dict)は手法detailsと既検算会計。
    返り値: None。説明に架空の活動や違う配分がないことを確認する。
    """
    paragraphs = [child for child in node.children if isinstance(child, Node) and child.tag == 'p']
    assert len(paragraphs) == 3
    text = paragraphs[0].text()
    if config['kind'] == 'portfolio':
        for symbol, label, cap in (('TOPIX', 'TOPIX', 10), ('NK225', '日経', 20)):
            first, second = config['allocations'][symbol]
            assert first+second == cap
            assert f'{label}は{first}対{second}枚' in text
        assert '追従Cと反転Rを別々に動かす' in text
    else:
        assert '1枚' in text and all(quantity == 1 for quantity in config['quantity'].values())
        if config['kind'] == 'previous':
            assert '旧対照' in text
        elif config['family'] == 'U':
            assert '自動選択' in text and '方向が競合したら見送る' in text
        elif config['family'] == 'C':
            assert '新しい価格が定着した方向' in text
        else:
            assert '進めず、反対の価格が定着' in text
    if config['kind'] != 'previous':
        gate, exit_id = config['gate'], config['exit_id']
        if gate == 'OWN':
            assert '自己市場だけ' in text
        else:
            window = int(gate[1:].replace('T2', ''))
            assert f'約{window}秒' in text
            assert ('同方向を確認' if gate.startswith('P') else '反対・不明・曖昧を除外') in text
            if gate.endswith('T2'):
                assert '2呼値以上' in text
        if exit_id == 'O':
            assert '広い追尾と最大30分' in text
        else:
            width = int(exit_id[1:])
            assert f'支持価格の{width}呼値外' in text
            if exit_id.startswith('T'):
                assert f'費用回収後は{width}呼値で利益追尾' in text
            else:
                assert '利益は広く追尾' in text
    expected_stats = []
    for symbol, label in (('TOPIX', 'TOPIXミニ'), ('NK225', '日経マイクロ')):
        rows = [row for row in value['rows'] if row['symbol'] == symbol]
        positive = sum(row['net'] > 1e-5 and row['campaigns'] > 0 for row in rows)
        negative = sum(row['net'] < -1e-5 and row['campaigns'] > 0 for row in rows)
        no_trade = sum(row['campaigns'] == 0 for row in rows)
        total = value['periods']['全32'][symbol]
        payoff = '—' if total['payoff'] is None else format(total['payoff'], '.2f')
        expected_stats.append(f'{label}：黒字{positive}・赤字{negative}・無取引{no_trade}場。平均利益/平均損失 {payoff}倍。')
    assert paragraphs[1].text() == ' '.join(expected_stats)
    assert len(paragraphs[2].text()) < 100, '内部理由の列挙を復活させない'
    COUNTS['手法数量と説明'] += 1


def main() -> None:
    """
    機能: 全121×33×2表示、32/33再合計、比較表と会計指紋を独立照合する。
    引数: なし。
    返り値: None。根指定の公開前証跡だけを保存する。金融再読再生はない。
    """
    target = WAVE/'report/独立HTML全場照合.json'
    assert not target.exists()
    preview = WAVE/'report/preview'
    html_path, public_path = preview/'支持境界と利益追尾の説明と全セッション損益.html', preview/'公開会計.json'
    html = html_path.read_text(encoding='utf-8')
    public = read(public_path)
    final = read(WAVE/'金融全32の結果.json')
    full_audit_path = WAVE/'review/finance_audit/全121条件と全32セッションの独立金融監査.json'
    extra_audit_path = WAVE/'review/finance_audit/追加Day全121と旧入口及び全266台帳の独立金融監査.json'
    full_audit, extra_audit = read(full_audit_path), read(extra_audit_path)
    assert full_audit['全合格'] and extra_audit['全合格']
    assert public['audit_SHA256'] == sha(full_audit_path) and public['extra_audit_SHA256'] == sha(extra_audit_path)
    assert public['formal_result_SHA256'] == sha(WAVE/'金融全32の結果.json')
    assert full_audit['SHA256'][str((WAVE/'金融全32の結果.json').relative_to(ROOT))] == public['formal_result_SHA256']
    assert public['assessment'] == read(WAVE/'安定性の全121判定.json')
    assert public['sessions'] == final['sessions'] and len(public['sessions']) == 32
    assert public['assessment']['adoption_candidates'] == [] and public['assessment']['ranking'] == ['C_N30_B4']
    assert public['extra'] == read(WAVE/'holdout_finance/追加Day全121の損益.json')
    extra = public['extra']
    assert extra_audit['SHA256'][str((WAVE/'holdout_finance/追加Day全121の損益.json').relative_to(ROOT))] == sha(WAVE/'holdout_finance/追加Day全121の損益.json')
    assert set(public['values']) == set(extra['cases']) == set(final['results']) and len(public['values']) == 121
    parser = Parser()
    parser.feed(html)
    root = parser.root
    details = {node.attrs['id']: node for node in root.find('details') if 'id' in node.attrs}
    assert set(details) == set(public['values']) and len(details) == 121
    for ident, value in public['values'].items():
        file_item = final['results'][ident]
        assert sha(ROOT/file_item['path']) == file_item['SHA256']
        assert value == read(ROOT/file_item['path'])
        node = details[ident]
        assert node.find('summary')[0].text() == ident
        explanation(node, value['config'], value)
        tables = [table for table in node.find('table') if table.attrs.get('class') == 'sessions']
        assert len(tables) == 1
        table = tables[0]
        header = table.find('thead')[0].text()
        assert 'TOPIXミニ' in header and '日経マイクロ' in header and '決済枚数 勝/負/零' in header
        old_rows, added_rows = value['rows'], extra['cases'][ident]['rows']
        assert len(old_rows) == 64 and len(added_rows) == 2
        assert extra['cases'][ident]['config'] == value['config']
        for row in added_rows:
            independent = extra_audit['全121独立追加場会計'][ident][row['symbol']]
            for key in ('profit', 'loss', 'net', 'winning_lots', 'losing_lots', 'flat_lots'):
                assert row[key] == independent[key]
        mapping = {(row['session'], row['symbol']): row for row in old_rows+added_rows}
        sessions = public['sessions']+[extra['session']]
        assert len(mapping) == 66 and len(set(sessions)) == 33
        body = table.find('tbody')[0].find('tr')
        assert len(body) == 33
        for row, session in zip(body, sessions, strict=True):
            label = session.replace('_Day', ' デイ').replace('_Night', ' ナイト')
            if session == extra['session']:
                label += '〔別確認〕'
                assert row.attrs.get('class') == 'extra'
            check_cells(cells(row), row_cells(label, {symbol: mapping[session, symbol] for symbol in ('TOPIX', 'NK225')}), (ident, session))
            for i, symbol in enumerate(('TOPIX', 'NK225')):
                net = mapping[session, symbol]['net']
                expected = 'positive' if net > 1e-5 else 'negative' if net < -1e-5 else 'neutral'
                assert cells(row)[3+4*i].find('span')[0].attrs['class'] == expected
            COUNTS['セッション商品行'] += 2
        footer = table.find('tfoot')[0].find('tr')
        assert len(footer) == 2
        for scope, rows, label, index in ((32, old_rows, '既知32場合計', 0), (33, old_rows+added_rows, '追加を含む合計', 1)):
            totals = {symbol: summed([row for row in rows if row['symbol'] == symbol]) for symbol in ('TOPIX', 'NK225')}
            if scope == 32:
                for symbol, total in totals.items():
                    for key, number in total.items():
                        assert abs(value['periods']['全32'][symbol][key]-number) < 1e-4
            check_cells(cells(footer[index]), row_cells(label, totals), (ident, label))
            COUNTS[f'{scope}場合計商品行'] += 2
    comparison = [node for node in root.find('table') if node.attrs.get('class') == 'comparison']
    assert len(comparison) == 1
    compare_rows = comparison[0].find('tbody')[0].find('tr')
    expected_ids = list(dict.fromkeys([*public['assessment']['ranking'][:5], 'U_P10_T2', 'P50_P10_B2', 'P50_P10_T2', 'OLD_G0']))
    assert [cells(row)[0].text() for row in compare_rows] == expected_ids
    for row in compare_rows:
        ident = cells(row)[0].text()
        expected = [ident]
        for symbol in ('TOPIX', 'NK225'):
            rows = [row for row in public['values'][ident]['rows'] if row['symbol'] == symbol]
            total = summed(rows)
            active = [row for row in rows if row['campaigns'] > 0]
            losing = sum(row['net'] < -1e-5 for row in active)
            share = total['profit']/(total['profit']+total['loss']) if total['profit']+total['loss'] else None
            worst = max((max(0., -row['net']) for row in rows), default=0.)
            excluded = total['net']-max((row['net'] for row in rows), default=0.)
            expected.extend([yen(total['net']), f'{losing}/{len(active)}', ratio(share), yen(worst), yen(excluded)])
        verdict = public['assessment']['results'][ident]
        expected.append('旧対照' if ident == 'OLD_G0' else '採用基準を達成' if verdict['adoption_achieved'] else '比較候補' if verdict['eligible'] else '候補資格未達')
        check_cells(cells(row), expected, ('比較表', ident))
        assert cells(row)[0].find('a')[0].attrs['href'] == '#'+ident
        COUNTS['比較表手法行'] += 1
    top_extra = {row['symbol']: row['net'] for row in extra['cases']['C_N30_B4']['rows']}
    assert top_extra == {'TOPIX': -17992., 'NK225': 734.}
    assert 'TOPIX -17,992円・日経 734円' in root.text()
    assert '無取引は勝ちに数えません' in root.text()
    assert '毎場' not in ''.join(node.text() for node in root.find('p') if '採用基準を満たした候補' in node.text())
    assert COUNTS['セッション商品行'] == 121*33*2
    assert COUNTS['32場合計商品行'] == COUNTS['33場合計商品行'] == 121*2
    proof = dict(全合格=True, scope='検算済み全121×33×2セッション表示、32/33合計、勝負零決済枚数、比較表及び数量/短い説明の独立照合。',
        HTML_SHA256=sha(html_path), 会計SHA256=sha(public_path), 検査数=dict(COUNTS),
        source={str(path.relative_to(ROOT)): sha(path) for path in (Path(__file__), WAVE/'report.py',
            full_audit_path, extra_audit_path, WAVE/'金融全32の結果.json', WAVE/'holdout_finance/追加Day全121の損益.json')},
        追加C_N30_B4=dict(TOPIX=-17992, NK225=734), 採用手法数=0,
        巨大台帳再読=0, 金融再生=0, 原本読取=0, NPZ読取=0, API取得=0, goal操作=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=dict(COUNTS), SHA256=sha(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()
