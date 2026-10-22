"""旧33保存会計と追加七場14実口座だけの八部品及び原本指紋を固定する。"""

import hashlib
import json
from pathlib import Path
import sys

from source_v6 import HERE, ROOT, MIRROR, SESSIONS, SYMBOLS, ENGINE_NAMES, SMALL_FIXED, read, save, digest
from adapter_v6 import ACTUAL, METHOD, OLD_ACCOUNT


TRIAL = '119f_少額E01の商品別固定設定を追加七場へ適用'
OLD_TRIAL = '106_E01公開支持強度による一回FAK許容切替八対照'
RUNTIME_NAMES = ('plan_v6.py', 'run_v6.py', 'source_v6.py', 'legacy_runtime.py', 'adapter_v6.py', 'artificial_v6.py')


def sources() -> dict:
    """
    機能: driver・adapter・旧数値の全所有Pythonをflat指紋へ接続する。
    引数: なし。
    返り値: dict[str,str]はrepo相対pathとSHA。生成されたJITはsourceへ含めない。
    """
    paths = [HERE / name for name in RUNTIME_NAMES]
    paths += [HERE / 'engine' / name for name in ENGINE_NAMES]
    paths += sorted((MIRROR / 'work').rglob('*.py'))
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}


def prepare() -> None:
    """
    機能: stat/hash-only目録と既存read_logの小射影から追加原本42を固定する。
    引数: なし。
    返り値: None。book本文・金融・登録は読まず実行しない。
    """
    raw_path = HERE / '原本の固定目録.json'
    raw = read(raw_path)
    proof_path = ROOT / 'work/stability119_20261017/root_review/追加七場の原book指紋を初回読取記録から抽出.json'
    books = read(proof_path)
    mapping = {v['path']: v for v in books['items']}
    assert len(mapping) == 14 and books['source_SHA256'] == '13bdd30ecf5ad8dd12ce4d8f0aec96a025e7bd1bb36e33fa8b30bc02de0d2c15'
    inputs = []
    for original in raw['inputs']:
        item = dict(original)
        if item['kind'] == 'book':
            prior = mapping[item['path']]
            assert item['bytes'] == prior['bytes'] and item['session'] == prior['session'] and item['symbol'] == prior['symbol']
            item['SHA256'] = prior['sha256']
        assert len(item['SHA256']) == 64
        inputs.append(item)
    assert len(inputs) == 42
    old = read(OLD_ACCOUNT)
    sessions = old['sessions'] + list(SESSIONS)
    assert len(sessions) == len(set(sessions)) == 40
    metadata = [dict(path=p.relative_to(ROOT).as_posix(), SHA256=digest(p))
                for p in [raw_path, proof_path, OLD_ACCOUNT]]
    save(HERE / '入力目録.json', dict(全合格=True, sessions=sessions, old_sessions=old['sessions'],
        new_sessions=list(SESSIONS), symbols=list(SYMBOLS), inputs=inputs, actual_config=ACTUAL,
        old_reference=dict(path=OLD_ACCOUNT.relative_to(ROOT).as_posix(), SHA256=digest(OLD_ACCOUNT)),
        inherited_metadata=metadata, fixed_metadata={p:digest(MIRROR/p) for p in SMALL_FIXED},
        counters=dict(new_raw_book_reads=14, new_csv_1min_reads=14, new_csv_5min_reads=14,
                      new_paper_accounts=14, new_actual_accounts=14, old_accounting_reused=66,
                      old_financial_rerun=0, displayed_accounts=80),
        注意='40場は既知開発。追加七場は今回の00106固定二設定が未適用だった範囲であり、全過去未見ではない。',
        読取='正式登録後に原本42を各一回同bytes複写。旧抽出の複数走査は所有コピーだけ。CSV28hash-onlyは別の事前指紋目的。',
        source_discovery_complete=True, 原book本文読取=0, 金融=0, 登録=0))
    print('追加七場の原本指紋と旧66保存引用を小目録だけで準備。金融/登録0。', flush=True)


