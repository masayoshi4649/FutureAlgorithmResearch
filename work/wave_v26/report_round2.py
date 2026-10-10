"""第２反復の保存結果を、目的適合と収益性を区別した日本語HTMLへまとめる。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlsplit
import gzip
import importlib.util
import json
import re
import shutil
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = '00021_時間窓への依存を減らす再探索'
OUT = ROOT / 'アルゴリズム調査' / NAME
PREVIOUS = HERE.parent / 'wave_v25'
SYMBOLS = ('TOPIX', 'NK225')

# ----------------------------------------
# 表示・合算検算だけを前報告から再利用する。売買コードは読み込まない。
_helper_spec = importlib.util.spec_from_file_location('v25_report_helpers', PREVIOUS / 'report_round.py')
helpers = importlib.util.module_from_spec(_helper_spec)
_helper_spec.loader.exec_module(helpers)
table, money, amount, ratio = helpers.table, helpers.money, helpers.amount, helpers.ratio
details, link = helpers.details, helpers.link


def read(path: Path, default: object = None) -> object:
    """機能: 存在する保存済みJSONを読み、未完成なら既定値を返す。

    引数: path (Path)、default (object)。返り値: 保存内容または既定値 (object)。
    """
    if not path.exists():
        return default
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: object) -> None:
    """機能: 日本語を保持して検査・表示データを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def update_index() -> None:
    """機能: 過去作業を保存したまま、最新の報告への入口を更新する。

    引数: なし。返り値: なし (None)。既存00021のカードだけを置換する。
    """
    index = OUT.parent / 'index.html'
    text = index.read_text(encoding='utf-8')
    text = re.sub(r'<!--00021開始-->.*?<!--00021終了-->', '', text, flags=re.S)
    text = text.replace('task latest', 'task').replace('<span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は00021。計56,444条件を２反復で探索。収益性だけでなく、指定された波への適合も確認。</p>', text, count=1)
    card = f'<!--00021開始--><article class="task latest"><div class="number">作業00021 <span class="badge">最新</span></div><h2>時間窓への依存を減らす再探索</h2><p>追加19,776条件。期間黒字と要求した波の捕捉を分け、反証・一回の現在照合を報告。</p><a class="button" href="{NAME}/再探索と反証.html">結果を開く →</a><p><a href="{NAME}/README.md">資料案内</a> · <a href="00020_大量探索と反証の反復/発見と反証.html">第１反復36,668条件</a></p></article><!--00021終了-->'
    text = text.replace('</header>', '</header>' + card, 1)
    index.write_text(text, encoding='utf-8')
    readme = OUT.parent / 'README.md'
    text = readme.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00021の[再探索と反証]({NAME}/再探索と反証.html)。追加19,776条件の収益性と、指定された波への適合を分けて報告しています。**', text, count=1)
    text = re.sub(r'^\| `00021_.*?\r?\n', '', text, flags=re.M).replace('（最新）', '')
    marker = '| --- | --- | --- | --- |'
    line = f'\n| `{NAME}`（最新） | 時間窓分散19,776条件・敵対検証・指定波診断 | [再探索と反証]({NAME}/再探索と反証.html) | [資料案内]({NAME}/README.md) |'
    text = text.replace(marker, marker + line, 1)
    readme.write_text(text, encoding='utf-8')


def baseline(candidate_id: str) -> dict:
    """機能: 新候補または固定比較の基準セッション成績を読む。

    引数: candidate_id (str)。返り値: rows・symbolsを持つ成績 (dict)。
    """
    if candidate_id.startswith('E'):
        full = read(HERE / 'adversarial' / f'{candidate_id}.json.gz')
        if full:
            case = next(item for item in full['cases'] if item['case'] == '基準再現')
            return {'rows': case['rows'], 'symbols': case['symbols']}
        signal_id = candidate_id.split('__')[0]
        rows = next(item['rows'] for item in read(HERE / 'sessions' / f'{signal_id}.json.gz') if item['id'] == candidate_id)
        candidates = read(HERE / '反証前の候補固定.json')['上位30']
        summary = next(item['symbols'] for item in candidates if item['id'] == candidate_id)
        return {'rows': rows, 'symbols': summary}
    if candidate_id == 'P02__D065':
        saved = read(PREVIOUS / 'd016_price_control.json')['決定的対照']['P02']
        return {'rows': saved['sessions'], 'symbols': saved['symbols']}
    path = PREVIOUS / 'adversarial' / f'{candidate_id}.json.gz'
    if path.exists():
        case = next(item for item in read(path)['cases'] if item['case'] == '基準再現')
        return {'rows': case['rows'], 'symbols': case['symbols']}
    rows = next(item['rows'] for item in read(PREVIOUS / 'sessions' / f'{candidate_id.split("__")[0]}.json.gz') if item['id'] == candidate_id)
    # F32固定比較の合算値は独立監査の結果と、探索の明細を結び付ける。
    audit = read(PREVIOUS / 'd016_statistical_audit.json')['全期間比較']['F32_G08']
    summaries = read(PREVIOUS / '全条件の期間集計.json.gz')
    if isinstance(summaries, dict):
        summaries = summaries.get('candidates', summaries.get('結果', []))
    own = next(item for item in summaries if item['id'] == candidate_id)
    for symbol in SYMBOLS:
        assert own['symbols'][symbol]['net_yen'] == audit[symbol]['net_yen']
    return {'rows': rows, 'symbols': own['symbols']}


