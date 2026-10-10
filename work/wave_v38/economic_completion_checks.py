"""経済診断の証拠種別と、消してはならない状態契約違反を検証する。"""

from __future__ import annotations

from copy import deepcopy
import math

import adaptive_runner as runner

ORIGINAL = '原版全検査合格'
DIAGNOSTIC = '診断版全経済検査'
KNOWN_ID = 'H019__B00_T120_F25_N3__R1__L015'


def references(values: dict, reference: dict) -> None:
    """機能: 全参照の実在内容指紋を照合し完備証拠へ追加する。

    引数: values/reference(dict)。返り値: なし(None)。
    """
    assert values
    for relative, sha in values.items():
        path = (runner.ROOT/relative).resolve()
        assert path.is_relative_to(runner.ROOT.resolve())
        assert runner.digest(path) == sha, relative
        reference[relative] = sha


def diagnostic_fixed(fixed: dict, reference: dict) -> None:
    """機能: 状態欠陥判明後の診断版と、原監査失敗を明示して結ぶ。

    引数: fixed/reference(dict)。返り値: なし(None)。
    """
    path = runner.HERE/'adaptive_accounting_diagnostic_fixed.json'
    value = runner.read(path)
    assert value['診断専用'] is True and value['既知状態不適合の後の固定'] is True
    assert value['探索前固定ではない'] is True
    assert value['主対象'] == fixed['conditions'] and value['補助対象'] == fixed['supplementary_conditions']
    assert (value['主条件数'], value['補助条件数']) == (206,768)
    assert value['原監査固定SHA256'] == runner.digest(runner.HERE/'adaptive_accounting_fixed.json')
    assert value['採否規則変更'] is False and value['売買コード変更'] is False
    assert value['API取得数'] == 0 and value['現在保存物使用'] is False
    references(value['参照SHA256'], reference)
    failed_path = runner.HERE/'adaptive_accounting_failed_run.json'
    failed = runner.read(failed_path)
    assert failed['監査プロセス終了'] is True and failed['終了コード'] == 1
    for p in (path,failed_path): reference[p.relative_to(runner.ROOT).as_posix()] = runner.digest(p)


def cash_header(cash: dict, specs: list, all_raw_rows: int, reference: dict) -> None:
    """機能: 経済・状態の集約が全証拠の合否と一致するか検査する。

    引数: cash/reference(dict)、specs(list)、all_raw_rows(int)。返り値: なし(None)。
    """
    assert cash['全範囲診断完了'] is True and cash['経済全合格'] is True
    assert cash['対象条件数'] == len(specs) and cash['全入力数'] == len(specs)*26
    assert cash['全原本行会計数'] == len(specs)*all_raw_rows
    assert cash['診断専用'] is True and cash['完全合格又は実運用可能を意味しない'] is True
    assert cash['監査固定SHA256'] == runner.digest(runner.HERE/'adaptive_accounting_fixed.json')
    assert cash['診断固定SHA256'] == runner.digest(runner.HERE/'adaptive_accounting_diagnostic_fixed.json')
    certificates = cash['条件']
    assert len(certificates) == len(specs) and {c['id'] for c in certificates} == {s['id'] for s in specs}
    assert all(c['経済監査合格'] is True for c in certificates)
    assert all(type(c['状態契約合格']) is bool for c in certificates)
    assert cash['状態全合格'] is all(c['状態契約合格'] for c in certificates)
    assert cash['全監査合格'] is cash['状態全合格']
    assert cash['状態不適合条件数'] == sum(not c['状態契約合格'] for c in certificates)
    assert cash['状態不一致行数'] == sum(c['状態不一致行数'] for c in certificates)
    assert cash['原版成功条件数'] == sum(c['証拠種別'] == ORIGINAL for c in certificates)
    assert cash['診断版条件数'] == sum(c['証拠種別'] == DIAGNOSTIC for c in certificates)
    assert cash['原版成功条件数'] + cash['診断版条件数'] == len(specs)
    assert cash['既知残存型に限定'] is all(c['既知残存型に限定'] for c in certificates)
    assert cash['既知残存型に限定'] is True, '未分類の状態欠陥を経済完備へ混入しない'
    references(cash['参照SHA256'], reference)


