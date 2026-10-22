"""完成した四会計・表示・診断を指紋で束ね、公開と終了の根拠目録を用意する。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=Path('アルゴリズム調査/00120_段階トレーリング新規と利益玉の部分回転')


def reference(path: Path) -> dict:
    """
    機能: 既存資料を内容指紋付きで目録へ結び付ける。
    引数: path(Path)は完成済み資料の絶対パス。
    返り値: dictはリポジトリ相対パスとSHA256。金融を再生しない。
    """
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def save(path: Path, value: dict) -> None:
    """
    機能: 日本語の小目録を新規保存する。
    引数: path(Path)は未使用先、value(dict)は計画と完成資料の参照。
    返り値: None。大きな試行台帳や市場資料を変更しない。
    """
    assert not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main() -> None:
    """
    機能: 独立会計・正式表示・損失診断が揃った後に七試行の終了根拠を固定する。
    引数: なし。
    返り値: None。途中停止を完成又は損益ゼロとしない。
    """
    definitions=[
        ('b','private/public','01_提案型と八つの管理','提案型と八つの管理',48,
         '段階トレーリングと利益玉部分返済の全四十場.json',
         'c99743d739c9d24a08088f1b5ebdc78af8285b19e9704773965ea05f13890ce1',
         '保存全四十八政策八十入力の注文玉時価の独立会計監査.json',
         '登録実体と八十入力参照及び源人工の独立拘束.json'),
        ('c','private_c/public','02_小試行と方向別停止','小試行と方向別停止',24,
         '利益条件付き段階追加と全四十場.json',
         '1071dc7f296d8ffbf3483e26b863d79cde48b82bcca986a7b5810c8e18f9ee9f',
         '新四管理二十四政策の全千九百二十口座独立会計監査.json',
         '登録実体と八十入力参照及び実行時人工の独立拘束.json'),
        ('d','private_d/public','03_最終約定値による追尾','最終約定値による追尾',24,
         '約定値基準の利益条件付き段階追加と全四十場.json',
         '665cc66e7f5f1788393082a80b2f8dc19468f9b5987f49025f4c813468166c59',
         'Last参照二十四政策の全千九百二十口座独立会計監査.json',
         '登録実体と八十入力参照及び実行時人工の独立拘束.json')]
    extra=json.loads((HERE/'e完成根拠.json').read_text(encoding='utf-8'))
    assert extra['root_checked'] is True
    definitions.append(('e','private_e/public','04_上下対称回転とカバー保持','上下対称回転とカバー保持',18,
        'カバーを維持する組全体追尾と全四十場.json',extra['result_sha256'],
        extra['audit_name'],extra['binding_name']))
    phases=[]
    trials=[]
    public_main=(PUBLIC/'段階トレーリングの結論と全セッション損益.html').as_posix()
    public_readme=(PUBLIC/'README.md').as_posix()
    for code,source,directory,title,count,result_name,result_sha,audit_name,binding_name in definitions:
        recovery=HERE/('recovery_'+('e1' if code=='e' else code))
        proposal_path=recovery/'試行計画.json'
        proposal=json.loads(proposal_path.read_text(encoding='utf-8'))
        result=reference(recovery/'measurement'/result_name)
        assert result['sha256']==result_sha
        suffix='' if code=='b' else '_'+code
        audit_directory=extra['audit_directory'] if code=='e' else 'audit_result120'+code
        evidence=[reference(HERE/audit_directory/audit_name),
                  reference(HERE/audit_directory/binding_name),
                  reference(HERE/('report_artificial'+suffix)/('正式120'+('e1' if code=='e' else code)+'表示の完成.json'))]
        for item in evidence:
            proof=json.loads((ROOT/item['path']).read_text(encoding='utf-8'))
            assert proof['passed'] is True
        phases.append(dict(source=source,directory=directory,title=title,policies=count,
                           result_sha256=result_sha,audits=evidence))
        trials.append(dict(id=proposal['id'],status='検証完了',
            proposal=proposal_path.relative_to(ROOT).as_posix(),
            fixed=(recovery/'固定計画.json').relative_to(ROOT).as_posix(),result=result,
            audits=evidence,readme=public_readme,report=public_main,
            accounting=dict(financial_accounts=count*80,stored_price_inputs=80,raw_market_reads=0,
                unclosed_lots=0,previous_financial_replay=0,real_orders=0,current_API=0),
            text=f'{count}固定条件×両商品×全40場={count*80}会計を完成。全玉場内返済、独立会計整合。両商品合計黒字0条件で安定黒字は未達。同じ既知40場の開発比較。'))
    # ----------------------------------------
    # 初回停止と未実行は正式114条件へ含めず、履歴として別に終了する。
    canceled=HERE/'recovery_a/実行前中止.json'
    save(canceled,dict(status='実データ実行前に中止',financial_accounts=0,stored_price_inputs=0,
        raw_market_reads=0,理由='予定した日経一場診断の実行前に純人工で通常JITのUID保存反例を特定。市場入力を読んだ診断を追加しない。',
        evidence=reference(HERE/'audit/通常JIT反例と境界検査修正の独立人工_環境既定/境界検査付き源の全八管理とUID保存の独立人工.json')))
    stopped=json.loads((HERE/'試行計画.json').read_text(encoding='utf-8'))
    not_run=json.loads((HERE/'recovery_a/試行計画.json').read_text(encoding='utf-8'))
    execution_audits=[reference(HERE/'中断と修正版の扱い.md'),
        reference(HERE/'audit/通常JIT反例と境界検査修正の独立人工_環境既定/境界検査付き源の全八管理とUID保存の独立人工.json')]
    records=[dict(id=stopped['id'],status='会計不整合で中断',
        proposal=(HERE/'試行計画.json').relative_to(ROOT).as_posix(),
        fixed=(HERE/'固定計画.json').relative_to(ROOT).as_posix(),
        result=reference(HERE/'実行False.json'),audits=execution_audits,
        readme=public_readme,report=public_main,
        accounting=dict(financial_accounts=None,stored_price_inputs=2,raw_market_reads=0,
            saved_unvalidated_accounts=48,additional_unsaved_accounts_range=[1,48],
            adopted_in_completed_accounts=0,real_orders=0,current_API=0),
        text='TOPIX初日48条件保存後、日経初日の途中で現金と玉会計の不一致により中断。追加未保存の実行数は1〜48の範囲で未確定。金融0とせず、保存48も完成成績へ採用しない。'),
        dict(id=not_run['id'],status='実データ実行前に中止',
        proposal=(HERE/'recovery_a/試行計画.json').relative_to(ROOT).as_posix(),
        fixed=(HERE/'recovery_a/固定計画.json').relative_to(ROOT).as_posix(),
        result=reference(canceled),audits=execution_audits,
        readme=public_readme,report=public_main,
        accounting=dict(financial_accounts=0,stored_price_inputs=0,raw_market_reads=0,
            real_orders=0,current_API=0),text='予定した日経一場の独立現金診断は、純人工反例の発見により実データ実行前に中止。実入力0・金融0。')]
    records.extend(trials)
    original_e=HERE/'recovery_e'
    original_proposal=json.loads((original_e/'試行計画.json').read_text(encoding='utf-8'))
    e_stopped=original_e/'実行前中止.json'
    save(e_stopped,dict(status='実データ実行前に中止',financial_accounts=0,stored_price_inputs=0,
        原因='登録後、金融run開始前にruntime人工のspreadがunitを超え全6比較が新規ゼロとなる空guardを独立指摘。e金融0のまま源不変で中止、経済源同bytesのe1に非空guardを固定して測定。'))
    records.append(dict(id=original_proposal['id'],status='実データ実行前に中止',
        proposal=(original_e/'試行計画.json').relative_to(ROOT).as_posix(),
        fixed=(original_e/'固定計画.json').relative_to(ROOT).as_posix(),result=reference(e_stopped),
        audits=[reference(ROOT/extra['runtime_audit'])],readme=public_readme,report=public_main,
        accounting=dict(financial_accounts=0,stored_price_inputs=0,raw_market_reads=0,real_orders=0,current_API=0),
        text='金融前の空runtime同値検査を発見し源不変で中止。e実入力0・金融0。経済engine/catalog同bytesのe1だけが正式18条件・1440会計。'))
    diagnosis=HERE/'diagnosis/formal_cd/改善後に残った損失.md'
    assert diagnosis.is_file()
    loss=reference(diagnosis)
    loss['destination']='改善後に残った損失.md'
    extra_loss=reference(HERE/'diagnosis/formal_e/逆側カバーと上下回転の診断.md')
    extra_loss['destination']='逆側カバーと上下回転の診断.md'
    extra_loss['link_rewrites']={
        '(実保有の逆側追越と利確後の残在庫.json)':
            '(../../work/stability120_20261017/diagnosis/formal_e/実保有の逆側追越と利確後の残在庫.json)',
        '(epoch時刻の表示訂正と非時刻全項目不変の確認.json)':
            '(../../work/stability120_20261017/diagnosis/formal_e/epoch時刻の表示訂正と非時刻全項目不変の確認.json)',
        '(../../root_owned_e/全条件の場内安定指標.json)':
            '(../../work/stability120_20261017/root_owned_e/全条件の場内安定指標.json)'}
    save(HERE/'公開根拠目録.json',dict(root_checked=True,phases=phases,loss_diagnoses=[loss,extra_loss]))
    save(HERE/'完成根拠目録.json',dict(root_checked=True,trials=records))
    print('公開四段階と終了七試行の根拠目録を固定しました。金融再生0。')


if __name__=='__main__':
    main()
