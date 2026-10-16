"""正式選択を保持したまま、全条件を見た後のS03の所見だけを別章へ保存する。"""

from copy import deepcopy
from html import escape
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report

ROOT = HERE.parents[1]
SOURCE = HERE / 'result_audit/S03とT01の事後値幅比較及び到達前経路の小射影_v2.json'
OUT = HERE / 'report_check/revision2'
ARCHIVE = HERE / 'report_archive/revision1'
MD_NAME = '事後に残った予兆候補S03.md'
MANIFEST = HERE / '四十四条件と全三十七場の公開射影.json'


# ----------------------------------------


def quantile(values: list[float], p: float) -> float | None:
    """
    機能: 有限な事後経路値だけの線形補間分位を計算する。
    引数: values(list[float])、p(float) は有限値と0～1の分位。
    返り値: float|None は分位。欠測や空集合を0へ補完しない。
    """
    if not values:
        return None
    values = sorted(values)
    position = p * (len(values) - 1)
    left = int(math.floor(position))
    right = int(math.ceil(position))
    return values[left] * (right - position) + values[right] * (position - left) if left != right else values[left]


def same_metric(a: dict, b: dict, label: str) -> None:
    """
    機能: 小射影と既公開採点の同じ分子分母・率を照合する。
    引数: a/b(dict)、label(str) は対応集計と名称。
    返り値: None。新しい採点や親削除による損益を計算しない。
    """
    report.validate_cell(a, label)
    report.validate_cell(b, label + '旧公開')
    for key in (*report.COUNTS, 'n', 'resolved'):
        report.check(a[key] == b[key], label + key)
    for key in ('全候補順先率', '解決内順先率', '解決率'):
        report.check(report.near(a[key], b[key]), label + key)


def validate(public: dict, diagnostic: dict) -> dict:
    """
    機能: S03/T01の全期間と全場、S03の別枠全予兆を独立小算術で確認する。
    引数: public(dict)、diagnostic(dict) は既公開採点と根指定の限定射影。
    返り値: dict はS03経路の再集計。原金融・原価格列・未来ラベルを再生しない。
    """
    summaries = {row['id']: row for row in public['summaries']}
    old_rows = {(row['id'], row['session']): row for row in public['rows']}
    for identity in ('S03', 'T01'):
        report.check(set(diagnostic['periods'][identity]) == set(public['periods']), '八期間対応')
        for period, saved in diagnostic['periods'][identity].items():
            old = summaries[identity]['periods'][period]
            for key in ('場数', '活動場数', '無信号場数', '予兆数', '買い数', '売り数'):
                report.check(saved[key] == old[key], identity + period + key)
            for ri in range(3):
                for group in report.GROUPS:
                    same_metric(saved['risks'][ri][group], old['risks'][ri][group], identity + period + group)
        rows = diagnostic['by_session'][identity]
        report.check(len(rows) == len({row['session'] for row in rows}) == 37, '37場一意')
        report.check([row['session'] for row in rows] == public['sessions'], '37場順序')
        for row in rows:
            old = old_rows[identity, row['session']]
            for key in ('公開候補数', '採用予兆数', '買い数', '売り数'):
                report.check(row[key] == old[key], '場件数')
            for ri in range(3):
                for group in report.GROUPS:
                    a = row['risks'][ri] if group == '全体' else row['risks'][ri][group]
                    b = old['risks'][ri] if group == '全体' else old['risks'][ri][group]
                    same_metric(a, b, '場の三幅')
    records = diagnostic['S03_別枠10_records']
    expected = summaries['S03']['periods']['別枠10']
    report.check(len(records) == expected['予兆数'], 'S03の全別枠予兆数')
    seen = set()
    for row in records:
        report.check(row['session'] in public['periods']['別枠10'], '別枠以外を経路へ混ぜない')
        key = row['session'], row['公開原row']
        report.check(key not in seen, '同じ予兆を重複しない')
        seen.add(key)
        report.check(row['方向'] in (-1, 1) and len(row['labels']) == 3, '経路方向と三幅')
        if row['十pt到達秒'] is not None:
            report.check(row['十pt到達原row'] > row['公開原row'] and row['十pt到達秒'] >= row['公開秒'], '到達は公開後')
        if row['labels'][1] == -1 and row['十pt到達原row'] >= 0:
            report.check(row['終端原row'][1] < row['十pt到達原row'], '逆5の先着後に10pt到達')
        for key in ('十pt到達前MAE', 'MFE', 'MAE'):
            report.check(row[key] is None or math.isfinite(row[key]), '経路欠測を保持')
    for ri in range(3):
        for code, name in ((1, '順先'), (-1, '逆先'), (0, '窓末未決'), (2, 'EOF未決'), (-2, '基準不可')):
            report.check(sum(row['labels'][ri] == code for row in records) == expected['risks'][ri]['全体'][name], '経路と先着母数')
    reached = [row for row in records if row['十pt到達秒'] is not None]
    finite = [row['十pt到達前MAE'] for row in reached if row['十pt到達前MAE'] is not None]
    elapsed = [row['十pt到達秒'] - row['公開秒'] for row in reached]
    later = [row for row in records if row['labels'][1] == -1 and row['十pt到達秒'] is not None]
    return dict(予兆数=len(records), 十pt到達=len(reached), 十pt未到達=len(records) - len(reached),
        逆5先着後十pt到達=len(later), 到達前MAE有限=len(finite), 到達前MAE不明=len(reached) - len(finite),
        到達代理秒分位={str(p): quantile(elapsed, p) for p in (0, .25, .5, .75, 1)},
        signed_MAE分位={str(p): quantile(finite, p) for p in (0, .25, .5, .75, 1)},
        十pt前観測逆行幅分位={str(p): quantile([max(0., -value) for value in finite], p) for p in (0, .25, .5, .75, 1)},
        留保='10pt初到達行を除く事後観測値。採用済み価格列の欠測区間や将来利益を補完しない。')


