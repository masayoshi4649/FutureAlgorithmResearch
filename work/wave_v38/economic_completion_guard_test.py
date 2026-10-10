"""状態不適合の隠蔽・証拠混同・経済資料破損を公表ガードが拒否するか検査する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import pickle
from unittest.mock import patch

import economic_completion_guard as guard


def preservation() -> dict:
    """機能: 原ガードの経済・因果・波・境界改訂照合が変更されていないか確認する。

    引数: なし。返り値: 保持された検査区間の証跡(dict)。
    """
    runner = guard.runner
    old = (runner.HERE/'completion_guard.py').read_text(encoding='utf-8')
    new = (runner.HERE/'economic_completion_guard.py').read_text(encoding='utf-8')
    old_ast, new_ast = ast.parse(old), ast.parse(new)
    functions = lambda root: {n.name:n for n in root.body if isinstance(n,ast.FunctionDef)}
    assert ast.dump(functions(old_ast)['cash_revision']) == ast.dump(functions(new_ast)['cash_revision'])
    regions = (
        ("        assert causal['全合格']", "        expected_ids ="),
        ("            for proof in detail['検査']:", "            causal_path ="),
        ("            causal_path =", "        for name in records:"),
        ("    ledgers={", "    final ="))
    for begin,end in regions:
        a = old[old.index(begin):old.index(end,old.index(begin))]
        b = new[new.index(begin):new.index(end,new.index(begin))]
        assert a == b,begin
    assert '(25324,3918,7792)' in new and "['原本78SHA256']" in new
    assert 'verification=True' not in new
    return dict(元境界改訂照合AST一致=True,経済詳細因果波暫定判定の四区間全文一致=True,
        全入力件数条件維持=True,原本78照合維持=True,採否verificationTrue呼出なし=True)


def main() -> None:
    """機能: 完成済み主証拠のメモリ複写だけを壊し、正式保存せず検査する。

    引数: なし。返り値: なし(None)。未完成補助を仮造して全完備とはしない。
    """
    runner, economic = guard.runner, guard.economic
    read, digest = runner.read, runner.digest
    cache = {}

    def cached(path: object) -> str:
        """機能: 不変の実物指紋を人工試験中だけ再利用する。

        引数: path(Path)。返り値: SHA256(str)。
        """
        if path not in cache: cache[path] = digest(path)
        return cache[path]

    fixed = read(runner.HERE/'探索条件の固定.json')
    raw = pickle.loads((runner.HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    times = {k:v['time_s'] for k,v in raw.items()}
    count = sum(len(t) for t in times.values())
    del raw
    cash = read(runner.HERE/'adaptive_accounting_diagnostic.json')
    original = next(c for c in cash['条件'] if c['証拠種別'] == economic.ORIGINAL)
    diagnostic = next(c for c in cash['条件'] if c['証拠種別'] == economic.DIAGNOSTIC)
    details = {c['id']:read(runner.ROOT/c['実体']) for c in (original,diagnostic)}
    selected = {s['id']:s for s in fixed['conditions']}
    provisional = read(runner.HERE/'暫定判定.json')
    passed = preservation()
    with patch.object(runner,'digest',cached):
        economic.cash_header(cash,fixed['conditions'],count,{})
        economic.diagnostic_fixed(fixed,{})
        for c in (original,diagnostic):
            economic.detail_path(runner.HERE,c,selected[c['id']])
            economic.detail_state(c,details[c['id']],times)
        issues = economic.detail_state(diagnostic,details[diagnostic['id']],times)
        final = economic.final_flags(provisional,issues)
    assert final['経済検証完了'] is True and final['実装状態契約合格'] is False
    assert final['監査完了'] is False and final['既知比較の採用候補'] is False
    assert {k:v for k,v in final.items() if k in provisional} == provisional
    cases = []

    def expect(label: str, call: object) -> None:
        """機能: 一種類の人工破損が拒否されることを記録する。

        引数: label(str)、call(callable)。返り値: なし(None)。
        """
        try: call()
        except (AssertionError,KeyError,FileNotFoundError): pass
        else: raise AssertionError('破損を拒否しませんでした: '+label)
        cases.append(dict(破損=label,拒否=True))

    # ----------------------------------------
    # 集約層の件数、経済合格、状態の偽装、原版と診断版の件数を壊す。
    mutations = (
        ('経済不合格','経済全合格',False),('未完成診断','全範囲診断完了',False),
        ('条件数欠落','対象条件数',205),('口座数欠落','全入力数',5355),
        ('原本行数欠落','全原本行会計数',0),('状態全合格偽装','状態全合格',True),
        ('完全合格偽装','全監査合格',True),('状態差件数隠蔽','状態不一致行数',0),
        ('状態差条件隠蔽','状態不適合条件数',0),('原版成功水増し','原版成功条件数',206),
        ('診断版脱落','診断版条件数',0),('監査固定誤り','監査固定SHA256','0'*64),
        ('診断固定誤り','診断固定SHA256','0'*64),('診断専用偽装','診断専用',False),
        ('完全合格と誤認','完全合格又は実運用可能を意味しない',False))
    with patch.object(runner,'digest',cached):
        for label,key,value in mutations:
            changed = deepcopy(cash); changed[key] = value
            expect(label,lambda x=changed:economic.cash_header(x,fixed['conditions'],count,{}))
        for mode in ('欠落','重複','経済false','指紋改変'):
            changed = deepcopy(cash)
            if mode == '欠落': changed['条件'].pop()
            elif mode == '重複': changed['条件'][0] = deepcopy(changed['条件'][1])
            elif mode == '経済false': changed['条件'][0]['経済監査合格'] = False
            else: changed['参照SHA256'][next(iter(changed['参照SHA256']))] = '0'*64
            expect('集約証拠'+mode,lambda x=changed:economic.cash_header(x,fixed['conditions'],count,{}))
        for label,key,value in (
            ('証拠種別偽装','証拠種別','不明'),('証拠パス混同','実体',original['実体']),
            ('実体SHA改変','実体SHA256','0'*64),('実体別ID','id',original['id']),
            ('証拠診断固定違い','診断固定SHA256','0'*64)):
            changed = deepcopy(diagnostic); changed[key] = value
            expect(label,lambda x=changed:economic.detail_path(runner.HERE,x,selected[diagnostic['id']]))
        changed = deepcopy(original); changed['原版phase比較も全行一致'] = False
        expect('原版状態検査脱落',lambda:economic.detail_path(runner.HERE,changed,selected[original['id']]))
    # ----------------------------------------
    # 明細層の12行を削除、重複、時刻変更、false消去などで壊す。
    for mode in ('口座欠落','口座重複','状態合格偽装','全体合格偽装','行脱落','行重複','時刻改変',
                 '原本外行','実状態と期待同値','予算なしへ改変','復元資格矛盾','列欠落','未分類型'):
        detail = deepcopy(details[diagnostic['id']]); cert = deepcopy(diagnostic)
        proof = next(p for p in detail['検査'] if p['状態不一致行数'])
        row = proof['状態不一致'][0]
        if mode == '口座欠落': detail['検査'].pop()
        elif mode == '口座重複': detail['検査'][0] = deepcopy(detail['検査'][1])
        elif mode == '状態合格偽装': proof['状態契約合格'] = True
        elif mode == '全体合格偽装': detail['全監査合格'] = True
        elif mode == '行脱落': proof['状態不一致'].pop()
        elif mode == '行重複': proof['状態不一致'][1] = deepcopy(row)
        elif mode == '時刻改変': row['時刻秒'] += 1
        elif mode == '原本外行': row['row'] = len(times[(proof['session'],proof['symbol'])])
        elif mode == '実状態と期待同値': row['実状態'] = row['期待状態']
        elif mode == '予算なしへ改変': row['実予算予約'] = False
        elif mode == '復元資格矛盾': row['復元資格枚数'] = 2
        elif mode == '列欠落': row.pop('期待状態')
        else:
            row['実状態'] = 9; row['既知の取消後残存型'] = False
            proof['既知残存型に限定'] = False; detail['既知残存型に限定'] = False; cert['既知残存型に限定'] = False
        expect('状態明細'+mode,lambda c=cert,d=detail:economic.detail_state(c,d,times))
    expect('既知12行を消した最終判定',lambda:economic.final_flags(provisional,issues[:-1]))
    for key in ('監査完了','既知比較の採用候補'):
        changed = deepcopy(provisional); changed[key] = True
        expect('暫定'+key+'偽装',lambda x=changed:economic.final_flags(x,issues))
    # ----------------------------------------
    # 元ガードから全文保持したcash改訂チェックも実物のメモリ破損で確認する。
    for mode in ('改訂未完了','旧結果同値不合格','旧結果1資料脱落'):
        def changed_read(path: object) -> object:
            """機能: 原資料を変更せずcash改訂の読取値だけ破損する。

            引数: path(Path)。返り値: メモリ上の資料(object)。
            """
            value = deepcopy(read(path))
            if mode == '改訂未完了' and path.name == 'adaptive_cash_revision_ready.json': value['再起動可能'] = False
            if path.name == 'adaptive_cash_revision_results.json':
                if mode == '旧結果同値不合格': value['全数値一致'] = False
                if mode == '旧結果1資料脱落': value['参照SHA256'].pop(next(iter(value['参照SHA256'])))
            return value
        with patch.object(runner,'read',changed_read),patch.object(runner,'digest',cached):
            expect(mode,lambda:guard.cash_revision({}))
    assert len(cases) >= 30
    runner.save(runner.HERE/'economic_completion_guard_test.json',dict(全合格=True,破損拒否数=len(cases),検査=cases,
        元ガード照合保持=passed,主証拠205原版と1診断の集約確認=True,既知状態12行の全照合=True,
        未完成補助の全完備検査は未実施=True,正式判定出力=False,売買再生=False,保存資料変更=False,
        ガードSHA256=digest(runner.HERE/'economic_completion_guard.py'),
        補助SHA256=digest(runner.HERE/'economic_completion_checks.py'),
        試験SHA256=digest(runner.HERE/'economic_completion_guard_test.py')))
    print('経済専用ガード破損拒否',len(cases),'正式出力なし',flush=True)


if __name__ == '__main__':
    main()
