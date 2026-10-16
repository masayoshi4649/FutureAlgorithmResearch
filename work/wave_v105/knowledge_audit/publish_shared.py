"""散在する保存済み知見を共通の正本へ移し、公開資料の索引を作る。金融は再生しない。"""

from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMMON = ROOT/'アルゴリズム調査/共通/知見台帳'
sys.dont_write_bytecode = True


def read(path: Path) -> dict:
    """
    機能: 保存済みの小資料を読む。
    引数: path(Path)はJSON。
    返り値: dictは資料内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def evidence(name: str, label: str = '根拠') -> dict:
    """
    機能: 根拠の相対位置と内容指紋を登録する。
    引数: name/label(str)は位置と表示名。
    返り値: dictは根拠参照。原板や巨大cacheは入力しない。
    """
    path = ROOT/name.replace('\\', '/')
    assert path.is_file()
    return dict(path=path.relative_to(ROOT).as_posix(), label=label,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def write(name: str, value: dict) -> None:
    """
    機能: 共通の正本を初回だけ生成する。
    引数: name(str)、value(dict)はファイル名と内容。
    返り値: None。既存の正本は上書きしない。
    """
    path = COMMON/'data'/name
    assert not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def make_studies(inventory: dict) -> list[dict]:
    """
    機能: 過去100作業の主資料を索引化する。
    引数: inventory(dict)は独立に存在確認した公開保存先。
    返り値: list[dict]は索引。リンクの存在確認と結論監査を区別する。
    """
    rows = []
    for item in inventory['公開保存先目録']:
        folder = ROOT/item['フォルダ'].replace('\\', '/')
        readme = folder/'README.md'
        text = readme.read_text(encoding='utf-8')
        report = None
        for target in re.findall(r'\]\(([^)]+\.html)\)', text):
            path = (folder/target).resolve()
            if path.is_relative_to(ROOT) and path.is_file():
                report = path.relative_to(ROOT).as_posix()
                break
        rows.append(dict(id=item['作業番号'], title=item['題名'], status='索引のみ',
            summary='作業 '+item['作業番号']+'。過去の説明・条件・結果は元資料を参照。',
            readme=readme.relative_to(ROOT).as_posix(), report=report,
            evidence=[evidence(readme.relative_to(ROOT).as_posix(), '保存時のREADME')]))
    return rows


def make_findings() -> list[dict]:
    """
    機能: 直近8知見を移し、既存の横断評価と具体損失の知見を加える。
    引数: なし。
    返り値: list[dict]は検証範囲を明示した知見。未検証効果を断定しない。
    """
    old = read(HERE.parent/'知見台帳.json')
    rows = [dict(id=row['ID'], title=row['知見'], claim='', status=row['区分'], scope=row['範囲'],
        action=row['判断'], evidence=[evidence(name) for name in row['根拠']]) for row in old['知見']]
    diagnosis = 'work/wave_v105/diagnosis/赤字上位場の具体板と当時兆候及び反証.json'
    additions = [
        ('K06', '確認済み', '赤字上位場には、短期の往復を継続方向と扱った入口があった。',
         'C_N30_B4の日経、2026-10-02 09:03:33売り→09:03:54返済。直前30秒の気配往復68.5呼値に対し売り方向の純進行1.5呼値。1枚・手数料後−522円。',
         'この兆候を避ける案は、除外される勝ちも含む運用全体の再生が必要。選んだ赤字場だけでは有効性を認定しない。', diagnosis),
        ('K07', '確認済み', '同じ候補列でも、出口変更により実際に入れる次の候補が変わる。',
         '00055の出口12対照、および105の寄与分解。入口候補固定は、同一約定取引固定と同義ではない。',
         '収支差を避けた損失・逃した利益・共通入口の出口差・新しい入口へ分ける。保有中の見送りを予測改善と呼ばない。',
         next(ROOT.glob('アルゴリズム調査/00055_*/README.md')).relative_to(ROOT).as_posix()),
        ('K08', '比較条件の注意', '注文手法だけの検証も済んでいるが、約定方式の違う成績はそのまま比較できない。',
         '00079は12系統・288条件の前半比較と主代表の全30場。主比較は判断観測の気配。後の次正常気配モデルとは別条件。',
         'IFD・グリッド等を再提案するときは、元の条件との差と再検証理由を先に記録する。注文管理だけで安定するという結論は得ていない。',
         next(ROOT.glob('アルゴリズム調査/00079_*/README.md')).relative_to(ROOT).as_posix()),
        ('K09', '確認済み', 'E01の時間帯見送りは既に検証済み。毎セッション黒字には届いていない。',
         '00081・既知30場・25条件。E01_G_Uは両市場の入口再確認と米国開始前後の見送り。観測現在値・初回TOPIX5枚／日経10枚。',
         '時間帯見送りを新しい発見として再計算せず、保存結果を先に参照する。現在の気配約定へ移すなら約定差を独立に示す。',
         next(ROOT.glob('アルゴリズム調査/00081_*/README.md')).relative_to(ROOT).as_posix()),
        ('K10', '確認済み', '異なる戦略への固定配分も検証済みで、安定性の目標は未達だった。',
         '00084・3手法への22配分・既知30場。元データと各源の失敗玉も含む会計。',
         '配分という発想だけを再探索せず、源の性質・失敗の重なり・枚数・約定方式の変更点を明示する。',
         next(ROOT.glob('アルゴリズム調査/00084_*/README.md')).relative_to(ROOT).as_posix()),
        ('K11', '比較条件の注意', '前半・後半に分け直しても、既に見た期間は未知データにはならない。',
         '00074の歴代再評価と統合162条件。全30場は既知資料であると元報告にも明記。',
         '同じ期間への条件追加は探索回数として蓄積する。未知性能の追試成功として数えない。',
         next(ROOT.glob('アルゴリズム調査/00074_*/README.md')).relative_to(ROOT).as_posix()),
    ]
    for ident, status, title, scope, action, source in additions:
        rows.append(dict(id=ident, status=status, title=title, claim='', scope=scope, action=action,
                         evidence=[evidence(source)]))
    return rows


def make_trials(inventory: dict) -> list[dict]:
    """
    機能: 直近研究の要点と104の条件別実績、105の未実行案を別々に登録する。
    引数: inventory(dict)は研究索引。
    返り値: list[dict]は実績・草案・未整理を区別した試行。
    """
    rows = []
    for item in inventory['直近研究']:
        rows.append(dict(id='研究_'+item['work'], name=item['work']+'：'+item['思想'],
            study_id=item['作業番号'], method_ids=item['手法ID'],
            status='入力準備失敗・金融未実行' if item['work'] == 'wave_v105' else '研究概要を登録',
            question=item['思想'], change=item['変更点'],
            result=item['状態'], repeat_reason='元資料に記録された変更点を引継ぎ。新たな金融再生はしていない。',
            limitations='研究単位の索引。全条件の完全な機械照合用仕様への展開は未完了。',
            parts={'入口': item['入口'], '途中': item['途中'], '出口': item['出口']}, spec=None,
            evidence=[evidence(name) for name in item['出典パス']]))
    # ----------------------------------------
    # 104のB/T単一手法は、保存入口と実行sourceを含む8部品まで正確に接続します。
    fixed = read(ROOT/'work/wave_v104/金融事前固定.json')
    public_path = next(ROOT.glob('アルゴリズム調査/00100_*/公開会計.json'))
    public = read(public_path)
    sources = fixed['source_SHA256']
    implementation = {name.replace('\\', '/'): value for name,value in sources.items()
        if '/engine/' in name.replace('\\', '/') and name.endswith('.py')}
    assert implementation
    data = dict(sessions=sorted(public['sessions']+[public['extra']['session']]), products=['TOPIX', 'NK225'],
        input_manifests=[evidence('work/wave_v104/入口準備の全32結果.json'), evidence('work/wave_v104/holdout_input/追加Dayの活動と19入口.json')],
        price_source='保存済みラージ板、既存正常原行対応')
    for config in fixed['catalog']:
        ident = config['id']
        existing = public['values'][ident]
        accounts = existing['rows']+public['extra']['cases'][ident]['rows']
        summaries = []
        for symbol in ('TOPIX', 'NK225'):
            chosen = [row for row in accounts if row['symbol'] == symbol]
            assert len(chosen) == 33
            profit, loss = sum(row['profit'] for row in chosen), sum(row['loss'] for row in chosen)
            active, red = sum(row['campaigns'] > 0 for row in chosen), sum(row['net'] < 0 for row in chosen)
            share = f'{100*profit/(profit+loss):.1f}%' if profit+loss else '算出不能'
            summaries.append(f'{symbol}：利益{profit:,.0f}円／損失{loss:,.0f}円／収支{profit-loss:+,.0f}円、金額利益割合{share}、赤字{red}/{active}活動場')
        exit_id = config.get('exit_id', '')
        spec = None
        if config['kind'] == 'single' and exit_id in ('B1', 'B2', 'B4', 'T2', 'T4'):
            spec = dict(entry=dict(saved_candidate_series=config['entry_id'], gate=config['gate'], family=config['family']),
                management=dict(mode='全量新規・追加なし', cooldown_seconds=30, start_offset_seconds=300,
                                entry_cut_offset_seconds=300, force_offset_seconds=60),
                exit=dict(support_ticks=int(exit_id[1:]), profit_trail=exit_id.startswith('T'),
                          initial_stop_fraction=.001, wide_price_fraction=.004),
                allocation=dict(products={'TOPIX': 'TOPIXmini', 'NK225': 'NK225micro'}, quantity=config['quantity']),
                costs=dict(fee_per_lot_per_side={'TOPIX': 41.8, 'NK225': 11}, rounding='注文ごとの合計円未満切捨て'),
                execution=dict(buy='次の正常ask', sell='次の正常bid', clock='PriceTime代理・当該原行で候補消費',
                               overnight=False, delay_worst_case_seconds=0), data=data, implementation=implementation)
        rows.append(dict(id='104_'+ident, name='104：'+ident, study_id='00100', method_ids=[ident], status='検証済み',
            question='支持境界と利益追尾で毎セッションの損失を抑えられるか。',
            change='固定121条件の一つ。条件は下記設定と根拠に保存。', parameters=config,
            result='\n'.join(summaries), repeat_reason='今回は既存33場の結果を読んで集約。再生していない。',
            limitations='各1枚の単一手法と10/20枚の配分を混同しない。全33場は既知。'+('8部品の完全一致を照合可能。意味の同等性は別途確認。' if spec else '完全な8部品仕様は未整理。重複なしと判定しない。'),
            spec=spec, evidence=[evidence(public_path.relative_to(ROOT).as_posix(), '全121条件の保存会計'),
                evidence('work/wave_v104/金融事前固定.json', '事前固定')]))
    spec = importlib.util.spec_from_file_location('知見登録用105catalog', HERE.parent/'catalog.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for config in module.catalog():
        rows.append(dict(id='105_'+config['id'], name='105草案：'+config['id'], study_id=None,
            method_ids=[config['id']], status='金融未実行', question=config['explanation'],
            change='104の3入口へ17対照。初期全量をTOPIX10枚／日経20枚にする。', parameters=config,
            result='入力準備で未知窓の対応不備を検出して停止。金融結果はまだ存在しない。',
            repeat_reason='具体損失の原因に対応する部品を分離する計画。再検証効果は未確認。',
            limitations='入力修正・新固定・既存類似試行の確認が必要。草案を検証済みに数えない。', spec=None,
            evidence=[evidence('work/wave_v105/catalog.py', '現在の草案'),
                      evidence('work/wave_v105/input/全33場の因果特徴準備.json', '入力準備の失敗記録')]))
    return rows


def main() -> None:
    """
    機能: 共通知見の初回正本を構築する。
    引数: なし。
    返り値: None。原本、旧成果、旧知見台帳は変更しない。
    """
    inventory = read(HERE/'input_inventory.json')
    stamp = datetime.now(timezone(timedelta(hours=9))).isoformat()
    studies, findings, trials = make_studies(inventory), make_findings(), make_trials(inventory)
    write('studies.json', dict(schema_version=1, updated_at=stamp, studies=studies))
    write('knowledge.json', dict(schema_version=1, updated_at=stamp,
        coverage='過去100作業の保存先を索引化。直近16研究の要点、104の121条件、105の未実行51案を登録。全歴代の条件同一性の監査は未完了です。',
        findings=findings, migrated_from=evidence('work/wave_v105/知見台帳.json', '移行前の台帳')))
    write('trials.json', dict(schema_version=1, updated_at=stamp, trials=trials, repetition_audit=[],
        completeness_note='未整理の過去試行は残っている。機械一致がないことだけで新規性を認めない。'))
    print(json.dumps(dict(知見=len(findings), 試行=len(trials), 保存先=len(studies)), ensure_ascii=False))


if __name__ == '__main__':
    main()
