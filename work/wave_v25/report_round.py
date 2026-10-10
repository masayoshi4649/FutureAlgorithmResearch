"""保存済みの大量探索・反証結果を、数値照合付きの日本語報告にまとめる。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import gzip
import json
import shutil
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査' / '00020_大量探索と反証の反復'
SYMBOLS = ('TOPIX', 'NK225')
LABELS = {'TOPIX': 'TOPIXミニ', 'NK225': 'NK225マイクロ'}
TABLES: dict[str, dict] = {}
FIELDS = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units',
          'loss_units', 'zero_units', 'closed_units')


def read(name: str) -> object:
    """機能: 保存済みのJSONまたは圧縮JSONを読む。

    引数: name (str) は作業領域からの相対パス。返り値: 保存内容 (object)。
    """
    path = HERE / name
    if name.endswith('.gz'):
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: object) -> None:
    """機能: 日本語を保ってJSONを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def money(value: float) -> str:
    """機能: 符号付きの円額を整形する。

    引数: value (float)。返り値: 表示用の文字列 (str)。
    """
    return f'{round(value):+,}' if value else '0'


def amount(value: float) -> str:
    """機能: 利益・損失の正の大きさを整形する。

    引数: value (float)。返り値: 表示用の文字列 (str)。
    """
    return f'{round(value):,}'


def ratio(value: float | None) -> str:
    """機能: 比率を小数２桁で整形する。

    引数: value (float | None)。返り値: 表示用の文字列 (str)。
    """
    return '—' if value is None else f'{value:.2f}'


