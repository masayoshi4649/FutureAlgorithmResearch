"""金融完了後の一目的読取だけで、主候補の赤字と実約定を診断する。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
from fractions import Fraction
import gzip
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
RESULT = WORK / 'finance/結果.json'
MAIN = 'QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1'
PLAN = HERE / '損失診断の目的と一読予算の固定.json'
OUTPUT = HERE / '主候補の赤字六場と実脚及び費用の小診断.json'
SOURCE_NAMES = ('catalog.py', 'engine.py', 'artificial.py', 'input_contract.py', 'plan.py',
                'finance.py', 'artificial_root.py', 'metrics/metrics.py', 'metrics/artificial_metrics.py')


def digest(raw: bytes) -> str:
    """
    機能: 同じbytesからSHA256を計算する。
    引数: raw(bytes)。
    返り値: str は十六進指紋。原入力へアクセスしない。
    """
    return hashlib.sha256(raw).hexdigest()


def number(value: object) -> Fraction:
    """
    機能: 有限の数値を厳密な比較用数へ移す。
    引数: value(object)。
    返り値: Fraction。真偽・未知・非有限を拒否する。
    """
    assert isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    return Fraction(str(value))


def primitive(value: object) -> object:
    """
    機能: 新生成台帳から選んだ小観測だけをJSONの型へ移す。
    引数: value(object)。
    返り値: object。未知観測だけNoneとし、金額の未知は事前に拒否する。
    """
    if isinstance(value, dict):
        return {str(k): primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [primitive(v) for v in value]
    if hasattr(value, 'tolist'):
        return primitive(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write(path: Path, value: dict) -> None:
    """
    機能: 自所有域へ完成済み証跡を上書きせず保存する。
    引数: path(Path)、value(dict)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(primitive(value), ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def sources() -> dict:
    """
    機能: 完了前に指定した金融九源の指紋だけを求める。
    引数: なし。
    返り値: dict[str,str]。金融結果・台帳を読まない。
    """
    return {(WORK/name).relative_to(ROOT).as_posix(): digest((WORK/name).read_bytes()) for name in SOURCE_NAMES}


def clock(value: object) -> str | None:
    """
    機能: 保存された価格時計を日本時刻の表示へ移す。
    引数: value(object) はepoch秒又はNone。
    返り値: str|None。受信時計や真の注文応答時刻へ読み替えない。
    """
    if value is None:
        return None
    return datetime.fromtimestamp(float(number(value)), timezone(timedelta(hours=9))).isoformat()


def rank_cases(result: dict) -> list[dict]:
    """
    機能: 主候補の各商品赤字上位3場だけを決定する。
    引数: result(dict) は一読した完成金融結果。
    返り値: list[dict]。同額時は場ID順、赤字が無ければ補完しない。
    """
    selected = []
    for symbol in ('TOPIX', 'NK225'):
        own = [row for row in result['rows'] if row['case'] == MAIN and row['symbol'] == symbol]
        assert len(own) == 33 and len({row['session'] for row in own}) == 33
        bad = sorted((row for row in own if number(row['収支']) < 0), key=lambda row: (number(row['収支']), row['session']))[:3]
        for row in bad:
            pp = [p for p in result['parents'] if p['case'] == MAIN and p['symbol'] == symbol and p['session'] == row['session']]
            assert sum((number(p['net_yen']) for p in pp), Fraction()) == number(row['収支'])
            losers = sorted((p for p in pp if number(p['net_yen']) < 0), key=lambda p: (number(p['net_yen']), int(p['parent'])))[:2]
            assert losers
            selected.append(dict(symbol=symbol, session=row['session'], row=row, losing_parents=losers))
    assert len(selected) <= 6
    return selected


def decompose(legs: list[dict], snapshot: dict, symbol: str) -> dict:
    """
    機能: 保存BBOがある脚だけ中値移動と気配差負担の恒等式へ分ける。
    引数: legs(list[dict])、snapshot(dict)、symbol(str)。
    返り値: dict。途中部分返済のBBOが無い親は全分解を未測定とする。
    """
    mult = 1000 if symbol == 'TOPIX' else 10
    entry, final = snapshot['新規'], snapshot['最終返済']
    entry_mid = (number(entry['bid'])+number(entry['ask']))/2
    exit_mid = (number(final['bid'])+number(final['ask']))/2
    spread_sum = number(entry['ask'])-number(entry['bid'])+number(final['ask'])-number(final['bid'])
    # final rawseqはsnapshotだけにあり、親exitrowとは別概念なので呼出側で対象脚を渡す。
    midpoint = sum((number(leg['side'])*number(leg['q'])*mult*(exit_mid-entry_mid) for leg in legs), Fraction())
    crossing = sum((number(leg['q'])*mult*spread_sum/2 for leg in legs), Fraction())
    gross = sum((number(leg['gross_yen']) for leg in legs), Fraction())
    assert midpoint-crossing == gross
    return dict(中値差粗損益=float(midpoint), 気配差負担=float(crossing), 実粗損益=float(gross), 二重控除ではない=True)


def parent_observation(parent: dict, legs: list[dict], snapshot: dict, breakdown: dict, symbol: str) -> dict:
    """
    機能: 負け親の公開・約定・極値と、保存できる金額分解を小さく保持する。
    引数: parent/snapshot/breakdown(dict)、legs(list[dict])、symbol(str)。
    返り値: dict。極値は事後診断であり出口の実現額ではない。
    """
    own = [leg for leg in legs if int(leg['parent']) == parent['parent'] and int(leg['uid']) == parent['uid']]
    assert own and sum((number(leg['net_yen']) for leg in own), Fraction()) == number(parent['net_yen'])
    assert sum((number(leg['q']) for leg in own), Fraction()) == number(parent['quantity'])
    result = dict(parent=parent, 実返済脚=own, snapshots=snapshot,
        価格時計={key: clock(snapshot[key]['price_time_s']) for key in ('公開', '新規', '最終返済')},
        極値は事後のみ=True, MFE実現損益ではない=True)
    assert int(breakdown['parent']) == parent['parent'] and int(breakdown['uid']) == parent['uid']
    remaining = list(breakdown['legs'])
    midpoint, crossing = Fraction(), Fraction()
    for leg in own:
        matching = [i for i, point in enumerate(remaining) if
            int(point['q']) == int(leg['q']) and int(point['side']) == int(leg['side']) and
            int(point['entry_row']) == int(leg['entry_row']) and int(point['exit_row']) == int(leg['exit_row'])]
        assert matching
        point = remaining.pop(matching[0])
        side = int(leg['side'])
        assert number(point['新規']['ask' if side > 0 else 'bid']) == number(leg['entry_price'])
        assert number(point['返済']['bid' if side > 0 else 'ask']) == number(leg['exit_price'])
        component = decompose([leg], dict(新規=point['新規'], 最終返済=point['返済']), symbol)
        midpoint += number(component['中値差粗損益'])
        crossing += number(component['気配差負担'])
    assert not remaining
    assert midpoint == number(breakdown['中値差粗損益'])
    assert crossing == number(breakdown['気配差負担'])
    assert number(breakdown['手数料']) == number(parent['fee_yen'])
    assert midpoint-crossing-number(parent['fee_yen']) == number(parent['net_yen']) == number(breakdown['収支'])
    result['親全体の中値と気配差分解'] = breakdown
    result['損失の観測分類'] = dict(中値も逆行=midpoint < 0,
        中値非負だが気配差後は負=midpoint >= 0 and midpoint-crossing < 0,
        粗利非負だが料で赤字=midpoint-crossing >= 0 and number(parent['net_yen']) < 0)
    public, entry = snapshot['公開'], snapshot['新規']
    side = parent['side']
    pub_quote = number(public['ask' if side > 0 else 'bid'])
    fill_quote = number(entry['ask' if side > 0 else 'bid'])
    assert fill_quote == number(parent['entry_price'])
    result['公開から新規の不利値幅'] = float(side*(fill_quote-pub_quote))
    result['公開気配差'] = float(number(public['ask'])-number(public['bid']))
    result['新規気配差'] = float(number(entry['ask'])-number(entry['bid']))
    result['入口拡幅'] = result['新規気配差'] > result['公開気配差']
    result['粗利ピーク2T以上'] = number(parent['peak_gross_ticks']) >= 2
    return result


def ledger_trace(daily: dict, selected: list[dict]) -> dict:
    """
    機能: 選定した親だけの実注文・予約・半返済理由を台帳から抽出する。
    引数: daily(dict) は新金融台帳、selected(list[dict]) は負け親。
    返り値: dict。曲線全行を展開せず、原相場のBBOも復元しない。
    """
    assert daily['completed'] is True and daily['config']['id'] == MAIN
    ids = {p['parent'] for p in selected}
    result = {}
    for name, field_name in (('orders', 'order_fields'), ('execution_events', 'execution_fields'), ('control_events', 'control_fields')):
        names = daily[field_name]
        rows = daily[name].tolist() if hasattr(daily[name], 'tolist') else daily[name]
        assert len(names) == len(set(names))
        mapped = [dict(zip(names, row)) for row in rows]
        assert all(len(row) == len(names) for row in rows)
        result[name] = [row for row in mapped if int(row['parent']) in ids]
    reasons = Counter(int(row['reason']) for row in result['orders'] if int(row['new']) == 0)
    result['返済理由の注文数'] = {str(code): dict(名称=daily['reason_labels'][code], 注文数=count) for code, count in sorted(reasons.items())}
    result['実半返済注文数'] = sum(int(row['new']) == 0 and int(row['reason']) == 143 for row in result['orders'])
    for parent in selected:
        matching = [p for p in daily['parent'] if p['parent'] == parent['parent'] and p['uid'] == parent['uid']]
        assert len(matching) == 1
        assert all(number(matching[0][key]) == number(parent[key]) for key in ('quantity', 'gross_yen', 'fee_yen', 'net_yen'))
    return result


def fixed_comparisons(result: dict) -> dict:
    """
    機能: 全十二条件の実成績と、主候補が別条件の黒字を失う場を記録する。
    引数: result(dict)。
    返り値: dict。親削除推定・同じ親の因果効果へ読み替えない。
    """
    cases = [item['id'] for item in result['configs']]
    assert len(cases) == len(set(cases)) == 12
    out = {}
    for symbol in ('TOPIX', 'NK225'):
        main_rows = {row['session']: row for row in result['rows'] if row['case'] == MAIN and row['symbol'] == symbol}
        own = {}
        for cid in cases:
            rr = [row for row in result['rows'] if row['case'] == cid and row['symbol'] == symbol]
            assert len(rr) == 33
            lost = [dict(session=row['session'], 別条件net=row['収支'], 主候補net=main_rows[row['session']]['収支'])
                    for row in rr if number(row['収支']) > 0 and number(main_rows[row['session']]['収支']) <= 0]
            own[cid] = dict(利益=float(sum((number(row['利益']) for row in rr), Fraction())),
                損失=float(sum((number(row['損失']) for row in rr), Fraction())),
                収支=float(sum((number(row['収支']) for row in rr), Fraction())),
                親数=sum(int(row['親数']) for row in rr), 黒字場数=sum(number(row['収支']) > 0 for row in rr),
                主候補で黒字でなくなった実場=lost)
        out[symbol] = own
    return out


def explanation(data: dict) -> str:
    """
    機能: 具体的な負け親の金額と価格時計を、未測定の予防案と区別して短く書く。
    引数: data(dict) は完成した小診断。
    返り値: str は日本語Markdown。未来極値を救済PLにしない。
    """
    lines = ['# 主候補の損失と未検証の予防案', '',
        '対象はC入口・半分返済＋追尾の、各商品赤字上位3場と各場負け親上位2。全体から選んだ損失診断であり、未知データの有効性試験ではない。', '',
        '| 商品・場 | 場net | 中値差粗損益 | 気配差負担 | 手数料 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for scene in data['対象']:
        values = scene['場の金額分解']
        lines.append(f"| {scene['symbol']} {scene['session']} | {values['収支']:,.0f} | {values['中値差粗損益']:,.0f} | {values['気配差負担']:,.0f} | {values['手数料']:,.0f} |")
    lines += ['', '中値差−気配差負担−手数料＝net。気配差は実約定粗損益の恒等分解であり、別途二重に控除する費用ではない。', '']
    for scene in data['対象']:
        for obs in scene['負け親']:
            p = obs['parent']
            kinds = '・'.join(key for key, value in obs['損失の観測分類'].items() if value)
            lines.append(f"- {scene['symbol']} {scene['session']} 親{p['parent']}：公開{obs['価格時計']['公開']}、"
                f"新規{obs['価格時計']['新規']}、最終返済{obs['価格時計']['最終返済']}。"
                f"net {p['net_yen']:,.0f}円。{kinds}。粗値幅ピーク{p['peak_gross_ticks']:g}Tは事後観測で、実現利益ではない。")
    lines += ['', '## 先着率と利益の違い', '',
        '114は公開した両気配から±1Tのどちらが先かを測った。今回は判断後の成行新規価格を起点に、2T半返済と追尾・損切りを実注文へ接続している。'
        '最初の1Tが既に進んだ後で新規になること、入口と返済の気配差、1Tを越えた後の反転を区別する必要がある。'
        'この診断だけでは各約80%の観測と各実親を同一対応させた到達確率は未測定。', '',
        '## 次の予防仮説（未検証）', '',
        '- 公開から新規へ不利に動いた例は、価格上限又は拡幅時取消しを対照候補にする。旧親を削除して改善額とはせず、未約定後の再参加を含む新運転が必要。',
        '- 中値自体が逆行した例は、数量条件を強めるだけでなく保有中の両気配の回復失敗を調べる。後の最安値・最高値から出口を決めない。',
        '- 順行後に損失化した例は、半返済の判断から実約定までの変化と残玉の追尾を分ける。利幅縮小で失う回復勝ちも全十二実運転の対照で確認する。', '',
        '公開・新規・各返済のBBO/Q/原seqは小診断JSONに保存。時刻はCurrentPriceTime代理であり、真の受信順・補充・焦りの証明ではない。'
        '原入力・114のevent・旧金融の追加読取も、新たな金融再生も行っていない。', '']
    return '\n'.join(lines)


def prepare() -> None:
    """
    機能: 結果本文を読まずに診断目的・対象選定と読取予算を固定する。
    引数: なし。
    返り値: None。
    """
    assert not PLAN.exists()
    write(PLAN, dict(状態='SOURCE_ONLY準備。金融完了通知と結果SHAの明示後だけ実行。', 主候補=MAIN,
        source_SHA256=sources(), 診断source_SHA256=digest(Path(__file__).read_bytes()),
        結果予定=RESULT.relative_to(ROOT).as_posix(), 結果最大bytes=64*1024*1024,
        対象選定='主候補各商品・実net赤字上位3場、各場負け親上位2。同額は場/親ID順。0〜6場で補完なし。',
        読取予算=dict(完成金融結果=1, 選定場の新金融台帳='各一回・最大6', 原NPZ=0, 保存eventNPZ=0,
                      旧金融=0, 原板=0, API=0),
        保存='一読bytesをSHA照合・私有保全してからparse。台帳は金融出力配下かつ保存目録SHA/bytes一致のみ。',
        分析='場のmidgross−spread−fee恒等式。各負け親の公開/新規/最終返済時刻BBO/Q、MFE/MAE、半分/理由/予約と実返済脚。',
        制限='根が金融前に追加したparent_breakdownの各脚BBOへ結び、部分返済を含む全親を分解。極値は事後診断のみ。',
        対照='十二実運転の集計と場差だけ。親削除/同一親反実仮想ではない。新しい予防仮説は未測。'))


def run(expected_sha: str) -> None:
    """
    機能: 根の完了通知後に結果一読と選定新台帳最大六読を実施し、小診断を保存する。
    引数: expected_sha(str) は根が指定した完成結果SHA256。
    返り値: None。金融の再実行は行わない。
    """
    assert len(expected_sha) == 64 and all(c in '0123456789abcdef' for c in expected_sha)
    assert not OUTPUT.exists()
    fixed = json.loads(PLAN.read_text(encoding='utf-8'))
    assert sources() == fixed['source_SHA256']
    assert digest(Path(__file__).read_bytes()) == fixed['診断source_SHA256']
    before = RESULT.stat()
    assert before.st_size <= fixed['結果最大bytes']
    raw = RESULT.read_bytes()
    after = RESULT.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    assert digest(raw) == expected_sha
    copied = HERE / '完成結果の同bytes私有コピー.json'
    assert not copied.exists()
    copied.write_bytes(raw)
    result = json.loads(raw.decode('utf-8'))
    assert result['全合格'] is True and result['金融'] is True and result['主候補'] == MAIN
    assert result['source_SHA256'] == fixed['source_SHA256']
    selected = rank_cases(result)
    out, seen_ledgers = [], set()
    for case in selected:
        symbol, session = case['symbol'], case['session']
        diagnostic = [d for d in result['diagnostics'] if d['case'] == MAIN and d['symbol'] == symbol and d['session'] == session]
        assert len(diagnostic) == 1
        diagnostic = diagnostic[0]
        assert number(diagnostic['中値差粗損益'])-number(diagnostic['気配差負担'])-number(diagnostic['手数料']) == number(diagnostic['収支']) == number(case['row']['収支'])
        ll = [leg for leg in result['actual_legs'] if leg['case'] == MAIN and leg['symbol'] == symbol and leg['session'] == session]
        observations = []
        for parent in case['losing_parents']:
            snap = [s for s in diagnostic['snapshots'] if s['parent'] == parent['parent'] and s['uid'] == parent['uid']]
            assert len(snap) == 1
            breakdown = [p for p in diagnostic['parent_breakdown'] if p['parent'] == parent['parent'] and p['uid'] == parent['uid']]
            assert len(breakdown) == 1
            observations.append(parent_observation(parent, ll, snap[0], breakdown[0], symbol))
        locators = [item for item in result['ledgers'] if item['case'] == MAIN and item['symbol'] == symbol and item['session'] == session]
        assert len(locators) == 1
        info = locators[0]
        path = (ROOT / info['path']).resolve()
        assert path.is_relative_to((WORK/'finance/ledgers').resolve()) and path not in seen_ledgers
        seen_ledgers.add(path)
        assert path.stat().st_size == info['bytes']
        ledger_raw = path.read_bytes()
        assert len(ledger_raw) == info['bytes'] and digest(ledger_raw) == info['SHA256']
        destination = HERE / 'ledger_copies' / (session+'_'+symbol+'.pkl.gz')
        destination.parent.mkdir(exist_ok=True)
        assert not destination.exists()
        destination.write_bytes(ledger_raw)
        daily = pickle.loads(gzip.decompress(ledger_raw))
        trace = ledger_trace(daily, case['losing_parents'])
        out.append(dict(symbol=symbol, session=session, row=case['row'], 場の金額分解={k:diagnostic[k] for k in
            ('中値差粗損益','気配差負担','手数料','収支')}, 負け親=observations, 台帳目録=info, 実注文経過=trace))
        del daily, ledger_raw
    assert len(seen_ledgers) <= 6 and sources() == fixed['source_SHA256']
    completed = dict(全合格=True, 結果SHA256=expected_sha, 診断計画SHA256=digest(PLAN.read_bytes()),
        source_SHA256=fixed['source_SHA256'], 対象=out, 十二条件の実運転対照=fixed_comparisons(result),
        読取=dict(完成結果=1, 新金融台帳=len(seen_ledgers), 原NPZ=0, eventNPZ=0, 旧金融=0, 原板=0, API=0),
        注意='先着1Tの率は利益・約定率ではない。中値差/交差/料は実grossの恒等分解で二重費用ではない。極値は未来診断だけ。')
    write(OUTPUT, completed)
    md = HERE / '具体損失と未検証の予防仮説.md'
    assert not md.exists()
    md.write_text(explanation(completed), encoding='utf-8')
    print(json.dumps(dict(全合格=True, 対象場=len(out), 新金融台帳読=len(seen_ledgers), SHA256=digest(OUTPUT.read_bytes())), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--root-result-sha')
    arguments = parser.parse_args()
    assert arguments.prepare_only != bool(arguments.root_result_sha)
    if arguments.prepare_only:
        prepare()
    else:
        run(arguments.root_result_sha)
