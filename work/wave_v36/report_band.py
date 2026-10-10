"""気配維持代理の比較を、短い結論と全セッション損益に分けて出力する。"""

from __future__ import annotations

import argparse
from html import escape
import sys

import band_runner as runner
import band_assessment as assessment

sys.path.insert(0, str(runner.HERE.parent / 'wave_v35'))
import report_conditional as previous

HERE, ROOT = runner.HERE, runner.ROOT
TITLE = '出来高通過と気配維持からの方向判定'
OUT = ROOT / 'アルゴリズム調査' / ('00031_' + TITLE)
style = previous.style
LABELS = {'Q034': '気配維持と出来高', 'Q007': '価格だけ', 'Q016': '価格と全出来高', 'H019': '旧中期方向'}


def description(spec: dict) -> str:
    """機能: 固定条件を簡潔な日本語に変換する。

    引数: spec (dict)。返り値: 説明 (str)。
    """
    if spec['signal_id'] == 'H019':
        text = '公開済み1分足EMA15/60の方向、60秒遅れの他銘柄、直近30秒の気配変化の一致を使う。'
    else:
        p = spec['signal']['params']
        info = {'price': '価格だけ', 'all_volume': '価格帯で観測した全出来高', 'stable_volume': '価格と両側気配・数量が動かない間に増えた出来高'}[p['proxy']]
        branch = {'reversal': '最初の反応が反転の場合だけ', 'breakout': '最初の反応が突破の場合だけ', 'automatic': '反転・突破の先に確定した方向へ'}[p['branch']]
        peer = {'none': '他銘柄の確認なし', 'veto': '他銘柄の逆方向を拒否', 'confirm': '他銘柄の同方向を要求'}[p['peer_mode']]
        score = '' if p['proxy'] == 'price' else f'。同価格帯の出来高÷その観測時の最良気配数量の合計が{p["volume_threshold"]:g}以上'
        text = f'{p["window_seconds"] * spec["clock_scale"]:g}秒の進行と終盤の停滞から準備。{info}{score}。{branch}注文を準備。{peer}。'
    text += '初回TOPIX5枚／NK10枚、初期1ATR損失予算・2ATRで半分利確・1.5ATR順行後3ATR追跡、最長360分・場内全返済。'
    if spec.get('observed_fill'):
        text += 'この診断だけ観測価格で約定。'
    if 'random_seed' in spec:
        text += '元方向へ30分ブロック共通の乱数符号を掛ける補助対照。'
    if spec.get('reverse_direction'):
        text += '元の方向を全て反転する補助対照。'
    return text


def money_tables(rows: list[dict], identifier: str, names: list[str]) -> str:
    """機能: 全期間・各週・各セッションの金額と返済枚数を両銘柄別に表示する。

    引数: rows (list[dict])、identifier (str)、names (list[str])。返り値: 表 (str)。
    """
    body = []
    for symbol in runner.SYMBOLS:
        part = sorted((r for r in rows if r['symbol'] == symbol), key=lambda r: r['session'])
        assert len(part) == 13
        output = [style.money_row('全13', style.totals(part)),
            style.money_row('共通後半7', style.totals([r for r in part if r['session'] in names[6:]])),
            style.money_row('9/21開始週', style.totals([r for r in part if r['session'] < '2026-09-28'])),
            style.money_row('9/28開始週・途中', style.totals([r for r in part if r['session'] >= '2026-09-28']))]
        output += [style.money_row(r['session'], r) for r in part]
        body.append('<h3>' + symbol + '</h3>' + style.table(
            ['区間', '利益 円', '損失 円', '収支 円', '利益枚数', '損失枚数', '同値枚数', '勝ち−負け枚数'],
            output, f'data-id="{identifier}" data-symbol="{symbol}"'))
    return ''.join(body)


