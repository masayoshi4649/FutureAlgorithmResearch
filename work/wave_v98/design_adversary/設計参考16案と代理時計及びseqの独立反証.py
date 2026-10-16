"""98は計画だけ。新策略・注文・損益を計算せず、時刻と連番の論理を反証する。"""

import hashlib
from itertools import product
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 読取専用の根拠と設計コードの内容指紋を求める。
    引数: path(Path)。
    返り値: strはSHA256。過去のコード又は成果を編集しない。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def save(name: str, value: dict) -> None:
    """
    機能: 自担当の新98設計参考へだけ日本語資料を保存する。
    引数: name(str)、value(dict)。
    返り値: None。正式研究の条件又は売買結果を生成しない。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE.resolve())
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def proxy_peer(rows: list[tuple], target: float) -> int | None:
    """
    機能: 旧仕様と同じ厳密過去・同時計先頭だけの相手源を人工列から得る。
    引数: rows(list[tuple[seq:int,clock:float,valid:bool,reset:bool]])、target(float)。
    返り値: int|Noneは原seq。後続正常行又は同時計末尾へ救済しない。
    """
    assert all(rows[i][0] < rows[i + 1][0] and rows[i][1] <= rows[i + 1][1]
        for i in range(len(rows) - 1))
    eligible = [row for row in rows if row[1] < target]
    if not eligible:
        return None
    latest_clock = eligible[-1][1]
    first = next(row for row in eligible if row[1] == latest_clock)
    if not first[2] or first[3] or not 0. < target - first[1] <= 30.:
        return None
    return int(first[0])


def source_fresh(anchor: tuple, current: tuple, strict_clock: bool) -> bool:
    """
    機能: 一銘柄内の新源を連番・indexと当該銘柄時計だけから人工判定する。
    引数: anchor/current(tuple[index:int,seq:int,clock:float])、strict_clock(bool)。
    返り値: bool。二銘柄に共通する実受信順序を推定する関数ではない。
    """
    return (all(math.isfinite(float(v)) for v in anchor + current)
        and current[0] > anchor[0] and current[1] > anchor[1]
        and (current[2] > anchor[2] if strict_clock else current[2] >= anchor[2]))


def fault_action(policy: str, *, reverse: bool = False, missing_clock: bool = False,
                 sequence_gap: bool = False, best_invalid: bool = False,
                 deep_or_volume_only: bool = False, legacy_reset: bool = False) -> str:
    """
    機能: 取消・停止・再準備の設計上の故障分類を人工で確認する。
    引数: policy(str:R0/R1/R2)、故障フラグ(bool)。
    返り値: strは状態方針。発注条件や仮想売買を実行しない。
    """
    assert policy in ('R0', 'R1', 'R2')
    if reverse:
        return '取消'
    if missing_clock or sequence_gap or best_invalid:
        return '取消' if policy == 'R0' else '停止して再準備'
    if legacy_reset:
        if policy == 'R0':
            return '取消'
        if policy == 'R1':
            return '停止して再準備'
        return '価格位相を保持・旧発注資格は補完しない' if deep_or_volume_only else '停止して再準備'
    return '保持'


def cancel_flags(now: float, previous: float, deadline: float, cut: float,
                 hard_opposite: bool, price_gap_enabled: bool) -> int:
    """
    機能: 価格gapだけを除いた場合に他の硬い取消理由が残ることを人工検査する。
    引数: now/previous/deadline/cut(float)、hard_opposite/price_gap_enabled(bool)。
    返り値: intは場末1・TTL2・価格gap4・硬反対32のビット。発注は行わない。
    """
    assert all(math.isfinite(value) for value in (now, previous, deadline, cut))
    return ((1 if now >= cut else 0) | (2 if now >= deadline else 0)
        | (4 if price_gap_enabled and now - previous > 10. + 1e-8 else 0)
        | (32 if hard_opposite else 0))


def artificial() -> dict:
    """
    機能: 冗長時計条件、相手の先頭参照、故障分類と再準備期限の必要境界を反証する。
    引数: なし。
    返り値: dictは人工証拠。新98の実入力、候補、注文又は損益を読まない。
    """
    checked = 0
    for own_now, peer_now, phase in product((99., 100., 101.), repeat=3):
        original = own_now > phase and peer_now > phase and peer_now <= own_now
        removed_self = peer_now > phase and peer_now <= own_now
        assert original == removed_self
        checked += 1
    source = [(1, 99., True, False), (2, 100., False, False),
        (3, 100., True, False), (4, 101., True, False)]
    assert proxy_peer(source, 100.) == 1
    assert proxy_peer(source, 100.5) is None
    assert proxy_peer(source, 102.) == 4
    future = source + [(5, 120., True, False)]
    assert proxy_peer(future, 100.5) == proxy_peer(source, 100.5)
    assert not source_fresh((1, 10, 100.), (2, 11, 100.), True)
    assert source_fresh((1, 10, 100.), (2, 11, 100.), False)
    assert not source_fresh((1, 10, 100.), (2, 10, 101.), False)
    assert not source_fresh((1, 10, 100.), (2, 11, 99.), False)
    # ----------------------------------------
    # 相手の価格時計が自己phase以前でも、各自anchor後という別意味なら通り得る。
    own_anchor, peer_anchor = (1, 10, 100.1), (1, 20, 99.9)
    own_current, peer_current = (2, 11, 105.1), (2, 21, 100.05)
    local = source_fresh(own_anchor, own_current, False) and source_fresh(peer_anchor, peer_current, False)
    assert local and peer_current[2] <= own_current[2]
    assert not peer_current[2] > own_anchor[2]
    # 同じ自己代理時計なら参照格子が変わらず、相手源の連番は増えない。
    own_same_time = 105.1
    old_peer, new_peer = proxy_peer(source, own_same_time), proxy_peer(future, own_same_time)
    assert old_peer == new_peer == 4
    assert cancel_flags(112., 100., 400., 1000., False, True) == 4
    assert cancel_flags(112., 100., 400., 1000., False, False) == 0
    assert cancel_flags(400., 385., 400., 1000., False, True) == 6
    assert cancel_flags(400., 385., 400., 1000., False, False) == 2
    faults = {}
    for policy in ('R0', 'R1', 'R2'):
        assert fault_action(policy, reverse=True) == '取消'
        expected = '取消' if policy == 'R0' else '停止して再準備'
        assert fault_action(policy, sequence_gap=True, legacy_reset=True) == expected
        assert fault_action(policy, best_invalid=True, deep_or_volume_only=True, legacy_reset=True) == expected
        faults[policy] = dict(時計逆行=fault_action(policy, reverse=True),
            時計不明=fault_action(policy, missing_clock=True),
            原行欠番=fault_action(policy, sequence_gap=True, legacy_reset=True),
            最良不正=fault_action(policy, best_invalid=True, legacy_reset=True),
            深板だけ=fault_action(policy, deep_or_volume_only=True, legacy_reset=True),
            出来高resetだけ=fault_action(policy, deep_or_volume_only=True, legacy_reset=True))
    assert fault_action('R2', deep_or_volume_only=True, legacy_reset=True) == '価格位相を保持・旧発注資格は補完しない'
    candidate_time, original_expiry, repair_time = 100., 400., 390.
    assert original_expiry - repair_time == 10. and original_expiry != repair_time + 300.
    assert original_expiry >= candidate_time + 300.
    return dict(全合格=True, 種類='設計上の人工論理のみ・新策略未実行',
        自己phase時計要件の冗長性全組合せ=checked,
        正例='自己seqが新しく時計同値なら一銘柄内の板更新は読める。ただし相手新源は別途必要。',
        負例='相手clock>phaseと相手clock<=ownが残ればown>phaseは必然。自己phase条件除去だけは改善枝に数えない。',
        旧peer参照={'同時計後続の正常救済禁止': True, '未来付加の過去不変': True,
            '自己時計固定では固定asofのpeer源も固定': True},
        各自anchor後と共通phase後の意味の違い=dict(自己phase=100.1, 相手anchor=99.9,
            現自己=105.1, 現相手=100.05, 各自基準から新源=True, 共通phaseの後=False),
        reset分類=faults, 再準備で元TTLを延長しない=True,
        gap取消除去の厳密一軸={'正常gap行へ暗黙の発注禁止を足さない': True,
            'TTLちょうどはgap設定に関係なく取消': True},
        静穏と停止の識別不能例={'保存行': ['seq100 clock100', 'seq101 clock120'],
            '経過20秒静穏後に更新': '同じ保存行になり得る',
            '経過20秒収集停止後に復帰': '同じ保存行になり得る',
            '結論': '連続seqだけで真受信断裂の不存在は証明できない。'},
        新策略実行=0, 新損益閲覧=0, API取得=0, 実注文=0)


def main() -> None:
    """
    機能: 取消・seq確認・再準備の有限案と因果性の限界を設計参考として保存する。
    引数: なし。
    返り値: None。最終条件数・出口・主はrootが実装前に決める未採用資料。
    """
    policies = {
        'C0': {'説明': '97完全対照。10秒価格gap取消・旧源時計更新・全旧reset取消。', '対照': None},
        'C1': {'説明': '価格時計gapだけでは取消しない。他の発注・取消・時計・peer選択はC0と同一。', '対照': 'C0',
            '禁止': 'gapがある正常行での発注禁止を足さない。足すなら別枝であり厳密一軸ではない。'},
        'C2': {'説明': 'C1の新源確認を各自anchor後のindex/seq厳密更新と当該時計非逆行へ変更。自己phase時刻より後という両時計比較は用いない。', '対照': 'C1',
            '意味の違い': '双方が同じphase時刻の後に進んだ証拠から、各市場の異なる公表基準から進んだ証拠へ変更する。',
            '必須': '旧の厳密過去・同時計先頭peerを保持。proxy上の未来peer、不明peer、源再利用、seq逆行を許さない。'},
        'C3': {'説明': 'C1の旧reset及び最良不正取消を、元期限内の停止→正常pairで再準備へ変更。価格位相は断裂ごとに破棄。', '対照': 'C1',
            '再準備': '元候補ID/方向/元quote/W/TTLは記録上保持し、発注用参照quote・peak・extreme・両BBO基準を新正常pairで作り直す。同行では発注せず新たな進行が必要。'},
        'C4': {'説明': 'C3から、原本連続・時計非逆行・最良価格数量正常な深板/出来高だけの故障は自己価格位相を保持する。', '対照': 'C3',
            '禁止': '完全10段Q、旧OFI、補充、累積出来高やJ2資格を正常化しない。best Qty0/NaNと遠方Qty不正を混同しない。'}}
    variants = [dict(id=f'{policy}_A{entry}_X1', 政策=policy, 入口=f'A{entry}', 出口='X1')
        for policy in policies for entry in (1, 5, 7)]
    variants.append(dict(id='即時A0_X1', 政策='変更なし', 入口='A0', 出口='X1'))
    assert len(variants) == 16
    source_paths = [ROOT / 'AGENTS.md', ROOT / 'work/wave_v57/features.py',
        ROOT / 'work/wave_v76/inputs/core.py', ROOT / 'work/wave_v77/inputs/core.py',
        ROOT / 'work/wave_v94/inputs_r1/core.py', ROOT / 'work/wave_v97/engine.py',
        ROOT / 'work/wave_v97/結果前の設計案.json',
        ROOT / 'work/wave_v97/review/3正式レビューの独立原因要旨と代理時計による活動不足の反証.json']
    artifact = dict(
        状態='98設計参考のみ・未採用。最終条件数/出口/主はrootが次の実装前に決める。',
        主結論='価格公表時計と原板の更新連番を分ける。ただし自己seqでは二市場の共通受信順序を証明できない。',
        旧97から確定する範囲='主のgap取消139件は原本seq連続。フィルタ欠番ではない。真受信時計が無いので静穏と収集停止は識別不能。押し回復全般の無効も証明していない。',
        有限政策=policies, 設計参考16案=variants,
        一軸比較=['C0→C1: 価格gap取消のみ', 'C1→C2: 新源の証拠定義のみ',
            'C1→C3: 故障後の取消と再準備のみ', 'C3→C4: 価格故障と深板/出来高故障の分類のみ'],
        無効な追加候補='自己clock更新だけseqへ替え、peer_clock>phase及びpeer_clock<=ownを残す枝は自己phase要件が冗長。別の改善候補数へ数えない。',
        入力と出口の分離={
            '固定': '候補P0/J8、既存密なJ2、自己執行資格Q/F/正常BBO、元候補消費、枚数8/16、次正常行fill、料金、W10bp、TTL300、場内返済及び返済後30秒を保持。',
            '入口': 'A1は気配進行のみ、A5は逆行必須でない追尾新規、A7は押し必須。価格位相の違いを代表3つで測る。',
            '出口': '16案のX1は説明用既存出口。97前16参考の再利用であり独立に選んだ新出口ではない。過去主のX3でも入口差を測るかはrootが正式前に決め、損益後に選ばない。',
            '除外': '新LPによるQ/OFI救済、J2再構成、W/TTL/費用/追尾幅の多数最適化、別の時間回避はこの入力対照へ混ぜない。'},
        peer因果モデル={
            '既存データ': '旧asofの格子より厳密過去かつ同時計先頭源だけを維持。自己実原行は自己seq順、相手は既存格子源。これは代理時計上の計算因果性であり真受信順の証明ではない。',
            '禁止': '別ファイルのseq大小比較、同時計peer末尾、後で正常になったpeer同時計後続、欠測のforwardfillによる正常化、時計逆行のソート修復。',
            'same_clock': '自己のseqだけ増えても旧peer格子は自己時計の関数なので相手源は増えない。自己same-clock発注が救われると約束しない。',
            '代替将来データ': '両銘柄を一つの記録順で受信し、共通global_seq・捕捉UTC時計・単調受信時計・接続epochを保存すれば、当該受信時点以前の最新peerを取れる。現31場へ後付けでこの順序を捏造しない。',
            '相手不明': '新規と新基準作成を停止。自己の正常価格経路は保持可能。相手の基準は無効化し、最初に戻った正常pairは基準だけ、以後の双方新源を要求。元TTLは延長しない。'},
        故障と有限状態={
            '優先順': '場末/TTL到達/既知の両市場硬反対→取消。clock又はseq逆行→候補取消及び当該入力区間隔離。以後は政策別の故障停止/再準備。最後に発注資格と価格/気配閾値を判定。',
            '取消後': '当該候補は消費済み。watchを解消した同じ行で別候補を新受理しない。新候補のepisodeからのみ再開始。',
            'TTL': '元candidate_time+300のまま。修復や極値で更新しない。CurrentPriceTime時計を使う限り300秒は代理時間であって真受信経過秒ではない。時計不明中は発注停止、正常時計が戻った最初に元期限判定を先行する。',
            '原行欠番/最良不正': 'C0/C1/C2は取消。C3/C4は位相と源基準を捨てて再準備待ち。未知区間をまたいだ古い極値から回復済みと判断しない。',
            '再準備の参照': '元quoteは親照合用の記録として保持する。発注用の新epoch_quoteは新正常pair時点の自己ask/bidへリセット。A7は新peakから再び押しを経験し、回復するまで発注しない。',
            '最初の準備行': '準備だけで発注不可。後続自己行と後続peer源が必要。新市場予約へ移る際にwatch占有を先に解除し二重保有にしない。',
            '深板だけ/出来高resetだけ': 'C4では最良価格数量正常・原seq連続・時計非逆行を直接確認した場合だけ価格位相を保持。OFI/補充の区間・出来高差は依然不明。旧bit1の深板異常直後を実初回と呼ばない。',
            '予約と保有': '成立後の市場予約は旧の次正常自己BBO約定を維持。予約中や保有中の信号を復活させない。既存返済及び場末返済は入力改修へ混ぜない。'},
        必要反証=[
            '同じ保存seq100/101と価格時計100/120から、静穏と真停止の両方が説明できる。',
            '自己clock条件だけ除去してもpeerの上下限から同じ自己phase条件が導かれる。',
            '同時計peerの最初が不正で後続が正常でも旧asofは不明のまま。未来追加で過去源は変わらない。',
            '自己seqは更新・相手seqは同じ、又は相手が未来時計なら確認成立しない。',
            '各自anchor後へ進んだpeerが自己phase前の価格時計を持つ場合、意味の変更を明示する。',
            'gapを取消理由から外した正常gap行で条件成立した場合、C1は発注を妨げない。別のgap行禁止を暗黙に入れない。',
            '最良数量0/NaN、原行欠番、時計不明では発注しない。遠方Qty異常だけと区別する。',
            '100から未知区間を越えて110へ復帰した例は、旧100の起点で1W済みと扱わず新epochで再準備する。',
            '修復時点が元TTL残り10秒でも期限は残り10秒。TTLちょうどで価格閾値が成立しても取消先行。',
            '時計逆行はseq増加があっても正常化しない。相手不明の初回復帰行は基準のみ。',
            '再準備中も枠は一つ。watch解除行の新pulseは消費、予約→fillの次行と全親会計を保持。'],
        毎場安定評価={
            '優先': '両商品別の赤字場数、活動黒字率、平均/最大赤字、共通上限10/20と全31分母の下方偏差。最大合計利益で順位を作らない。',
            '必須': '無取引を勝ちに数えず、親数/活動場を併記。20親8活動場、両費用後黒字、金額80%、平均勝ち/負け比、最大利益日/親除外は別判定。',
            '分解': '同じ元候補row/seq/方向を照合し、実建値差・返済差・料金差・見送った利益/回避した損失・新固有親・後続連鎖を全会計へ含める。',
            '活動': '価格gapだけ保持した候補、reset修復候補、相手不明で停止した候補を分類。取引数を減らした損失縮小と同候補の収益改善を区別する。',
            '既知': '全31は既知。前16/後15・日夜を分けるが未知成功と呼ばず、前16参考も損益前に固定する。'},
        論理的利点と反証={
            '保持': '普通の静穏を情報断裂と決めず、価格回復を観測する機会を残せる。一方、古い候補から遅い高値買い/安値売りを増やす危険がある。',
            'seq': '価格時計が変わらない板更新を一銘柄内で読める。一方、peerが古い又は時計モデルが不適切なら共通方向の確認は見かけになる。',
            '再準備': '欠けた価格経路を極値として継承せず、復帰を一度の新証拠へ区切れる。一方、元期限内に再度押し回復を待つため勝ち波を逃し取引数が減る。',
            'reset分類': '遠方深板だけの故障を最良価格の破綻と混同しない。一方、旧J2が不明のままなら保有待機だけ増えて成立は増えない。'},
        次実装前に決める事項=['最終条件数・出口X1のみかX3を併記するか・理論主',
            'C2の正確な新源定義と、旧asof下で本当に独立した採否差があること',
            '故障診断のraw reset分類とunknown段階の列、再準備epochと元候補の別列'],
        根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in source_paths},
        計算コードSHA256=digest(Path(__file__)),
        新98正式候補生成=0, 新98売買実行=0, 新98損益閲覧=0, API取得=0, 実注文=0,
        旧97固定編集=0, 最終98採用=False)
    save('入力と取消の設計参考16案及び因果順の独立反証.json', artifact)
    save('代理時計とseq及び故障分類の人工反証.json', dict(artificial(),
        計算コードSHA256=digest(Path(__file__)),
        設計参考SHA256=digest(HERE / '入力と取消の設計参考16案及び因果順の独立反証.json')))
    print('98設計参考16案と人工論理を保存。最終条件未決定、新売買・新損益・APIは0。', flush=True)


if __name__ == '__main__':
    main()
