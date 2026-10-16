"""旧J8をコードから調査し、正式損益を読む前の独立監査計画を保存する。"""

import ast
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 読み取った資料の内容指紋を求める。
    引数: path(Path)。読取専用のコード又は既存証跡。
    返り値: str。SHA256の十六進文字列。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def inspect_source(relative: str, names: tuple[str, ...]) -> dict:
    """
    機能: コードを実行せず、実際の関数区間と内容指紋を抽出する。
    引数: relative(str)。ルートからの相対パス。names(tuple[str,...])。関数名。
    返り値: dict。コードSHA256、関数名ごとの開始行・終端行。
    """
    path = ROOT / relative
    tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=relative)
    definitions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert set(names) <= set(definitions), (relative, names)
    return dict(SHA256=digest(path), 関数={name: dict(開始行=definitions[name].lineno,
               終端行=definitions[name].end_lineno) for name in names})


def save(name: str, value: dict) -> None:
    """
    機能: 新95の監査領域だけへ、日本語UTF-8の有限JSONを保存する。
    引数: name(str)。ファイル名。value(dict)。調査又は計画。
    返り値: None。
    """
    path = (HERE / name).resolve()
    assert path.is_relative_to(HERE.resolve())
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main() -> None:
    """
    機能: 旧入口の委譲先を静的に記録し、次段の最小監査範囲と未確定点を提案する。
    引数: なし。
    返り値: None。コード調査JSONとplan.jsonを新95/auditへ保存する。
    旧モジュールのimport、売買再生、正式95結果の読取、API・実注文は行わない。
    """
    specifications = {
        'work/wave_v75/inputs/core.py': ('asof_indices', 'session_sync'),
        'work/wave_v75/signals.py': ('features', 'conditions', 'event_pulses', 'map_pulses'),
        'work/wave_v77/prepared/prepare_legacy.py': ('build_extra',),
        'work/wave_v77/signals.py': ('flow_test', 'direction_condition', 'session_state'),
        'work/wave_v77/inputs/core.py': ('market_features', 'session_features'),
        'work/wave_v90/strategy.py': ('mapping', 'prepare'),
        'work/wave_v91/catalog.py': ('condition',),
        'work/wave_v91/strategy.py': ('prepare',),
        'work/wave_v92/catalog.py': ('condition', 'catalog'),
        'work/wave_v93/catalog.py': ('condition', 'catalog'),
        'work/wave_v94/catalog.py': ('clone', 'catalog'),
        'work/wave_v94/strategy.py': ('prepare',),
        'work/wave_v94/engine.py': ('simulate', 'execute'),
        'work/wave_v94/data_r1.py': ('old_price_channel', 'load_inputs'),
        'work/wave_v94/inputs_r1/last_price.py': ('extract_last_prices', 'last_price_features'),
        'work/wave_v94/audit/full.py': ('main', 'management', 'account', 'stability'),
        'work/wave_v94/audit_parallel/driver.py': ('parts', 'worker', 'assemble'),
    }
    inspected = {path: inspect_source(path, names) for path, names in specifications.items()}
    # ----------------------------------------
    # 入口候補と許可を混同しないため、各コード系の実定数も静的に確かめる。
    tree = ast.parse((ROOT / 'work/wave_v75/signals.py').read_text(encoding='utf-8-sig'))
    pulse = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'event_pulses')
    assert [ast.literal_eval(node) for node in pulse.args.defaults] == [60., 600.]
    old_candidate_code = (ROOT / 'work/wave_v77/prepared/prepare_legacy.py').read_text(encoding='utf-8-sig')
    assert "SIGNAL_ID='J1_W300_L0'" in old_candidate_code
    assert "legacy.conditions(stats[s],stats[p],300,0,True)" in old_candidate_code
    permission_code = (ROOT / 'work/wave_v77/signals.py').read_text(encoding='utf-8-sig')
    assert 'np.minimum(ra,rb)>=.25*np.maximum(ra,rb)' in permission_code
    assert "(f['nonzero_ofi_count']>=3)" in permission_code
    assert 'signed<=-.1' in permission_code

    inspected_evidence = (
        'work/wave_v94/事前固定.json',
        'work/wave_v94/audit/元full単純起動の中断と依存名補足.json',
        'work/wave_v94/audit_parallel/凍結監査の全手順同一と実行並列化及び依存名補足.json',
        'work/wave_v94/audit/全53並列再検算の全証跡とチェックポイント及び根の全値の独立最終受入.json',
        'work/wave_v95/engine_preflight/入口と反転の実装前設計.json',
    )
    evidence_hashes = {path: digest(ROOT / path) for path in inspected_evidence}
    old = dict(
        段階='静的コード読取による旧J8実条件の確認。95の本体・損益は未実行。',
        条件継承=['94.catalog J8 ←93.catalog S00 ←92.catalog J8 ←91.condition',
                  '94.strategy.prepare ←93 ←92 ←91 ←90.prepare。94では価格分類を変更しても旧eventを差替えない。'],
        入口候補=dict(
            生成元='75.signals family0、保存名J1_W300_L0。77.prepare_legacyのbuild_extraも同じ式。',
            価格='旧完全板系列のmid。LastPriceではない。',
            参照='15秒格子、grid−1秒より厳密過去。最新代理時刻の先頭行だけ、鮮度30秒以内。現在・300秒前・15秒前を独立に選ぶ。',
            有効性='両市場features.valid。端点完全板・非reset・2呼値以内spread、old/short<now、窓内完全板の破断なし。300/15秒OFI不明なしも価格資格に結合される。',
            方向='両300秒midの符号付き変化各3bp以上。自己15秒bidとaskが各1ラージ呼値以上同方向。相手15秒midが逆行しない（符号付き変化>=0）。',
            イベント='初回armed。有効中立の連続60秒で再準備、600秒の最小発火間隔。欠測は中立としない。15秒を超える格子gapは中立連続を切る。',
            写像='発火格子以降の最初の自己retained行だけ。10秒超遅れ、旧完全板不正、reset、spread2呼値超、新規締切以上なら拒否。後続正常行で救済せずpulseは既に消費。',
        ),
        J2許可=dict(
            生成元='77.signals.session_state。J2.eventは0のまま、許可long_allowed/short_allowedだけを旧候補へ後置。',
            格子='start+300秒からlimit−60秒までの5秒格子。旧候補の自己判断行に公開される最新格子へ接続。',
            条件='両current.valid、両300秒ret_bpが同方向で厳密正、弱い側>=強い側×0.25、十分な15秒OFI逆証拠なし。',
            OFI='source_valid・valid・missing_ofiなし・nonzero_ofi_count>=3・ratio有限の場合だけ十分。いずれか市場で方向×ratio<=−0.1なら拒否。不明又は少数は逆証拠にしない。',
            注意='J2の300秒ret計算は77価格窓、候補のret計算は75features。同じ数理量でも演算順・資格が異なるため、境界で混同しない。',
        ),
        J8執行と出口=dict(
            配分='TOPIXmini8枚、NK225micro16枚。range0。fixed選択なのでER、高ERmode、往復modeは追従新規の追加gateにならない。',
            新規='event非0、自己slot空、旧quality正常・非reset、有効BBO、開始300秒以後、limit−300秒未満、前回の実返済から30秒以上。',
            約定='新規予約の同じ行で約定しない。次以降の最初の有効retainedBBO行で買ask/売bid。行番号が後なら同じ代理時計でのfillは旧模型上あり得る。実受信順・実発注時計を証明するものではない。',
            幅='既知ref_open×0.004をラージ呼値へ切上げ、最低2呼値。約定後の出口幅はLP/ATRや後からの高安で差替えない。',
            追跡='初期stopは実entry価格から1幅。返済側気配（longはbid、shortはask）で判定し、ピークが有利に更新すればstopも同じ幅だけ追跡。初期stop理由1、ピーク更新後のstop理由2。',
            優先='場末強制返済→設定が有効な反対確認→期限1800秒→停止/追跡。元J8では反対確認が無効。新規fill行では通常返済を判定せず、次行以降から。',
            費用='片道注文毎floor(quantity×fee)。TOPIXmini8枚は334円、NKmicro16枚は176円。親net=gross−entry_fee−exit_fee。',
            実返済='返済予約でslotを消さず、実fillで親netを確定してlast_exit代理時計を更新する。',
        ),
        新95で未検証=['新LPから追従候補とJ2許可の両方を作るP1〜P3', '料金後負の実返済を起点とする反対候補だけの再参加制限'],
        読取コード=inspected,
        旧証跡及び暫定提案SHA256=evidence_hashes,
        正式95損益実行=0, 正式95損益閲覧=0, 現在API取得=0, 実注文=0,
    )
    save('旧J8の入口と源及び損切りのコード調査.json', old)

    # ----------------------------------------
    # 対照数と反転記憶の規則を先に創作せず、仕様確定後に計画を具体化する。
    plan = dict(
        段階='95の38条件と反転境界をrootが結果前に確定。独立静的・人工・入力監査へ進行。正式95損益未閲覧。',
        所有範囲='work/wave_v95/auditのみ。旧94以下、原本、固定181依存、95root/engineファイルは変更しない。',
        対象=dict(保存場数=31, 全て既知=True, 商品数=2, 条件数=38,
                  正式口座数=2356, 正式商品期間数=608, 主='P3_R3_N'),
        root確定案=dict(
            入口='P0旧候補旧J2、P1旧候補LP J2、P2 LP候補LP J2に旧legacy.validをAND、P3独立LP候補LP J2。',
            再参加='各入口sourceについてR0＋R1反対禁止/R2fresh quotes/R3fresh price quotes/R4sustained price quotesをN/S別にし、4×9=36。J10と主の4枚/8枚数量対照を追加して38。',
            発動='Nは料金後net負の全完了親、Sは理由1/2かつnet負の完了親。実fill後にのみ成立。',
            価格='反転gateの価格は入口P0〜P3と独立に、常にI3 rawLP。入口P0だからgate価格も旧midへ変えることは禁止。',
            基準='自己anchorは実exitBBO/LP/seq/time。peerはexitまで公表済み旧BBOとI3LPそれぞれの源。4必要源のどれか未知ならexit後4源freshな最初正常pairを別anchorとし、その行合格禁止、後の新更新と進行を要求。自己LP/clock未知も同手続き。',
            R2='LP両源とBBO両源すべてclock>実exit、index更新。両市場のbid/askが基準より新方向へ各1tick。LPの値の順行は不要。',
            R3='R2にLPも新方向へ1tickを追加。',
            R4='R3が10秒持続して両源がさらに更新。grid gap>5秒又は不明で持続をreset。',
            作用='反対候補だけを制限し、同方向候補は旧まま。直前完了親だけを記憶する。net>=0又は対象外で解除、Sのnet負nonstopも対象外として解除。予約/未確定返済では更新0。見送りpulseは返却/復活禁止。'),
        判定の独立性=[
            '新価格窓、候補、許可、発火、写像は原観測と定数から別実装する。正式strategyのevent/state/traceを正答の生成材料にしない。',
            '再参加記憶は独立に照合した実ordersと料金から作る。潜在failure trace又は失敗イベントを正答にしない。',
            '停止理由と最初triggerも元管理loopを呼ばず、実entry後の返済側気配の前方区間式で求める。',
            'source/index/raw_seq/clockと全疎復元を分離し、価格laneのseqを旧BBOindexへ流用しない。',
            '不一致を許可リスト拡張やNaNskipで隠さず、補修後は影響する全証跡を最終SHAで再実行する。',
        ],
        最小独立部品=[
            dict(ID='A0', 対象='旧I0完全一致', 範囲='P0無追加制限の全62入力及びroot許可後の全62旧J8保存結果',
                 検査='旧候補state/valid/pulse/5列candidate、J2許可/event、元signal/state、全注文・親・イベント・stats・全原板/source時価・11旧状態を全件照合。新列だけ追加として別監査する。'),
            dict(ID='A1', 対象='新LP15/300秒窓', 範囲='全62原本LP系列×5秒及び15秒格子の全観測点',
                 検査='各期限よりstrictly pastの最新時計先頭を列挙で求める。current/old/now、価格、rawseq、clock、鮮度、全間隔reset/invalidを別計算。欠測clock/原seqgap/場外/逆行も旧94r1抽出証跡へ照合。Q/F/BBO旧配列のSHA不変を確認。'),
            dict(ID='A2', 対象='候補とJ2許可の再構成', 範囲='確定全P軸×31場×両商品、損益なし',
                 検査='P0旧候補旧許可、P1旧候補新許可、P2新候補新許可＋旧legacy.valid、P3新候補新許可の軸を分ける。300/15LP、旧15BBO支持、旧15OFI逆証拠、600秒pulse、60秒中立、5秒最新許可を独立計算。LP正常でQ/Fを救済しない。'),
            dict(ID='A3', 対象='実損切り後の反対候補だけの制限', 範囲='全条件の全原行。人工で正負境界、正式はroot許可後',
                 検査='停止理由限定net負と全理由net負を別述語で再構成。予約時点で失敗を確定せず、実返済row/time/net/sideとその時に公開された両価格・両BBO源を保存。反対候補だけに現在同一判断の共同条件を適用し、同方向は旧入口のまま。見送りpulseの復活を拒否。'),
            dict(ID='A4', 対象='注文・保有・出口・料金', 範囲='全条件×両商品×上下反射の人工、正式は全62×N',
                 検査='予約→最初の後続有効quote、sameclock後続fill、次quotegap、取消競合、停止/期限/場末の最初trigger、実枚数・親net、原板毎清算時価、占有/保有capを独立検算。cut超過とtrue立会末超過を区別する。'),
            dict(ID='A5', 対象='新source/反転状態の疎復元', 範囲='controller.ledgerが保存する新列すべて×全口座',
                 検査='名称・列順・shape・初期値・変化点firstrow・疎展開・dense SHAを原入力と確定fillsから再生成。price/BBO clockが違う人工で列取り違えを拒否。gate拒否、pending exit、未知基準を状態0に潰さない。'),
            dict(ID='A6', 対象='会計集計・安定性・前16選定', 範囲='前16の注文だけで独立選定後、root許可の後15と全31',
                 検査='商品別総利益/総損失/純額、活動場勝率、全評価場数Nと共通上限10/20による下方RMS、最大赤字、下位25%、利益割合、最大利益日除外を再算定。無取引を勝ちに含めず、少数/無活動への置換を採用認定しない。'),
        ],
        人工ケース族=[
            '300秒3bp、J2厳密正、弱強0.25、自15秒bid/ask各1tick、peer15秒非逆行の等号と両側境界。',
            'LP正常・旧OFI300不明・旧legacy.valid FalseをP2/P3で分け、OFI15不明と十分逆OFIを分ける。',
            '同時計先頭不正で後続正常又は古い正常へ救済しない。広spread端点/窓内広spread/LP不正/LP時計欠測を区別。',
            'pulse初回armed、600秒未満と等号、有効中立60秒未満と等号、欠測中立・格子gapの偽再準備を拒否。',
            '15秒pulseと5秒permissionの交差・複数gridが同じ自己行に届く最新優先・映写10秒境界・初回却下後の正常復帰でも古pulseを復活させない。',
            '予約行ではfillしない、同代理時計の後続rowで旧fillは可能、返済未約定中に失敗/再参加を始めない。',
            '返済予約時に負だが次有効fillでnet正となる例、gross0で料金後net負となる例。',
            '理由1/2限定と期限/場末/反対出口のnet負を分け、strict net<0とnet=0の純会計境界を別検査。',
            '失敗親と同方向の候補は旧まま、反対だけ証拠不足なら拒否。失敗memoryの更新/解除はroot確定規則を逐次検算。',
            '新seqだけで同clock、片市場だけ新源、価格だけ新源、BBOだけ新源、返済clock以下の源を新反転証拠にしない。',
            '自己支持True後に消失してからpeer支持Trueとなる例で、別時点latchの足し合わせを拒否。現在双方同時に進む正例は受理。',
            '反対pulse拒否後の同watchで条件が戻っても再発注しない。正当な将来pulseのみ受理。',
            '返済約定rowの公開源と事前源を分ける。newprice rawseqと旧BBOindexが異なる正常例、両時計が異なる正常例を必須にする。',
            'entry後の初期stop/peak更新trail/期限と停止同時/場末と停止同時の最初trigger・優先理由・次気配gapを検算。',
            '両商品・上下反射の全ケースで手数料切捨、全原板時価、保有/占有枠、closeのnet符号が一致。',
            '入力途中cut、末尾pending、取消とfill競合、原clockgap、場内flat、運用cutと立会末を区別。',
        ],
        人工件数の方針='16ケース族×両商品×上下反射×38=2432を基本とし、各族の正負境界を省略しない。さらにR4持続・peer未知anchor等の分岐を追加する。実装仕様確定後に実経路数を明示する。未検証を件数だけで合格としない。',
        実接頭と未来毒入れ=dict(
            計画='5場×両市場の10入力組を選び、全N×10cutの実接頭を検査。5場は価格/BBO源不一致、clock継続、旧窓未知、反転境界、場末を損益額ではなく入力資格で選ぶ。',
            比較='finish=False。当該cut以前の全signal/event/予約/確定注文/全source/stateを比較。末尾による強制closeを過去に補完しない。',
            毒入れ=['自己未来LP価格/valid/reset/rawseq/clock', '相手未来LP価格/valid/reset/rawseq/clock',
                      '両未来旧BBO/OFIと新price特徴、同時計後続rowの価格変形'],
            注意='未来変形は入力copyだけ。自己とpeerを別々に破壊し、相手状態だけの未来依存を独立に検出する。原本は不変。'),
        終端までの監査preflight=dict(
            背景='94 frozen fullの540行にstate_checks参照が残りimportが欠けた。元1674口座の途中検査は正式合格に流用せず、外部AST同一driverで53全件を再検算して補った履歴を保持。',
            必須='95は各部品だけでなく正式full.mainそのものを人工input/result/ledger/manifest/aggregateの隔離fixtureで起動し、load→全条件loop→後段集計比較→全fingerprint→最終JSON保存→再読取まで、通常CLIで終了コード0を確認する。',
            依存='main末尾・fingerprint対象も含め全importを明示する。静的未定義名確認と実終端保存を両方実施。環境へ未定義名を注入して成功としない。',
            件数='人工専用の明示モードで本番件数62×N/16×Nをfixtureの件数へ置換し、通常formal mainの演算・保存ルートを共有する。正式モードの範囲/基準は縮小しない。',
            偽合格防止='人工最終JSONは人工と明記し、正式結果のpathを読む/上書きする/正式合格名で保存することを拒否。保存failureの人工も終了非0で検出。',
            全pipeline='strategy→engine人工結果→rootresearch.ledger→独立監査→rootaccounting集計→最終metadata保存まで接続確認。95正式P/Lは0。'),
        凍結と実行順=[
            'root/engine/adversaryが未確定仕様を先に固定し、全条件catalog・主・対照・評価集合・監査範囲を結果前に明示。',
            '新95入力の純準備検算・独立人工・旧I0対照・実prefix/future・全終端preflightを最終SHAで合格し、rootfreezeへ渡す。',
            'root許可の前16正式再生とselectが終わってから、後15未参照の独立選定を注文会計から行う。',
            '独立選定合格後にrootが後15を許可。全31正式account/source/period/安定性/境界を新95auditで照合する。',
            '全formal証跡のSHA・全入力・固定依存・合計件数を末尾で再照合。合格までは結果公開/採用認定をしない。',
        ],
        接続及び検査項目=[
            '38条件案を新catalogへ照合し、主P3_R3_N、J10、主Q4の一軸対照を結果前に固定。',
            '新候補の自己15秒両BBO支持の源と旧資格。P2旧legacy.valid ANDは故意の対照、P3から旧300OFI破断を価格資格へ混ぜない。',
            'NとS別trigger、S負nonstop対象外解除は確定。gross0 fee負とnet0の境界を人工で明示。',
            '自己actual exit anchor／peer公開済み別源、4必要源いずれか未知のfallback別anchorは確定。後から原失敗時の既知情報だったと扱わない。',
            'R2全4源clock/index更新、R3LP1tick、R4連続10秒＋両源再更新＋gap5秒超resetは確定。',
            '直前完了親のみの記憶、net>=0/対象外解除、新規/返済予約/未約定では記憶更新0を逐次照合。',
            '全禁止対照は反対候補だけを拒否。全建玉/全方向/無取引へ広げない。確認対照の却下pulseを復活させない。',
            '新source/反転traceのschemaとrootledgerの疎保存/指紋を確定。通常formal mainを人工で終端まで検査できる隔離接続を用意。',
        ],
        料金反例の範囲='合法ラージ呼値TOP0.5/NK10と8/16枚では1tickgross4000/1600円が往復手数料668/352円を上回る。gross微黒fee後負は合法価格path正例へ捏造せず、必要なら純会計境界として区別。gross0 fee後負は実行人工で検査する。',
        演算順の対照='rootは結果前にLP窓ratio_ret_bp=(now/old−1)×10000を追加し候補P2/P3で旧75式を維持。J2許可ret_bpは旧77同様(now−old)/old×10000。LP=MID同源同資格nullは候補閾値まで完全一致を要求し、公差で救済しない。',
        初回静的反証='95prepare_prices.pyのcandidate_grid上限がlimit−300+1e−6で旧75のlimit−300厳密未満と異なる点をrootへ通知し、rootが+1e−6を除いて修正。正式生成は修正後だけ。旧state長assertだけでなく全格子値も独立比較して修正版を検査する。当方はrootコード変更0。',
        証明の限界='原CurrentPriceTimeは最終約定代理時計。真受信/送信/注文fill時計がないので、保存seq上の仮想執行と因果参照を検証する。未知31ではなく全31既知、価格可観測性改善又は監査合格だけで収益性・将来安定性を証明しない。',
        旧固定参照SHA256=evidence_hashes,
        調査コードSHA256=digest(Path(__file__)),
        正式95損益実行=0, 正式95損益閲覧=0, 現在API取得=0, 実注文=0,
    )
    save('plan.json', plan)
    print('旧J8の静的調査と95独立監査計画を保存しました。正式95損益・API・注文は0です。')


if __name__ == '__main__':
    main()