def detail_path(directory: object, certificate: dict, spec: dict) -> object:
    """機能: 証拠種別に対応する唯一の保存先と指紋を検査する。

    引数: directory(Path)、certificate/spec(dict)。返り値: 証拠パス(Path)。
    """
    kind = certificate['証拠種別']
    assert kind in (ORIGINAL, DIAGNOSTIC)
    folder = 'adaptive_accounting_details' if kind == ORIGINAL else 'adaptive_accounting_diagnostic_details'
    path = directory/folder/(spec['id']+'.json.gz')
    assert certificate['id'] == spec['id']
    assert certificate['実体'] == path.relative_to(runner.ROOT).as_posix()
    assert certificate['実体SHA256'] == runner.digest(path)
    if kind == ORIGINAL:
        assert certificate['原版phase比較も全行一致'] is True
    else:
        assert certificate['診断固定SHA256'] == runner.digest(runner.HERE/'adaptive_accounting_diagnostic_fixed.json')
    return path


def detail_state(certificate: dict, detail: dict, times: dict) -> list:
    """機能: 状態不一致を全行保持し、原本時刻・各階層の合否を照合する。

    引数: certificate/detail/times(dict)。返り値: 条件・入力を付けた状態不適合行(list)。
    """
    original = certificate['証拠種別'] == ORIGINAL
    assert certificate['経済監査合格'] is True
    assert detail['id'] == certificate['id']
    assert certificate['全入力数'] == detail['全入力数'] == 26
    assert len(detail['検査']) == 26 and {(p['session'],p['symbol']) for p in detail['検査']} == set(times)
    records = []
    if original:
        assert certificate['状態契約合格'] is True and certificate['全監査合格'] is True
        assert certificate['状態不一致行数'] == 0 and certificate['既知残存型に限定'] is True
        assert detail['全監査合格'] is True
        assert '状態不一致行数' not in detail or detail['状態不一致行数'] == 0
    else:
        assert detail['経済監査合格'] is True
        assert detail['診断固定SHA256'] == certificate['診断固定SHA256']
        for proof in detail['検査']:
            key = (proof['session'], proof['symbol'])
            rows = proof['状態不一致']
            assert proof['状態不一致行数'] == len(rows)
            assert proof['状態契約合格'] is (len(rows) == 0)
            indices = [r['row'] for r in rows]
            assert indices == sorted(set(indices))
            kinds = []
            for row in rows:
                i = row['row']
                assert type(i) is int and 0 <= i < len(times[key])
                assert row['時刻秒'] == float(times[key][i])
                for field in ('実状態','期待状態','実予約','復元資格枚数'):
                    assert type(row[field]) in (int,float) and math.isfinite(row[field])
                assert abs(row['実状態']-row['期待状態']) > 1e-6
                known = bool(row['実予算予約'] is True and row['独立予算予約'] is True
                    and row['実予約'] == 0 and ((row['実状態'],row['期待状態']) in ((1,0),(3,2))))
                assert row['既知の取消後残存型'] is known
                if known:
                    assert (row['復元資格枚数'] == 0) is (row['期待状態'] == 0)
                kinds.append(known)
                records.append(dict(id=certificate['id'],session=key[0],symbol=key[1],**row))
            assert proof['既知残存型に限定'] is all(kinds)
        valid = len(records) == 0
        known_all = all(r['既知の取消後残存型'] for r in records)
        assert known_all, '今回説明した予算中の残存以外は追加診断が必要'
        for value in (certificate,detail):
            assert value['状態不一致行数'] == len(records)
            assert value['状態契約合格'] is valid and value['全監査合格'] is valid
            assert value['既知残存型に限定'] is known_all
    return records


def final_flags(provisional: dict, records: list) -> dict:
    """機能: 経済判定値を変えず、状態欠陥により採用と完全監査をfalseに保つ。

    引数: provisional(dict)、records(list)。返り値: 経済検証済みだが実装不合格の判定(dict)。
    """
    known = [r for r in records if r['id'] == KNOWN_ID and r['session'] == '2026-09-24_Night' and r['symbol'] == 'NK225']
    assert [r['row'] for r in known] == list(range(46748,46760)), '既知12行の握りつぶし'
    assert all(r['実状態'] == 1 and r['期待状態'] == 0 for r in known)
    assert provisional['監査完了'] is False and provisional['既知比較の採用候補'] is False
    result = deepcopy(provisional)
    result.update(経済検証完了=True,実装状態契約合格=False,完全実装合格=False,
        全体目標達成=False,状態不適合条件数=len({r['id'] for r in records}),状態不一致行数=len(records))
    return result