def all_results(items: list[dict], names: list[str], preview: bool) -> None:
    """機能: 主364と補助65を区別して全損益を保存する。

    引数: items (list[dict])、names (list[str])、preview (bool)。返り値: なし (None)。
    """
    body = [f'<p><a href="{TITLE}.html">比較へ</a></p><h1>全条件の損益</h1>',
        '<p>円額と延べ返済枚数。勝ち−負け枚数は数量差で、損益額ではありません。保有上限と期間の累計枚数は別です。</p>',
        '<div class="filters"><label>手法<select id="signal-filter">' + ''.join(
            f'<option value="{identifier}"' + (' selected' if identifier == 'Q034' else '') + '>' + identifier + '</option>'
            for identifier in sorted({r['spec']['signal_id'] for r in items})) + '</select></label>',
        '<label>区分<select id="role-filter"><option value="primary" selected>基本91</option><option value="diagnostic">感度・約定273</option><option value="supplementary">方向対照65</option><option value="">全て</option></select></label><span id="visible-count"></span></div>']
    for item in items:
        spec, identifier = item['spec'], item['id']
        supplementary = spec.get('supplementary', False)
        role = 'supplementary' if supplementary else 'primary' if spec['primary'] else 'diagnostic'
        opened = ' open' if role == 'primary' else ''
        rows = runner.read(HERE / ('supplementary' if supplementary else '') / 'sessions' / (identifier + '.json.gz'))
        body += [f'<details class="method" data-signal="{spec["signal_id"]}" data-role="{role}" id="{identifier}"{opened}><summary>{identifier}</summary>',
            '<p>' + escape(description(spec)) + '</p>', money_tables(rows, identifier, names), '</details>']
    if preview:
        body.insert(1, '<p><strong>独立監査中の暫定表示。</strong></p>')
    script = '''/**
 * 固定手法と診断区分に従い表示だけを切り替える。
 * @param {Event|undefined} event - 選択操作。
 * @returns {undefined} 返り値なし。売買条件は変更しない。
 */
function filter(event){let n=0;document.querySelectorAll('.method').forEach(e=>{e.hidden=['signal','role'].some(k=>{const v=document.getElementById(k+'-filter').value;return v&&v!==e.dataset[k]});if(!e.hidden)n++});document.getElementById('visible-count').textContent=n+'条件を表示'}document.querySelectorAll('select').forEach(e=>e.addEventListener('change',filter));filter();'''
    (OUT / '全条件損益.html').write_text(style.page('全条件の損益', body, script), encoding='utf-8')