def table(table_id: str, headers: list[str], rows: list[list]) -> str:
    """機能: 横スクロール可能な表を作り、検査用の表示値を記録する。

    引数: table_id (str)、headers (list[str])、rows (list[list])。
    返り値: 表のHTML (str)。
    """
    assert table_id not in TABLES
    normal = [[str(value) for value in row] for row in rows]
    assert all(len(row) == len(headers) for row in normal)
    TABLES[table_id] = {'headers': headers, 'rows': normal}
    head = ''.join(f'<th>{escape(value)}</th>' for value in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{escape(value)}</td>' for value in row) + '</tr>' for row in normal)
    return f'<div class="scroll"><table id="{table_id}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def details(title: str, body: str, element_id: str = '') -> str:
    """機能: 詳細を折り畳む領域を作る。

    引数: title (str)、body (str)、element_id (str)。返り値: HTML (str)。
    """
    attr = f' id="{element_id}"' if element_id else ''
    return f'<details{attr}><summary>{escape(title)}</summary><div class="inside">{body}</div></details>'


def link(name: str, label: str | None = None) -> str:
    """機能: 報告内または再現コードへのリンクを作る。

    引数: name (str)、label (str | None)。返り値: HTML (str)。
    """
    return f'<a href="{escape(name, quote=True)}">{escape(label or name)}</a>'


def sum_rows(rows: list[dict]) -> dict:
    """機能: セッションの円損益と決済枚数を独立に合計・照合する。

    引数: rows (list[dict])。返り値: 合計 (dict)。
    """
    for row in rows:
        assert abs(row['gross_profit_yen'] - row['gross_loss_yen'] - row['net_yen']) < 0.01
        assert row['profit_units'] + row['loss_units'] + row['zero_units'] == row['closed_units']
    total = {key: sum(row[key] for row in rows) for key in FIELDS}
    assert abs(total['gross_profit_yen'] - total['gross_loss_yen'] - total['net_yen']) < 0.01
    return total


def pl_cells(row: dict) -> list:
    """機能: 損益と決済枚数の共通セルを生成する。

    引数: row (dict)。返り値: 表のセル (list)。
    """
    return [amount(row['gross_profit_yen']), amount(row['gross_loss_yen']), money(row['net_yen']),
            int(row['profit_units']), int(row['loss_units']),
            int(row['profit_units'] - row['loss_units']), int(row['zero_units'])]


def session_label(value: str) -> str:
    """機能: 開始日を保った日本語セッション名に変換する。

    引数: value (str)。返り値: セッション名 (str)。
    """
    return value.replace('_Day', ' 日中').replace('_Night', ' 夜間')


def method_section(method_id: str, description: str, status: str, data: dict) -> str:
    """機能: 手法別の期間・開始週・全セッション成績を照合して表示する。

    引数: method_id (str)、description (str)、status (str)、data (dict)。
    返り値: 折り畳みHTML (str)。
    """
    rows = data['rows']
    assert len(rows) == 26
    assert len({(row['session'], row['symbol']) for row in rows}) == 26
    period_rows, session_rows, quality_rows = [], [], []
    for symbol in SYMBOLS:
        own = sorted((row for row in rows if row['symbol'] == symbol), key=lambda row: row['session'])
        total = sum_rows(own)
        source = data['symbols'][symbol]
        for key in FIELDS:
            assert abs(total[key] - source[key]) < 0.01, (method_id, symbol, key)
        for name, selected in [
            ('9/21開始週・10区間', [row for row in own if row['session'][:10] < '2026-09-28']),
            ('9/28開始週・3区間', [row for row in own if row['session'][:10] >= '2026-09-28']),
            ('全期間・13区間', own),
        ]:
            period_rows.append([LABELS[symbol], name] + pl_cells(sum_rows(selected)))
        session_rows.extend([[LABELS[symbol], session_label(row['session'])] + pl_cells(row) for row in own])
        quality_rows.append([LABELS[symbol], ratio(source['money_ratio']), ratio(source['average_unit_payoff']),
                              amount(source['drawdown_yen']), source['cycles'],
                              f"{source['max_long']} / {source['max_short']}",
                              money(source['two_cycles_removed_net']), money(source['two_start_days_removed_net'])])
    header = ['銘柄', '期間', '利益 円', '損失 円', '収支 円', '勝ち枚数', '負け枚数', '枚数差', '同値枚数']
    body = f'<p><strong>{escape(description)}</strong></p><p class="muted">{escape(status)}</p>'
    body += table(f'{method_id}-quality', ['銘柄', '利益/損失比', '1枚平均勝ち/負け', '最大DD 円', '売買組数', '最大買/売保有', '最大2勝ち組除外 円', '最大2勝ち開始日除外 円'], quality_rows)
    body += '<h3>全期間と開始週</h3>' + table(f'{method_id}-period', header, period_rows)
    body += '<h3>各セッション</h3>' + table(f'{method_id}-session', ['銘柄', 'セッション開始日'] + header[2:], session_rows)
    return details(f'{method_id} — {description.split("。")[0]}', body, f'method-{method_id}')


class ReportParser(HTMLParser):
    """タグの対応・ID・リンク・表の文字列を検査する解析器。"""

    def __init__(self) -> None:
        """機能: 検査用の状態を初期化する。

        引数: なし。返り値: なし (None)。
        """
        super().__init__(convert_charrefs=True)
        self.stack, self.ids, self.links = [], set(), []
        self.tables, self.current_table, self.current_row, self.cell = {}, None, [], None

    def handle_starttag(self, tag: str, attrs: list[tuple]) -> None:
        """機能: 開始タグと表・リンクの情報を記録する。

        引数: tag (str)、attrs (list[tuple])。返り値: なし (None)。
        """
        attr = dict(attrs)
        if 'id' in attr:
            assert attr['id'] not in self.ids, attr['id']
            self.ids.add(attr['id'])
        if tag == 'a':
            self.links.append(attr['href'])
        if tag == 'table':
            self.current_table = attr['id']
            self.tables[self.current_table] = []
        if tag == 'tr':
            self.current_row = []
        if tag in ('td', 'th'):
            self.cell = ''
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        """機能: 終了タグの対応と表の行を検査する。

        引数: tag (str)。返り値: なし (None)。
        """
        assert self.stack and self.stack.pop() == tag, tag
        if tag in ('td', 'th'):
            self.current_row.append(self.cell)
            self.cell = None
        if tag == 'tr':
            self.tables[self.current_table].append(self.current_row)
        if tag == 'table':
            self.current_table = None

    def handle_data(self, data: str) -> None:
        """機能: 表示されたセルの文字列を収集する。

        引数: data (str)。返り値: なし (None)。
        """
        if self.cell is not None:
            self.cell += data


def main() -> None:
    """機能: 保存結果だけを読み、00020の報告・検査記録を更新する。

    引数: なし。返り値: なし (None)。原本・旧成果・ルート目次は変更しない。
    """
    OUT.mkdir(exist_ok=True)
    TABLES.clear()
    fixed = read('探索条件の固定.json')
    gate = read('反証前の候補固定.json')
    adversarial = read('一次反証の結果.json')
    passed = [item for item in adversarial if not item['first_stage_failures']]
    random_results = read('無関係対照の要約.json')
    price = read('d016_price_control.json')
    sensitivity = read('D016追加感度の結果.json')
    audit = read('d016_statistical_audit.json')
    sequential = read('sequential_selection_result.json')
    assert (fixed['全組合せ数'], gate['最低基準通過数'], len(adversarial), len(passed)) == (36668, 113, 75, 17)
    assert len(random_results) == 12
    assert all(len(item['summary']) == 2 and all(part['試行数'] == 64 for part in item['summary']) for item in random_results)
    methods = {}
    for candidate_id in ('D016__D065', 'F32__D181', 'D056__D040'):
        original = read(f'adversarial/{candidate_id}.json.gz')['cases'][0]
        assert original['case'] == '基準再現'
        methods[candidate_id] = {'rows': original['rows'], 'symbols': original['symbols']}
    methods['P02'] = {'rows': price['決定的対照']['P02']['sessions'], 'symbols': price['決定的対照']['P02']['symbols']}
    order = ('D016__D065', 'P02', 'F32__D181', 'D056__D040')

    # ----------------------------------------
    # 最初の画面で、候補の利益と未解決の弱点を同時に示す。
    body = '<p class="eyebrow">作業00020 · 保存済みデータの発見と反証 · 2026/09/21〜09/29</p>'
    body += '<h1>期間では黒字。<br>指定された波は取れていない。</h1>'
    body += '<p class="lead"><strong>D016は、指定4波×2銘柄の全8区間で正方向のネット保有が0分でした。</strong><br>期間黒字だけで、求める波を取る主候補とは言えません。価格だけのP02も利益を出し、D016には時間窓への依存も残りました。</p>'
    body += '<p>' + link('../../work/wave_v26/episode_audit.md', '指定4波への適合診断（追加反証）') + '：波の区間は売買計算に使わず、事後に保有時間を照合しました。</p>'
    body += '<p class="stages">36,668条件 → 最低基準113 → 反証75 → 一次通過17</p>'
    overview = []
    for method_id in order:
        top, nk = (methods[method_id]['symbols'][symbol] for symbol in SYMBOLS)
        overview.append([method_id, money(top['net_yen']), ratio(top['money_ratio']), money(nk['net_yen']), ratio(nk['money_ratio'])])
    body += table('overview', ['代表手法（順位ではない）', 'TOPIX収支 円', '利益/損失比', 'NK収支 円', '利益/損失比'], overview)
    body += '<p class="muted">この4例は各銘柄1枚で再生。13セッション・7開始日はすべて既知。費用0・指定価格約定・全玉場内返済。P02は追加診断で、36,668条件・一次通過17には含めません。</p>'
    body += '<div class="next">次回00021で実行中：時間窓を分散し、価格だけの対照と比較します。現在セッションの照合は候補固定後に予定。00020ではAPI追加取得0回です。</div>'
    body += '<nav><a href="#results">手法別の損益</a><a href="#weakness">弱点と反証</a><a href="#evidence">検算・全条件</a></nav>'

    # ----------------------------------------
    # 手法の説明と金額・枚数を同じ章に置く。
    body += '<h2 id="results">手法別の利益・損失・収支</h2>'
    body += '<p>金額は同銘柄内で比較します。利益/損失比（PF）は総利益÷総損失。1枚平均勝ち/負けは（総利益÷勝ち枚数）÷（総損失÷負け枚数）です。枚数差は<strong>勝ち決済枚数−負け決済枚数</strong>で、保有残ではありません。同値決済も別記し、すべて場内で返済します。</p>'
    body += '<p class="muted">週はセッション開始日の月曜日基準。9/21週は10セッション、9/28週は3セッションの途中集計です。TOPIXミニは1pt=1,000円、NKマイクロは1pt=10円。NKは原本ラージの10pt刻みを維持した換算で、マイクロ専用板の実約定再現ではありません。最大DDは含みを含む資産の最大減少額です。</p>'
    definitions = {
        'D016__D065': ('板フローで入る時機を絞り、両市場の30秒価格方向へ1枚入る。1ATR損切り、3ATRトレーリングと最高利益の25%保護で返済する。', '収支の一次反証は通過。ただし指定4波×2銘柄の全8区間で正方向ネット保有0分で、要求した波の検知には未達です。実在する参加者の「吸収」を特定した手法ではなく、時間窓の変更にも弱さが残りました。'),
        'P02': ('両市場の60秒価格方向から30秒価格方向への反転を拾う。板数量の条件を使わず、返済管理はD016と同じにする。', '後付けの価格対照。D016より期間収支は高いものの、TOPIXの最大DDは26,000円から81,500円へ拡大。一次反証17に含まれず、優位性を確認済みとは扱いません。'),
        'F32__D181': ('最良板の買い売り数量の偏りと価格の進行方向が一致したら、0.25ATRの順行を確認して1枚入る。3連敗後は2ATR進むまで休止する。', '一次反証を通過したF32系の固定1枚代表。基準のF32_G08とは条件IDが異なります。1ATR損切りと2ATRトレーリングを基本にします。'),
        'D056__D040': ('長めに蓄積した板フローに対し、短い板フローと価格が反転したら、0.1ATRの順行を確認して1枚入る。0.75ATR進めば建値を保護する。', '一次反証を通過した別系統の固定1枚代表。1ATR損切りと2ATRトレーリングを基本にします。参加者の返済を識別したという意味ではありません。'),
    }
    for method_id in order:
        body += method_section(method_id, *definitions[method_id], methods[method_id])

    # ----------------------------------------
    # 形式的な合否と反証の解釈を混ぜない。
    body += '<h2 id="weakness">何が残り、何が崩れたか</h2>'
    body += table('key-findings', ['確認したこと', '結果', '今回の判断'], [
        ['D016の大勝ち依存', '最大2勝ち開始日を除いても TOPIX +66,000円 / NK +9,300円', '一部の大勝ちだけでは説明されない'],
        ['60秒 → 48秒の窓変更', 'TOPIX +18,000円 / NK +200円', '正確な時間設定への依存が強い'],
        ['価格だけのP02', 'TOPIX +151,000円 / NK +31,500円', '板数量が利益に不可欠とは言い切れない'],
        ['過去最良を機械的に選択', '次の7区間は TOPIX −31,500円 / NK −25,300円', '良い固定候補と、良い選択工程は別問題'],
    ])
    entry = '<p>D016は、60秒の板数量変化の方向（OFI）を<strong>タイミングのフィルター</strong>に使い、直近30秒の価格方向で売買方向を決めます。相手市場は60秒遅らせた公開済み情報を参照します。</p>'
    entry += '<ol><li>両市場の60秒OFIの絶対値が0.03を超え、符号が一致。</li><li>OFIの符号×60秒価格変化が0.35ATR以下。符号付き条件なので、OFIと逆方向への大きな値動きも含む。</li><li>両市場の30秒価格変化の絶対値が0.03ATRを超え、OFIと反対方向に一致したら、その価格方向を採用。</li><li>条件成立行の次の有効原本行で1枚成行。1ATR損切り。1ATR進んだ後の3ATRトレーリングに加え、最高利益が初期リスクを超えたら、その25%を最低利益として保護。価格幅は原本の呼値へ丸める。</li><li>保有は最大360分、遅くとも場末に全返済。新規は開始20分後から場末5分前まで。条件の有効期限120秒と撤回条件を持つが、方向信号の撤回と保有玉の自動即時返済は同義ではない。</li></ol>'
    entry += '<p>このデータでは価格確認0.03ATRが原本の1刻み未満だった発火は374/377件。取消と約定、同一参加者の補充は識別できません。「吸収が見えた」と断定せず、<strong>OFIで絞った価格反転</strong>として扱います。</p>'
    entry += '<p>' + link('d016_signal_audit.md', '信号の独立監査') + ' / ' + link('d016_price_control.md', '価格だけの対照') + '</p>'
    body += details('D016の実際の条件 — 板の「吸収」を断定しない', entry)

    sensitivity_rows, clock_rows = [], []
    for part in sensitivity['結果']:
        top, nk = (part['symbols'][symbol] for symbol in SYMBOLS)
        variant = part['variant']
        row = [f"{variant['変数']} = {variant['値']}", money(top['net_yen']), ratio(top['money_ratio']), money(nk['net_yen']), ratio(nk['money_ratio'])]
        sensitivity_rows.append(row)
        if variant['変数'] in ('seconds', 'peer_delay_seconds'):
            clock_rows.append(row)
    sensitivity_body = '<p><strong>14変形をまとめた事前基準では、両銘柄とも13/14条件が黒字・PF1.20以上で、形式上は合格。</strong>ただし時間に関わる4条件だけを見ると、収支中央値はTOPIX27,500円（基準の20%）、NK9,500円（42%）まで落ちます。時計条件の弱さが、変化しなかった管理条件などと一緒に集計されて薄まっています。</p>'
    sensitivity_body += table('clock-variants', ['変更', 'TOPIX収支 円', 'PF', 'NK収支 円', 'PF'], clock_rows)
    sensitivity_body += '<p>事前基準は、各銘柄で75%以上の変形が黒字・PF1.20以上、収支中央値が基準の50%以上、最悪収支が基準総利益の−25%以上。14条件全体の収支中央値はTOPIX131,250円・NK22,400円でした。時計4条件の切り出しは<strong>結果を見た後の診断</strong>であり、元の合格判定を不合格へ書き換えるものではありません。ただし、頑健性を確認できたとする根拠にもできません。</p>'
    sensitivity_body += details('追加14条件をすべて表示', table('all-variants', ['変更', 'TOPIX収支 円', 'PF', 'NK収支 円', 'PF'], sensitivity_rows))
    sensitivity_body += '<p>48秒などへ変更した条件を新しい採用条件にはしていません。' + link('D016追加感度の固定.json', '追加前の基準') + ' / ' + link('D016追加感度の結果.json', '全結果') + '</p>'
    body += details('追加感度 — 一括基準は合格、時計4条件では大幅悪化', sensitivity_body)

    controls = []
    for name in ('D016_ORIGINAL', 'D016_PRICE_VETO', 'P01', 'P02', 'P03', 'P04'):
        part = price['決定的対照'][name]
        top, nk = (part['symbols'][symbol] for symbol in SYMBOLS)
        controls.append([name, money(top['net_yen']), ratio(top['money_ratio']), amount(top['drawdown_yen']), money(nk['net_yen']), ratio(nk['money_ratio']), amount(nk['drawdown_yen'])])
    price_body = '<p>P01は両市場の30秒方向一致、P02は両市場の60秒→30秒反転、P03は自市場だけの60秒→30秒反転、P04はP01に符号付き0.35ATR条件を足した価格対照です。P02の好成績により、「この利益には板数量が必要」とする説明は成立しません。一方、すべての価格対照が良いわけでもありません。</p>'
    price_body += table('price-controls', ['対照', 'TOPIX収支 円', 'PF', '最大DD 円', 'NK収支 円', 'PF', '最大DD 円'], controls)
    price_body += '<p>D016_PRICE_VETOは信号撤回を価格だけに変えた対照で、元D016と方向・台帳が一致しました。価格だけのP02も、価格観測の行・時刻自体は原本板データに依存します。</p>'
    price_body += '<p>別の64乱数試行では、価格条件を満たす時点へ仮想OFI符号を振り、元D016の収支以上は各銘柄とも0/64でした。ただし発火数・持続性・市場間相関が実OFIと一致しないため、OFIの必要性や正式な有意確率の証明にはなりません。</p>'
    price_body += '<p>' + link('d016_price_control.md', '対照の定義と解釈') + ' / ' + link('d016_price_control.json', '決定的対照と全64乱数の結果') + '</p>'
    body += details('価格だけの反例 — P02は高収支、TOPIXの落ち込みも大きい', price_body)

    random_rows = []
    for item in random_results:
        for part in item['summary']:
            top, nk = (part['symbols'][symbol] for symbol in SYMBOLS)
            random_rows.append([item['candidate']['id'], '元の発火時刻だけ' if part['発火時刻限定'] else '全時間の3分乱数',
                                money(top['net_percentiles'][2]), money(nk['net_percentiles'][2]),
                                f"{top['net_at_least_candidate']}/64", f"{nk['net_at_least_candidate']}/64",
                                f"{part['両銘柄収支が候補以上']}/64"])
    random_body = '<p>12候補それぞれについて、同じ管理条件を用いた64乱数×2方式を完了しました。合計1,536組は同じ既知期間の再利用で、1,536の独立した相場ではありません。両市場で同じ時間区分の乱数方向を共有します。</p>'
    random_body += '<p>D016は、全時間の3分乱数でも、元の発火時刻を残した乱数でも、両銘柄同時に候補収支以上は0/64。ただし後者はタイミング情報を残し、前者とは取引頻度も異なります。候補の選択バイアスを補正したp値にはしません。</p>'
    random_body += table('random-controls', ['候補', '対照方式', 'TOPIX中央値 円', 'NK中央値 円', 'TOPIX収支以上', 'NK収支以上', '両銘柄収支以上'], random_rows)
    random_body += '<p>' + link('無関係対照の要約.json', 'PF比較・分位点を含む保存結果') + '</p>'
    body += details('12候補 × 64乱数 × 2方式 — 乱数との比較を完了', random_body)

    # ----------------------------------------
    # 期間集中・選択バイアス・実行上の限界を記す。
    boot_rows = []
    for reference in ('F32_G08', 'X05_G08', 'D016_SELF_PEER'):
        comparison = audit['対応開始日bootstrap']['比較'][reference]
        for symbol in SYMBOLS:
            part = comparison[symbol]
            bounds = part['収支差の中央95%区間']
            boot_rows.append([reference, LABELS[symbol], money(part['実測収支差円']),
                              money(bounds['下側2_5']) + ' ～ ' + money(bounds['上側97_5'])])
    concentration = '<p>D016は、最大2勝ち売買組を除いてTOPIX+62,500円・NK+6,600円、最大2勝ちセッション除外で+59,500円・+8,000円、最大2勝ち開始日除外で+66,000円・+9,300円。元の黒字は、少数の最大利益を除いても残りました。</p>'
    concentration += table('d016-parts', ['分解', 'TOPIX収支 円', 'NK収支 円'], [
        ['日中', '+103,500', '+14,200'], ['夜間', '+31,000', '+8,200'],
        ['9/21開始週', '+68,500', '+21,800'], ['9/28開始週', '+66,000', '+600'],
        ['ロング', '+53,500', '+12,400'], ['ショート', '+81,000', '+10,000'],
    ])
    concentration += '<p>ただし「基準を上回った差」は不安定です。D016−F32の差は全期間でTOPIX+31,500円・NK+5,300円ですが、9/29を除くとTOPIX−8,500円、9/24を除くとNK−2,100円へ反転します。</p>'
    concentration += table('bootstrap', ['比較相手', '銘柄', 'D016との差 円', '開始日再標本の中央95%範囲 円'], boot_rows)
    concentration += '<p>7開始日を共通の単位として、両銘柄の同日関係を保ち5,000回再標本化しました（固定seed）。これは少数の既知日での<strong>探索バイアス未補正の診断</strong>です。母集団の保証や正式な有意差判定にはしません。</p>'
    concentration += '<p>相手市場を遅延させた自市場へ置換すると、TOPIXは−42,000円、NKは+24,300円。TOPIXには相手市場参照が効いて見える一方、NKでは元の+22,400円を上回ります。<strong>両銘柄に相手市場が必須とは言えません。</strong>この置換は発火から返済までの経路を変えるため、独立した情報価値の足し算でもありません。</p>'
    concentration += '<p>' + link('d016_statistical_audit.md', '独立統計監査') + ' / ' + link('d016_statistical_audit.json', '全分解・台帳・再標本結果') + '</p>'
    body += details('大勝ちを除いても黒字。ただし基準との差はまだ不安定', concentration)

    seq_rows = []
    for fold in sequential['folds']:
        nxt = {row['symbol']: row for row in fold['次セッション結果']}
        seq_rows.append([session_label(fold['評価セッション']), fold['過去入口合格数'], fold['採用ID'],
                         money(nxt['TOPIX']['net_yen']), money(nxt['NK225']['net_yen'])])
    seq_summary = []
    for name, result in [('逐次選択', sequential['選択工程結果'])] + list(sequential['同じ7区間の固定基準'].items()):
        for symbol in SYMBOLS:
            part = result['全評価期間'][symbol]
            seq_summary.append([name, LABELS[symbol]] + pl_cells(part) + [ratio(part['money_ratio'])])
    seq_body = '<p>全36,668候補を毎回対象に、完了した最初の6セッションから選び、次の1セッションだけを評価。以後は過去を増やす方式です。採用IDは両銘柄共通。上位候補だけに絞らず、同点はID順に固定しました。最初の6区間は評価損益に含みません。</p>'
    seq_body += table('sequential-folds', ['次の評価区間', '過去基準の合格数', '採用ID', 'TOPIX収支 円', 'NK収支 円'], seq_rows)
    seq_body += table('sequential-total', ['方法', '銘柄', '利益 円', '損失 円', '収支 円', '勝ち枚数', '負け枚数', '枚数差', '同値枚数', 'PF'], seq_summary)
    seq_body += '<p>選択工程は両銘柄赤字。最大2勝ち売買組を除くとTOPIX−90,500円・NK−33,900円です。選択された一部条件はTOPIX最大5枚・NK最大10枚、固定基準は1枚のため、この表を同リスク比較とは呼びません。1枚平均勝ち/負けが良くても、負け枚数が増えれば収支はマイナスになります。</p>'
    seq_body += '<p>未来セッションの削除・改変14検査で、それ以前の候補検査・順位・採用は不変でした。ただし、設計者は全13区間を知っています。時間順の手順を守った事後検証であり、真の未見検証ではありません。</p>'
    seq_body += '<p>' + link('sequential_selection_summary.md', '逐次選択の報告') + ' / ' + link('sequential_selection_result.json', '全選択結果') + ' / ' + link('sequential_selection_audit.json', '未来改変監査') + '</p>'
    body += details('選び方もアルゴリズムとして検証 — 過去最良の逐次選択は赤字', seq_body)

    body += '<h2 id="evidence">検算と再現資料</h2>'
    checks = '<p>D016とF32の52銘柄セッション・5,863,690原本行を独立再生し、現金・保有・含み・返済台帳を照合しました。D016の信号は26区間・2,931,845行で別式と一致。途中切断や未来変更の比較364組・20,565,118方向値でも一致しました。</p>'
    checks += '<p>原本順では、新規は必ず判断行より後。全59新規の判断・約定には、同じCurrentPriceTimeが付いていました。この時刻は直近約定時刻で、受信時刻ではありません。「次行約定」を実時間の通信遅延検証とは扱えません。一次反証では1/5/15秒遅延も調べましたが、これも記録時刻上の評価です。</p>'
    checks += '<p>板特徴は次の異なる時刻の最初の有効行で公開し、元データ順番号は常に公開行より過去でした。相手市場の60秒遅延参照にも時刻違反は見つかりませんでした。ただし受信時刻がないため、実際の両市場の到着順まで確認したことにはなりません。</p>'
    checks += '<p>' + ' / '.join(link(name) for name in ['d016_signal_audit.md', 'clock_alignment_audit.md', 'd016_statistical_audit.md', 'data_audit.json']) + '</p>'
    body += details('因果性・会計・時計の独立監査と、その限界', checks)

    pass_rows = []
    for item in passed:
        candidate = item['candidate']
        top, nk = (candidate['symbols'][symbol] for symbol in SYMBOLS)
        pass_rows.append([candidate['id'], money(top['net_yen']), ratio(top['money_ratio']),
                          f"{top['max_long']}/{top['max_short']}", money(nk['net_yen']), ratio(nk['money_ratio']),
                          f"{nk['max_long']}/{nk['max_short']}"])
    all_body = '<p>178信号×206管理＝36,668条件。最低基準は、両銘柄でPF1.30以上、1枚平均勝ち/負け1.20以上、売買組13以上、活動・勝ちセッション各7以上、最大2勝ちセッション・売買組除外後も黒字、日中・夜間・両開始週とも黒字など。通過113から重複台帳等を整理した75候補を一次反証し、17が残りました。</p>'
    all_body += '<p>以下は一次通過の一覧で、最終採用の順位ではありません。保有枚数が異なるので円収支だけでは比較できません。一次反証の通過は、価格対照や追加時計検証も通ったという意味ではありません。</p>'
    all_body += table('first-stage-passed', ['候補', 'TOPIX収支 円', 'PF', '最大買/売枚数', 'NK収支 円', 'PF', '最大買/売枚数'], pass_rows)
    all_body += '<p>' + ' / '.join(link(name) for name in ['全条件の期間集計.json.gz', '一次反証の結果.json', '反証仕様の固定.json', '探索条件の固定.json', 'validation_protocol.md']) + '</p>'
    all_body += '<p>全セッション結果の原データは ' + link('../../work/wave_v25/sessions/', 'sessionsフォルダ（信号ID別の圧縮JSON）') + '、反証各条件は ' + link('../../work/wave_v25/adversarial/', 'adversarialフォルダ') + '。これらは今回の報告と同じ保存結果です。</p>'
    body += details('一次通過17条件と、全36,668条件の保存結果', all_body)
    coin = '<p>公平な価格過程を用いた16,384回の再生では、8管理×2方向の平均損益はすべてゼロから1.22標準誤差以内でした。非対称OCOは勝率約79.7%でも期待収支はほぼゼロ。損切り・利益保護・両建て等は損益の形を変えますが、この公平な条件ではそれだけで正の期待値を作りません。</p><p>実市場がコイントスであるという結論ではありません。予測に情報があるかと、注文管理が損小利大を作るかを分けて調べる対照です。' + link('fair_market_audit.md', '公平価格過程の監査') + '</p>'
    body += details('注文手法だけの利益も対照で検査', coin)
    body += '<p class="muted">今ある13セッションを繰り返し使った研究結果です。選択バイアスは残り、どんな相場でも安定して稼げることの確認には至っていません。見つかった利益と弱点の両方を、次の反復へ引き継ぎます。</p>'
    body += '<footer>' + link('README.md', '読む順序・再現コード') + ' · ' + link('表示データ.json', '表示値のJSON') + ' · ' + link('報告検査.json', '数値・リンク・HTML検査') + ' · ' + link('../index.html', '調査一覧') + '</footer>'

    # ----------------------------------------
    # 報告フォルダ内だけを更新し、数値・リンク・マークアップを検査する。
    css = '''
    :root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b111c;color:#e4eaf3;font:15px/1.7 system-ui,"Yu Gothic",sans-serif}main{max-width:1220px;margin:auto;padding:28px 30px 60px}h1{font-size:32px;line-height:1.35;margin:8px 0 18px}h2{font-size:24px;margin:34px 0 12px}h3{font-size:17px;margin:24px 0 8px}p{margin:10px 0}.eyebrow,.muted{color:#a6b5cc;font-size:13px}.lead{font-size:17px}.stages{color:#76d7cc;font-weight:700}.next{border-left:4px solid #e5bd70;background:#1e2531;padding:10px 15px;margin:14px 0}a{color:#8ec6ff;text-decoration:none}a:hover{text-decoration:underline}nav{display:flex;gap:22px;flex-wrap:wrap;margin:14px 0}.scroll{overflow:auto;margin:12px 0}table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums;white-space:nowrap}th,td{padding:9px 12px;border-bottom:1px solid #2b374b;text-align:right}th{background:#1b283b;color:#cdd9ea;font-weight:600}th:first-child,td:first-child{text-align:left}tbody tr:nth-child(even){background:#111b2a}details{border:1px solid #2d3c51;border-radius:7px;margin:11px 0;background:#111a28}summary{cursor:pointer;padding:14px 17px;font-weight:650}summary:hover{background:#1b283b}.inside{padding:0 18px 18px}ol{padding-left:25px}li{margin:8px 0}footer{border-top:1px solid #2d3c51;margin-top:30px;padding-top:18px;font-size:13px}@media(max-width:700px){main{padding:18px 14px}h1{font-size:27px}h2{font-size:21px}.lead{font-size:16px}}
    '''
    html = '<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>00020 大量探索と反証の反復</title><style>' + css + '</style></head><body><main>' + body + '</main></body></html>'
    (OUT / '発見と反証.html').write_text(html, encoding='utf-8')
    copied = ['signal_design.md', 'manager_design.md', 'validation_protocol.md', 'validation_protocol.json',
              'validation_protocol_fixed.json', 'data_audit.json', '探索条件の固定.json', '反証仕様の固定.json',
              '反証前の候補固定.json', '全条件の期間集計.json.gz', '一次反証の結果.json', '無関係対照の要約.json',
              'd016_price_control.md', 'd016_price_control.json', 'd016_price_control_fixed.json',
              'd016_signal_audit.md', 'd016_signal_audit.json', 'd016_statistical_audit.md', 'd016_statistical_audit.json',
              'D016追加感度の固定.json', 'D016追加感度の結果.json', 'clock_alignment_audit.md', 'clock_alignment_audit.json',
              'sequential_selection_summary.md', 'sequential_selection_result.json', 'sequential_selection_audit.json',
              'sequential_selection_fixed.json', 'sequential_selection_reference_audit.json',
              'fair_market_audit.md', 'fair_market_audit.json', 'fair_market_fixed.json']
    for name in copied:
        shutil.copy2(HERE / name, OUT / name)
        assert (HERE / name).read_bytes() == (OUT / name).read_bytes()
    save(OUT / '表示データ.json', {'注意': '全期間は既知。枚数差は勝ち決済枚数−負け決済枚数。全玉場内返済。',
                                '代表手法': methods, '表示表': TABLES})
    readme = '''# 00020 大量探索と反証の反復

最初に [発見と反証.html](発見と反証.html) を開いてください。結論を最初の画面に置き、各手法の利益・損失・収支と決済枚数は折り畳みにまとめています。

## 読む順序

1. [発見と反証.html](発見と反証.html)：結論、4手法の全期間・開始週・各セッションの損益。
2. [価格だけの対照](d016_price_control.md)、[実際の信号条件](d016_signal_audit.md)、[追加14条件](D016追加感度の結果.json)：D016の反例と時間窓への依存。
3. [独立統計監査](d016_statistical_audit.md)、[逐次選択](sequential_selection_summary.md)、[時計監査](clock_alignment_audit.md)：大勝ち依存、選ぶ工程、因果性の限界。
4. [全36,668条件の期間集計](全条件の期間集計.json.gz)、[一次反証75候補](一次反証の結果.json)、[12候補の乱数対照](無関係対照の要約.json)。
5. [表示値](表示データ.json)、[報告検査](報告検査.json)：表示表・原集計・リンクの照合記録。

## この回の結論

36,668条件から最低基準113、一次反証75、一次通過17。追加の[指定4波診断](../../work/wave_v26/episode_audit.md)では、D016は4波×2銘柄の全8区間で正方向ネット保有0分。期間黒字だけで要求に適う主候補とは言えません。最大2勝ちを除いても黒字ですが、60秒→48秒の窓や相手市場遅延の変更で大幅悪化しました。追加14変形の一括基準は合格のまま、時計4条件の弱さを別に報告しています。価格だけのP02は高収支ですがTOPIXの最大DDも大きく、確定解ではありません。過去最良を選ぶ工程は次の7区間で赤字でした。

すべて既知の13セッション・7開始日を再利用した結果です。費用0、指定価格約定、全玉場内返済。代表4手法は各1枚。金額を銘柄間で単純合算しません。勝ち−負け枚数は決済枚数差で保有残ではなく、同値決済枚数も表示しています。

TOPIXミニは1pt=1,000円、NKマイクロは1pt=10円で換算。NKの原本はラージの10pt格子を維持しています（実マイクロの5pt格子・板約定を再現したものではありません）。

この回ではAPI追加取得0回。次回00021で時間窓分散と価格対照を検証し、候補固定後の現在セッション照合を予定しています。プロトコル内の提案と実装済み項目は区別してください。

## 再現コードと原結果

- [全探索](../../work/wave_v25/discovery_runner.py)、[信号](../../work/wave_v25/discovery_signals.py)、[管理](../../work/wave_v25/discovery_managers.py)。
- [一次反証](../../work/wave_v25/adversarial_round.py)、[価格対照](../../work/wave_v25/d016_price_control.py)、[追加感度](../../work/wave_v25/d016_extended_sensitivity.py)。
- [逐次選択](../../work/wave_v25/sequential_selection.py)、[独立統計監査](../../work/wave_v25/d016_statistical_audit.py)、[報告生成](../../work/wave_v25/report_round.py)。
- [信号別・全条件のセッション成績](../../work/wave_v25/sessions/)、[反証条件別成績](../../work/wave_v25/adversarial/)。

報告のみの再生成：プロジェクトルートで `python work/wave_v25/report_round.py`。保存結果だけを読み、00020内の成果を更新します。API取得、原本変更、ルート目次変更は行いません。
'''
    (OUT / 'README.md').write_text(readme, encoding='utf-8')
    parser = ReportParser()
    parser.feed(html)
    assert not parser.stack
    assert len(parser.tables) == len(TABLES)
    for table_id, expected in TABLES.items():
        assert parser.tables[table_id] == [expected['headers']] + expected['rows'], table_id
    links = []
    for href in parser.links:
        parts = urlsplit(href)
        if parts.scheme:
            continue
        if parts.path:
            target = (OUT / unquote(parts.path)).resolve()
            if target.name != '報告検査.json':
                assert target.exists(), target
            links.append(str(target))
        else:
            assert parts.fragment in parser.ids, href
    # READMEのリンクも同じ保存先を起点に照合する。
    import re
    for href in re.findall(r'\]\(([^)]+)\)', readme):
        target = (OUT / href).resolve()
        if target.name != '報告検査.json':
            assert target.exists(), target
    qa = {'更新時刻': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '報告コードSHA256': sha256(Path(__file__).read_bytes()).hexdigest(),
          'HTMLタグ対応': True, 'ID重複なし': True, '表示表照合数': len(TABLES),
          '表示データ行数': sum(len(part['rows']) for part in TABLES.values()), 'リンク確認件数': len(parser.links),
          '代表4手法セッション損益枚数照合': 104, '代表4手法期間合算照合': 8, '開始週合算照合': 16,
          '原資料コピー一致数': len(copied), 'READMEリンク照合': True,
          '追加API取得': 0, 'ルート目次変更': False, 'リンク先': sorted(set(links))}
    save(OUT / '報告検査.json', qa)
    print(json.dumps({key: value for key, value in qa.items() if key != 'リンク先'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
