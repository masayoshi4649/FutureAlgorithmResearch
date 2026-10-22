"""旧引用と時計資格訂正後の追加七場を、初回停止と区別して表示する。"""

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import re
import statistics


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
PRIVATE = BASE / 'privatev6'
HTML_NAME = '少額E01固定設定と追加七場を含む全セッション損益.html'
METHOD = 'E01_006_FIXED'
SYMBOLS = ('TOPIX', 'NK225')
ACTUAL = {'TOPIX': 'E01_ADAPT_G50_ADAPT75_P1', 'NK225': 'E01_ADAPT_G25_ADAPT100_P1'}
EPS = 1e-7
TRIAL_H = '119h_少額E01の時計逆行行除外による入力停止修正'
OLD_FLAT_PROOF = HERE / 'audit_source/旧三十三場の終端flat保証を数量補完せず委譲するSOURCE確認.json'
OLD_FLAT_SHA = 'cad15e47f14e6e4ff526019437c440e0f9cad023369e420deb0c13a8a633f431'


def sha(raw: bytes) -> str:
    """
    機能: 一読内容又は生成物の指紋を計算する。
    引数: raw(bytes)は対象の内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


def encoded(value: object) -> bytes:
    """
    機能: 有限の日本語JSONをUTF-8へ変換する。
    引数: value(object)は公開小会計又は証跡。
    返り値: bytesは保存内容。未知はnullのまま残す。
    """
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf8')


def esc(value: object) -> str:
    """
    機能: 説明と識別子をHTMLへ安全に写す。
    引数: value(object)は表示対象。
    返り値: strはエスケープ済み文字列。
    """
    return html.escape(str(value), quote=True)


def fmt(value: float | None, signed: bool = False) -> str:
    """
    機能: 未保存と零を区別して金額又は枚数を表示する。
    引数: value(float|None)は数値、signed(bool)は符号指定。
    返り値: strは千位区切り又は未保存。
    """
    if value is None:
        return '未保存'
    if abs(value) <= EPS:
        return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def validate(data: dict) -> tuple[list[str], list[str], dict]:
    """
    機能: 一つの固定組合わせ・旧六十六引用・新十四口座を確認する。
    引数: data(dict)は根担当指定SHAの完成内容又は完全合成値。
    返り値: tuple[list[str],list[str],dict]は全場・追加場・商品場行。
    """
    assert data['全合格'] is True and data['trial'] == TRIAL_H
    assert data['source_SHA256'] == data['source_end_SHA256']
    scenes = data['sessions']
    new = data['new_sessions']
    assert data['method'] == METHOD and data['actual_config'] == ACTUAL
    assert len(scenes) == len(set(scenes)) == 40
    assert len(new) == len(set(new)) == 7 and set(new) <= set(scenes)
    assert len(data['rows']) == 80 and data['source_SHA256']
    assert data['old_reference']['path'] and re.fullmatch('[0-9a-fA-F]{64}', data['old_reference']['SHA256'])
    rows = {}
    for row in data['rows']:
        key = row['symbol'], row['session']
        assert key not in rows and key[0] in SYMBOLS and key[1] in scenes
        assert row['method'] == METHOD and row['actual_config'] == ACTUAL[row['symbol']]
        for name in ('profit', 'loss', 'net', 'fees'):
            assert isinstance(row[name], (int, float)) and math.isfinite(row[name]), (key, name)
        for name in ('campaigns', 'winning_campaigns', 'losing_campaigns', 'winning_lots', 'losing_lots'):
            assert isinstance(row[name], (int, float)) and int(row[name]) == row[name] and row[name] >= 0, (key, name)
        assert min(row[name] for name in ('profit', 'loss', 'fees')) >= 0
        assert abs(row['profit'] - row['loss'] - row['net']) <= 1e-5
        assert row['winning_campaigns'] + row['losing_campaigns'] <= row['campaigns']
        assert row['unclosed'] is None or int(row['unclosed']) == row['unclosed'] >= 0
        assert row['origin'] == ('追加七場の新金融' if key[1] in new else '旧33保存会計の引用')
        if not row['campaigns']:
            assert abs(row['net']) <= EPS and abs(row['fees']) <= EPS
            assert row['winning_lots'] == row['losing_lots'] == 0
        rows[key] = row
    assert set(rows) == {(symbol, scene) for symbol in SYMBOLS for scene in scenes}
    return scenes, new, rows


def aggregate(rows: list[dict], old_verified: bool = False) -> dict:
    """
    機能: 保存済み完結親の会計を無取引・終端不明と分けて集計する。
    引数: rows(list[dict])は同一商品・同一期間の場行、old_verified(bool)は旧完了源への委譲確認。
    返り値: dictは公開互換の金額と安定指標。未保存の終端は零へ補完しない。
    """
    ns = [row['net'] for row in rows]
    positive = [row['net'] for row in rows if row['campaigns'] and row['net'] > EPS]
    negative = [-row['net'] for row in rows if row['campaigns'] and row['net'] < -EPS]
    p, loss = sum(row['profit'] for row in rows), sum(row['loss'] for row in rows)
    known_open = sum(bool(row['unclosed']) for row in rows if row['unclosed'] is not None)
    unknown = sum(row['unclosed'] is None for row in rows)
    mean_abs = statistics.mean(abs(v) for v in ns) if ns else None
    median = statistics.median(ns) if ns else None
    ordered = sorted(ns)
    q25 = ordered[(len(ordered) - 1) // 4] if ordered else None
    q75 = ordered[(len(ordered) - 1) * 3 // 4] if ordered else None
    verified_flat = not known_open and all(row['unclosed'] == 0 or
        old_verified and row['unclosed'] is None and row['origin'] == '旧33保存会計の引用' for row in rows)
    return dict(sessions=len(rows), net=sum(ns), profit=p, loss=loss, fees=sum(row['fees'] for row in rows),
        parents=sum(row['campaigns'] for row in rows), wins=sum(row['winning_campaigns'] for row in rows),
        losses=sum(row['losing_campaigns'] for row in rows), winning_lots=sum(row['winning_lots'] for row in rows),
        losing_lots=sum(row['losing_lots'] for row in rows), zero_lots=None, black=len(positive), red=len(negative),
        inactive=sum(row['campaigns'] == 0 for row in rows), flat=sum(row['campaigns'] > 0 and abs(row['net']) <= EPS for row in rows),
        mean=statistics.mean(ns) if ns else None, median=median, q25_observed=q25, q75_observed=q75,
        quantile_definition='昇順でfloor((N−1)×p)番目の観測値', worst=min(ns) if ns else None,
        top3_removed=sum(ns) - sum(sorted(positive, reverse=True)[:3]) if not known_open else None,
        share=p / (p + loss) if p + loss > EPS else None,
        normalized_median=median / mean_abs if mean_abs and median is not None else None,
        worst_to_mean_black=max(negative, default=0) / statistics.mean(positive) if positive else None,
        unclosed_sessions=known_open, unclosed_unknown_sessions=unknown,
        verified_flat=verified_flat, all_positive=len(positive) == len(rows) and verified_flat)


def load_old_flat_basis(path: Path, expected: str) -> dict:
    """
    機能: 旧終端枚数を補完せず、指定されたSOURCE委譲証跡だけを読む。
    引数: path(Path)とexpected(str)は根が指定した小証跡とそのSHA。
    返り値: dictは表示用の根拠。旧金融又は曲線を再読したとは扱わない。
    """
    raw = path.read_bytes()
    assert sha(raw) == expected
    proof = json.loads(raw.decode('utf8'))
    assert proof['全合格'] is True and proof['verified_flat_basis']['使用可'] is True
    assert proof['verified_flat_basis']['unknownを0へ補完'] is False
    old = proof['根から受領した既検証事実']
    assert old['各商品33行'] == old['全会計合格True'] == 66
    assert old['正式結果SHA256'] == '13f534a10b081db94944d723171214a2132829b66b70f177e0d3055b27116944'
    return dict(verified_flat=True, type='旧finish=True成功フラグと独立小会計への委譲',
        path=path.resolve().relative_to(ROOT).as_posix(), SHA256=expected, old_result_SHA256=old['正式結果SHA256'],
        selected_configs=ACTUAL, delegated_rows=66, terminal_quantity_imputed=False, new_full_curve_audit=False)


def metric_cells(m: dict) -> list[str]:
    """
    機能: 全期と旧新内訳の共通集計列を生成する。
    引数: m(dict)は一商品一期間の集計。
    返り値: list[str]は円・黒赤無・枚数・終端不明の表示。
    """
    return [fmt(m['profit']), fmt(m['loss']), fmt(m['net'], True), f"{m['black']}/{m['red']}/{m['inactive']}",
        fmt(m['mean'], True), fmt(m['median'], True), fmt(m['worst'], True), fmt(m['top3_removed'], True),
        fmt(m['fees']), fmt(m['winning_lots']) + '/' + fmt(m['losing_lots']), str(m['parents']),
        '—' if m['share'] is None else f"{m['share'] * 100:.1f}%", str(m['unclosed_sessions']), str(m['unclosed_unknown_sessions'])]


def table(headers: tuple[str, ...], body: list[str], css: str) -> str:
    """
    機能: 横幅が狭い場合も本文を押し広げない表を生成する。
    引数: headers(tuple[str,...])、body(list[str])、css(str)は列と行と分類。
    返り値: strはHTML表。
    """
    return '<div class="table-wrap"><table class="' + css + '"><thead><tr>' + ''.join('<th>' + esc(v) + '</th>' for v in headers) + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>'


def render(data: dict, result_sha: str, result_path: str, old_flat_basis: dict | None = None) -> tuple[str, dict, str]:
    """
    機能: 旧引用と追加実行を区別した一政策の全四十場を表示する。
    引数: data(dict)、result_sha/result_path(str)は一読内容、old_flat_basis(dict|None)は旧終端委譲証跡。
    返り値: tuple[str,dict,str]はHTML・公開小会計・案内。市場と金融は読まない。
    """
    scenes, new, rows = validate(data)
    old = [s for s in scenes if s not in new]
    old_verified = old_flat_basis is not None and old_flat_basis['verified_flat'] is True
    metrics = {s: aggregate([rows[s, scene] for scene in scenes], old_verified) for s in SYMBOLS}
    periods = {label: {s: aggregate([rows[s, scene] for scene in ss], old_verified) for s in SYMBOLS}
               for label, ss in (('旧33引用', old), ('追加7新規', new))}
    qualified = all(m['net'] > EPS and m['median'] > EPS and m['top3_removed'] is not None and m['top3_removed'] > EPS
                    and m['verified_flat'] for m in metrics.values())
    all_positive = all(m['all_positive'] for m in metrics.values())
    rules = dict(入口='両市場の主方向が一致するE01候補を、対象市場の直近60秒の票で確認します。TOPIXと日経には、旧調査で固定した別の閾値を使います。',
        保有='当時のATR・気配差・料金に応じて数量を減らし、支持が強ければ不利1観測呼値まで、弱ければ公開価格までの一回FAKで参加します。',
        出口='元E01の途中減量・損切り・追尾を維持し、費用後の小利益目標へ届いたら残玉を返済してその場を終えます。セッション内で全返済する設計です。')
    case = dict(spec=dict(id=METHOD, family='E01', name='少額E01の商品別固定設定', actual_config=ACTUAL),
        rules=rules, metrics=metrics, periods=periods, rows=[rows[s, scene] for scene in scenes for s in SYMBOLS])
    summary_headers = ('商品・期間', '利益円', '損失円', '収支円', '黒／赤／無', '平均円', '中央値円', '最悪円',
        '上位3黒字除外円', '手数料円', '勝／負枚数', '完結親', '金額利益割合', '既知未返済場', '終端数量未保存場')
    summary = ['<tr><th>' + s + ' 全40</th>' + ''.join('<td>' + esc(v) + '</td>' for v in metric_cells(metrics[s])) + '</tr>' for s in SYMBOLS]
    periodrows = ['<tr><th>' + s + ' ' + label + '</th>' + ''.join('<td>' + esc(v) + '</td>' for v in metric_cells(mm[s])) + '</tr>'
                  for label, mm in periods.items() for s in SYMBOLS]
    body = []
    for scene in scenes:
        for s in SYMBOLS:
            r = rows[s, scene]
            values = [s, '追加7' if scene in new else '旧33引用', fmt(r['profit']), fmt(r['loss']), fmt(r['net'], True),
                fmt(r['fees']), fmt(r['winning_lots']), fmt(r['losing_lots']), str(r['campaigns']), fmt(r['unclosed'])]
            body.append('<tr data-session="' + esc(scene) + '" data-symbol="' + s + '"><th>' + esc(scene.replace('_Day', ' デイ').replace('_Night', ' ナイト')) + '</th>' + ''.join('<td>' + esc(v) + '</td>' for v in values) + '</tr>')
    session_headers = ('セッション', '商品', '出典', '利益円', '損失円', '収支円', '手数料円', '勝ち枚数', '負け枚数', '完結親', '未返済枚数')
    session_html = table(session_headers, body, 'sessions')
    foot = ''.join('<tr><th>全40合計</th><td>' + s + '</td><td>旧33＋追加7</td>' + ''.join('<td>' + esc(v) + '</td>' for v in
        [fmt(metrics[s]['profit']), fmt(metrics[s]['loss']), fmt(metrics[s]['net'], True), fmt(metrics[s]['fees']),
         fmt(metrics[s]['winning_lots']), fmt(metrics[s]['losing_lots']), str(metrics[s]['parents']),
         '未保存あり' if metrics[s]['unclosed_unknown_sessions'] else fmt(sum(rows[s, scene]['unclosed'] for scene in scenes))]) + '</tr>' for s in SYMBOLS)
    session_html = session_html.replace('</tbody>', '</tbody><tfoot>' + foot + '</tfoot>')
    headline = '毎場黒字を既知40場で確認しました。未知の成功ではありません。' if all_positive else '<strong>毎セッションの安定黒字は未達です。</strong>'
    css = 'body{margin:0;background:#0b1120;color:#e5edf8;font:16px/1.65 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:26px 20px}h1{font-size:27px}h2{font-size:21px}a{color:#92caff}strong{color:#ffd083}.note{background:#18263d;border-left:4px solid #d9ac54;padding:14px}.muted{color:#afbed3;font-size:14px}code{overflow-wrap:anywhere}.table-wrap{max-width:100%;overflow-x:auto;border:1px solid #34445a}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:14px}td,th{padding:8px 10px;text-align:right;border-bottom:1px solid #34445a}th:first-child{text-align:left}thead,tfoot{background:#1a2b44}details{margin:16px 0}summary{cursor:pointer;color:#a7d0ff}@media(max-width:600px){main{padding:15px 10px}h1{font-size:23px}}'
    limit = '旧33場は保存会計66行の引用、新7場14口座だけが119hの追加実行です。旧106と設定の数値は同じですが、新7場は原seq・原時計を保持し、高水位より古い行と場外行を不適格にした入力です。旧33と入力仕様が完全同一ではありません。全40場は既知の開発で、旧33を新証拠へ数え直しません。'
    unknown = '旧33場の未返済枚数と零損益枚数は公開会計に未保存です。零を補完しません。' + (
        '旧33は旧finish=Trueの残玉0検査を通った成功フラグへ委譲し、verified_flat=Trueと別記します。今回旧全曲線を再監査した意味ではありません。追加7は新口座の終端で確認します。'
        if old_verified else '終了保証の別証跡が無い場合は、終端確認を未評価のまま残します。') + '枚数欄は勝ち／負けの決済枚数で、全保有枚数や資金利回りではありません。'
    text = '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + HTML_NAME[:-5] + '</title><style>' + css + '</style></head><body><!--\n[コンポーネント概要]\nmainは商品別固定二設定を一つの組合わせとして表示します。\n.table-wrapは全四十場の商品別会計と、旧引用・追加実行の表を横スクロールします。\n市場通信や金融再実行を行わず、元結果の未保存値を零へ置換しません。\n--><main><h1>' + HTML_NAME[:-5] + '</h1><p class="note">' + headline + ' 両商品の比較資格：' + ('達成' if qualified else '未達又は未評価') + '。</p>'
    text += '<p>TOPIXミニ上限10枚・日経マイクロ上限20枚の範囲で数量を縮める少額型です。商品別の閾値が異なる固定組合わせで、同じ数値条件が両商品に通用したという意味ではありません。</p>'
    text += ''.join('<p><b>' + k + '：</b>' + esc(v) + '</p>' for k, v in rules.items())
    terminal_note = '旧33の終了保証は旧完了源へ委譲し、未保存枚数を零へ書き換えません。' if old_verified else '旧終了保証の別証跡が無ければ、終端確認を未評価とします。'
    text += table(summary_headers, summary, 'summary') + '<p class="muted">無取引は保存された完結親が0の場です。低活動による中央値0円と赤字は区別します。比較資格は両商品とも合計・中央値・上位3黒字除外が正、未返済0の確認です。' + terminal_note + '</p>'
    text += '<h2>旧33と追加7の内訳</h2><p>' + limit + '</p><p class="muted">119fは原本42ファイルの準備後、旧106でも既知だった時計逆行で停止し、新金融は0です。日付へ1日を足す補正は行いません。119hは同bytesのstage済み素材を再走査し、原本の再読は0です。</p>' + table(summary_headers, periodrows, 'periods')
    text += '<h2>全40場の商品別損益</h2><p class="muted">利益／損失は完結親の手数料後netの総正負。手数料は既に収支へ含まれ、二重に控除しません。</p>' + session_html
    text += '<details><summary>固定設定と確認範囲</summary><p>TOPIX：<code>' + ACTUAL['TOPIX'] + '</code>。入口支持0.50・価格許容切替0.75。日経：<code>' + ACTUAL['NK225'] + '</code>。入口支持0.25・切替1.00。いずれも2票以上・P1純利益目標を維持します。</p><p>' + unknown + '</p><p>当時のラージ板による代理約定で、実ミニ・マイクロ板の待ち順位・部分FAK・真の受信順は未確認です。観測呼値はラージTOPIX0.5pt／日経10円で、実小型商品の最小呼値と混同しません。旧ready.tickと旧limitを維持し、119の時計又は締切へ変更していません。</p></details>'
    if old_verified:
        text += '<p class="muted">旧終了保証の委譲：<code>' + esc(old_flat_basis['path']) + '</code>、SHA256：<code>' + esc(old_flat_basis['SHA256']) + '</code>。</p>'
    text += '<p><a href="data.json">固定設定・全80行の会計</a> ／ <a href="README.md">案内</a></p><p class="muted">原結果：<code>' + esc(result_path) + '</code><br>SHA256：<code>' + esc(result_sha) + '</code><br>旧引用：<code>' + esc(data['old_reference']['path']) + '</code><br>SHA256：<code>' + esc(data['old_reference']['SHA256']) + '</code></p></main></body></html>'
    public = dict(sessions=scenes, new_sessions=new, source_path=result_path, source_SHA256=result_sha,
        economic_source_SHA256=data['source_SHA256'], old_reference=data['old_reference'], main_ids=[METHOD],
        old_flat_basis=old_flat_basis, input_revision=dict(trial=TRIAL_H, prior_trial='119f', prior_financial_accounts=0,
            prior_staged_original_files=42, original_clock_preserved=True, raw_seq_preserved=True, date_shift_days=0,
            backward_or_outside_rows_ineligible=True, original_rereads=0, staged_material_rescanned=True),
        qualification_count=int(qualified), common_ranking=[dict(id=METHOD, family='E01', qualified=qualified)],
        cases={METHOD: case}, reused_account_rows=66, new_accounts=14, market_reads=0, financial_replay=0, API=0)
    readme = '# 少額E01固定設定と追加七場を含む全セッション損益\n\n最初に[' + HTML_NAME + '](' + HTML_NAME + ')を開いてください。\n\n' + limit + '\n\nTOPIXと日経には異なる固定閾値を使います。全40場の利益・損失・収支・料金・勝負枚数・完結親を商品別に掲載します。無取引を勝ちにせず、低活動の中央値0を赤字と混同しません。\n\n' + unknown + '\n\n[data.json](data.json)が公開小会計です。原結果 `' + result_path + '`、SHA256 `' + result_sha + '`。原市場又は金融を再実行しません。\n'
    readme += '\n119fは原本42準備後に新金融0で停止。119hはstage済み素材を再走査し、原本の再読は0、原seqと原時計を保持し逆行・場外行を不適格にしました。旧設定数値は同じでも入力仕様の完全同一ではありません。\n'
    return text, public, readme


def generate(data: dict, output: Path, result_sha: str, result_path: str, fixture: bool = False, old_flat_basis: dict | None = None) -> dict:
    """
    機能: 一読メモリから正式版と合成版を区別して新規生成する。
    引数: data(dict)、output(Path)、result_sha/result_path(str)、fixture(bool)、old_flat_basis(dict|None)は内容と由来。
    返り値: dictは根の公開器と互換の生成証跡。既存成果は上書きしない。
    """
    doc, public, readme = render(data, result_sha, result_path, old_flat_basis)
    assert not output.exists()
    output.mkdir(parents=True)
    payloads = {HTML_NAME: doc.encode('utf8'), 'data.json': encoded(public), 'README.md': readme.encode('utf8')}
    for name, payload in payloads.items():
        (output / name).write_bytes(payload)
    proof = dict(passed=True, fixture=fixture, result_path=result_path, result_sha256=result_sha,
        report_sha256=sha(Path(__file__).read_bytes()), artifacts={k: sha(v) for k, v in payloads.items()},
        policies=1, common_ranking=1, baseline_controls=0, sessions=40, account_rows=80,
        reused_account_rows=66, new_accounts=14, main_ids=[METHOD], market_reads=0, financial_replay=0, API=0)
    (output / '生成証跡.json').write_bytes(encoded(proof))
    return proof


def main() -> None:
    """
    機能: 根担当指定SHAの完成結果だけを一読し、同bytesを私有保全する。
    引数: CLI --result(Path)、--expected-sha256(str)、任意--output/--received(Path)、--fixture(bool)。
    返り値: None。実測は完成SHA指定後のみ読む。
    """
    p = argparse.ArgumentParser()
    p.add_argument('--result', type=Path, required=True)
    p.add_argument('--expected-sha256', required=True)
    p.add_argument('--output', type=Path, default=PRIVATE / 'public')
    p.add_argument('--received', type=Path, default=PRIVATE / 'received')
    p.add_argument('--fixture', action='store_true')
    p.add_argument('--old-flat-basis', type=Path, default=OLD_FLAT_PROOF)
    p.add_argument('--expected-old-flat-sha256', default=OLD_FLAT_SHA)
    args = p.parse_args()
    expected = args.expected_sha256.lower()
    assert re.fullmatch('[0-9a-f]{64}', expected) and not args.output.exists() and not args.received.exists()
    raw = args.result.read_bytes()
    assert sha(raw) == expected, '指定SHA不一致。'
    args.received.mkdir(parents=True)
    own = args.received / args.result.name
    own.write_bytes(raw)
    (args.received / '一読と同bytes保全.json').write_bytes(encoded(dict(source_path=str(args.result), source_SHA256=expected,
        own_copy=str(own), source_reads=1, fixture=args.fixture, market_reads=0, financial_replay=0, API=0)))
    try:
        source_path = args.result.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        source_path = str(args.result.resolve())
    basis = None if args.fixture else load_old_flat_basis(args.old_flat_basis, args.expected_old_flat_sha256)
    print(json.dumps(generate(json.loads(raw.decode('utf8')), args.output, expected, source_path, args.fixture, basis), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