def main() -> None:
    """機能: 主仮説と対応対照を比較し、全保存成績への導線を作る。

    引数: --preview (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--preview', action='store_true')
    preview = parser.parse_args().preview
    if not preview:
        proof = runner.read(HERE / '完備監査.json')
        assert proof['検証完了'] and proof['全条件数'] == 364 and proof['補助条件数'] == 65
        for name, value in proof['参照資料SHA256'].items():
            assert runner.digest(ROOT / name) == value
    items = runner.read(HERE / '全条件の期間集計.json.gz')
    extras = runner.read(HERE / 'supplementary/全条件の期間集計.json.gz')
    index = {r['id']: r for r in items}
    verdict = runner.read(HERE / ('暫定判定.json' if preview else '独立判定.json'))
    diagnosis = runner.read(HERE / '全格子の機序診断.json')
    names = runner.read(HERE / '探索条件の固定.json')['全セッション']
    rows = [(LABELS[signal], index[signal + '__V000']) for signal in LABELS]
    outcome = '既知比較の採用基準を通過。将来成績は未確認。' if verdict['既知比較の採用候補'] else '今回の気配維持代理は採用基準を通過しませんでした。'
    body = ['<p><a href="../index.html">作業一覧</a></p><h1>' + TITLE + '</h1><p class="lead"><strong>' + outcome + '</strong></p>',
        '<p>主仮説Q034を結果前に固定。90種類の新方向判定と旧方式を同じ返済ルールで比較しました。</p>',
        '<p>Q034は両銘柄で黒字、最大の勝ちを除いても黒字でした。方向を乱した64対照の中央値も上回りました。ただし窓を0.8倍にするとNKは赤字、1.2倍では大勝ちへの依存が残り、指定波は1/8でした。安定した汎用方式としての採用には至りません。</p>',
        '<p><a class="button" href="全条件損益.html">週・セッション別の金額／枚数</a><a class="button" href="５分足と売買.html">５分足と売買</a></p>',
        '<h2>全13セッション</h2>', previous.main_table(rows, 'all_symbols'),
        '<p class="muted">TOPIXミニ5枚／NKマイクロ10枚。片方向上限10／20枚、費用0、指定価格約定、場内全返済。最大下落は含み損益込み。1枚平均比は利益額÷勝ち枚数と損失額÷負け枚数の比。</p>',
        '<details><summary>後半7セッション</summary>', previous.main_table(rows, 'symbols'), '</details>',
        '<details><summary>どのような手法か</summary><p>価格が進んでから停滞した帯を見つけます。その帯で、出来高が増えても最終価格・両側の最良気配と数量が変わらない観測を集計。反転か突破を価格で確認し、先に起きた方向へ進みます。他銘柄が逆向きなら見送ります。</p>',
        '<p>Q034は120秒の進行・直近30秒の停滞、出来高÷気配数量の合計2以上。公開済み情報だけで判定し、価格帯の条件は準備時に固定します。気配の維持は隠れ注文・補充そのものの証明ではありません。</p>',
        '<p>' + escape(description(index['Q034__V000']['spec'])) + '</p><p>方向が出た後、さらに0.25ATRの新規トレーリングを使います。ATRは新規準備時に固定し、最長360分・返済後5分休止。詳細は<a href="../../work/wave_v36/band_signal_contract.md">実装仕様</a>。</p></details>',
        '<details><summary>追加情報に価値があったか</summary>', style.table(['対照', '収支と最大下落の比較'],
            [[name, row['関係']] for name, row in verdict['対応比較'].items()]),
        '<p>全13・後7の両銘柄で、収支を減らさず最大下落を増やさないことを要求しました。母集団を揃えて価格・全出来高と比較。フィルター後の新規数と保有時間は変わるため、同じ取引の比較ではありません。</p></details>',
        '<details><summary>他の条件に有望なものはあったか</summary><p>新90条件で全13・後7の両銘柄の基礎条件を通ったのは' +
        escape('、'.join(diagnosis['基礎全通過IDs']) or 'なし') + '。時間窓の両側まで通ったのは' +
        str(len(diagnosis['基礎と窓全通過IDs'])) + '/90でした。Q028は反転だけを使う同系統です。</p><p>気配維持を追加した36組のうち、価格だけに収支と下落を同時改善したのは' +
        str(diagnosis['関係集計']['price']['同時改善']) + '/36、全出来高に対しては' +
        str(diagnosis['関係集計']['all_volume']['同時改善']) + '/36。4セル全てで両指標が非悪化、少なくとも1指標が改善という意味です。情報追加に効果の兆しはありますが、安定性の検査は別です。</p><p>これらは全格子の結果後の記述で、別IDへの採用差替ではありません。基本91の異なる返済台帳は' +
        str(diagnosis['基本91の異なる台帳数']) + '、診断込み364では' + str(diagnosis['異なる台帳数']) + '。反復条件を独立した証拠の数にしません。</p></details>',
        '<details><summary>敵対的な確認</summary>', style.table(['確認', '結果'], [
            ['利益/損失・1枚平均比・活動・最大勝ち除外', '通過' if all(r['合格'] for p in verdict['基礎'].values() for r in p.values()) else '未通過'],
            ['時間窓0.8倍/1.2倍', '通過' if all(r['合格'] for p in verdict['窓感度'].values() for r in p.values()) else '未通過'],
            ['純価格・全出来高に対する追加価値', '通過' if verdict['代理の追加価値基準'] else '未通過'],
            ['指定4波×両銘柄', str(verdict['指定波']) + '/8'],
            ['64方向対照・全反転', '通過' if verdict['方向対照']['合格'] else '未通過'],
            ['独立検算', '完了' if verdict['監査完了'] else '処理中']]),
        '<p>方向対照は元方向へ30分ブロック共通の±1を掛けます。活動時刻・ブロック内の方向変化・両市場の相対関係を保ち、売買は再生し直します。正式なp値ではありません。</p>',
        '<p>時間窓を変えた時、後7のNKでは同じ原本行での入口は8組中2組しか残りませんでした（0.8倍）。疎な信号に加え、価格準備の区間自体が入れ替わっています。<a href="../../work/wave_v36/時間窓感度の内訳.md">窓感度の分解</a>。</p>',
        '<p>全13は既知で、後半7も未知データではありません。主91＋感度273＝364、別集計の方向対照65。現在API・保存ライブは使用していません。</p></details>',
        '<p><a href="README.md">資料案内と再現手順</a></p>']
    if preview:
        body.insert(1, '<p><strong>独立監査中の暫定表示。採否は確定前。</strong></p>')
    OUT.mkdir(exist_ok=True)
    (OUT / (TITLE + '.html')).write_text(style.page(TITLE, body), encoding='utf-8')
    all_results(items + extras, names, preview)
    print('主比較と全429条件の週・セッション損益を出力。', flush=True)


if __name__ == '__main__':
    main()