def episode_body(episode: dict) -> str:
    """機能: 指定波の捕捉時間と損益を、収益性とは別の診断として表示する。

    引数: episode (dict)。返り値: HTML (str)。
    """
    body = '<p>ユーザー指定4波×2銘柄の8区間です。区間を売買計算には渡さず、事後に照合しました。20分は説明用の目安であり、合格を保証する統計基準ではありません。全波を取る必要はなくても、例示した波で何が起きたかは別途確認します。</p>'
    waves = [[item['id'], item['name'], item['start'][5:16].replace('T', ' '), item['end'][5:16].replace('T', ' '), 'ロング' if item['side'] > 0 else 'ショート'] for item in episode['固定仕様']['規則']['対象']]
    body += table('wave-windows', ['波', '指定された場面', '開始', '終了', '方向'], waves)
    for summary in episode['方法別要約']:
        identifier = summary['method']
        own = [item for item in episode['結果'] if item['method'] == identifier]
        assert len(own) == summary['対象区間数']
        assert sum(item['正方向ネット20分目安達成'] for item in own) == summary['目安達成区間数']
        rows = [[item['wave'], item['symbol'], f"{item['正方向信号分']:.1f} / {item['逆方向信号分']:.1f}",
                 f"{item['正方向ネット保有分']:.1f} / {item['逆方向ネット保有分']:.1f}", money(item['時価損益差円']),
                 '20分以上' if item['正方向ネット20分目安達成'] else '未達'] for item in own]
        title = f"{identifier}：20分目安 {summary['目安達成区間数']}/{summary['対象区間数']}、正方向保有0は{len(summary['正方向保有0区間'])}区間"
        body += details(title, table(f'wave-{identifier}', ['波', '銘柄', '正/逆信号 分', '正/逆ネット保有 分', '波の時価損益差 円', '説明用目安'], rows))
    body += '<p>時価損益差は波の前から持つ玉・区間内決済・未返済の含みを含み、区間内新規玉だけの最終利益ではありません。完全に相殺する両建ては正方向ネット保有に数えません。CurrentPriceTimeが同値の行間は0分で、実受信時刻を再現した計測ではありません。</p>'
    body += '<p>' + link('episode_audit.md', '波の診断全文') + ' / ' + link('episode_audit.json', '正逆各脚・約定・返済・方向変更の全記録') + '</p>'
    return body


def sensitivity_body(identifier: str, data: dict) -> str:
    """機能: 時計・確認・入口・出口を分け、全変形と個別判定を表示する。

    引数: identifier (str)、data (dict)。返り値: HTML (str)。
    """
    labels = {'entry': '入口幅', 'management': '出口管理全体', 'clock': '時計窓と相手遅延', 'confirmation': '連続確認秒',
              'peer': '相手遅延', 'stop_atr': '損切り幅', 'main_trail': '追跡幅', 'lock_fraction': '利益保護比率', 'timeout_min': '保有期限'}
    rows = []
    for title, category in [('一次基準', data['カテゴリ判定']), ('小区分の診断', data['個別変数診断'])]:
        for key, part in category.items():
            top, nk = (part['symbols'][symbol] for symbol in SYMBOLS)
            unused = part['構造的不使用']
            rows.append([title, labels.get(key, key), '不使用・除外' if unused else f"{part['通過数']}/{part['有効条件数']}",
                         '—' if unused else money(top['中央値']), '—' if unused else money(top['最悪']),
                         '—' if unused else money(nk['中央値']), '—' if unused else money(nk['最悪']),
                         '対象外' if unused else ('通過' if part['通過'] else '未達')])
    body = table(f'sensitivity-{identifier}', ['範囲', '変数', '両銘柄黒字PF≥1.2', 'TOPIX中央値 円', 'TOPIX最悪 円', 'NK中央値 円', 'NK最悪 円', '保存判定'], rows)
    body += '<p>一次基準はカテゴリごとの判定です。小区分の診断で未達でも一次判定の定義を後から変更せず、その弱点を表示します。構造上使わない値は分母から除外。使う値を変更しても今回の方向が偶然同じだった場合は、別に件数を記録します。</p>'
    body += f'<p>有効な信号近傍 {data["有効信号近傍数"]} 件、基準と方向が完全一致 {data["基準と方向完全一致の近傍数"]} 件。</p>'
    case_rows = []
    for case in data['cases']:
        top, nk = (case['symbols'][symbol] for symbol in SYMBOLS)
        case_rows.append([case['case'], money(top['net_yen']), ratio(top['money_ratio']), money(nk['net_yen']), ratio(nk['money_ratio']),
                          '一致' if case['ledger_hash'] == data['cases'][0]['ledger_hash'] else '異なる'])
    body += details('各パラメータ・遅延・部品対照の全結果', table(f'cases-{identifier}', ['変更', 'TOPIX収支 円', 'PF', 'NK収支 円', 'PF', '基準との台帳'], case_rows))
    return body