def appendix(public: dict, diagnostic: dict, metrics: dict, source_sha: str) -> tuple[str, str]:
    """
    機能: 正式候補と切り離したS03の短いHTML章と平易なMDを作る。
    引数: public/diagnostic/metrics(dict)、source_sha(str) は採点・限定射影・再計算・指紋。
    返り値: tuple[str,str] はHTML章とMD。risk10の後選択を正式検証と呼ばない。
    """
    spec = next(row for row in public['specifications'] if row['id'] == 'S03')
    periods = diagnostic['periods']['S03']
    hold = periods['別枠10']
    comparison_rows = []
    comparison_md = []
    for identity in ('S03', 'T01'):
        saved = diagnostic['periods'][identity]['別枠10']
        p = saved['risks'][2]
        fixed = max(p['常時買い']['全候補順先率'], p['常時売り']['全候補順先率']) if p['全体']['n'] else None
        delta = None if fixed is None else p['全体']['全候補順先率'] - fixed
        comparison_rows.append('<tr><th>' + identity + '</th><td>' + report.cell_text(p['全体']) + '</td><td>' + report.cell_text(p['常時買い']) +
            '</td><td>' + report.cell_text(p['常時売り']) + '</td><td>' + ('—' if delta is None else f'{delta * 100:+.1f}pt') + '</td></tr>')
        comparison_md.append('| ' + identity + ' | ' + report.cell_text(p['全体']) + ' | ' + report.cell_text(p['常時買い']) + ' | ' + report.cell_text(p['常時売り']) + ' |')
    width_rows = []
    width_md = []
    for saved in hold['risks']:
        p = saved['全体']
        pending = p['窓末未決'] + p['EOF未決']
        width_rows.append('<tr><th>逆' + report.number(saved['逆行幅']) + 'pt</th><td>' + report.cell_text(p) + f"</td><td>{p['逆先']}</td><td>{pending}</td></tr>")
        width_md.append('| ' + report.number(saved['逆行幅']) + 'pt | ' + report.cell_text(p) + f" | {p['逆先']} | {pending} |")
    period_rows = []
    period_md = []
    for name in report.PERIODS:
        saved = periods[name]
        p = saved['risks'][2]['全体']
        pending = p['窓末未決'] + p['EOF未決']
        period_rows.append('<tr><th>' + name + '</th><td>' + report.cell_text(p) + f"</td><td>{p['逆先']}</td><td>{pending}</td><td>{saved['活動場数']}/{saved['場数']}</td></tr>")
        period_md.append('| ' + name + ' | ' + report.cell_text(p) + f" | {p['逆先']} | {pending} | {saved['活動場数']}/{saved['場数']} |")
    session_rows = []
    session_md = []
    for row in diagnostic['by_session']['S03']:
        cells = [report.cell_text(item) for item in row['risks']]
        session_rows.append('<tr><th>' + escape(row['session']) + '</th>' + ''.join('<td>' + value + '</td>' for value in cells) + '</tr>')
        session_md.append('| ' + row['session'] + ' | ' + ' | '.join(cells) + ' |')
    median = metrics['signed_MAE分位']['0.5']
    path_text = (f"別枠10場の{metrics['予兆数']}予兆のうち、観測終端までに10ptへ到達したのは{metrics['十pt到達']}件。" +
        f"うち、先に逆5ptへ触れてから後で10ptへ到達したものは{metrics['逆5先着後十pt到達']}件です。" +
        f"到達前の最小signed値幅の中央値は{report.number(median)}pt（有限{metrics['到達前MAE有限']}件、不明{metrics['到達前MAE不明']}件）。")
    time_text = '到達した例だけの所要価格時計差の中央値は' + report.number(metrics['到達代理秒分位']['0.5']) + '秒です。固定保有時間や未到達も含めた所要時間ではありません。'
    body = '''<section class="panel" id="posthoc-s03"><h2>事後に残った予兆候補：S03</h2><p class="tag">全44条件の結果を見た後の発見。正式3候補の差し替えではありません。</p><p>短い時間の値幅が狭まった後、短期移動平均が揃い始め、現在値が過去の帯を抜ける場面を拾う手法です。</p><details><summary>S03の具体的な入口条件</summary><p>''' + escape(spec.get('condition', spec.get('description', ''))) + '''</p></details><p>逆行10ptまで許す先着では、固定方向より良かったため追跡候補に残します。ただし、逆行5ptで止めた場合は別の結果になります。</p><div class="scroll"><table id="posthoc-comparison-table"><thead><tr><th>事後注目ID</th><th>順10／逆10先着</th><th>固定買い</th><th>固定売り</th><th>良い方との差</th></tr></thead><tbody>''' + ''.join(comparison_rows) + '''</tbody></table></div><div class="scroll"><table id="posthoc-width-table"><thead><tr><th>S03・別枠10場の逆行許容</th><th>順10pt先着/全予兆</th><th>逆先</th><th>未決</th></tr></thead><tbody>''' + ''.join(width_rows) + '''</tbody></table></div><p>''' + escape(path_text) + '''</p><p class="note">到達前MAEは事後に分かる値です。許容幅や出口をこの値で決めた場合の損益は測っていません。40予兆を40個の独立した市場と扱いません。全44比較後に条件と幅へ注目した多重比較の影響があり、未知での再現は未確認です。</p><details><summary>S03の期間別・全37セッション</summary><div class="scroll"><table id="posthoc-period-table"><thead><tr><th>期間</th><th>順10／逆10先着</th><th>逆先</th><th>未決</th><th>活動場</th></tr></thead><tbody>''' + ''.join(period_rows) + '''</tbody></table></div><div class="scroll"><table id="posthoc-session-table"><thead><tr><th>セッション</th><th>順10／逆2.5</th><th>順10／逆5</th><th>順10／逆10</th></tr></thead><tbody>''' + ''.join(session_rows) + '''</tbody></table></div></details><p><a href="''' + MD_NAME + '''">S03の追補MDと根拠</a></p></section>'''
    markdown = '# 事後に残った予兆候補S03\n\n'
    markdown += 'S03は、狭くなった短期の帯から移動平均が整列し、現在値も帯の外へ進む場面を選ぶ手法です。**全44条件の結果を見た後で注目した候補**です。選択6場で決めた正式3候補は変更しません。\n\n'
    markdown += '具体的な入口：' + spec.get('condition', spec.get('description', '')) + '\n\n'
    markdown += '別枠10場の順10pt／逆10pt比較：\n\n| ID | 順先/全予兆 | 同時点固定買い | 同時点固定売り |\n| --- | ---: | ---: | ---: |\n' + '\n'.join(comparison_md) + '\n\n'
    markdown += 'S03の逆行許容を変えた比較。同じ公開予兆を採点しています。\n\n| 逆行許容 | 順10pt先着/全予兆 | 逆先 | 未決 |\n| --- | ---: | ---: | ---: |\n' + '\n'.join(width_md) + '\n\n'
    markdown += path_text + '\n\n' + time_text + '\n\n到達前のMAEは10ptへ到達した行を除いた、採用済み未来観測の最小signed値幅です。先行観測がない場合は不明のままです。後から10ptへ到達しても、先に損切り幅へ触れた事実は消えません。\n\n'
    markdown += '期間別（順10pt／逆10pt）：\n\n| 期間 | 順先/全予兆 | 逆先 | 未決 | 活動場 |\n| --- | ---: | ---: | ---: | ---: |\n' + '\n'.join(period_md) + '\n\n'
    markdown += '全37場：\n\n| セッション | 順10／逆2.5 | 順10／逆5 | 順10／逆10 |\n| --- | ---: | ---: | ---: |\n' + '\n'.join(session_md) + '\n\n'
    markdown += 'この結果を未知の市場で有効とする証明にはしません。全44条件と複数幅を見た後の注目であり、多重比較・相場の方向の偏り・セッション内の相関があります。40予兆を40の独立市場と扱わず、既知の後6場と追加4場を、完全未見の検証とは呼びません。\n\n'
    markdown += 'Lastの観測先着であり、完全約定テープ・実約定・費用後収支・平均セッション10万円の達成ではありません。今回の追補は既派生データからの再集計で、新たな実測や新しい有効性標本ではありません。\n\n'
    markdown += '[正式3候補と全37場](' + report.HTML_NAME + ')・[限定射影](../../' + SOURCE.relative_to(ROOT).as_posix() + ')。限定射影SHA256：`' + source_sha + '`。\n'
    return body, markdown


