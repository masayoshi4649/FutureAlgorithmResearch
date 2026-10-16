"""実結果未読で型を固定し、根のSHA解除後の新110結果一目的読取だけを行う。"""

import argparse
import hashlib
import json
from pathlib import Path
import traceback
import analysis

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ENGINE=HERE.parent/'engine'
PLAN=HERE/'出来高入口の損失原因と保存PRICE比較の一読固定計画.json'


def sources() -> dict:
    """
    機能: engine外の三診断sourceだけをSHA256へ束縛する。
    引数: なし。
    返り値: dict はroot相対path別の指紋。旧診断又は金融sourceへ書き込まない。
    """
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}


def read(path: Path) -> tuple:
    """
    機能: 許可された小metadata又はSHA解除後の結果を一bytes読取から解釈する。
    引数: path(Path) は明示JSON。
    返り値: tuple はJSON辞書とSHA256。packet/台帳/原boardのreaderを持たない。
    """
    saved=path.read_bytes();return json.loads(saved.decode('utf-8-sig')),hashlib.sha256(saved).hexdigest()


def write(name: str,value: dict) -> None:
    """
    機能: 新診断領域の未保存ファイルだけにNaNなしJSONを保存する。
    引数: name(str)、value(dict) は新所有証跡。
    返り値: None。成功/Falseを上書き又は自動再開始しない。
    """
    path=HERE/name;assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def prepare() -> None:
    """
    機能: 未読の新結果schema・数式・分母と一回読取を先に固定する。
    引数: なし。
    返り値: None。結果の有無又は本文を確認せず、正式固定と純人工だけを読む。
    """
    fixed,fsha=read(ENGINE/'金融事前固定.json');art,asha=read(HERE/'出来高入口の金額分解と唯一金融及びaliasの純人工.json');ss=sources()
    assert fixed['正式freeze'] and art['全合格'] and len(ss)==3
    assert {Path(k).name:v for k,v in ss.items()}==art['source_SHA256']
    write(PLAN.name,dict(全合格=True,状態='SCHEMA_ONLY。新金融結果未読で型/数式を閉じた。',
        source_SHA256=ss,engine_source_SHA256=fixed['source_SHA256'],fixed_SHA256=fsha,case_SHA256=fixed['case_SHA256'],人工SHA256=asha,
        予定=dict(新110結果一目的読取=1,元109結果本文=0,input=0,台帳=0,原board=0,NPZ=0,API=0,新金融=0),
        金融分母=dict(唯一新金融495=495,内部同値99=99,保存PRICE198=198,比較掲載792=792),
        数式='side*(exitMid-entryMid)*q*m − .5*(entrySpread+exitSpread)*q*m − 各実注文floor料 = 親net。横断不利は実grossの分解であり追加控除しない。',
        検算='全量一UID一新規一返済、初回q10/20。原seq/代理時計/公開volume signed式/親net/料/各場会計・alias同親同値。',
        対象='新volume九表示の全実親、商品/退出/買売/DayNight/前16後17。各条件商品赤字上位三場と最大負二親。',
        資格範囲='完結実親のvolume通過とprice通過又は不通過を分類。全公開候補の交差資格は未保存で未測、資格countは勝率ではない。',
        約定範囲='保存activityの候補/受理/実fill/FAK失効/取消は別表示。各親は実fill済み、未約定を敗/勝へ数えない。',
        旧比較='新結果内の109保存PRICE小会計三退出の全33P/L/net/qだけ。共通親効果/避けた損失親/失った勝親/旧時刻経路は未保存。',
        未測='pubのown_known単独列は未保存None。保存price_acceptedは全体価格資格。欠測BBO/峰値/目標は0又は未来値へ補完しない。',
        時刻='CurrentPriceTime代理時計。二市場strict価格時計模型で物理受信先後は未証明。',
        事後='峰値/最悪清算は実保有区間の診断だけ。採否/別出口救済利益を作らない。',
        結果path=(ENGINE/'finance/結果.json').relative_to(ROOT).as_posix(),
        実行='根SHA解除後 python -B -X utf8 run.py --root-finance-complete --expected-result-sha <根通知SHA> を一回。'))
    print('110実結果未読の三源/純人工/一読診断計画を固定。',flush=True)


def run(expected_sha: str) -> None:
    """
    機能: 根のSHA解除後に新結果を一目的だけ読み、金額分解と原因射影を保存する。
    引数: expected_sha(str) は根が通知した完成結果のSHA256。
    返り値: None。元金融/packet/台帳/API/経済再生へ接続しない。
    """
    assert len(expected_sha)==64 and all(c in '0123456789abcdef' for c in expected_sha)
    plan,psha=read(PLAN);ss=sources();assert ss==plan['source_SHA256']
    fixed,fsha=read(ENGINE/'金融事前固定.json');assert fsha==plan['fixed_SHA256']
    for path,sha in plan['engine_source_SHA256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
    assert not (HERE/'開始.json').exists() and not (HERE/'診断False.json').exists()
    write('開始.json',dict(一目的一回=True,計画SHA256=psha,期待結果SHA256=expected_sha,source_SHA256=ss));reads=0
    try:
        saved=(ROOT/plan['結果path']).read_bytes();reads+=1;sha=hashlib.sha256(saved).hexdigest();assert sha==expected_sha
        result=json.loads(saved.decode('utf-8-sig'));del saved;out=analysis.analyze(result,fixed);del result
        assert sources()==ss
        for path,h in plan['engine_source_SHA256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h
        out.update(結果SHA256=sha,計画SHA256=psha,diagnosis_source_SHA256=ss,
            読取=dict(新110結果=reads,元109金融本文=0,input=0,台帳=0,原board=0,NPZ=0,新金融=0,API=0))
        write('出来高代理入口の金額分解と具体損失及びPRICE保存比較.json',out)
        print('110損失原因小診断完了 '+str(out['検算件数'])+'検算、唯一金融親'+str(out['unique_financial_completed_parent_count']),flush=True)
    except BaseException:
        write('診断False.json',dict(全合格=False,原因=traceback.format_exc(),新結果読取=reads,
            原109本文=0,input=0,台帳=0,新金融=0,API=0,自動再開始=False));raise


def main() -> None:
    """
    機能: 未読準備と根の金融完了解除後一回診断を分離する。
    引数: CLI --prepare/--root-finance-complete(bool)、--expected-result-sha(str)。
    返り値: None。正式金融又は原入力読取のコマンドを持たない。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--root-finance-complete',action='store_true')
    parser.add_argument('--expected-result-sha');args=parser.parse_args()
    if args.prepare:prepare();return
    assert args.expected_result_sha;run(args.expected_result_sha)


if __name__=='__main__':main()
