"""旧33保存会計と追加七場14実口座だけの八部品及び原本指紋を固定する。"""

import hashlib
import json
from pathlib import Path
import sys

from source_v6 import HERE, ROOT, MIRROR, SESSIONS, SYMBOLS, ENGINE_NAMES, SMALL_FIXED, read, save, digest
from adapter_v6 import ACTUAL, METHOD, OLD_ACCOUNT


TRIAL = '119h_少額E01の時計逆行行除外による入力停止修正'
OLD_TRIAL = '106_E01公開支持強度による一回FAK許容切替八対照'
RUNTIME_NAMES = ('plan_v6.py', 'run_v6.py', 'source_v6.py', 'legacy_runtime.py', 'adapter_v6.py', 'artificial_v6.py', 'clock_adapter.py', 'artificial_clock.py')


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
    機能: 旧fの既stage42と初回中断履歴だけを小目録で再固定する。
    引数: なし。
    返り値: None。原本・stage本文・金融・登録は0。
    """
    old_here=HERE.parent/'v6'
    origin=old_here/'入力目録.json';meta=read(origin)
    stopped=old_here/'実行False.json';failure=read(stopped)
    assert failure['新会計完了数']==0 and not any(k in failure['counters'] for k in ('新実GU','新実政策会計'))
    staged=old_here/'原本の一回複写履歴.json';history=read(staged)
    logs={v['path']:v for v in history['read_log']}
    assert history['全合格'] and len(logs)==42
    inputs=[]
    for item in meta['inputs']:
        log=logs[item['path']]
        assert item['SHA256']==log['SHA256'] and item['bytes']==log['bytes']
        row=dict(item,staged_path=log['owned_path'])
        p=(ROOT/row['staged_path']).resolve()
        assert p.is_relative_to(old_here/'legacy_root') and p.stat().st_size==row['bytes']
        inputs.append(row)
    output=dict(meta)
    output.update(inputs=inputs,counters=dict(new_raw_book_reads=0,new_csv_1min_reads=0,new_csv_5min_reads=0,
        staged_book_views=14,staged_csv_copies=28,new_paper_accounts=14,new_actual_accounts=14,
        old_accounting_reused=66,old_financial_rerun=0,displayed_accounts=80),
        stopped_trial=dict(id='119f_少額E01の商品別固定設定を追加七場へ適用',original_reads=42,new_financial=0,
            failure=dict(path=stopped.relative_to(ROOT).as_posix(),SHA256=digest(stopped)),
            read_history=dict(path=staged.relative_to(ROOT).as_posix(),SHA256=digest(staged))),
        old_manifest=dict(path=origin.relative_to(ROOT).as_posix(),SHA256=digest(origin)),
        clock_contract='有限正Lastかつ価格clockが場内・採用済最大clock以上のみ採用。その他はCurrentPriceTimeをNone表示、原行数/seq保持、足算/sortなし。原44票は未加工stageの元clockを使う。',
        期間差='旧33は旧無訂正保存会計の引用。追加七場だけ新時計資格。全40同一入力資格とは呼ばない。',
        読取='旧f stage42だけを使用。book14は高水位表示を新保存、CSV28は同bytes複写。原本再読0。',
        原book本文読取=0,stage本文読取=0,金融=0,登録=0)
    save(HERE/'入力目録.json',output)
    print('h小目録固定、旧f原42/金融0中断を保持。今回原本/stage本文/金融0。',flush=True)


def make_proposal(meta: dict, implementation: dict) -> dict:
    """
    機能: 旧商品別二設定をそのまま使う追加データ試行の八部品を構成する。
    引数: meta(dict)、implementation(dict[str,str])は固定目録と実装指紋。
    返り値: dictは正式登録用提案。損益や新候補の選別は含まない。
    """
    manifest = dict(path=(HERE/'入力目録.json').relative_to(ROOT).as_posix(), sha256=digest(HERE/'入力目録.json'))
    return dict(id=TRIAL, name='少額E01の時計逆行行除外による入力停止修正', purpose='不具合修正',
        question='旧33場で少額黒字だった固定組合わせを追加七場へそのまま適用した時、費用後黒字場と最悪場は維持されるか',
        change='旧119fは元原本42複写後、最初の時計逆行でengine/金融0のまま中断。原clock/seqを保ち高水位未満・不明・場外・Last不正を不適格にする入力表示を追加。旧stageだけから追加14会計を作り、旧66保存会計は引用。',
        repeat_reason='旧fは原本42をstageした後の最初の価格時計逆行で中断し、新金融は0。既stageだけを使い、元時計を翌日へ推定せず、不適格時計をNone表示する別入力資格で再開する。旧33は無訂正保存引用、新7のみ資格変更である。旧8対照・00105比較・旧33金融を再実行しない。未整理の全過去と重複なしとは断定しない。',
        compares_to=['119f_少額E01の商品別固定設定を追加七場へ適用', OLD_TRIAL, '119_全玉清算教師と異なる戦略から場内安定黒字を探す'],
        evidence=[meta['old_reference']], spec=dict(
            entry=dict(method=METHOD, actual_config=ACTUAL,clock_qualification=meta['clock_contract'],
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
                時刻='追加七場のみ有限正Last・場内価格clock・採用済高水位以上を必要とする。同clock原順を保持。不適格行を削除/sort/翌日復元せず、consumer時計だけNone表示。正常seqは元raw44と完全一致。真受信時計の因果や日付誤りの正解を証明しない。',
                約定='買ask/売bid、約定済の事後取消なし。全feed後参加・UID・注文別費用を元部品で再判定する。'),
            data=dict(input_manifests=[manifest], sessions=meta['sessions'], new_sessions=meta['new_sessions'],
                inputs=meta['inputs'], old_reference=meta['old_reference'], counters=meta['counters'], stopped_trial=meta['stopped_trial'], clock_contract=meta['clock_contract'],期間差=meta['期間差'],
                生成='旧数値源は同bytes。旧f stage42を再利用。追加七場のみ高水位価格資格の別表示を旧48/85へ渡し、出来高票raw44は未加工stage元clockと既存reset/usableを維持する。119preparedへの近似交換なし。',
                CSV時刻資格='登録後・金融前に所有CSVの足時計が観測窓内かつ重複逆行なしと検査。不適合なら停止し、日付加算/sort/除外で救済しない。',
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
