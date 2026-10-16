"""読んだ小資料に限って、同条件再検証と新条件を区別する。"""

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
READ = {}


def read(path: Path) -> dict:
    """
    機能: 事前固定と公開・比較の小JSONだけを一回読み根拠指紋を保持する。
    引数: path(Path)は小metadata又は小証跡。
    返り値: dictは資料。巨大台帳、packet、原本、NPZは読まない。
    """
    payload = path.read_bytes()
    assert path.suffix == '.json' and len(payload) < 1500000
    READ[str(path.relative_to(ROOT))] = hashlib.sha256(payload).hexdigest()
    return json.loads(payload.decode('utf-8'))


def parameter_key(config: dict) -> str:
    """
    機能: 説明と旧ID系譜だけを除き、明示パラメータ辞書の一致を照合する。
    引数: config(dict)は保存された条件。
    返り値: strは比較文字列。コード・入力・デフォルト同値の一致を証明しない。
    """
    ignored = {'id', 'name', 'explanation', 'entry_price_cap_name'}
    values = {key: value for key, value in config.items() if key not in ignored and not key.startswith('previous_')}
    return json.dumps(values, ensure_ascii=False, sort_keys=True, allow_nan=False)


def sessions(fixed: dict) -> list:
    """
    機能: 保存済み固定の明示対象場を取得する。
    引数: fixed(dict)は事前固定。
    返り値: list[str]は場名。未記載を想像で補わない。
    """
    for key in ('sessions', '全31', '全30'):
        if key in fixed:
            return fixed[key]
    return []