def synthetic() -> None:
    """
    機能: 実公開を読まず、追補全schemaと正式選択保持を架空結果で確認する。
    引数: なし。
    返り値: None。射影・原結果・原入力・金融を読まない。
    """
    result = report.synthetic_result()
    for key in ('specifications', 'summaries', 'accounts'):
        for item in result[key]:
            if item['id'] == 'T03':
                item['id'] = 'S03'
    result['selection']['比較参照'] = ['S03', 'T04', 'T05']
    public = report.build(result, '0' * 64)
    summaries = {item['id']: item for item in public['summaries']}
    diagnostic = dict(periods={identity: summaries[identity]['periods'] for identity in ('S03', 'T01')},
        by_session={identity: [row for row in public['rows'] if row['id'] == identity] for identity in ('S03', 'T01')},
        S03_別枠10_records=[dict(session=row['session'], **item) for row in result['accounts']
            if row['id'] == 'S03' and row['session'] in public['periods']['別枠10'] for item in row['records']])
    metrics = validate(public, diagnostic)
    body, md = appendix(public, diagnostic, metrics, '0' * 64)
    report.check(metrics['予兆数'] == metrics['十pt到達'] == 20, '合成の全経路分母')
    report.check(metrics['逆5先着後十pt到達'] == 10 and metrics['到達前MAE有限'] == 20, '逆先後到達を区別')
    report.check('正式3候補の差し替えではありません' in body and '全37場' in md, '正式と事後の区別')
    print(json.dumps(dict(全合格=True, 限定射影読取=0, 原結果再読=0, 原入力=0, 金融=0, API=0), ensure_ascii=False))


