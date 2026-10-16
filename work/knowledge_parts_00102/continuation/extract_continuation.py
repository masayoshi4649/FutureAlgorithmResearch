"""保存済み小診断だけから、継続判断の条件・対照効果・分母を抽出する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCES = {}


def source(path: str) -> dict:
    """
    機能: 保存済みの小JSONを一回読み、再生せず指紋を固定する。
    引数: path(str)はルート相対パス。
    返り値: dictは診断の保存値。板・金融台帳・APIを読まない。
    """
    if path not in SOURCES:
        saved = (ROOT/path).read_bytes()
        assert len(saved) < 1500000
        SOURCES[path] = dict(sha256=hashlib.sha256(saved).hexdigest(), value=json.loads(saved))
    return SOURCES[path]['value']


def evidence(path: str, pointer: str, label: str = '') -> dict:
    """
    機能: JSONの出典位置と当該内容のSHAを保存する。
    引数: path/pointer/label(str)はファイル・JSONpointer・説明。
    返り値: dictは追跡可能な出典。複合算数はmeasurement側へ明記する。
    """
    source(path)
    return dict(path=path, pointer=pointer, sha256=SOURCES[path]['sha256'], label=label)


def pointer_value(path: str, pointer: str) -> object:
    """
    機能: 記録したJSONpointerが実際に保存資料へ解決できることを検査する。
    引数: path/pointer(str)は出典とJSONpointer。
    返り値: objectは解決した保存値。
    """
    value = source(path)
    for part in pointer.lstrip('/').split('/') if pointer else []:
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def measurement(symbol: str, label: str, kind: str, path: str, pointer: str,
                value: float | None, total: int | None, denominator: str, horizon: str,
                scope: str, successes: int | None = None, unit: str = '円', **extra: object) -> dict:
    """
    機能: 分母と測定の種類を省略しない数値記録を作る。
    引数: symbol/label/kind/path/pointer/denominator/horizon/scope/unit(str)、value(float|None)、total/successes(int|None)、extra(dict)。
    返り値: dictは確率・頻度又は対照効果。不明な成功数を逆算で創作しない。
    """
    return dict(symbol=symbol, label=label, kind=kind, successes=successes, total=total,
        value=value, unit=unit, denominator=denominator, horizon=horizon, scope=scope,
        source=evidence(path, pointer), **extra)


def rule(identifier: str, title: str, condition: str, mechanical: object,
         observed: str, use: str, limitations: list[str], measurements: list[dict],
         cited: list[dict]) -> dict:
    """
    機能: 一つの継続判断を、当時条件と測定済み・未測定の区別へまとめる。
    引数: identifier/title/condition/observed/use(str)、mechanical(object)、limitations/measurements/cited(list)。
    返り値: dictは共通台帳へ移せる継続判断規則。
    """
    return dict(id=identifier, stage='継続判断', title=title, condition=condition,
        mechanical_condition=mechanical, observed=observed, use=use,
        limitations=limitations, measurements=measurements, evidence=cited)


def run() -> dict:
    """
    機能: 八つの保存済み継続判断の知見を、商品別の測定と出典へ変換する。
    引数: なし。
    返り値: dictはrulesと抽出範囲。未来値は結果ラベルだけで当時採否へ使わない。
    """
    rules = []
    old_scope = '既知13場・2026-09-21_Day〜2026-09-29_Day、TOPIXmini初回5枚/NK225micro10枚、費用0・指定価格約定・場内全返済'
    new_scope = '既知29場・2026-09-21_Day〜2026-10-09_Day、TOPIXmini10枚/NK225micro20枚、次有効ラージask/bid・両側手数料込み'
    # ----------------------------------------
    p = 'work/wave_v30/context_comparison.json'
    m = source(p)
    values = []
    for index, row in enumerate(m['全12入口の等重み集計']):
        if row['mode'] == '中立' and row['comparison'] in ('S-C', 'S-B0'):
            total = row['入口数']
            successes = sum(r['収支差円'] > 0 for r in m['対応差'] if r['mode'] == '中立'
                and r['comparison'] == row['comparison'] and r['symbol'] == row['symbol'])
            assert total == 12 and abs(successes/total-row['収支改善率']) < 1e-10
            values.append(measurement(row['symbol'], row['comparison']+'の収支が改善した固定入口割合',
                '対応対照の改善割合・相場の方向確率ではない', p,
                f'/全12入口の等重み集計/{index}/収支改善率', 100.*successes/total, total,
                '同じ13場を繰り返す12固定入口。独立した12相場ではない', '13場全体', old_scope,
                successes=successes, unit='%'))
            values.append(measurement(row['symbol'], row['comparison']+'の収支差中央値', '途中条件の対照効果',
                p, f'/全12入口の等重み集計/{index}/収支差中央値円', row['収支差中央値円'], total,
                '12固定入口の全13場収支差', '13場全体', old_scope))
    design = 'work/wave_v30/管理設計の固定.json'
    rules.append(rule('CONT01', '相手の一致消失と自己の方向消失を分ける',
        '自分の方向が残っていても相手と一致しなくなった場合、直ちに同じ撤退理由とは扱わない。',
        dict(C='自己と相手が一致した中期方向', S='自己だけの同じ中期方向',
            C_rule='C=0が10分連続で全返済', S_rule='S=0が10分連続で全返済',
            control='B0は中立による保有撤回なし。全方式の入口は同一'),
        'S中立返済はCよりTOPIX11/12・日経9/12入口で改善した。しかしB0より改善したのは1/12・3/12だけだった。',
        '相手不一致だけの全返済を標準にしない。自己判断へ替えても、価格保険だけの基準を上回るか別に確認する。',
        ['当時不一致後に実際に続く/反転する確率は未測定。改善割合は固定入口の対照頻度。',
         'C=0には相手不一致と相手方向未提供が混在し、保存列だけでは分離できない。',
         '既知・費用0の旧モデル。現在の費用込み成績へ金額を移植しない。'], values,
        [evidence(design, '/保有判断'), evidence(design, '/managers/3'), evidence(design, '/managers/4')]))
    # ----------------------------------------
    p = 'work/wave_v76/analysis/主要結論と数値根拠.json'
    m = source(p)
    values = []
    for symbol in ('TOPIX', 'NK225'):
        m2 = m['Q25の数値']['全29収支'][symbol]
        m3 = m['支持消失で降りることの代償']['Q25同設定M3_30秒全29収支'][symbol]
        values += [measurement(symbol, '支持消失M3の全29収支', '保存済み途中管理の対照会計', p,
            '/支持消失で降りることの代償/Q25同設定M3_30秒全29収支/'+symbol, m3,
            m['支持消失で降りることの代償']['Q25同設定M3_30秒全29取引数'][symbol],
            'M3の全完結取引。勝ち数はこの小要約からは抽出しない', '全29場', new_scope),
            measurement(symbol, '強い反対確認M2へ対するM3収支差', '途中管理変更の完全再運転差', p,
            '/支持消失で降りることの代償', m3-m2, None,
            '同入口・同保険幅・同30秒確認のM3全29収支−M2全29収支。以後の新規も変わる', '全29場', new_scope,
            arithmetic='M3_30秒全29収支−/Q25の数値/全29収支')]
    rules.append(rule('CONT02', '支持が弱いだけの撤退は、反対確認の撤退と違う',
        '両市場の弱い支持が揃わなくなった場合と、両方が保有と反対へ強く揃った場合を区別する。',
        dict(reference='Q25：最良板の数量偏り0.25で10秒入口確認',
            M2='両市場の強い反対方向を30秒確認して返済、実返済後の新観測で再確認してドテン',
            M3='両市場の弱支持（偏り0.125）が揃わない状態も30秒確認して返済。片側不足を含む',
            freshness='5秒判断格子・情報5秒遅延・確認中に両市場の源更新が必要',
            insurance='始値0.4%追尾、通常30分期限なし、場末全返済'),
        'M3の全29収支はTOPIX−5,542,820円・日経−2,023,920円。小さな平均損失だけでは、多頻度の再入場と失う利益を補えなかった。',
        'UNKNOWNや支持不足を強い反対と同一視せず、反対確認を別部品として検証する。',
        ['P(反転|支持消失)はこの要約では未測定。取引数745/618は支持消失の独立イベント数ではない。',
         'M2/M3は返済後の新規も変わるため、一回の撤退の純粋な因果効果ではない。',
         'Q25条件は情報遅延への感度が強く、普遍的な板読みに一般化しない。'], values,
        [evidence(p, '/支持消失で降りることの代償'), evidence(p, '/Q25の数値/途中')]))
    # ----------------------------------------
    values = []
    for symbol in ('TOPIX', 'NK225'):
        block = m['Q25の数値']['同入口保険のみM0との比較']
        values.append(measurement(symbol, '強い反対確認と再確認ドテンM2のM0比収支差', '途中管理の完全再運転差', p,
            '/Q25の数値/同入口保険のみM0との比較/全29収支改善/'+symbol,
            block['全29収支改善'][symbol], None, '保険のみM0とM2の同入口全29場比較', '全29場', new_scope))
        improvement = block['全29改善悪化同値場数'][symbol]
        values.append(measurement(symbol, 'M2がM0より収支を改善したセッション割合', '対応セッションの改善割合', p,
            '/Q25の数値/同入口保険のみM0との比較/全29改善悪化同値場数/'+symbol,
            100.*improvement[0]/sum(improvement), sum(improvement),
            '同じ29セッション。無変化場も分母に含む', '1セッション', new_scope, successes=improvement[0], unit='%'))
        for delay in (1, 15):
            values.append(measurement(symbol, str(delay)+'秒情報遅延時のM2全29収支', '情報条件を変えた頑健性対照', p,
                '/Q25の数値/遅延'+str(delay)+'秒全29収支/'+symbol,
                m['Q25の数値']['遅延'+str(delay)+'秒全29収支'][symbol], None,
                '同じQ25入口10秒・M2反対30秒・0.4%保険・場末までの全29場', '全29場', new_scope))
    rules.append(rule('CONT03', '明確な反対方向を待つ管理には限定的効果があった',
        '二市場が保有と反対へ強く一致し、双方の更新を伴って30秒持続したら撤退する。ドテンは返済後に別確認する。',
        dict(method='Q25_E10_M2_C30_T40_HS', strong='各市場の保有と反対向き最良数量偏り≥0.25',
            confirm_seconds=30, source_updates='確認開始後の両市場参照行が更新',
            flip='実返済後の新しい判断で再確認。新規・返済は別注文と料金'),
        '5秒情報遅延ではM0比+1,109,068円/+323,000円。ただし改善場は11/29・13/29で、日経は情報遅延1秒/15秒では全29赤字。',
        '反対確認は候補部品として残すが、この数値だけで標準的な継続判断へ採用しない。',
        ['P(反転|強い反対合意)の条件イベント母集団は未測定。場別改善率を方向的中率と呼ばない。',
         'M2には再確認ドテンと後続新規機会の変更がある。反転玉15/8件の利益をM2−M1効果と同一視しない。',
         '5秒という価格代理情報遅延と確認時間に依存し、真の受信時計は不明。'], values,
        [evidence(p, '/Q25の数値')]))
    # ----------------------------------------
    p = 'work/wave_v78/evidence/統合部品の効果と失敗.json'
    m = source(p)
    index = next(i for i, r in enumerate(m['同入口部品対照']) if r['比較先'] == 'J2_F1_B0_H0_R0')
    row = m['同入口部品対照'][index]
    values = []
    for period in ('前16', '後14', '全30'):
        for symbol in ('TOPIX', 'NK225'):
            values.append(measurement(symbol, '同じJ2入口に板反対撤退を足した'+period+'収支差', '途中部品の完全再運転差', p,
                f'/同入口部品対照/{index}/差/{period}/{symbol}/net', row['差'][period][symbol]['net'],
                m['対照全会計']['J2_F0_B0_H0_R0'][period][symbol]['trades'],
                '基準J2_F0_B0_H0_R0の当該期間完結組数。差分の作動回数ではない', period,
                '既知30場・2026-09-21_Day〜10-09_Night、TOPIX10/NK20枚、次有効ラージ気配と両側手数料'))
    rules.append(rule('CONT04', '従来J2の保有へ短期反対を足す効果は小標本だった',
        '5分の共同方向で入った後、両市場の15秒フローと距離加重板が強い反対で15秒続くなら返済する。',
        dict(method='J2_F1_B0_H0_R0', control='J2_F0_B0_H0_R0',
            opposite='各市場のOFI非ゼロ有効イベント≥3、保有反対向きOFI比≥0.1かつ距離加重板偏り≥0.1',
            confirm_seconds=15, source_updates='両市場の参照行更新を必要とする',
            other_rules='J2入口・始値0.4%追尾・30分期限・数量を保持'),
        '全30差はTOPIX+50,000円・日経+8,000円。ただし後14のTOPIXは−75,000円、日経0円で効果の継続性は確認できない。',
        '支持不足からの撤退より具体的な反対条件として保存するが、期間劣化と変更件数を併記する。',
        ['条件成立からその後反転した確率は未測定。全期間黒字の説明と途中情報の追加価値は別。',
         '前16と後14は既知データ。後半成績を見て新しい閾値を選び直していない。',
         '板フローは表示純変化で、約定か取消か主体の返済需要かを特定しない。'], values,
        [evidence(p, f'/同入口部品対照/{index}'), evidence(p, '/解釈上の区別'),
         evidence('work/wave_v78/事前固定.json', '/F')]))
    # ----------------------------------------
    p = 'work/wave_v35/同じ新規の退出差.json'
    m = source(p)
    values = []
    for index, row in enumerate(m['同じ新規の全組比較']):
        if row['期間'] != '後7':
            continue
        total = row['全組数']
        values.append(measurement(row['銘柄'], '価格逆行時の幅短縮で収支が改善した同一初回組の割合',
            '対照収支改善割合・方向予測確率ではない', p, f'/同じ新規の全組比較/{index}',
            100.*row['改善']/total, total, '初期6で固定したB06を既知後7の全同一初回組へ適用。変更なしも分母',
            '各元組の場内完結まで', old_scope, successes=row['改善'], unit='%',
            adverse=row['悪化'], unchanged=row['同値']))
        values.append(measurement(row['銘柄'], '後7の同一初回組収支差合計', '継続判断による退出経路差', p,
            f'/同じ新規の全組比較/{index}/純差円', row['純差円'], total, '同じ初回組のB06実収支−固定A0影収支',
            '後7場', old_scope))
    rules.append(rule('CONT05', '二市場の逆価格確認だけで追尾を縮めても利益を切る',
        '保有と逆の短期価格進行が二市場で揃うと、現在ATRを使う狭い追尾を追加する。',
        dict(method='H019__B06__V000', window_seconds=120, short_window_seconds=30,
            price='120秒変化≥max(0.25ATR,2呼値)かつ30秒変化≥max(0.10ATR,1呼値)、両変化の符号一致',
            peer='相手は追加60秒遅延の同方向価格反応',
            trail='保有反対なら3*min(初回ATR,現在ATR)の保護候補を追加。一度上げた床は緩めない',
            baseline='固定3初回ATR追尾。初回新規は全組同一'),
        '後7ではTOPIX4/23組改善・4/23組悪化、日経8/34組改善・4/34組悪化。差額は−139,000円/−61,000円で、少数の失う大勝ちが改善を上回った。',
        '価格逆行の確認と、追尾幅を縮める行為の価値を分ける。悪化確認済みでも利益改善が保証されるとはしない。',
        ['指定されたB06は板数量を使わず両市場価格である。他の板フロー方式と混同しない。',
         '改善率の分母は同じ初回を持つ組で、当時の逆価格イベントや独立相場の的中率ではない。',
         '費用0・指定価格約定・既知13場の旧モデル。'], values,
        [evidence(p, '/同じ新規の全組比較'), evidence(p, '/機序別作動量'),
         evidence('work/wave_v35/deterioration_design_fixed.json', '/conditions/6'),
         evidence('work/wave_v35/conditional_design_fixed.json', '/規則/固定追跡候補')]))
    # ----------------------------------------
    p = 'work/wave_v37/slot_difference_audit.json'
    m = source(p)
    values = []
    for index, row in enumerate(m['分解']):
        if row['id'] != 'H019__B06_RB06_F50_N1__V000':
            continue
        for key, label in [('delta_yen', '固定管理に対する全組収支差')]:
            values.append(measurement(row['symbol'], label, '数量と継続管理の対照効果', p,
                f'/分解/{index}/{key}', row[key], row['元組数'], '固定A0から同じ初回で開始する全元組', '全13場', old_scope))
        for key, label in [('avoided_yen', '悪化減量中に避けた損失'), ('missed_yen', '悪化減量中に失った利益')]:
            values.append(measurement(row['symbol'], label, '保有数量差の価格経路分解', p,
                f'/分解/{index}/分類/悪化減量/{key}', row['分類']['悪化減量'][key],
                row['分類']['悪化減量']['intervals'], '保有差区間。繰返しの枠/区間で独立取引数ではない', '元組の生存期間', old_scope))
    rules.append(rule('CONT06', '悪化で半量減らし、新しい肯定で戻す効果は小幅だった',
        '二市場の逆価格を確認したら全返済ではなく一部を閉じ、減量後の新しい肯定情報で生存枠だけを戻す。',
        dict(method='H019__B06_RB06_F50_N1__V000', deterioration='CONT05と同じ120秒B06価格方向が保有と反対',
            reduce='影生存nに対してmin(n-1,max(1,floor(0.5*n)))枠を返済、最低1枠を残す。1組1回',
            restore='減量約定より後に公開された新しいB06肯定のsource_rowで、空いて影が生存する枠のみ復元',
            keep='元の初回ATR・停止・2ATR利確・期限・元Rをリセットしない'),
        '全13の固定管理比はTOPIX+25,500円・日経+7,400円。減量中は避けた損失98,500/57,600円と失った利益88,000/56,200円が接近していた。',
        '全返済を避ける途中管理として残すが、数量を減らしただけの効果と回復情報の価値を分離する。',
        ['P(継続|復元肯定)は未測定。復元脚自身の利益を管理全体の改善額と同一視しない。',
         '予算終了の経路差も収支差へ含まれ、半減単体の因果効果ではない。',
         '既知・費用0で同時改善基準を未達。次数・閾値の一般的な最適性は示さない。'], values,
        [evidence(p, '/分解'), evidence(p, '/新売買再生'),
         evidence('work/wave_v37/partial_design_fixed.json', '/rules')]))
    # ----------------------------------------
    p = 'work/wave_v104/旧自己入口の支持破れと順行の診断.json'
    m = source(p)
    values = []
    scope = '旧C_OWN_O、既知32場・2026-09-21_Day〜2026-10-12_Night、各商品1枚、ラージ正常気配・両側手数料、通常30分/保険停止までの元保有経路'
    for symbol in ('TOPIX', 'NK225'):
        total_win = m['totals']['C_OWN'][symbol]['利益']['count']
        broken_win = m['totals']['C_OWN'][symbol]['利益']['boundaries']['2']['crossed']
        values.append(measurement(symbol, '支持2呼値破れを一度経験した最終勝ち親の割合',
            '逆条件の事後経路割合 P(破れ|元戦略の最終利益)', p,
            '/totals/C_OWN/'+symbol+'/利益/boundaries/2/crossed', 100.*broken_win/total_win, total_win,
            '最終的に費用後利益で終わった親だけを選んだ分母。P(勝ち|破れ)ではない',
            '元新規fill〜元返済fillを含む経路', scope, successes=broken_win, unit='%'))
        account = [row for row in m['rows'] if row['method'] == 'C_OWN' and row['symbol'] == symbol]
        chosen = [row for row in account if row['support_boundaries']['2'] is not None
            and row['support_boundaries']['2']['seconds_after_fill'] > 0
            and row['support_boundaries']['2']['time'] < row['exit_time']
            and (row['first_fee_plus2_row'] is None or row['support_boundaries']['2']['row'] < row['first_fee_plus2_row'])]
        reached = [row for row in chosen if row['first_fee_plus2_row'] is not None and row['first_fee_plus2_time'] < row['exit_time']]
        winning = [row for row in chosen if row['outcome'] == '利益']
        for successes, label, kind in [(len(reached), '未利確の2呼値破れ後、元返済前に費用回収幅＋2呼値へ達した割合',
              '当時未利確の破れを条件にした将来経路割合'),
              (len(winning), '同じ未利確破れ母集団の元戦略最終利益割合', '条件付き最終結果頻度・保有成功保証なし')]:
            values.append(measurement(symbol, label, kind, p, '/rows', 100.*successes/len(chosen), len(chosen),
                '全C_OWN親から、初回2呼値破れがfill後・exit_timeより厳密前、破れ時点まで費用＋2未達の親を選ぶ',
                '破れの最初観測〜元O返済fill直前。固定予測秒数ではなく元出口で打切り', scope,
                successes=successes, unit='%', derivation=dict(method='C_OWN', symbol=symbol,
                    boundary='2', strictly_after_entry=True, strictly_before_exit_time=True,
                    fee_plus2_before_break=False, target='first_fee_plus2_time<exit_time' if kind.startswith('当時') else 'outcome=利益'),
                sessions_in_cohort=len({row['session'] for row in chosen})))
    rules.append(rule('CONT07', '支持線破れの後にも回復はあるが、回復と最終利益は違う',
        '新規後、費用回収幅＋2呼値へまだ達していない状態で、固定支持線を2呼値外へ初めて割った。',
        dict(direction='d=買+1/売-1', line='fixed_support-d*2*tick',
            break_event='正常清算quote Lでd*(L-line)<=0。最初の該当行',
            qualification='fill_time<最初破れtime<exit_timeを価格代理時計で厳密要求。破れ以前にfee_plus2到達なし',
            target='fee_width=ceil((新規料+元返済料)/(枚数*倍率*tick))*tick、d*(L-entry)>=fee_width+2*tick'),
        '全母集団からの未利確破れ181/110親中、その後所定順行へ戻ったのは91/28親（50.3%/25.5%）。元戦略で最終黒字は54/13親（29.8%/11.8%）だった。',
        '支持破れを方向誤認の確定とはせず、回復目標と返済管理を区別する。ここから停止幅を広げる運用利益は計算していない。',
        ['69/106・20/42はP(破れ|勝ち)であり、P(勝ち|破れ)へ逆転させない。後半の181/110集計は全親から別に抽出した。',
         '元O出口で観測が打切られる。返済後の回復、固定時間先の方向、生存全ての波を測っていない。',
         '小JSONに元返済予約行がなく、破れ時に既に返済予約済みの親を完全に分離できない。実際の継続判断機会の確率とは断定しない。',
         '初回支持破れは原順のquote観測だが、共通受信時計はなく実配信時刻が未測定。旧Oの結果を新B/T手法の勝率へ流用しない。'], values,
        [evidence(p, '/totals/C_OWN'), evidence(p, '/rows'), evidence(p, '/限界')]))
    # ----------------------------------------
    p = 'work/wave_v105/diagnosis/具体的に負けた板と改善の代償.json'
    source(p)
    values = [measurement(symbol, '支持喪失かつ相手逆行の後に反転する確率', '未測定', p,
        '/次の優先対照/2', None, None, '未定義。全保有親の当時イベントを重複なく採る設計が必要',
        '未固定。元返済による打切りと未来限界を先に定義する',
        '104/105の保存診断からの未検証継続判断仮説', unit='%') for symbol in ('TOPIX', 'NK225')]
    rules.append(rule('CONT08', '支持喪失と相手逆行を組にする判断はまだ未測定',
        '自己の固定支持が崩れた時、相手市場も既知の逆方向へ進んでいるなら保有仮説を弱める。',
        dict(proposal='自己支持破れと相手strictpastの反対状態を同時に要求する別部品',
            unknown='相手UNKNOWN/古い時計を反対へ補完しない',
            needed='何呼値の支持破れ、相手Wと強度、持続と再準備、結果の予測範囲を結果前に固定する'),
        '104では相手の確認を入口に使ったが、相手逆圧力の途中返済は別研究として未実装だった。105の診断も次の仮説を示しただけ。',
        '入口の同方向一致をそのまま保有継続の証明にせず、別の事前条件と母集団で測る対象へ残す。',
        ['4代表箇所と赤字上位場の選択だけから成功確率を作らない。',
         '105は金融未実行で入力準備失敗を検出して停止した段階。新改善の成功例はない。',
         '表示量減少が約定か取消か、補充が真の再発注かを観測だけで同定できない。'], values,
        [evidence(p, '/次の優先対照'), evidence(p, '/重要な反証')]))
    # ----------------------------------------
    for item in rules:
        for record in item['evidence']+[entry['source'] for entry in item['measurements']]:
            pointer_value(record['path'], record['pointer'])
        for entry in item['measurements']:
            if entry['successes'] is not None:
                assert entry['total'] > 0 and 0 <= entry['successes'] <= entry['total']
                assert abs(entry['value']-100.*entry['successes']/entry['total']) < 1e-8
    return dict(schema_version=1, generated_at=datetime.now().astimezone().isoformat(),
        scope='継続判断の保存資料を8件抽出。全歴代を再監査したものではなく、新規相場再生・原板・APIなし。',
        rules=rules, source_sha256={path: value['sha256'] for path, value in SOURCES.items()},
        probability_policy='条件付き経路割合、逆条件、対応対照の改善割合、金額効果、未測定を区別。異商品円額を合算しない。',
        execution=dict(financial_replay=0, raw_book_read=0, ledger_read=0, cache_read=0, api=0, original_edit=0))


if __name__ == '__main__':
    answer = run()
    output = HERE/'continuation_rules.json'
    if output.exists():
        previous = HERE/'continuation_rules_初回出典補足前.json'
        assert not previous.exists()
        previous.write_bytes(output.read_bytes())
    output.write_text(json.dumps(answer, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(全合格=True, rules=len(answer['rules']), measurements=sum(len(row['measurements']) for row in answer['rules']),
        SHA256=hashlib.sha256(output.read_bytes()).hexdigest()), ensure_ascii=False))
