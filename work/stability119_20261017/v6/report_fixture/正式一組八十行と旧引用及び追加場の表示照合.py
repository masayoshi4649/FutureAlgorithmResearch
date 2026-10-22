"""生成後の小会計と保全コピーだけで、旧六十六引用と追加十四口座の表示を照合する。"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
V6 = HERE.parent
BASE = V6.parent
ROOT = BASE.parents[1]
PUBLIC = BASE / 'privatev6/public'
METHOD = 'E01_006_FIXED'
HTML_NAME = '少額E01固定設定と追加七場を含む全セッション損益.html'
REPORT_SHA = '19de233d6b9835a45c43572e1b68b6a7133715211d6fc179e78185ca8614cfa3'
COUNTS = Counter()


def check(value: bool, label: str) -> None:
    """
    機能: 元会計・独立再加算と表示の一致を記録する。
    引数: value(bool)は期待、label(str)は検査名。
    返り値: None。不一致なら停止する。
    """
    assert value, label
    COUNTS[label] += 1


def near(a: float | None, b: float | None) -> bool:
    """
    機能: 未保存と微小金額差を区別して比較する。
    引数: a/b(float|None)は比較値。
    返り値: boolは一致。金融の金額は変更しない。
    """
    return a is b if a is None or b is None else math.isclose(a, b, rel_tol=0, abs_tol=1e-5)


def fmt(value: float | None, signed: bool = False) -> str:
    """
    機能: 表示の期待文字列を独立に作る。
    引数: value(float|None)は数値、signed(bool)は符号指定。
    返り値: strは金額又は未保存。
    """
    if value is None:
        return '未保存'
    if abs(value) <= 1e-7:
        return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def summary_cells(m: dict) -> list[str]:
    """
    機能: 独立再加算した集計を表の列順へ並べる。
    引数: m(dict)は商品一期間の集計。
    返り値: list[str]は表の期待セル。
    """
    return [fmt(m['profit']), fmt(m['loss']), fmt(m['net'], True), f"{m['black']}/{m['red']}/{m['inactive']}",
        fmt(m['mean'], True), fmt(m['median'], True), fmt(m['worst'], True), fmt(m['top3_removed'], True),
        fmt(m['fees']), fmt(m['winning_lots']) + '/' + fmt(m['losing_lots']), str(m['parents']),
        '—' if m['share'] is None else f"{m['share'] * 100:.1f}%", str(m['unclosed_sessions']), str(m['unclosed_unknown_sessions'])]


def independently_sum(rows: list[dict]) -> dict:
    """
    機能: 表示器を呼ばず、一期間の金額と黒赤無・外れ値依存を再計算する。
    引数: rows(list[dict])は保存された完結親の場集計。
    返り値: dictは未保存終端数量と旧完了保証を分離した集計。
    """
    ns = [r['net'] for r in rows]
    green = [r['net'] for r in rows if r['campaigns'] and r['net'] > 1e-7]
    red = [-r['net'] for r in rows if r['campaigns'] and r['net'] < -1e-7]
    p, loss = sum(r['profit'] for r in rows), sum(r['loss'] for r in rows)
    return dict(net=sum(ns), profit=p, loss=loss, fees=sum(r['fees'] for r in rows),
        parents=sum(r['campaigns'] for r in rows), wins=sum(r['winning_campaigns'] for r in rows),
        losses=sum(r['losing_campaigns'] for r in rows), winning_lots=sum(r['winning_lots'] for r in rows),
        losing_lots=sum(r['losing_lots'] for r in rows), sessions=len(rows), black=len(green), red=len(red),
        inactive=sum(r['campaigns'] == 0 for r in rows), mean=statistics.mean(ns), median=statistics.median(ns),
        worst=min(ns), top3_removed=sum(ns) - sum(sorted(green, reverse=True)[:3]), share=p / (p + loss) if p + loss else None,
        unclosed_sessions=sum(bool(r['unclosed']) for r in rows if r['unclosed'] is not None),
        unclosed_unknown_sessions=sum(r['unclosed'] is None for r in rows))


def main() -> None:
    """
    機能: 正式生成物の全八十行・合計と自己保全コピーを一回だけ照合する。
    引数: CLI --expected-sha256(str)は根が指定した完成結果SHA。
    返り値: None。元結果・原市場・金融再生は追加しない。
    """
    p = argparse.ArgumentParser()
    p.add_argument('--expected-sha256', required=True)
    args = p.parse_args()
    target = HERE / '正式八十行と旧終端委譲及び追加七場の実表示照合.json'
    stats_path = BASE / 'privatev6/固定一組の全四十旧三十三追加七の小集計.json'
    assert not target.exists() and not stats_path.exists()
    names = ('data.json', HTML_NAME, 'README.md', '生成証跡.json')
    payloads = {n: (PUBLIC / n).read_bytes() for n in names}
    public = json.loads(payloads['data.json'])
    generated = json.loads(payloads['生成証跡.json'])
    page = BeautifulSoup(payloads[HTML_NAME].decode('utf8'), 'html.parser')
    check(generated['passed'] and generated['fixture'] is False and generated['result_sha256'] == args.expected_sha256,
          '正式会計で合成物との混同なし')
    check(generated['report_sha256'] == REPORT_SHA == hashlib.sha256((V6 / 'report_v6.py').read_bytes()).hexdigest(),
          '凍結表示源一致')
    for name, expected in generated['artifacts'].items():
        check(hashlib.sha256(payloads[name]).hexdigest() == expected, '正式生成物指紋')
    check(generated['reused_account_rows'] == 66 and generated['new_accounts'] == 14, '旧引用六十六と新十四')
    own = BASE / 'privatev6/received/少額E01固定二設定の追加七場と全四十場.json'
    source_bytes = own.read_bytes()
    check(hashlib.sha256(source_bytes).hexdigest() == args.expected_sha256, '保全コピー同bytes')
    source = json.loads(source_bytes.decode('utf8'))
    check(public['source_SHA256'] == args.expected_sha256 and public['economic_source_SHA256'] == source['source_SHA256'],
          '完成会計の源結合')
    scenes, new = public['sessions'], public['new_sessions']
    check(scenes == source['sessions'] and len(scenes) == 40 and len(new) == 7 and new == source['new_sessions'], '四十場と追加七場の固定')
    check(scenes[0] == '2026-09-21_Day' and scenes[-1] == '2026-10-16_Night', '正式期間を合成日付へ置換しない')
    check(public['old_reference'] == source['old_reference'] and public['old_flat_basis']['SHA256'] ==
          'cad15e47f14e6e4ff526019437c440e0f9cad023369e420deb0c13a8a633f431', '旧引用と終端SOURCE委譲')
    case = public['cases'][METHOD]
    check(public['main_ids'] == [METHOD] and len(case['rows']) == 80, '商品別固定二設定を一組として掲載')
    rows = {(r['symbol'], r['session']): r for r in source['rows']}
    check(len(rows) == 80 and all(rows[r['symbol'], r['session']] == r for r in case['rows']), '元八十行を同値保存')
    check(sum(r['origin'] == '旧33保存会計の引用' for r in rows.values()) == 66 and
          sum(r['origin'] == '追加七場の新金融' for r in rows.values()) == 14, '新金融口座数を水増ししない')
    check(all(r['unclosed'] is None and r['verified_flat'] is True for r in rows.values() if r['session'] not in new),
          '旧数量null維持と旧終了保証を別保存')
    check(all(r['unclosed'] == 0 for r in rows.values() if r['session'] in new), '追加十四の実終端')
    periods = (('全40', scenes), ('旧33引用', [s for s in scenes if s not in new]), ('追加7新規', new))
    stats = {}
    for symbol in ('TOPIX', 'NK225'):
        stats[symbol] = {}
        for label, ss in periods:
            m = independently_sum([rows[symbol, scene] for scene in ss])
            shown = case['metrics'][symbol] if label == '全40' else case['periods'][label][symbol]
            for key, expected in m.items():
                check(near(shown[key], expected), '商品全期旧新の独立再加算')
            check(shown['verified_flat'] is True and shown['zero_lots'] is None, '終了委譲と未保存零枚数の分離')
            stats[symbol][label] = m
    summary = page.select('table.summary tbody tr')
    check(len(summary) == 2, '全四十場の商品二行')
    for tr, symbol in zip(summary, ('TOPIX', 'NK225')):
        check([c.get_text(strip=True) for c in tr.select('td')] == summary_cells(stats[symbol]['全40']), '主表の独立期待')
    periods_table = page.select('table.periods tbody tr')
    check(len(periods_table) == 4, '旧新商品四行')
    for tr, (label, symbol) in zip(periods_table, ((l, s) for l in ('旧33引用', '追加7新規') for s in ('TOPIX', 'NK225'))):
        check([c.get_text(strip=True) for c in tr.select('td')] == summary_cells(stats[symbol][label]), '旧新表の独立期待')
    trs = page.select('table.sessions tbody tr')
    check(len(trs) == 80, '正式全八十行')
    for tr, (scene, symbol) in zip(trs, ((t, s) for t in scenes for s in ('TOPIX', 'NK225'))):
        r = rows[symbol, scene]
        expected = [symbol, '追加7' if scene in new else '旧33引用', fmt(r['profit']), fmt(r['loss']), fmt(r['net'], True),
            fmt(r['fees']), fmt(r['winning_lots']), fmt(r['losing_lots']), str(r['campaigns']), fmt(r['unclosed'])]
        check(tr['data-session'] == scene and tr['data-symbol'] == symbol and [c.get_text(strip=True) for c in tr.select('td')] == expected,
              '八十行の金額手数料枚数親と終端表示')
    for tr, symbol in zip(page.select('table.sessions tfoot tr'), ('TOPIX', 'NK225')):
        m = stats[symbol]['全40']
        expected = [symbol, '旧33＋追加7', fmt(m['profit']), fmt(m['loss']), fmt(m['net'], True), fmt(m['fees']),
            fmt(m['winning_lots']), fmt(m['losing_lots']), str(m['parents']), '未保存あり']
        check([c.get_text(strip=True) for c in tr.select('td')] == expected, '全場合計フッター')
    qualified = all(m['net'] > 0 and m['median'] > 0 and m['top3_removed'] > 0 for m in (stats[s]['全40'] for s in stats))
    check(public['qualification_count'] == int(qualified), '厳密な両商品資格')
    text = page.get_text(' ', strip=True)
    check('低活動による中央値0円と赤字は区別します' in text and '新たな実行は追加7場14口座だけ' in text,
          '低活動と引用の限界')
    check('verified_flat=True' in text and '今回旧全曲線を再監査した意味ではありません' in text, '旧完了源への委譲説明')
    check('商品別の閾値が異なる' in text and '実小型商品の最小呼値と混同しません' in text, '別商品設定と観測呼値')
    check(page.select_one('meta[name=viewport]') is not None and not page.select('script[src],img[src]'), '画面幅対応と外部通信なし')
    small = dict(scope='全四十場のうち旧三十三は保存引用、新七場十四口座だけ追加金融。', result_sha256=args.expected_sha256,
        qualification_count=int(qualified), cases=stats, old_flat_basis=public['old_flat_basis'],
        read_scope=dict(元結果追加読取=0,自身同bytesコピー=1,生成小会計=1,市場入力=0,金融再生=0,API=0))
    stats_path.write_text(json.dumps(small, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    proof = dict(passed=True, scope='正式公開小会計の再加算とHTML全八十行。新金融又は旧全曲線の再監査ではない。',
        counts=dict(COUNTS), total_checks=sum(COUNTS.values()), result_sha256=args.expected_sha256,
        HTML_SHA256=hashlib.sha256(payloads[HTML_NAME]).hexdigest(), accounting_SHA256=hashlib.sha256(payloads['data.json']).hexdigest(),
        report_SHA256=REPORT_SHA, stats_path=stats_path.relative_to(ROOT).as_posix(),
        stats_sha256=hashlib.sha256(stats_path.read_bytes()).hexdigest(), read_scope=small['read_scope'])
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(passed=True, checks=sum(COUNTS.values()), proof_SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
                         stats_SHA256=proof['stats_sha256'], cases=stats), ensure_ascii=False))


if __name__ == '__main__':
    main()