def main() -> None:
    """
    機能: wave90〜105の読取範囲内で反復の五分類を根拠付きに保存する。
    引数: なし。
    返り値: None。全過去の重複無しは主張せず、未確認範囲も残す。
    """
    waves, definitions = {}, {}
    changes = {
        90: '二市場の追従Jと指値反発Oを状態で配分。27条件の後、同じ30場で執行Q/攻撃Aの15条件を追加。',
        91: '持続的な往復準備・反対確認出口・利益追尾と固定幅を比較し、新しい10/12Dayを追加確認。',
        92: '逸脱から回復を待つ成行入口、中心保持と再参加・相手中心を比較。',
        93: '入口のリスク/中心利益余地、停止線、中心目標、失敗後の再準備を切り分け。',
        94: '価格種類・価格正常資格を板/OFIから分離する入力軸と、入口/停止/利確軸。',
        95: '旧P0及びLP入力P1〜P3、実損失後の反対方向の再参加制限。',
        96: '同じ旧P0入口を保持して初期S、広いD、利益床、通常期限を切り分け。思想自体の再発見とは呼んでいない。',
        97: '同じ元候補後に両BBO進行又は押し回復を待つ入口。即時A0は96経済の同値対照。',
        98: '候補後待機における価格代理時計とgap/reset/C0〜C3政策。旧入口・数量・出口を維持。',
        99: '元候補と待機を保持し、現在支持L0から独立LPのL1への変更を比較。',
        100: '同じ元候補・C1・L0/L1・入口A1/A7の発注判断価格だけに上限を追加。',
        101: '初回絶対1/2/4枚と利益で支える増玉。旧8/16枚及び無増玉を比較。',
        102: '初回と入口を維持し、追加余裕0.5/1/2S及び追加時の停止線据置を変更。旧8条件も持込。',
        103: '元P0入口から離れ、表示量・出来高方向代理・価格定着Cと進行失敗Rの状態機械を新設。',
        104: '自己C/R候補は継承し、相手を同じ板ready必須から一般BBO支持へ緩和。支持B/T出口と配分を比較。',
        105: '104の三入口を継承する51条件草案。往復効率/逆行余地、固定R利益、支持帯再参加、場の停止を切り分ける。正式金融未実行時点。',
    }
    for wave in range(90, 105):
        folder = ROOT/'work'/('wave_v'+str(wave))
        path = folder/('事前固定.json' if wave <= 102 else '金融事前固定.json')
        fixed = read(path)
        configs = fixed.get('条件', fixed.get('catalog'))
        assert isinstance(configs, list)
        definitions[wave] = configs
        publication = None
        for name in ('公開結果.json', '生成結果.json'):
            source = folder/'report'/name
            if source.exists():
                publication = dict(path=str(source.relative_to(ROOT)), metadata=read(source))
                break
        if wave == 90:
            second = read(folder/'round2/事前固定.json')
            assert len(second['条件']) == 15 and second['旧27保持']
            configs = configs+second['条件']
            definitions[wave] = configs
        waves[str(wave)] = dict(固定条件数=len(configs), 明示場数=len(sessions(fixed)), 主=fixed.get('主', fixed.get('primary')),
            新しく変えた部品=changes[wave], 事前固定=str(path.relative_to(ROOT)), 公開metadata=publication['path'] if publication else None,
            公開合格=publication['metadata'].get('全合格') if publication else None,
            全期間未知と主張していない=bool(fixed.get('全31既知', fixed.get('全32既知', False))) if wave >= 92 else '固定の意味に既知再評価と明記')
    # ----------------------------------------
    # 105は未完了金融結果を読む代わりに、純catalogの51だけを確認する。
    catalog_path = ROOT/'work/wave_v105/catalog.py'
    READ[str(catalog_path.relative_to(ROOT))] = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location('105反復点検の純条件だけ', catalog_path)
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    assert len(catalog.catalog()) == 51
    waves['105'] = dict(固定予定条件数=51, 新しく変えた部品=changes[105], 金融結果読取=0,
        注意='51条件は草案と人工検証段階。105の新収益や安定改善はこの資料では認定しない。')
    comparisons = []
    for previous in range(90, 104):
        left, right = {}, {}
        for value in definitions[previous]:
            left.setdefault(parameter_key(value), []).append(value['id'])
        for value in definitions[previous+1]:
            right.setdefault(parameter_key(value), []).append(value['id'])
        same = sorted(set(left)&set(right))
        comparisons.append(dict(前wave=previous, 後wave=previous+1, 明示パラメータ辞書一致数=len(same),
            一致=[dict(前条件=left[key], 後条件=right[key]) for key in same],
            限界='0でも思想や数学が新しいとは限らない。デフォルト項目の明文化だけで辞書は変わる。逆に一致でも入力・実装・数量約定を含む完全一致は別検証が必要。'))
    # ----------------------------------------
    # 実際の同経済対照は、辞書一致だけでなく保存済み独立比較証跡を採用する。
    proof97_path = ROOT/'work/wave_v97/review/全36条件全31の独立親会計と安定性及び即時旧対照一致.json'
    proof97 = read(proof97_path)
    assert proof97['全合格'] and len(proof97['即時旧対照一致']) == 4 and all(row['全62口座一致'] for row in proof97['即時旧対照一致'].values())
    proof102_path = ROOT/'work/wave_v102/audit/旧八対照の101全496口座と旧経済及び増玉支持の完全一致.json'
    proof102 = read(proof102_path)
    assert proof102['合格'] and proof102['公差'] == 0
    proof104_path = ROOT/'work/wave_v104/engine/旧自己入口同出口の全32経済null.json'
    proof104 = read(proof104_path)
    assert proof104['全合格'] and proof104['口座数'] == 128 and proof104['旧O同値再生口座数'] == 128
    old103_final = read(ROOT/'work/wave_v103/金融全32の結果.json')
    old104_final = read(ROOT/'work/wave_v104/金融全32の結果.json')
    assert old103_final['既存対照参照口座数'] == old104_final['既存対照参照口座数'] == 64
    v2 = read(ROOT/'work/wave_v103/input_v2/metadata.json')
    assert v2['全合格'] and v2['金融再生'] == 0
    correction = read(ROOT/'work/wave_v103/input_v2/前価格時計逆行の二列訂正と人工未来不変.json')
    holdout = read(ROOT/'work/wave_v104/holdout_finance/追加Day金融の事前固定.json')
    display = read(ROOT/'work/wave_v104/report/独立HTML全場照合.json')
    assert holdout['既知32と同条件'] and holdout['追加場での再選択'] == 0
    assert display['全合格'] and display['検査数']['セッション商品行'] == 121*33*2
    observations = [
        dict(分類='完全同条件の再実行', 事実='97の即時A0四条件は96対応条件の全62口座と注文・親・会計が一致。',
             件数=248, 目的='待機入口を追加した新実装で、旧即時条件の意味を変えていないか確かめる同経済対照。', 根拠=[str(proof97_path.relative_to(ROOT))]),
        dict(分類='完全同条件の再実行', 事実='102へ持ち込む101旧8対照の496口座を事前に同経済で検査し、102正式20条件にも旧8条件を含めた。',
             件数=496, 目的='新余裕/据置を有効にしない時の旧増玉と旧固定の不変確認。新しい有用手法496件ではない。', 根拠=[str(proof102_path.relative_to(ROOT)), 'work/wave_v102/事前固定.json']),
        dict(分類='完全同条件の再実行', 事実='104のC_OWN_O/R_OWN_Oは103自己入口・旧固定出口の128口座と経済完全一致。本番121内にもその二条件を含む。',
             件数=128, 目的='新wrapper/一般相手支持/支持出口の変更を同旧入口出口へ混入させないnull対照。事前nullと本番を別の新規発見には数えない。', 根拠=[str(proof104_path.relative_to(ROOT)), 'work/wave_v104/金融全32の結果.json']),
        dict(分類='引用であり再生ではない', 事実='103と104のOLD_G0は各64口座の過去会計を参照。旧G0の同じ32場を新金融として各64再生したという説明は誤り。',
             目的='既検算の共通基準を再利用する。', 根拠=['work/wave_v103/金融全32の結果.json', 'work/wave_v104/金融全32の結果.json']),
        dict(分類='実装修正による再検証', 事実='103 input_v1の価格clock逆行後usableに人工反例があり、v2は二列だけ訂正。実64口座で変更行は0、42列は不変、金融再生0。',
             目的='旧金融へ未来価格を足した再最適化ではなく、データ資格の数学を局所修正した人工/派生検証。', 根拠=['work/wave_v103/input_v2/metadata.json', 'work/wave_v103/input_v2/前価格時計逆行の二列訂正と人工未来不変.json']),
        dict(分類='新データ更新', 事実='91の旧30に10/12Dayを別手順で追加。102は元31を固定して10/12Nightを隔離後に追加確認。104は同121条件で10/13Dayを別確認。',
             目的='同じアルゴでもデータ範囲が増えており、同一入力の無意味な再実行とは別。追加確認の結果を旧選定に混ぜない。',
             根拠=['work/wave_v91/事前固定.json', 'work/wave_v102/事前固定.json', 'work/wave_v102/report/公開結果.json', 'work/wave_v104/holdout_finance/追加Day金融の事前固定.json', 'work/wave_v104/holdout_finance/追加Day全121の損益.json']),
        dict(分類='条件変更', 事実='96のS/M/期限、97のA待機、98のC時計、99のL支持、100のP価格上限、101の初回枚数/増玉、102のB/T追加余裕は異なる実行規則。',
             目的='一つの部品を変えて効果を切り分ける。大半の元P0候補は共通で、全面的に異なる予測方式が毎回増えたわけではない。', 根拠=[f'work/wave_v{wave}/事前固定.json' for wave in range(96, 103)]),
        dict(分類='部分的重複', 事実='96はSとDの分離自体は既検証と明記。103→104→105も自己C/Rという入口仮説の継承が多く、支持・追尾・再参加・リスク量の部品変更が中心。',
             目的='既に否定された思想を新発見と言い換えず、入口/途中/出口/数量/入力の差分と反証を紐付ける。', 根拠=['work/wave_v96/事前固定.json', 'work/wave_v103/金融事前固定.json', 'work/wave_v104/金融事前固定.json', 'work/wave_v105/catalog.py'])]
    repeated = observations[:3]
    observations = [dict(分類='完全同条件の再実行', 事実='同経済の比較対照として97/102/104に明示的な同条件再生がある。',
        具体例=repeated, 目的='新しい実装で旧ルールが変わっていないことを確認。独立した新しい市場仮説の成功回数へ足さない。',
        根拠=[str(path.relative_to(ROOT)) for path in (proof97_path, proof102_path, proof104_path)]), *observations[3:]]
    # ----------------------------------------
    # 従来反復に明記された同値族は、単なる条件数より経済的独立性が少ない例として保持。
    fixed96 = read(ROOT/'work/wave_v96/事前固定.json')
    assert fixed96['理論']['予定条件数'] == 18 and fixed96['理論']['経済的な独立条件数の予定'] == 14
    independent_null = dict(例='96の18条件は、結果前に経済的独立14予定と明記。S40のM0/M1/M2×期限には同値族がある。',
        根拠='work/wave_v96/事前固定.json', 注意='18という名目数を、18個の独立な市場仮説と呼ばない。')
    conclusions = dict(重複はある='同じ比較基準の再生、共通入口の部品改修、思想の再利用が資料に明示されている。',
        無目的完全再試行の全否定は不可='読んだ資料で明確なものは同経済対照・入力修正・追加データ・部品変更。すべてのジョブ履歴を読んだわけではなく、無駄な完全再実行が一件もないとは証明しない。',
        毎回全く違う手法でもない='特に96〜102はP0/J8候補を中心に連続改修。方法名を変えた回数だけ多様な方向予測を試したとはいえない。',
        今後の記録='完全試行fingerprintと抽象仮説IDを分ける。既存と同じfingerprintは引用を優先し、再実行するなら追加データ・実装修正・同値検査など目的と差分を必須で残す。')
    output = dict(全合格=True, scope='wave90〜104の事前固定・公開小metadata及び特定同経済/修正証跡、105純51草案だけの反復点検。',
        調査済みwave=list(range(90, 106)), 調査範囲=waves, 明示パラメータだけの隣接比較=comparisons,
        根拠付き分類=observations, 名目条件数と同値族=independent_null, 結論=conclusions,
        読取根拠SHA256=READ, sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        完全同条件の意味='アルゴ規則/入力transform/原データ範囲/商品/実数量/fee floor/約定順/境界が全て一致すること。名前や説明だけの変更は新試行ではない。',
        fingerprint必須項目=['抽象仮説IDと親試行ID', '入口/途中/出口/数量の明示有効条件', '実行math sourceと入力変換source/version',
            '使用データ指紋と対象セッション', '参照板と取引商品の区別/倍率/呼値/上限数量', '注文別floor手数料/次quote約定/遅延モデル',
            '開始/cut/force/通常期限/未知/reset規則', '結果前評価/選択規則'],
        未確認=['wave1〜89の全条件比較', '90〜105の全OSジョブ起動ログと一時プロセス', '全catalogのデフォルト展開と全入力信号の数学同値',
            '全公開レポート本文の思想重複分類', '105新金融実行結果'],
        初回I_O注記='追加Day全会計JSONは小metadataサイズ制限で本文decode前に停止したため、事前固定と公開HTML独立照合metadataを根拠に差替えた。金融会計や台帳の再計算なし。',
        巨大入力読取=0, 台帳再読=0, 原本読取=0, NPZ読取=0, 新金融再生=0, API取得=0, goal操作=0)
    target = HERE/'repetition_audit.json'
    assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 小資料数=len(READ), SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
