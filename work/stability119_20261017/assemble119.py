"""実会計版だけの公開目録と、停止を含む試行終了の根拠目録を作る。"""

import argparse
import hashlib
import json
from pathlib import Path

import package119
import finalize119


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00119_戦略の自動選択と場内黒字の再探索'


def digest(path: Path) -> str:
    """
    機能: 完成した結果・証跡の内容指紋だけを確認する。
    引数: path(Path)は完成ファイル。
    返り値: strはSHA256。市場入力・金融再生を行わない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ref(path: Path) -> dict:
    """
    機能: 正本ルート内の完成根拠を終了目録の参照へ変換する。
    引数: path(Path)は実在する証跡。
    返り値: dictはpath/sha256。
    """
    assert path.is_file() and path.resolve().is_relative_to(ROOT)
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=digest(path))


def write(path: Path, value: dict) -> None:
    """
    機能: 根が確認した小目録を新規保存する。
    引数: path(Path)は新規保存先、value(dict)は目録。
    返り値: None。既存目録を置き換えない。
    """
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def main() -> None:
    """
    機能: 九段階の実表示と十試行の結果・独立監査を同じ公開資料へ結ぶ。
    引数: CLI v9-result/v9-sha/v9-auditは最後の完成結果と独立照合。
    返り値: None。公開と台帳変更は別の根担当処理とする。
    """
    p = argparse.ArgumentParser()
    p.add_argument('--v9-result', required=True)
    p.add_argument('--v9-sha', required=True)
    p.add_argument('--v9-audit', required=True)
    args = p.parse_args()
    extras = [
        dict(directory='改善4_二脚相対回帰', source='privatev5/public', title='二脚の相対回帰', description='4政策。共通元本差・単脚・両側気配・費用を含む組会計。', result='v5/measurement/二脚相対回帰四条件と全四十場.json', expected='f4147e05de741ec1e3681237209d7ea9892170adbabe77ac5225cb9431bd22c9'),
        dict(directory='改善5_相対強さの継続', source='privatev7/public', title='相対的な強さの継続と残差追尾', description='8政策。強い側を買う対照。回帰型の負けを改善して失った利益も記録。', result='v7/measurement/相対的な強さの継続と残差追尾の全四十場.json', expected='6920051e4b9217284cf89f9afb4652f9ac7ec560a17b25928a66135f876fcb14'),
        dict(directory='改善6_相対差の復帰確認', source='privatev8/public', title='実際の復帰を二度確認する相対回帰', description='8政策。準備時に中心を固定し、別価格時計の二確認から参加。初期気配差と停止予算の欠点も診断。', result='v8/measurement/相対乖離の実際の復帰確認と全四十場.json', expected='2f7c15e27d7c0e20b6b14de8ab682ac62d49a55b6ba35d2079b6245d9699dcf4'),
        dict(directory='改善7_気配差を含む停止予算', source='privatev9/public', title='初期気配差を清算予算へ含めた対照', description='新8政策。予算1部品だけを変更。極値撤回線・約定・実費用は維持し、旧8会計は保存引用。', result=args.v9_result, expected=args.v9_sha),
        dict(directory='再確認_少額E01追加', source='privatev6/public', title='少額E01の固定設定と追加7場', description='商品別の旧設定を固定。旧33場66行は保存引用、追加7場14行のみ新測定。入力資格変更と初回停止も明記。', result='v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json', expected='d0f1f86cb955a2da7016f0a33f6ff097eb64edb14068e8d0a0b4278aebca963b'),
    ]
    for phase in extras:
        proof = json.loads((BASE/phase['source']/'生成証跡.json').read_text(encoding='utf-8'))
        names = [name for name in proof['artifacts'] if name.endswith('.html')]
        assert len(names) == 1
        phase.update(report=names[0], data='data.json')
    manifest = package119.create(extras)
    manifest.update(overview_directory='再確認_少額E01追加', overview_heading='基礎となる商品別の少額E01',
        conclusion='現時点の暫定候補は、少額E01の二口座並行運転です。全40場で26黒字・1赤字・13無取引。毎場の安定黒字や損小利大を確立したものではありません。',
        dual=ref(BASE/'v6_resume/root_owned/少額E01二口座の場末収支合算.json'),
        overview_rules={
            '入口':'元E01の二市場方向判定に、直近60秒の出来高増更新の方向支持を要求。TOPIXは偏り0.5以上、日経は0.25以上、既知票2以上。最初の後続正常気配が指値許容内なら新規。',
            '数量':'公開時点のATR・気配差・料金から予定リスクを計算し、TOPIX5,000円／日経2,000円の予算内へ縮小。比較上限はミニ10枚／マイクロ20枚ですが、追加7場の実取引は各1枚です。',
            '出口':'元E01の損切り・追尾・部分返済と時刻回避を保持。最初の受理予定枚数×観測1呼値の円利益が成立したら全返済を予約し、その場は終了。場末も返済します。停止線での約定保証はありません。'})
    write(BASE/'公開目録.json', manifest)
    by_directory = {phase['directory']:phase for phase in manifest['phases']}
    identities = [
        ('119_全玉清算教師と異なる戦略から場内安定黒字を探す','初回_戦略選択','recovery119/戦略自動選択と全四十場の復元結果.json','試行計画.json','正式固定.json','source_SHA256',20160,'audit_result119/集約型停止後の保存会計復元と独立照合の証跡.json'),
        ('119b_共同進行の失速復帰と事前価格保護の原因対照','改善1_復帰と価格保護','v2/measurement/復帰確認と執行保護の全四十場.json','v2/試行計画.json','v2/固定計画.json','sources',2880,'v2/audit_result/三十六政策の会計と旧単体同値及び全場資産の独立監査.json'),
        ('119c_小試行と当初リスクを増やさない順行追加の対照','改善2_張り方と増玉','v3/measurement/小試行と順行追加の全四十場.json','v3/試行計画.json','v3/固定計画.json','sources',2880,'v3/audit_result/小試行と順行追加の全注文親会計及び全場MTMの独立監査.json'),
        ('119d_広い共同進行と離脱及び遅行追随を同時点で逆建て','改善3_順逆と時間回避','v4/measurement/広い進行条件の順逆比較と全四十場.json','v4/試行計画.json','v4/固定計画.json','sources',3840,'v4/audit_result/四十八政策の保存親会計と全場資産の独立監査.json'),
        ('119e_両脚の費用と時間差を含む相対乖離の場内回帰','改善4_二脚相対回帰','v5/measurement/二脚相対回帰四条件と全四十場.json','v5/試行計画.json','v5/固定計画.json','sources',160,'v5/audit_result/二脚全百六十組の注文親会計と共同snapshotの独立監査.json'),
        ('119g_相対的な強さの継続と残差追尾の場内対照','改善5_相対強さの継続','v7/measurement/相対的な強さの継続と残差追尾の全四十場.json','v7/試行計画.json','v7/固定計画.json','sources',320,'v7/audit_result/二脚全三百二十組の注文親会計と共同snapshotの独立監査.json'),
        ('119h_少額E01の時計逆行行除外による入力停止修正','再確認_少額E01追加','v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json','v6_resume/試行計画.json','v6_resume/固定計画.json','source_SHA256',14,'v6_resume/audit_result/h旧六十六引用と新十四口座の全注文親UID及び全行時価の独立監査.json'),
        ('119i_相対乖離の実際の復帰確認と残差追尾の対照','改善6_相対差の復帰確認','v8/measurement/相対乖離の実際の復帰確認と全四十場.json','v8/試行計画.json','v8/固定計画.json','sources',320,'v8/audit_result/二確認全三百二十組の親会計と準備系譜及び共同snapshotの独立監査.json'),
        ('119j_相対復帰の初期気配差を含む清算予算の対照','改善7_気配差を含む停止予算',args.v9_result,'v9/試行計画.json','v9/固定計画.json','sources',320,args.v9_audit),
    ]
    records = []
    for identity,directory,result,proposal,fixed,source_key,count,audit in identities:
        phase = by_directory[directory]
        row = dict(id=identity, result=ref(BASE/result), audits=[ref(BASE/audit)],
            readme=(PUBLIC/directory/'README.md').relative_to(ROOT).as_posix(),
            report=(PUBLIC/directory/phase['report']).relative_to(ROOT).as_posix())
        if identity not in {item['id'] for item in finalize119.TARGETS}:
            counters = dict(raw_reads=0, financial_accounts=count)
            if identity.startswith('119h_'):
                counters.update(reused_financial_accounts=66, inherited_original_reads=42,
                    owned_stage_book_reads=14,owned_stage_1min_reads=14,owned_stage_5min_reads=14,old_financial_rerun=0)
            if identity.startswith('119j_'):
                counters.update(reused_financial_accounts=320, baseline_financial_rerun=0)
            row['definition'] = dict(result=result,proposal=proposal,fixed=fixed,source_key=source_key,
                accounting=counters,text=phase['description'])
        records.append(row)
    records.append(dict(id='119f_少額E01の商品別固定設定を追加七場へ適用',
        result=ref(BASE/'v6/実行False.json'),
        audits=[ref(BASE/'v6_resume/audit_source/旧百二十不変と時計CSV差分及び全百二十二源の最終独立拘束.json')],
        readme=(PUBLIC/'README.md').relative_to(ROOT).as_posix(),
        report=(PUBLIC/'結論と全セッション損益.html').relative_to(ROOT).as_posix(),
        definition=dict(result='v6/実行False.json',proposal='v6/試行計画.json',fixed='v6/固定計画.json',
            source_key='source_SHA256',accounting=dict(raw_reads=42,financial_accounts=0,input_preparation_failed=True,
                preflight_csv_hash_only_reads=28,reused_financial_accounts=0),
            text='原素材42を各一回複写した後、旧consumerの既知時計逆行で入力停止。新金融0を保全し、119hで別入力資格へ移った。')))
    write(BASE/'完成根拠目録.json',dict(全合格=True,根による完成確認=True,trials=records,
        意味='完了又は入力停止を忠実に記録する。目標達成の宣言ではない。'))
    print('実表示九段階と十試行の完成目録を準備しました。公開・台帳変更・金融0。')


if __name__ == '__main__':
    main()