def main() -> None:
    """
    機能: 根指定小射影を一回読み、旧公開を同bytes保全して追補revision2を公開する。
    引数: CLIの--expected-sha(str)。
    返り値: None。元測定結果・原入力・金融・APIを再読・再実行しない。
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-sha')
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        report.check(args.expected_sha is None, 'pureで実射影を読まない')
        synthetic()
        return
    report.check(isinstance(args.expected_sha, str) and len(args.expected_sha) == 64 and not OUT.exists() and not ARCHIVE.exists(), '根指定SHAと自動再試行禁止')
    OUT.mkdir(parents=True)
    proof = dict(全合格=False, 元結果再読=0, 原入力=0, 金融=0, API=0, 限定射影読取=0)
    try:
        payload = SOURCE.read_bytes()
        proof['限定射影読取'] = 1
        sha = hashlib.sha256(payload).hexdigest()
        report.check(sha == args.expected_sha and len(payload) < 2 * 1024 * 1024, '指定した小射影のみ')
        (OUT / '事後限定射影の同bytes保全.json').write_bytes(payload)
        diagnostic = json.loads(payload.decode('utf-8'))
        ARCHIVE.mkdir(parents=True)
        archived = []
        originals = [report.PUBLIC / report.JSON_NAME, report.PUBLIC / report.HTML_NAME, report.PUBLIC / 'README.md', MANIFEST, HERE / 'report.py']
        old_payloads = {}
        for path in originals:
            data = path.read_bytes()
            report.check(not (ARCHIVE / path.name).exists(), '旧公開保全の上書き禁止')
            (ARCHIVE / path.name).write_bytes(data)
            old_payloads[path.name] = data
            archived.append(dict(original=path.relative_to(ROOT).as_posix(), path=(ARCHIVE / path.name).relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(data).hexdigest()))
        public = json.loads(old_payloads[report.JSON_NAME].decode('utf-8'))
        report.check(report.render(public).encode('utf-8') == old_payloads[report.HTML_NAME], '旧HTMLと元表示sourceの同値')
        metrics = validate(public, diagnostic)
        old_selection = deepcopy(public['selection'])
        old_displayed = deepcopy(public['displayed'])
        body, markdown = appendix(public, diagnostic, metrics, sha)
        updated = deepcopy(public)
        updated['posthoc_S03'] = dict(source=dict(path=SOURCE.relative_to(ROOT).as_posix(), SHA256=sha), metrics=metrics,
            note='全44条件と幅の結果を見た後の注目。正式選択は変更しない。独立有効性標本ではない。')
        html = report.render(updated)
        token = '<section class="panel" id="all-sessions">'
        report.check(html.count(token) == 1, '追補挿入位置一意')
        html = html.replace(token, body + token)
        report.check(updated['selection'] == old_selection and updated['displayed'] == old_displayed, '正式候補と説明の不変更')
        readme = old_payloads['README.md'].decode('utf-8') + '\n## 事後の追補\n\n[' + MD_NAME + '](' + MD_NAME + ') とHTMLのS03章を追加しました。正式選択3候補は変えず、全44条件を見た後に注目した予兆として別扱いにします。\n'
        files = {report.JSON_NAME: json.dumps(updated, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                 report.HTML_NAME: html, 'README.md': readme, MD_NAME: markdown}
        outputs = []
        for name, text in files.items():
            data = text.encode('utf-8')
            (OUT / name).write_bytes(data)
            (report.PUBLIC / name).write_bytes(data)
            outputs.append(dict(path=(report.PUBLIC / name).relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(data).hexdigest()))
        old_manifest = json.loads(old_payloads[MANIFEST.name].decode('utf-8'))
        new_manifest = dict(old_manifest, revision=2, outputs=outputs, 原版同bytes保全=archived,
            事後追補=dict(path=SOURCE.relative_to(ROOT).as_posix(), SHA256=sha),
            append_source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 原結果再読=0, 新金融=0)
        MANIFEST.write_text(json.dumps(new_manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        proof.update(全合格=True, 限定射影SHA256=sha, metrics=metrics, 原版同bytes保全=archived,
            正式選択不変=True, 先頭3候補不変=True, outputs=outputs,
            source_SHA256=updated['source_SHA256'], append_source_SHA256=new_manifest['append_source_SHA256'])
    except BaseException as error:
        proof.update(全合格=False, error=repr(error))
        raise
    finally:
        (OUT / '事後S03追補と正式選択不変及び原版保全の証跡.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 限定射影読取=1, 元結果再読=0, 正式選択不変=True, metrics=proof['metrics']), ensure_ascii=False))


if __name__ == '__main__':
    main()
