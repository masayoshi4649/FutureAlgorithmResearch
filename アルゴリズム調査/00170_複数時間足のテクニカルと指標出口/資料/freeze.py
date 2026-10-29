"""結果を見る前の実装・入力・選択規則を固定し、小さな参照記録を追記する。"""
import hashlib
import importlib.util
import json
import shutil
from datetime import datetime
from pathlib import Path


def digest(path):
    """機能: 小さい資料の指紋を計測。引数: path(Path)。返り値: str。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, obj):
    """機能: UTF-8の固定資料を保存。引数:path(Path),obj(object)。返り値:None。"""
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main():
    """機能: 新規計画だけを登録。引数:なし。返り値:None。旧結果を読み込まない。"""
    here=Path(__file__).resolve().parent;root=here.parents[1]
    study=root/'アルゴリズム調査/00170_複数時間足のテクニカルと指標出口'
    planpath=study/'計画.json'
    if planpath.exists():raise RuntimeError('計画の上書きを禁止します')
    sources=sorted([*here.glob('*.go'),*here.glob('*.py'),here/'go.mod'])
    archive=study/'資料';archive.mkdir(exist_ok=True)
    for p in sources:shutil.copyfile(p,archive/p.name)
    implementation={p.name:digest(p) for p in sources}
    manifest=study/'入力目録.json';inputs=json.loads(manifest.read_text(encoding='utf-8'))
    definitions=json.loads((study/'候補定義.json').read_text(encoding='utf-8'))
    spec={
      'entry':{'hypotheses':'方式仮説.mdのH01～H12','candidates':definitions,'bar_publication':'確定した1分足と上位足だけ。上位足未確定値・未来極値・セッション最終方向を使わない','past_results':'方式設計と条件固定まで参照しない'},
      'management':{'position':'固定10枚、両建てなし。確定した反対支持でI/Fは返済後ドテン可能。Tは保有中の指標判断を使わない','trailing':'正常BBOの全原行で建値基準割合の保護。保護判断を同じ更新の指標より優先','stale_bars':'確定足終了から60秒超なら新規禁止、返済のみ可能'},
      'exit':{'I':'通常指標出口＋非常停止0.30%＋利益0.10%以後に0.05%追尾','T':'同じ入口式。通常指標出口と保有中反対シグナルを無効化し保護と場内返済だけ','F':'Iに順行0.04%で0.01%利益下限を追加','cutoff':'予定終了10分前に新規予約取消・新規停止。6分前に全返済判断。次の正常原行で約定。完全場の最終代理は明示','incomplete':'未完場に架空決済しない。全残玉と含み損益を別記し閉鎖場ランキングから除外'},
      'allocation':{'NK225':'NK225mini固定10枚、1円100円/枚','TOPIX':'TOPIXmini固定10枚、1pt1000円/枚','sizing_purpose':'入口と出口の比較に限定。可変数量は今回比較しない'},
      'costs':{'primary':'手数料0、正常BBO差は含む','reference':'約定を変えない手数料感度だけ別記。NK225mini片道38.5円/枚、TOPIXmini41.8円/枚。現在手数料を確認した主張ではなくユーザー提示表を参照'},
      'execution':{'clock':'CurrentPriceTime、同時計更新は物理行順を維持','fill':'判断した原行より後の正常原行。買いSell1.Price、売りBuy1.Price。Lastでの有利約定なし','source':'saved raw only; no controller API; no live orders','tests':'人工データの全候補共有エンジン一致・未来足禁止・同時計次行・締切予約取消・古足出口・EOF/未完の区別を確認'},
      'data':{'input_manifests':[{'path':str(manifest.relative_to(root)),'sha256':digest(manifest)}],
              'sessions':sorted({f['session'] for f in inputs['files']}),'scope':f"原板{len(inputs['files'])}ファイルを再生前後のサイズ・更新時刻と再生中SHA256で監査",
              'split':'銘柄ごとに開始時刻順の前60%を検討、後40%を確認。既知保存データで完全未見とは称さない','selection':'銘柄×Day/NightでI/F候補を検討収支だけで各1つ固定。確認成績で選び直さない','rank':'総赤字・最大黒字除外赤字・無取引・買売片側未確認の不備数→赤字場率→中央値→最大赤字/平均黒字→PF→収支'},
      'implementation':{str(p.relative_to(root)):digest(p) for p in sources}}
    plan={'schema_version':1,'trial_id':'R170_001','frozen_at':datetime.now().astimezone().isoformat(),
          'implementation':implementation,'manifest_path':'../../'+manifest.relative_to(root).as_posix(),
          'manifest_sha256':digest(manifest),'hypothesis_sha256':digest(study/'方式仮説.md'),
          'definitions_sha256':digest(study/'候補定義.json'),'spec':spec,
          'historical_comparison':'過去資料非参照の最新指定を優先。旧3.8GB台帳の類似照合は未実施で、重複なしとは判定しない。'}
    modulepath=root/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
    module_spec=importlib.util.spec_from_file_location('check170',modulepath);module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    check=module.analyze({'spec':spec},[])
    if check.get('問題') or check.get('issues'):raise RuntimeError(check)
    # ----------------------------------------
    # 構造検査と歴史照合は別の事実として小さく記録します。
    save(planpath,plan)
    save(study/'仕様検査.json',{'structure_check':check,'historical_comparison_performed':False,'note':'比較母集団は空。構造検査の結果を過去との重複なしと読み替えない。'})
    registry=modulepath.parent/'data/trials_v3.jsonl';registry.parent.mkdir(exist_ok=True)
    row={'trial_id':'R170_001','status':'計画固定','at':plan['frozen_at'],'plan':planpath.relative_to(root).as_posix(),'sha256':digest(planpath),'historical_comparison':'未実施'}
    with registry.open('a',encoding='utf-8',newline='\n') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps({'fixed':'R170_001','files':len(inputs['files']),'conditions':len(definitions),'plan_sha256':row['sha256']},ensure_ascii=False))


if __name__=='__main__':main()
