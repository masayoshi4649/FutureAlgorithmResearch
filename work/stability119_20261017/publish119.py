"""保存済みの各段階を混ぜず、短い結論と全場損益への入口を公開する。"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = '00119_戦略の自動選択と場内黒字の再探索'
PUBLIC = ROOT / 'アルゴリズム調査' / NAME
MAIN = '結論と全セッション損益.html'


def esc(value) -> str:
    """
    機能: 保存されたIDと説明を安全にHTMLへ写す。
    引数: value(任意型) は表示する値。
    返り値: str はエスケープ済み文字列。
    """
    return html.escape(str(value))


def money(value) -> str:
    """
    機能: 金額を比較しやすい円表記へ変換する。
    引数: value(float|int|None) は円額。
    返り値: str。未測定をゼロへ置換しない。
    """
    if value is None:
        return '未測定'
    return f'{value:+,.0f}' if value else '0'


def main(path: Path) -> None:
    """
    機能: 完成SHAの生成物を段階別へ保存し、結論・案内・出典を一つに結ぶ。
    引数: path(Path) は根が確認した公開目録JSON。
    返り値: None。新しい市場読取・金融再生を行わない。
    """
    manifest = json.loads(path.read_text(encoding='utf-8'))
    assert manifest['root_checked'] is True and 4 <= len(manifest['phases']) <= 9
    assert not PUBLIC.exists(), '公開済み資料を無断で置換しません'
    PUBLIC.mkdir()
    phase_links = []
    for phase in manifest['phases']:
        source = ROOT / phase['source']
        target = PUBLIC / phase['directory']
        assert target.resolve().is_relative_to(PUBLIC.resolve())
        target.mkdir()
        for item in phase['files']:
            payload = (source / item['name']).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == item['sha256']
            (target / item['name']).write_bytes(payload)
        assert (target / phase['report']).is_file()
        title = phase['title']
        (target / 'README.md').write_text(f'# {title}\n\n最初に[{title}]({phase["report"]})を開いてください。\n\n{phase["description"]}\n\n各場の利益・損失は完結親の費用後損益です。無取引を黒字に数えず、未返済は別記します。元結果は `{phase["result"]}`。この案内の作成による金融再生はありません。\n', encoding='utf-8')
        phase_links.append(f'<li><a href="{esc(phase["directory"])}/{esc(phase["report"])}">{esc(title)}</a>：{esc(phase["description"])}</li>')
    # ----------------------------------------
    # 最新段階の小会計から表示だけを作り、過去の失敗段階を勝者へ差し替えない。
    last = next((phase for phase in manifest['phases'] if phase['directory'] == manifest.get('overview_directory')), manifest['phases'][-1])
    view = json.loads((PUBLIC / last['directory'] / 'data.json').read_text(encoding='utf-8'))
    dual = None
    if manifest.get('dual'):
        reference = manifest['dual']
        payload = (ROOT / reference['path']).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == reference['sha256']
        dual = json.loads(payload)
        assert dual['全合格'] and dual['new_financial_replay'] == 0 and len(dual['rows']) == 40
        (PUBLIC / '二口座の合算損益.json').write_bytes(payload)
    policy_id = view['main_ids'][0]
    case = view['cases'][policy_id]
    rows = []
    symbols = ('PAIR',) if 'PAIR' in case['metrics'] else ('TOPIX', 'NK225')
    for symbol in symbols:
        m = case['metrics'][symbol]
        rows.append('<tr><th>' + ('二脚合計口座' if symbol == 'PAIR' else symbol) + '</th>' + ''.join('<td>' + esc(value) + '</td>' for value in (
            money(m['net']), f"{m['black']}／{m['red']}／{m['inactive']}", money(m['mean']), money(m['median']),
            money(m['worst']), money(m['top3_removed']))) + '</tr>')
    qualified = view['qualification_count']
    if qualified and symbols == ('PAIR',):
        conclusion = '既知40場の二脚合計口座で、安定性を改善する候補が得られました。各商品単独の成功や将来の安定黒字は未確認です。'
    elif qualified:
        conclusion = '既知40場の両商品で改善候補が得られました。将来の安定黒字は未確認です。'
    else:
        conclusion = '毎セッションの安定黒字を裏付ける手法は、今回の検証でも確立できませんでした。'
    conclusion = manifest.get('conclusion', conclusion)
    rules = manifest.get('overview_rules', case.get('rules', {}))
    rules_html = ''.join('<p><b>' + esc(k) + '：</b>' + esc(v) + '</p>' for k, v in rules.items())
    page = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>今回の結論と全セッション損益</title><style>
body{background:#0b1120;color:#e5edf8;font:16px/1.7 system-ui,sans-serif;margin:0}main{max-width:1100px;margin:auto;padding:28px 22px}h1{font-size:27px}h2{font-size:21px;margin-top:28px}a{color:#91c9ff}strong{color:#ffd083}.note{padding:16px;background:#18263d;border-left:4px solid #deb555}.wrap{overflow-x:auto;border:1px solid #34445a}table{width:100%;white-space:nowrap;border-collapse:collapse;font-size:14px}td,th{padding:9px 11px;text-align:right;border-bottom:1px solid #34445a}th:first-child{text-align:left}thead{background:#1a2b44}.muted{color:#aebed3;font-size:14px}code{overflow-wrap:anywhere}li{margin:11px 0}@media(max-width:600px){main{padding:18px 12px}h1{font-size:23px}}
</style></head><body><!--
[コンポーネント概要]
mainは段階別の検証結果と、各段階の全セッション表への入口です。
.wrapは金額表のみ横スクロールできる領域です。無取引や評価だけの利益は黒字へ含めません。
リンク先は同じ作業フォルダ内の保存成果です。市場通信・売買注文・金融再計算は行いません。
--><main><h1>今回の結論と全セッション損益</h1>'''
    page += '<p class="note"><strong>' + esc(conclusion) + '</strong></p>'
    if dual:
        m = dual['metrics']['全40']
        page += '<h2>第一候補：少額E01の二口座並行運転</h2><p>TOPIXと日経の少額E01を独立に動かし、各商品で小利益に達したらその場の取引を終えます。以下は保存済み二口座の場末収支の合算で、新しい金融再生ではありません。</p>'
        page += '<div class="wrap"><table><thead><tr><th>合計円</th><th>黒字／赤字／無取引</th><th>全場平均円</th><th>中央値円</th><th>最大赤字円</th><th>上位3黒字除外円</th></tr></thead><tbody><tr>'
        page += ''.join('<td>' + esc(value) + '</td>' for value in (money(m['net']), f"{m['black']}／{m['red']}／{m['inactive']}", money(m['mean']), money(m['median']), money(m['worst']), money(m['top3_removed']))) + '</tr></tbody></table></div>'
        page += '<p>黒字場の平均は' + money(m['mean_positive']) + '円。追加7場は合計' + money(dual['metrics']['追加7']['net']) + '円です。少額・低活動の候補で、毎場黒字を達成したものではありません。共同の資金制約・保有中の合成時価と最大下落は未検証です。二つともE01に基づくため、別銘柄であることだけで分散効果を確認したとはしません。</p>'
        page += '<p class="muted">旧33場でも、保有中にはTOPIX最大3,166円・日経1,566円の評価損が記録されています。小さい確定利益と高い決済勝率だけで、損小利大や将来の安全性を確認したとはしません。</p>'
    heading = manifest.get('overview_heading', '相対的な強さを追う型' if symbols == ('PAIR',) else '少額E01の固定設定')
    status = '二口座合算を構成する商品別設定です。' if dual else ('既知期間の候補です。' if qualified else '採用基準未達の参考です。')
    page += '<h2>' + heading + '</h2><p><code>' + esc(policy_id) + '</code>。' + status + '</p>'
    page += rules_html
    page += '<div class="wrap"><table><thead><tr><th>商品</th><th>40場合計円</th><th>黒字／赤字／無取引</th><th>全場平均円</th><th>中央値円</th><th>最悪円</th><th>上位3黒字除外円</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
    page += '<p class="muted">2026年9月21日デイ〜10月16日ナイトの40場。TOPIXミニ上限10枚・日経マイクロ上限20枚を比較尺度に使用。少額E01はその範囲でリスクに応じて数量を減らします。二脚型は別の合計口座で、各商品単独の成功とは区別。注文ごとの手数料、ラージBBOによる気配差、全残玉の評価を含み、損益は資金利回りではありません。</p>'
    if dual:
        page += '<h2>第一候補の全40場：二口座の場末収支合算</h2><p class="muted">両口座の完結親の費用後損益を合算。損失は絶対額で、収支＝利益−損失です。無取引を黒字に数えず、旧33場の保存引用と追加7場を区別します。商品別の内訳は少額E01の段階別レポートを参照してください。</p><div class="wrap"><table><thead><tr><th>セッション</th><th>利益円</th><th>損失円</th><th>収支円</th><th>手数料円（内数）</th><th>元会計</th></tr></thead><tbody>'
        for row in dual['rows']:
            page += '<tr data-session="' + esc(row['session']) + '"><th>' + esc(row['session']) + '</th>' + ''.join('<td>' + esc(money(row[key]) if key == 'net' else f'{row[key]:,.0f}') + '</td>' for key in ('profit', 'loss', 'net', 'fees')) + '<td>' + esc(row['origin']) + '</td></tr>'
        page += '</tbody></table></div><p><a href="二口座の合算損益.json">二口座合算の保存会計と留保</a></p>'
    page += '<details><summary>他の手法の結果・検証条件を開く</summary><p>共同追従・復帰・離脱失敗・自動選択を比較し、実際の負けを調べて注文保護、張り方、順逆売買と時刻回避を修正しました。日経とTOPIXを逆向きに持つ相対価値型も検証しています。</p>'
    page += '<p>初回252政策には両商品合計黒字が11政策あります。ただし例のCENTER_L40_X1_E0_G1はTOPIX＋4,792円・日経＋142,440円でも、上位3黒字場を除くと−380,192円・−14,480円、中央値は両方0円。「一部の日に依存しない」という希望に沿って採用していません。</p>'
    page += '<h2>各段階の全セッション損益</h2><ol>' + ''.join(phase_links) + '</ol>'
    page += '<p>比較元の<a href="../00106_支持の強さで注文価格を切り替えるE01/README.md">00106の少額型</a>は、旧33場でTOPIX8黒字・0赤字・25無取引、合計8,260円、日経22黒字・0赤字・11無取引、5,552円でした。この33場は保存会計を再利用し、追加7場だけ新たに実行。初めから40場すべてを同じ新規金融として数えていません。</p>'
    page += '<p class="muted">追加7場は入力の資格を修正しています。原価格時計と原連番を保持し、場外・過去最大時計より古い行を採用しません。日付を翌日へ推測補完していません。旧33場の入力は変更しておらず、入力まで完全同一の比較ではありません。最初の旧入力生成は時計逆行で停止し、新金融0として別に保存しています。</p></details>'
    page += '<p><a href="損失の原因と改善の結果.md">具体的な損失と改善の結果</a> ／ <a href="README.md">資料の案内</a> ／ <a href="../共通/知見台帳/README.md">共通知見</a></p>'
    page += '<p class="muted">初回の後13場は設定選択から分離しました。その結果を見た後の修正は、すべて既知40場の開発検証です。新しい未知データで成功したとは扱いません。</p></main></body></html>'
    (PUBLIC / MAIN).write_text(page, encoding='utf-8')
    text = f'# 戦略の自動選択と場内黒字の再探索\n\n最初に[今回の結論と全セッション損益]({MAIN})を開いてください。\n\n**{conclusion}**\n\n'
    if dual:
        text += '第一候補は少額E01の二口座並行運転。場末収支の合算で、新しい金融再生ではありません。全40場の合算表は最初のHTML内、商品別80行は少額E01の段階別HTMLへ掲載しています。\n\n'
    text += '1. 短い結論と参考候補の成績を確認します。\n2. [具体的な損失と改善の結果](損失の原因と改善の結果.md)で、何時のどの注文を直そうとしたかを確認します。\n3. 各段階のHTMLにある全セッションの利益・損失・収支を確認します。失敗した初回結果も残しています。\n\n'
    text += '\n'.join(f'- [{p["title"]}]({p["directory"]}/{p["report"]})：{p["description"]}' for p in manifest['phases']) + '\n\n'
    text += '元データと過去の経済実装は変更していません。初回は完成80入力＋初期化失敗時2入力を読み、少額E01以外の改善は同じ保存入力を再利用しました。少額E01は追加7場の素材42ファイルを各一回複写した後、旧consumerが既知の価格時計逆行で停止し、新金融0でした。再開はその複写を使用し、原時計を推測変更せず、古い時計の行を採用対象外にした別入力仕様です。旧33場は保存引用です。読取数と再利用の範囲はその段階の証跡を参照してください。実注文・現在API取得は0です。\n\n各注文の費用はTOPIXミニ片道41.8円、日経マイクロ11円を注文枚数全体で円未満切捨て。ラージの気配による代理約定で、実小型板・待ち順位・真の受信順は未証明です。\n'
    (PUBLIC / 'README.md').write_text(text, encoding='utf-8')
    shutil.copyfile(path, PUBLIC / '成果の元ファイルと指紋.json')
    print(json.dumps(dict(public=PUBLIC.as_posix(), report=MAIN, source_SHA256=view['source_SHA256'], qualification_count=qualified), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    main(parser.parse_args().manifest)