def make_proposal(meta: dict, implementation: dict) -> dict:
    """
    機能: 旧商品別二設定をそのまま使う追加データ試行の八部品を構成する。
    引数: meta(dict)、implementation(dict[str,str])は固定目録と実装指紋。
    返り値: dictは正式登録用提案。損益や新候補の選別は含まない。
    """
    manifest = dict(path=(HERE/'入力目録.json').relative_to(ROOT).as_posix(), sha256=digest(HERE/'入力目録.json'))
    return dict(id=TRIAL, name='少額E01の商品別固定設定を追加七場へ適用', purpose='新データ',
        question='旧33場で少額黒字だった固定組合わせを追加七場へそのまま適用した時、費用後黒字場と最悪場は維持されるか',
        change='旧33×2の66会計を保存引用、追加7×2の14口座だけ元E01入力から生成・金融する。',
        repeat_reason='旧00106の数値条件は変更しない。既知40場への範囲延長であり、旧8対照・00105比較・旧33金融を再実行しない。条件撤廃後の小利益候補の再評価で、新思想の発明ではない。未整理の全過去と重複なしとは断定しない。',
        compares_to=[OLD_TRIAL, '119_全玉清算教師と異なる戦略から場内安定黒字を探す'],
        evidence=[meta['old_reference']], spec=dict(
            entry=dict(method=METHOD, actual_config=ACTUAL,
                元='旧48抽出→元entry/B00/B01→旧85 E01_G_U全feed。足公開遅延・両市場gate・原normal行順を保持。',
                採否='原公開行W60既知二方向票以上。TOP signed釣合い>=.5、NK>=.25。Last対直前rawBBOの出来高増更新代理で、真の攻撃主体ではない。'),
            management=dict(数量='旧ATRと公開spread/費用から予算TOP5000/NK2000、予定qを公開当行で固定。影は5/10、実上限10/20。',
                初期化='旧26cacheの包括読取だけ小FIXEDと追加INPUTSの注入へ置換。旧85initialize後半と数値関数は同一AST。',
                比較='旧66保存行と新14行を80行へ統合。旧親個別経路や未保存診断を新しい実測として補完しない。'),
            exit=dict(利益='P1。最初の受理予定q×観測1tick×倍率を一回固定。FAK失効でも初回尺度保持。',
                損失='TOP5000/NK2000の旧固定円線。全UID次正常気配返済、場停止後の新規なし。',
                その他='元paper部分/全退出、quiet U、ready.limit/旧期限を完全保持。119の15:20/05:40へ交換しない。'),
            allocation=dict(組合わせ=ACTUAL, 解釈='商品ごとに旧設定が異なる固定組合わせ。両商品共通の一数値条件と称さない。',
                上限='TOPmini10/NKmicro20、旧リスク数量・影/実分離を保持。'),
            costs=dict(片道='TOPmini41.8円/NKmicro11円、各注文ごとfloor。新規/部分返済/全返済の実数量課金。',
                気配='ラージBBOを小型執行の代理とする。料金とspreadを別計上、実小型板の待ち順位・深さは未証明。'),
            execution=dict(FAK='公開行でTOP balance>=.75/NK>=1.0かつ既知二票以上だけ不利1観測tick、他0。最初の後続正常気配一回でfill又は失効。',
                時刻='元normal rawseq/価格時計を完全一致させる。同clock原行順を保持し、真受信時計の因果を証明しない。',
                約定='買ask/売bid、約定済の事後取消なし。全feed後参加・UID・注文別費用を元部品で再判定する。'),
            data=dict(input_manifests=[manifest], sessions=meta['sessions'], new_sessions=meta['new_sessions'],
                inputs=meta['inputs'], old_reference=meta['old_reference'], counters=meta['counters'],
                生成='旧85/48の元板・1分・5分足の生成版を所有mirrorへ同bytes複写。119preparedへの近似交換なし。',
                未知='追加7を過去全試行未見のholdoutと呼ばない。原本の今回目的別読取と旧実測保存引用を区別。'),
            implementation=implementation))


def freeze() -> None:
    """
    機能: 根担当の人工結合後だけsourceと八部品を正式固定する。
    引数: なし。根担当の後段実行専用。
    返り値: None。登録及び金融は実行しない。
    """
    meta = read(HERE/'入力目録.json')
    binding = read(HERE/'人工監査の結合.json')
    current = sources()
    assert binding['passed'] is True and binding['source_SHA256'] == current
    assert meta['actual_config'] == ACTUAL and meta['new_sessions'] == list(SESSIONS)
    proposal = make_proposal(meta, current)
    save(HERE/'固定計画.json', dict(source_SHA256=current, input_manifest=proposal['spec']['data']['input_manifests'][0],
        inputs=meta['inputs'], actual_config=ACTUAL, sessions=meta['sessions'], new_sessions=list(SESSIONS),
        old_reference=meta['old_reference'], counters=meta['counters'], binding=binding))
    save(HERE/'試行計画.json', proposal)
    print('v6正式八部品を固定。登録/原本準備/金融は別途根担当のみ。', flush=True)


if __name__ == '__main__':
    {'prepare':prepare, 'freeze':freeze}[sys.argv[1]]()