def current_body(result: dict | None, selected: dict | None) -> str:
    """機能: 現在照合の保存状況に応じ、未取得または途中損益を区別して表示する。

    引数: result (dict | None)、selected (dict | None)。返り値: HTML (str)。通信しない。
    """
    if not result:
        record = read(HERE / 'live' / '取得記録.json')
        if record:
            return '<p>一回取得の記録はありますが、現在照合の最終結果はまだ保存されていません。未完了の結果を黒字・赤字とは判定しません。</p>'
        text = '収益基準による研究候補は固定済みですが、指定波への要求未達が残ります。' if selected else '照合候補は未固定です。'
        return f'<p>{text}<strong>現在APIはまだ取得していません。</strong>次の反復で目的適合を見直しています。現在照合を行う際は対象とコードを固定し、各URL一回・再選択なしで評価します。</p>'
    rows = []
    suffix = {(item['手法ID'], item['銘柄']): item for item in result.get('前回未読部分の増減', [])}
    for item in result['結果']:
        assert abs(item['実現利益円'] - item['実現損失円'] - item['実現収支円']) < 0.01
        assert abs(item['実現収支円'] + item['含み損益円'] - item['合算損益円']) < 0.01
        later = suffix.get((item['手法ID'], item['銘柄']))
        rows.append([item['手法ID'], item['銘柄'], amount(item['実現利益円']), amount(item['実現損失円']),
                     money(item['実現収支円']), money(item['含み損益円']), money(item['合算損益円']),
                     f"{item['保有買い枚数']} / {item['保有売り枚数']}",
                     f"{item['利益決済枚数']} / {item['損失決済枚数']} / {item['利益決済枚数']-item['損失決済枚数']:+}",
                     money(later['17時25分以降増減円']) if later else '—'])
    body = f'<p><strong>{escape(result["セッション"])} の途中、共通締切 {escape(result["共通締切"])}。</strong>状態URL1回＋データ6URL各1回。条件固定後の同じ保存データで比較しています。</p>'
    body += '<p>17:25までは前作業で既読、以降は今回初取得です。セッション全体を未見とは呼びません。下表の17:25以降増減には、その前から持つ玉の値動きも含みます。途中で場末の架空返済を作らず、13完了セッションの合計には加えません。</p>'
    body += table('current-result', ['手法', '銘柄', '実現利益 円', '実現損失 円', '実現収支 円', '含み 円', '合算 円', '保有買/売枚', '勝/負/差 決済枚', '17:25以降増減 円'], rows)
    body += '<p>これは保存スナップショットの再生です。実際に注文を送った取引成績ではありません。' + link('current_result.json', '途中照合結果') + ' / ' + link('取得記録.json', '各URL一回の取得記録') + ' / ' + link('現在照合の凍結記録.json', '取得前の候補とコード固定') + '</p>'
    return body


