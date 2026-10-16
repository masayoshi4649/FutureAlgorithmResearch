"""根の金融完了通知後だけ保存結果一目的一読し、原入力/台帳を読まず診断する。"""

import argparse
import hashlib
import json
from pathlib import Path
import traceback
import analysis


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ENGINE=HERE.parent/'engine'
PLAN=HERE/'保存小結果一読の診断固定計画.json'


def sources() -> dict:
    """
    機能: engine外の診断三源だけを所有署名へ結ぶ。
    引数: なし。
    返り値: dict は相対path/SHA256。金融sourceを更新しない。
    """
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}


def read_small(path: Path) -> tuple:
    """
    機能: 明示JSON小資料を同bytesから読み、そのSHAを返す。
    引数: path(Path) は人工/固定計画又は根が許可した結果。
    返り値: tuple はJSON値とSHA256。原inputや台帳の読取口を持たない。
    """
    saved=path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')),hashlib.sha256(saved).hexdigest()


def write_new(name: str, value: dict) -> None:
    """
    機能: 診断所有域の未保存JSONだけを作り、初回Falseを保持する。
    引数: name(str)、value(dict) は新証跡名と内容。
    返り値: None。既結果/公共/金融sourceを上書きしない。
    """
    path=HERE/name;assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def prepare() -> None:
    """
    機能: 結果未読のSCHEMA_ONLY診断目的と一読範囲を人工/正式sourceへ固定する。
    引数: なし。
    返り値: None。金融結果の存在確認や本文読取をしない。
    """
    fixed,fixed_sha=read_small(ENGINE/'金融事前固定.json')
    art,art_sha=read_small(HERE/'共通入口と実料及び再参加差の純人工.json')
    source=sources();assert art['全合格'] and len(source)==len(art['source_SHA256'])==3
    assert {Path(k).name:v for k,v in source.items()}==art['source_SHA256']
    assert fixed['正式freeze'] and len(fixed['configs'])==12 and len(fixed['sessions'])==33
    write_new(PLAN.name,dict(全合格=True,状態='SCHEMA_ONLY。実結果未読。',source_SHA256=source,
        engine_source_SHA256=fixed['source_SHA256'],case_SHA256=fixed['case_SHA256'],configs=fixed['configs'],sessions=fixed['sessions'],
        正式固定SHA256=fixed_sha,人工SHA256=art_sha,
        入力=dict(path=(ENGINE/'finance/結果.json').relative_to(ROOT).as_posix(),一目的読取数=1,
            SHA256='根の金融完了通知後にCLIで指定。結果未読のため未取得。'),
        目的=['ORIGINと各再参加を同じ出口ごとに公開入口対応する。',
            '共通親の数量/出口差、避け損失、失った利益、後の新規を分ける。',
            '条件別/商品別赤字上位3場（収支昇順、同点場名）、最大負親（収支昇順、場名/実CID）を保存。',
            '10/2Night TOP実買いの退出/保護/紙上方向と21:29:50の旧参照時計を比較する。'],
        共通入口key=['session','symbol','paper_parent','entry.判断.raw_seq','side'],
        利用列=['actual_parent_diagnostics','boundary.actual_origins','boundary.judgments','results.rows','activity'],
        時刻='CurrentPriceTimeの価格代理時計。日本日付を維持、物理受信/応答先後は未証明。',
        分類留保='欠けた親のbusyは他の保存実親の受理～返済区間との重なりだけ確認。拒否/失効の個別未保存理由を補完しない。',
        事後極値='各政策の実保有期間だけ。別出口の救済利益/金融後採否条件を作らない。',
        予定=dict(保存結果一読=1,packet=0,原board=0,NPZ=0,台帳=0,新金融=0,API=0),
        実行許可='根の金融完了通知と明示診断授権後だけ。自動再開始なし。'))
    print('SCHEMA_ONLY診断計画を保存。結果未読。')


def run(expected_sha: str) -> None:
    """
    機能: 根完了通知のSHAを一読bytesで照合し、全親小射影だけを診断する。
    引数: expected_sha(str) は根が通知した正式結果SHA256。
    返り値: None。結果一読計数/Falseを保持し、packet/台帳/金融に接続しない。
    """
    plan,plan_sha=read_small(PLAN);source=sources();assert source==plan['source_SHA256']
    assert len(expected_sha)==64 and all(c in '0123456789abcdef' for c in expected_sha)
    assert not (HERE/'診断開始.json').exists() and not (HERE/'診断False.json').exists()
    fixed,fixed_sha=read_small(ENGINE/'金融事前固定.json');assert fixed_sha==plan['正式固定SHA256']
    for name,sha in plan['engine_source_SHA256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha
    write_new('診断開始.json',dict(正式一目的一回=True,計画SHA256=plan_sha,予定結果SHA256=expected_sha,source_SHA256=source))
    reads=0
    try:
        path=ROOT/plan['入力']['path'];saved=path.read_bytes();reads+=1
        actual=hashlib.sha256(saved).hexdigest();assert actual==expected_sha
        result=json.loads(saved.decode('utf-8-sig'));del saved
        out=analysis.analyze(result,fixed);del result
        assert sources()==source
        for name,sha in plan['engine_source_SHA256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha
        out.update(結果SHA256=actual,計画SHA256=plan_sha,診断source_SHA256=source,
            読取計数=dict(保存結果=reads,packet=0,原board=0,NPZ=0,台帳=0,新金融=0,API=0))
        write_new('十二条件の共通入口と再参加及び具体損失.json',out)
        print('保存結果一読の診断完了。検算'+str(out['検算件数'])+'件。')
    except BaseException:
        write_new('診断False.json',dict(全合格=False,原因=traceback.format_exc(),読取計数=dict(保存結果=reads,packet=0,台帳=0,新金融=0,API=0),
            source_SHA256=source,自動再開始=False));raise


def main() -> None:
    """
    機能: 未読のschema準備と、根完了授権後の一回分析を分離する。
    引数: CLI --schema-only/--root-finance-complete(bool)、--expected-result-sha(str)。
    返り値: None。金融結果生成や相場取得を行わない。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--schema-only',action='store_true');group.add_argument('--root-finance-complete',action='store_true')
    parser.add_argument('--expected-result-sha');args=parser.parse_args()
    if args.schema_only:prepare();return
    assert args.expected_result_sha,'根の完了SHAと診断授権が必要。'
    run(args.expected_result_sha)


if __name__=='__main__':main()
