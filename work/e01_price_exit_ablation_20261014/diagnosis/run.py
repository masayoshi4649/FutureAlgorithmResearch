"""型を先に固定し、根授権の109結果一読だけから金額分解を保存する。"""

import argparse
import hashlib
import json
from pathlib import Path
import traceback
import analysis

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ENGINE=HERE.parent/'engine'
PLAN=HERE/'反票OFF実親の金額分解の一読固定計画.json'


def sources() -> dict:
    """
    機能: engine外三源を指紋へ結ぶ。
    引数: なし。
    返り値: dict は相対pathとSHA256。金融源は変更しない。
    """
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}


def read(path: Path) -> tuple:
    """
    機能: 明示JSONを同bytesから解釈し署名を返す。
    引数: path(Path) は小人工/固定/授権結果。
    返り値: tuple は値とSHA256。packet/台帳のreaderを持たない。
    """
    saved=path.read_bytes();return json.loads(saved.decode('utf-8-sig')),hashlib.sha256(saved).hexdigest()


def write(name: str,value: dict) -> None:
    """
    機能: 未保存の診断JSONだけを作り、既成功/Falseを上書きしない。
    引数: name(str)、value(dict) は新所有証跡。
    返り値: None。NaN/未来値による補完をしない。
    """
    path=HERE/name;assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def prepare() -> None:
    """
    機能: 実結果未読の型と分解/比較の分母を純人工へ先に束縛する。
    引数: なし。
    返り値: None。予定結果の存在又は本文を確認しない。
    """
    fixed,fsha=read(ENGINE/'金融事前固定.json');art,asha=read(HERE/'mid方向と横断不利及び実料の純人工.json');ss=sources()
    assert fixed['正式freeze'] and art['全合格'] and len(ss)==3 and {Path(k).name:v for k,v in ss.items()}==art['source_SHA256']
    write(PLAN.name,dict(全合格=True,状態='SCHEMA_ONLY。実結果未読で型/数式を閉じた。',source_SHA256=ss,engine_source_SHA256=fixed['source_SHA256'],
        fixed_SHA256=fsha,case_SHA256=fixed['case_SHA256'],人工SHA256=asha,
        予定=dict(新結果一目的読取=1,原108結果本文=0,input=0,原board=0,NPZ=0,台帳=0,新金融=0,API=0),
        数式='side*(exitMid-entryMid)*q*m − .5*(entrySpread+exitSpread)*q*m − 各実注文料 = 実親net。横断不利を二重控除しない。',
        Native='全量1UID1新規1返済、初回q=TOP10/NK20、出数量同一。',
        分類='方向mid逆行／mid不変費用負け／mid順行幅不足／黒字又は零。紙上残量は観測paperとの一致を別表示。',
        scope='十二OFFの全親、再参加/退出/買売/昼夜、赤字上位三場（同点場名）、最大負親。時刻は価格代理。',
        ON比較='paired_saved_on全場/trim/買売/各場純netだけ保存再利用。ON親対応/時刻経路/P&L内訳は未収録。',
        結果path=(ENGINE/'finance/結果.json').relative_to(ROOT).as_posix(),期待結果SHA256='6bc96e20d9ea72af1df51ed73d4595be5cadc1e9ac8760c9a69a1a501cd8886d',
        実行='根授権後一回。初回False保持、自動再開始なし。'))
    print('実結果未読の型/数式/一読計画を固定。')


def run() -> None:
    """
    機能: 固定完了後に授権新結果を一読し、全親金額分解とON純会計差を検算する。
    引数: なし。
    返り値: None。原入力/台帳/元108本文/金融再生をしない。
    """
    plan,psha=read(PLAN);ss=sources();assert ss==plan['source_SHA256'];fixed,fsha=read(ENGINE/'金融事前固定.json');assert fsha==plan['fixed_SHA256']
    for path,sha in plan['engine_source_SHA256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
    assert not (HERE/'開始.json').exists() and not (HERE/'診断False.json').exists()
    write('開始.json',dict(計画SHA256=psha,一目的一回=True,source_SHA256=ss));reads=0
    try:
        saved=(ROOT/plan['結果path']).read_bytes();reads+=1;sha=hashlib.sha256(saved).hexdigest();assert sha==plan['期待結果SHA256']
        result=json.loads(saved.decode('utf-8-sig'));del saved;out=analysis.analyze(result,fixed);del result
        assert sources()==ss
        for path,h in plan['engine_source_SHA256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h
        out.update(結果SHA256=sha,計画SHA256=psha,diagnosis_source_SHA256=ss,読取=dict(新結果=reads,原108本文=0,input=0,台帳=0,原board=0,NPZ=0,新金融=0,API=0))
        write('反票OFF十二条件の方向と気配不利及び具体損失.json',out)
        print('反票OFF小診断完了 '+str(out['検算件数'])+'検算。'+json.dumps(out['net_change_counts'],ensure_ascii=False))
    except BaseException:
        write('診断False.json',dict(全合格=False,原因=traceback.format_exc(),新結果読取=reads,原108本文=0,input=0,台帳=0,新金融=0,API=0,自動再開始=False));raise


def main() -> None:
    """
    機能: 未読prepareと授権一回分析を分離する。
    引数: CLI --prepare/--root-review-complete(bool)。
    返り値: None。正式金融に接続しない。
    """
    parser=argparse.ArgumentParser();g=parser.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',action='store_true');g.add_argument('--root-review-complete',action='store_true');a=parser.parse_args()
    if a.prepare:prepare();return
    run()


if __name__=='__main__':main()