def main() -> None:
    """機能: 保存済み段階に合わせ報告・資料案内・数値検査を更新する。

    引数: なし。返り値: なし (None)。API取得・売買計算・他作業の上書きは行わない。
    """
    OUT.mkdir(exist_ok=True)
    helpers.TABLES.clear()
    fixed = read(HERE / '探索条件の固定.json')
    gate = read(HERE / '反証前の候補固定.json')
    first = read(HERE / '一次反証の結果.json', [])
    passed = [item for item in first if not item['first_stage_failures']]
    random_results = read(HERE / '無関係対照の要約.json', [])
    episode = read(HERE / 'episode_audit.json')
    attribution = read(HERE / 'basis_attribution.json')
    selected = read(HERE / '現在照合候補の固定.json')
    current = read(HERE / 'live' / 'current_result.json')
    count = len(fixed['signals']) * len(fixed['managers'])
    assert count == 19776
    chosen = []
    if selected:
        chosen = selected['候補']
    else:
        families = set()
        for item in passed:
            candidate = item['candidate']
            if candidate['signal_family'] in families:
                continue
            families.add(candidate['signal_family'])
            chosen.append({'id': candidate['id'], 'signal': next(s for s in fixed['signals'] if s['id'] == candidate['signal_id']),
                           'manager': next(m for m in fixed['managers'] if m['id'] == candidate['manager_id']),
                           '用途': '一次通過の代表。現在照合候補はまだ未固定。'})
            if len(chosen) == 2:
                break
        if episode:
            chosen += episode['手法'][:3]
    method_data = {item['id']: baseline(item['id']) for item in chosen}
    wave_summary = {item['method']: item for item in episode['方法別要約']} if episode else {}
    latest = [item for item in chosen if item['id'].startswith('E')]
    diagnostic_ready = bool(latest) and all(item['id'] in wave_summary for item in latest)
    wave_complete = diagnostic_ready and all(wave_summary[item['id']]['目安達成区間数'] == 8 for item in latest)
    title = '新候補も、指定波の一部を<br>全く保有できていない。' if diagnostic_ready and not wave_complete else '収益性の候補と、<br>指定された波への適合は別。'
    body = '<p class="eyebrow">作業00021 · 第2反復 · 保存済み13セッション・7開始日</p><h1>' + title + '</h1>'
    if diagnostic_ready and not wave_complete:
        counts = '、'.join(f"{item['id']} は{wave_summary[item['id']]['目安達成区間数']}/8" for item in latest)
        body += f'<p class="lead"><strong>{escape(counts)}区間で20分目安。</strong><br>双方とも9/21後半のNKロング・9/22午前の両銘柄ショートは正方向保有0分。期間では黒字でも、要求に適う手法としては未採用です。</p>'
    else:
        body += '<p class="lead"><strong>D016は指定4波×2銘柄の全8区間で正方向保有0分でした。</strong><br>期間黒字だけで要求を満たしたとは言えません。追加19,776条件を、収益と波の捕捉の両面から見直します。</p>'
    body += f'<p class="stages">第1反復36,668 ＋ 第2反復19,776 ＝ 計56,444条件<br>今回：最低基準 {gate["最低基準通過数"] if gate else "集計中"} → 一次反証 {len(first)} → 通過 {len(passed)} → 乱数対照 {len(random_results)}/10 完了</p>'
    if selected:
        primary = selected['主候補'] or 'なし'
        body += f'<p>数値基準内の研究候補首位：<strong>{escape(primary)}</strong>。これは目的適合の採用決定ではありません。</p>'
    overview = []
    for item in chosen:
        identifier = item['id']
        top, nk = (method_data[identifier]['symbols'][symbol] for symbol in SYMBOLS)
        wave = wave_summary.get(identifier)
        wave_cell = f"{wave['目安達成区間数']}/8（正方向0: {len(wave['正方向保有0区間'])}）" if wave else '照合待ち'
        overview.append([identifier, money(top['net_yen']), ratio(top['money_ratio']), money(nk['net_yen']), ratio(nk['money_ratio']), wave_cell])
    body += table('overview', ['比較対象', 'TOPIX収支 円', 'PF', 'NK収支 円', 'PF', '指定波20分目安'], overview)
    if diagnostic_ready:
        text = '新候補は8区間の説明用目安を満たしましたが、それだけで未知相場の安定性は証明できません。' if wave_complete else '新候補にも指定波の未達が残っています。収益性のふるいを通過しても、当初の要求を満たす解を発見したとは宣言しません。'
    else:
        text = '新候補の指定波診断は完了待ちです。完了するまで要求に適う主候補とは扱いません。'
    body += '<div class="notice">' + text + '</div>'
    body += '<p class="muted">同じ既知期間の再探索。費用0・指定価格約定・全玉場内返済。TOPIXミニ片方向10枚／NKマイクロ20枚以内。円額は銘柄間で合算せず比較。20分は説明用目安で、連続20分・統計的有意性の条件ではありません。</p>'
    body += '<nav><a href="#waves">指定波</a><a href="#methods">手法別損益</a><a href="#sensitivity">弱点とパラメータ</a><a href="#current">現在途中の照合</a></nav>'

    # ----------------------------------------
    # 目的適合を期間合計から分離し、未捕捉を明示する。
    body += '<h2 id="waves">指定された波で、何が起きたか</h2>'
    if episode:
        newly_checked = [item for item in episode['方法別要約'] if item['method'].startswith('E')]
        if newly_checked:
            body += f'<p>一次通過{len(newly_checked)}候補を同じ波区間で診断し、最多でも{max(item["目安達成区間数"] for item in newly_checked)}/8区間。全8区間の説明用目安を満たした手法は{sum(item["目安達成区間数"] == 8 for item in newly_checked)}件でした。元D016は8区間すべてで正方向保有0分です。</p>'
    body += details('4波の区間・正逆の保有時間・時価損益差', episode_body(episode)) if episode else '<p>指定波の診断は未完成です。</p>'
    body += '<p>前回の黒字D016は短い価格反転の発火を絞る設計で、指定した中長時間の波を拾うこととは一致しませんでした。今回の多窓合意も、条件を厳しくするほど発火を減らし、波の途中で入れなくなる可能性があります。利益だけでこの取り逃しを隠しません。</p>'
    if attribution:
        basis_rows = []
        for part in attribution['結果']:
            total = part['全体']
            basis = total['主採用元件数']
            basis_rows.append([part['id'], total['初回主玉新規件数'], basis['F32'], basis['D016'], basis['D056'], basis['P02'],
                               '一致' if part['全期間F32単独と方向一致'] else '相違あり'])
        basis_body = '<p>E037の初回新規94件中92件はF32、2件はD016が主採用元。E015は60件中55件がF32、残り5件が価格と板の合意です。切替方式を作っても、入口の大部分は最良板の数量偏りに基づくF32でした。</p>'
        basis_body += table('basis-attribution', ['候補', '初回新規', 'F32採用', 'D016採用', 'D056採用', 'P02採用', '同設定F32単独との方向'], basis_rows)
        basis_body += '<p>注文を決めた元行で集計しています。P02と板の合意は両方へ1件ずつ数えるため合計が初回件数を超える場合があります。採用件数は損益への因果寄与ではありません。他基礎が反対時の抑止も働き、2候補はF32単独と完全一致ではありません。比較用F32単独は同じ窓・合意率・確認秒で、旧F32_G08とは異なります。</p>'
        basis_body += '<p>' + link('basis_attribution.md', '採用元の診断') + ' / ' + link('basis_attribution.json', '全発注起源と方向差分') + '</p>'
        body += details('新候補の入口の大半はF32 — 合成方式の採用元を確認', basis_body)
    body += '<div class="notice">次の仮説：中期の価格方向を主にし、板は入る時刻の調整へ使う。第3反復を準備しています。今回の未捕捉を踏まえた仮説で、解決済みとは扱いません。</div>'

    body += '<h2 id="methods">手法の説明と、期間・各セッションの損益</h2>'
    body += '<p>勝ち/負け枚数は返済した枚数。同値決済も別記し、枚数差は勝ち−負けで保有残ではありません。PF＝総利益÷総損失。1枚平均勝ち/負け＝（利益÷勝ち枚数）÷（損失÷負け枚数）。9/28開始週は3セッションの途中週です。</p>'
    body += '<p class="muted">TOPIXミニ1pt=1,000円、NKマイクロ1pt=10円。NKは原本ラージの10pt格子での換算です。最大DDは含み込み資産の最大減少額。最大保有枚数が異なる条件を、円額だけで順位付けしません。</p>'
    for item in chosen:
        identifier = item['id']
        description = item['signal']['description'] + ' 注文管理：' + item['manager'].get('description', item['manager']['name'])
        if identifier == 'D016__D065':
            description = 'OFIで発火時機を絞り、両市場の30秒価格方向へ入る。実在主体の吸収を識別したものではない。1ATR損切り、3ATR追跡と最高利益25%保護。'
        if identifier == 'P02__D065':
            description = '両市場の60秒価格方向から30秒方向への反転を拾う価格対照。板数量は使わず、注文管理はD016と同じ。観測時刻は板原本に依存する。'
        status = item.get('用途', '前回からの固定比較。今回の新候補とは別。')
        if identifier.startswith('E'):
            params = item['signal']['params']
            status += f" 窓倍率 {params['window_multipliers']}、必要一致率 {params['required_fraction']:.0%}、連続確認 {params['confirmation_seconds']}秒。"
        body += helpers.method_section(identifier, description, status, method_data[identifier])

    # ----------------------------------------
    # 反証カテゴリと小区分を分け、変更していない値を頑健性の証拠にしない。
    body += '<h2 id="sensitivity">時計・入口・出口を分けた反証</h2>'
    body += '<p>時計4条件は少なくとも3条件で両銘柄黒字・PF1.20以上を要求。時計・連続確認・入口・出口の各カテゴリで、各銘柄の収支中央値が基準の半分以上、最悪が基準収支の−25%以上かを別々に判定しました。前回のように時計の弱さを他の変数と混ぜません。</p>'
    body += '<p>1/5/15秒遅延と観測価格約定は全条件で両銘柄黒字・PF1.20以上が必要。観測価格約定は、費用0・指定価格約定の主結果とは別の追加検査です。</p>'
    for item in latest:
        path = HERE / 'adversarial' / f"{item['id']}.json.gz"
        data = read(path)
        if data:
            body += details(item['id'] + ' の全パラメータ感度', sensitivity_body(item['id'], data))
    pass_rows = []
    for item in passed:
        candidate = item['candidate']
        top, nk = (candidate['symbols'][symbol] for symbol in SYMBOLS)
        pass_rows.append([candidate['id'], money(top['net_yen']), ratio(top['money_ratio']), f"{top['max_long']}/{top['max_short']}",
                          money(nk['net_yen']), ratio(nk['money_ratio']), f"{nk['max_long']}/{nk['max_short']}"])
    failures = Counter(reason for item in first for reason in item['first_stage_failures'])
    pass_body = '<p>一次反証通過は収益耐性の判定で、指定波への適合・現在収益・実運用の保証を含みません。</p>'
    pass_body += table('passed', ['候補', 'TOPIX収支 円', 'PF', '最大買/売枚', 'NK収支 円', 'PF', '最大買/売枚'], pass_rows)
    pass_body += details('不合格理由の内訳（同一候補の重複あり）', table('failure-reasons', ['理由', '該当候補数'], [[key, value] for key, value in failures.most_common()]))
    body += details(f'一次反証{len(first)}候補・通過{len(passed)}候補の一覧', pass_body)

    random_body = '<p>10対象について64乱数×2方式を実行。全時間の30分コイントスと、元信号の発火時刻だけに乱数方向を入れる対照です。後者はタイミング情報を残します。同じ既知価格経路を使うため、正式な有意確率にはしません。</p>'
    random_rows = []
    for item in random_results:
        for part in item['summary']:
            top, nk = (part['symbols'][symbol] for symbol in SYMBOLS)
            random_rows.append([item['candidate']['id'], '発火時刻限定' if part['発火時刻限定'] else '30分コイントス',
                                money(top['収支0_5_50_95_100百分位'][2]), money(nk['収支0_5_50_95_100百分位'][2]),
                                f"{part['両銘柄で候補以上の収支seed数']}/64",
                                f"{top['候補以上のPF_seed数']}/64", f"{nk['候補以上のPF_seed数']}/64"])
    if random_rows:
        random_body += table('random-controls', ['候補', '対照', 'TOPIX中央値 円', 'NK中央値 円', '両収支以上', 'TOPIX PF以上', 'NK PF以上'], random_rows)
    else:
        random_body += '<p>要約はまだ保存されていません。途中のseedから採用を選びません。</p>'
    random_body += '<p>照合候補の事前規則は、2方式とも両銘柄収支以上が3/64以下、各銘柄PF以上が6/64以下。通過後も元の探索順位を維持し、異なる信号思想を最大2件選びます。これは実用的なふるいで、5%や10%の統計検定ではありません。</p>'
    if selected:
        random_body += f'<p>この規則への適格数 {len(selected["適格候補"])}、対照不合格 {len(selected["対照不合格"])}。選択後は現在収益で再選択しません。</p>'
    body += details(f'無関係な方向との対照 — {len(random_results)}/10対象の要約保存済み', random_body)

    # ----------------------------------------
    # 現在セッションは保存完了時だけ掲載し、過去13区間へ混ぜない。
    body += '<h2 id="current">現在セッションの一回照合</h2>' + current_body(current, selected)
    body += '<h2>検算と再現資料</h2>'
    evidence = '<p>価格・板・相手市場を過去方向へ参照し、条件生成時点以降のデータを切断・変更する監査を実施。CurrentPriceTimeは直近約定の時刻で、受信時刻ではありません。原本順の因果性と二市場の実到着順の完全再現は区別します。</p>'
    evidence += '<p>注文は判断より後の原本行で執行し、全玉合算・枚数上限・会計・場末返済を再生時に検算。現在途中だけは未返済を含みとして残します。大量探索後の既知期間内の結果で、未知相場の安定性は未確認です。</p>'
    evidence += '<p>' + ' / '.join(link(name) for name in ['ensemble_signal_audit.json', '反証インターフェース検算.json', '反証合成検算.json', 'ensemble_design.md', 'validation_round2.md']) + '</p>'
    body += details('因果性・会計・実装検査と限界', evidence)
    body += '<p>' + ' / '.join(link(name) for name in ['README.md', '全条件の期間集計.json.gz', '一次反証の結果.json', '表示データ.json', '報告検査.json']) + '</p>'
    body += '<p class="muted">今回の成果は、利益の残る条件と、その用途・未達・弱点を分けて記録したことです。あらゆる相場で安定する解を発見したとは結論していません。</p>'
    body += '<footer>' + link('../00020_大量探索と反証の反復/発見と反証.html', '第1反復の反証') + ' · ' + link('../index.html', '全調査') + '</footer>'
    css = ':root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b111c;color:#e4eaf3;font:15px/1.7 system-ui,"Yu Gothic",sans-serif}main{max-width:1240px;margin:auto;padding:24px 28px 60px}h1{font-size:31px;line-height:1.35;margin:8px 0 16px}h2{font-size:23px;margin:30px 0 10px}h3{font-size:17px}.eyebrow,.muted{font-size:13px;color:#a6b5cc}.lead{font-size:17px}.stages{color:#76d7cc;font-weight:650}.notice{background:#2a251d;border-left:4px solid #e6bd75;padding:10px 14px}.scroll{overflow:auto;margin:12px 0}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:13px;font-variant-numeric:tabular-nums}th,td{padding:8px 11px;border-bottom:1px solid #2b3c51;text-align:right}th{background:#1b2a3e;color:#cfdded}th:first-child,td:first-child{text-align:left}tbody tr:nth-child(even){background:#111c2b}details{border:1px solid #2e4057;background:#111b2a;border-radius:7px;margin:10px 0}summary{padding:13px 16px;cursor:pointer;font-weight:650}summary:hover{background:#1a2a3f}.inside{padding:0 17px 17px}p{margin:10px 0}a{color:#8ec6ff;text-decoration:none}a:hover{text-decoration:underline}nav{display:flex;flex-wrap:wrap;gap:20px;margin:18px 0}footer{border-top:1px solid #2e4057;padding-top:18px;margin-top:25px}@media(max-width:700px){main{padding:18px 14px}h1{font-size:26px}.lead{font-size:16px}}'
    component = '<!--\n[コンポーネント概要]\nmainは結論と保存済み結果、detailsは手法別損益とパラメータ診断、.scrollは横長表を表示します。\n外部通信を行わない静的なダークテーマ報告です。\n-->'
    html = '<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>00021 再探索と反証</title><style>' + css + '</style></head><body>' + component + '<main>' + body + '</main></body></html>'
    (OUT / '再探索と反証.html').write_text(html, encoding='utf-8')
    sources = ['ensemble_design.md', 'ensemble_design_fixed.json', '探索条件の固定.json', '反証前の候補固定.json',
               '反証規則の固定.json', '反証実装の固定.json', 'validation_round2.md', '一次反証の結果.json',
               '全条件の期間集計.json.gz', '無関係対照の要約.json', '現在照合選抜の事前規則.json', '現在照合候補の固定.json',
               'episode_audit.md', 'episode_audit.json', 'episode_audit_fixed.json', 'basis_attribution.md', 'basis_attribution.json', 'ensemble_signal_audit.json',
               '反証インターフェース検算.json', '反証合成検算.json', 'current_offline_check.json']
    copied = []
    for name in sources:
        if (HERE / name).exists():
            shutil.copy2(HERE / name, OUT / name)
            copied.append(name)
    if current:
        for name in ['current_result.json', '取得記録.json', '現在照合の凍結記録.json']:
            shutil.copy2(HERE / 'live' / name, OUT / name)
            copied.append(name)
    save(OUT / '表示データ.json', {'代表手法': method_data, '表示表': helpers.TABLES,
                                '状態': {'一次反証': len(first), '一次通過': len(passed), '乱数対象完了': len(random_results),
                                         '現在結果保存済み': bool(current), '新候補波診断済み': diagnostic_ready}})
    readme = '''# 00021 時間窓への依存を減らす再探索

最初に [再探索と反証.html](再探索と反証.html) を開いてください。冒頭に結論と指定波の未達、詳細は折り畳みにまとめています。

## 読む順序

1. [再探索と反証.html](再探索と反証.html)：主結論、代表手法の全期間・開始週・各セッション損益、現在途中の照合状況。
2. [指定4波の診断](episode_audit.md)と[採用元の診断](basis_attribution.md)：期間黒字と目的適合を分け、入口の大半がF32であることも確認。
3. [設計](ensemble_design.md)・[反証基準](validation_round2.md)：時計、確認、入口、出口を別々に検査。
4. [一次反証](一次反証の結果.json)・[全19,776条件の期間集計](全条件の期間集計.json.gz)・[表示値](表示データ.json)・[報告検査](報告検査.json)。

13セッション・7開始日はすべて既知です。第1反復36,668条件と今回19,776条件を合わせ56,444条件。収益性の基準通過と、ユーザー指定波の検知は別に記載します。D016は指定4波×2銘柄の全8区間で正方向ネット保有0分。新候補E037__D055・E015__D025は各5/8区間の目安を達成したものの、9/21後半NKロング・9/22午前の両銘柄ショートは正方向保有0分でした。全17一次通過候補でも最大6/8。20分の目安は事後の説明用で、統計的有意性を意味しません。

E037は初回新規94件中92件、E015は60件中55件でF32が主採用元でした。F32単独との完全一致ではなく、採用件数は損益への因果寄与でもありません。要求した波の捕捉に未達が残るため未採用。次の反復で「中期方向を主・板を入口時刻」にする仮説を準備しています。現在APIは未取得です（結果が保存された場合はHTMLに途中照合を表示します）。

費用0、指定価格約定、完了セッションでは全玉場内返済。途中照合では未返済を含みとして別表示し、完了期間合計へ足しません。勝ち−負け枚数は決済枚数差で、保有残ではありません。同値決済も表示します。TOPIXミニ1pt=1,000円、NKマイクロ1pt=10円。NKはラージ原本の10pt格子を保った換算です。

## 再現コード

- [方向の合意・切替](../../work/wave_v26/ensemble_signals.py)、[探索](../../work/wave_v26/ensemble_runner.py)、[反証](../../work/wave_v26/validation_round2.py)。
- [指定波診断](../../work/wave_v26/episode_audit.py)、[現在候補選択](../../work/wave_v26/select_current.py)、[一回取得・保存再生](../../work/wave_v26/current_validation.py)。
- [報告生成](../../work/wave_v26/report_round2.py)、[表示・合算検算の共通処理](../../work/wave_v25/report_round.py)。
- [全セッション成績](../../work/wave_v26/sessions/)、[各反証の詳細](../../work/wave_v26/adversarial/)、[全乱数試行](../../work/wave_v26/randomized/)。

報告のみの再生成：プロジェクトルートで `python work/wave_v26/report_round2.py`。保存済み段階を読み、通信・売買計算はしません。現在APIを再取得するコマンドではありません。新結果の保存後に再生成すると、選択候補・波診断・途中損益の最新の保存状態を反映します。
'''
    if current:
        readme = readme.replace('現在APIは未取得です（結果が保存された場合はHTMLに途中照合を表示します）。',
                                f'現在照合は共通締切 {current["共通締切"]} の途中結果を保存済み。HTMLに実現・含み・保有を分けて掲載し、13完了セッションには加えていません。')
    (OUT / 'README.md').write_text(readme, encoding='utf-8')
    parser = helpers.ReportParser()
    parser.feed(html)
    assert not parser.stack
    for table_id, expected in helpers.TABLES.items():
        assert parser.tables[table_id] == [expected['headers']] + expected['rows'], table_id
    for href in parser.links:
        parts = urlsplit(href)
        if parts.scheme:
            continue
        if parts.path:
            target = (OUT / unquote(parts.path)).resolve()
            if target.name != '報告検査.json':
                assert target.exists(), target
        else:
            assert parts.fragment in parser.ids
    for href in re.findall(r'\]\(([^)]+)\)', readme):
        target = (OUT / href).resolve()
        if target.name != '報告検査.json':
            assert target.exists(), target
    for name in copied:
        source = HERE / name if (HERE / name).exists() else HERE / 'live' / name
        assert source.read_bytes() == (OUT / name).read_bytes()
    save(OUT / '報告検査.json', {'生成時刻': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                                '報告コードSHA256': sha256(Path(__file__).read_bytes()).hexdigest(),
                                '表示共通コードSHA256': sha256((PREVIOUS / 'report_round.py').read_bytes()).hexdigest(),
                                '表数': len(helpers.TABLES), '表データ行数': sum(len(value['rows']) for value in helpers.TABLES.values()),
                                'リンク件数': len(parser.links), 'タグとID一致': True, '表表示一致': True,
                                '代表セッション合算検査': len(chosen) * 26, '原資料コピー一致': len(copied),
                                '報告生成によるAPI取得': 0, '現在結果掲載': bool(current), '新候補波診断掲載': diagnostic_ready})
    update_index()
    print(json.dumps({'報告': str(OUT / '再探索と反証.html'), '表数': len(helpers.TABLES), 'リンク': len(parser.links),
                      '代表': [item['id'] for item in chosen], '乱数完了': len(random_results), '現在結果': bool(current)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
