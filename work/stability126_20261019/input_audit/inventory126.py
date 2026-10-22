"""原版E01の再接続に必要な保存済み入力を、小目録だけから照合する。"""

from pathlib import Path
import hashlib
import json


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
READS = []


def read(relative: str) -> dict:
    """
    機能: 市場原本を開かず、小さい既存目録と監査証跡を一読する。
    引数: relative(str)はプロジェクト相対JSON位置。
    返り値: dictは既存内容。指紋とサイズを読取履歴へ保存する。
    """
    path = ROOT / relative
    assert relative.startswith('work/') and path.suffix == '.json'
    payload = path.read_bytes()
    assert len(payload) < 8_000_000
    READS.append(dict(path=relative, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)))
    return json.loads(payload)


def saved(path: str, expected: str, origin: str, **extra: object) -> dict:
    """
    機能: 保存された市場派生入力の存在とサイズだけを確認する。
    引数: path/expected/origin(str)は位置・既存指紋・根拠、extra(object)は補助項目。
    返り値: dictは本文未読の入力目録。既存指紋を今回の再計算値と呼ばない。
    """
    path = path.replace('\\', '/')
    actual = ROOT / path
    assert path.startswith('work/') and actual.is_file() and len(expected) == 64
    return dict(path=path, expected_sha256=expected, bytes=actual.stat().st_size,
                hash_source=origin, body_read=False, **extra)


def execute() -> None:
    """
    機能: 旧30・追加3・追加8を分けて原版E01の全41場入力候補を記録する。
    引数: なし。
    返り値: None。市場本文読取・金融再生・API・注文は全て0。
    """
    old_path = 'work/wave_v85/prepared/入力準備の完了.json'
    old = read(old_path)
    refs_path = 'work/stability124_20261019/保存気配八十入力と追加一場の参照.json'
    refs = read(refs_path)
    full = refs['sessions']
    assert len(full) == 41 and full[:30] == old['全30']
    records = []
    for pair in old['入力対応']:
        for kind, name in pair.items():
            records.append(saved(name, old['使用入力SHA256'][name], old_path,
                                 kind=kind, cohort='旧30保存入力'))
    p33 = 'work/wave_v106/e01_reference/prepared/入力準備の完了.json'
    ready33 = read(p33)
    assert ready33['全33'] == full[:33]
    for item in ready33['追加']:
        scene = item['対象']
        for name, value in item['入力SHA256'].items():
            records.append(saved('work/wave_v106/e01_reference/prepared/' + scene + '/' + name,
                                 value, p33, session=scene, cohort='追加3保存入力'))
    records.append(saved('work/wave_v106/e01_reference/prepared/quotes.pkl',
                         ready33['全気配SHA256'], p33, cohort='全33同一原行気配'))
    # ----------------------------------------
    qualification = []
    for scene in full[33:]:
        prefix = ('work/stability124_20261019/e01c/' if scene == '2026-10-19_Day'
                  else 'work/stability119_20261017/v6_resume/')
        folder = prefix + 'legacy_root/work/v6_prepared/' + scene
        audit_path = folder + '/入力監査.json'
        audit = read(audit_path)
        causal_path = folder + '/信号監査.json'
        causal = read(causal_path)
        assert audit['全合格'] and causal['全合格'] and audit['対象'] == scene
        for name, value in audit['出力SHA256'].items():
            records.append(saved(prefix + 'legacy_root/' + name, value, audit_path,
                                 session=scene, cohort='追加8保存入力'))
        for symbol in ('TOPIX', 'NK225'):
            qpath = prefix + 'clock_masks/' + symbol + '/' + scene + '.json'
            clock = read(qpath)
            coverage = next(v for v in audit['入力被覆'] if v['symbol'] == symbol)
            source = next(v for v in audit['原本監査'] if v['symbol'] == symbol)
            quote = folder + '/features/約定系列_' + symbol + '_' + scene + '.npz'
            records.append(saved(quote, source['実売買系列SHA256'], audit_path,
                                 session=scene, symbol=symbol, cohort='追加8同一原行気配'))
            csv = []
            for kind in ('candle_1min', 'candle_5min'):
                p = ROOT / prefix / 'legacy_root' / kind / symbol / (scene + '.csv')
                assert p.exists()
                csv.append(dict(kind=kind, path=p.relative_to(ROOT).as_posix(),
                                bytes=p.stat().st_size, hash_check_deferred_to_owner=True))
            qualification.append(dict(session=scene, symbol=symbol, clock_source=qpath,
                                      rows=clock['rows'], accepted=clock['accepted_rows'],
                                      rejected=clock['rejected_rows'], reason_counts=clock['reason_counts'],
                                      coverage=coverage, csv=csv, prefix_causal_passed=True))
    # ----------------------------------------
    own = read('work/stability124_20261019/e01c/所有六素材のconsumer資格表示.json')
    tail = [dict(symbol=v['symbol'], kind=v['kind'], guard=v['csv_clock_guard'])
            for v in own['read_log'] if v['kind'].startswith('candle_')]
    proof = dict(passed=True, sessions=full, account_count=82,
                 groups=dict(旧30=full[:30], 追加3=full[30:33], 追加8=full[33:]),
                 saved_inputs=records, additional_clock_qualification=qualification,
                 new_day_csv_qualification=tail, metadata_reads=READS,
                 expected_sha256_are_saved_evidence=True,
                 current_market_body_hashes_recomputed=False,
                 market_body_reads=0, original_market_reads=0, financial_replays=0,
                 API=0, real_orders=0,
                 contract='旧33は旧入力を保持。追加8は高水位資格済み所有入力を保持。異なる入力資格を全41同一原資格と呼ばない。')
    target = HERE / '原版E01全四十一場の保存入力候補と時計資格.json'
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, sessions=len(full), inputs=len(records),
                          metadata_reads=len(READS), market_body_reads=0,
                          output=target.relative_to(ROOT).as_posix()), ensure_ascii=False))


if __name__ == '__main__':
    execute()
