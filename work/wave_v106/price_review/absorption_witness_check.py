"""不成立の299小観測を独立射影と照合し、四部品交差の分母だけを確認する。"""

from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json

from range_engine_check import digest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/e01_absorption_gate'
COMPONENTS = ('数量非減少','支持非進行','接触二回以上','活動比一以上')


def read(path: Path) -> dict:
    """
    機能: 小さな保存射影だけを解析する。
    引数: path(Path)はJSONの位置。
    返り値: dictは保存観測。大型preparedやNPZを再読しない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def verify_group(rows: list[dict], saved: dict) -> dict:
    """
    機能: 同じ商品・側・場の四成分16交差と不足組合せを独立集計する。
    引数: rows(list[dict])、saved(dict)は検査済み小観測と所有集計。
    返り値: dictは分母付きの簡潔な不成立説明。勝敗は測定しない。
    """
    known = [r for r in rows if r['eligible'] and r['known']]
    allowed = [r for r in known if r['base_known_veto_allowed']]
    simple = dict(全公開数=len(rows),元許可数=sum(r['base_known_veto_allowed'] for r in rows),
        適用対象数=sum(r['eligible'] for r in rows),適用対象既知数=len(known),
        適用対象未知数=sum(r['eligible'] and not r['known'] for r in rows),
        元票未知数=sum(not r['base_known'] for r in rows),
        元票既知二票未満数=sum(r['base_known'] and r['base_direction_votes']<2 for r in rows),
        成立数=sum(r['hit'] is True for r in rows),
        尾部一原行数=sum(r['episode_start_raw_row']==r['candidate_raw_row'] for r in known),
        接触零数=sum(r['touch_count']==0 for r in known),接触一回数=sum(r['touch_count']==1 for r in known),
        最大接触回数=max((r['touch_count'] for r in known),default=None),
        最大活動比=max((r['touch_activity_ratio'] for r in known),default=None))
    for key,value in simple.items(): assert saved[key]==value,(key,saved[key],value)
    assert len(saved['条件交差'])==16
    for bits,item in enumerate(saved['条件交差']):
        subset = [name for i,name in enumerate(COMPONENTS) if bits&(1<<i)]
        expected = dict(条件=subset,適用対象既知分母=len(known),件数=sum(all(r['components'][k] for k in subset) for r in known),
            元許可分母=len(allowed),元許可件数=sum(all(r['components'][k] for k in subset) for r in allowed))
        assert item==expected,(item,expected)
    groups = {}; ordered = []
    for row in known:
        failed = tuple(k for k in COMPONENTS if not row['components'][k])
        if failed not in groups: groups[failed]=[]; ordered.append(failed)
        groups[failed].append(row)
    assert len(saved['不足組合せ'])==len(groups)
    for names,item in zip(ordered,saved['不足組合せ']):
        group = groups[names]
        assert item['不足成分']==list(names) and item['件数']==len(group) and item['元許可件数']==sum(r['base_known_veto_allowed'] for r in group)
        assert item['原順例']==group[:2]
    three = [r for r in known if all(r['components'][k] for k in COMPONENTS if k!='接触二回以上')]
    return dict(**simple,元許可での三条件成立=sum(r['base_known_veto_allowed'] for r in three),接触以外三条件成立=len(three),
        同価格一接触のうち終点だけ=sum(r['touch_count']==1 and r['touch_rows']==[r['candidate_raw_row']] for r in known))


def main() -> None:
    """
    機能: 全299witnessを一読の独立射影へ結び、全商品・売買・場の集計を検算する。
    引数: なし。prepared/原cache/NPZ/金融/APIを読まない。
    返り値: Noneは所有領域の限定診断証跡。市場全体の現象不存在を主張しない。
    """
    target = HERE/'absorption_全299小観測と全成分交差の独立検算.json'; assert not target.exists()
    path = SOURCE/'diagnosis/全299公開の表示維持観測と条件交差.json'
    diagnosis = read(path); independent_path = HERE/'absorption_全299公開観測の独立射影.json'; independent = read(independent_path)
    meta = read(SOURCE/'全33場の表示維持公開観測の準備.json'); assert diagnosis['全合格'] and independent['全合格'] and meta['全合格']
    assert diagnosis['source']['SHA256']==digest(ROOT/diagnosis['source']['path'])
    assert diagnosis['consumer_SHA256']==digest(SOURCE/'diagnosis/project.py')
    assert diagnosis['目的SHA256']==digest(SOURCE/'diagnosis/固定部品の射影と不成立原因の目的.json')
    assert diagnosis['source_SHA256']==meta['source_SHA256']=={p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    rows = diagnosis['witness']; originals = independent['公開小観測']; assert len(rows)==len(originals)==299
    assert [(r['session'],r['symbol'],r['normal_row']) for r in rows]==[(r['session'],r['symbol'],r['normal_row']) for r in originals]
    checked = 0
    features = dict(candidate_raw_row='candidate_raw_row',candidate_raw_seq='candidate_raw_seq',eligible='eligible',known='known',hit='hit',
        feature_reason='reason',first_window_raw_row='first_window_raw_row',episode_start_raw_row='episode_start_raw_row',
        episode_start_raw_seq='episode_start_raw_seq',opposite_price='opposite_price',Q0='initial_quantity',Qmin='minimum_quantity',
        support_price='support_price',maximum_support_advance='maximum_support_advance',touch_rows='touch_rows',
        touch_raw_seq='touch_raw_seq',touch_count='touch_count',touch_activity_volume='touch_activity_volume',touch_activity_ratio='touch_activity_to_initial_ratio')
    for row,source in zip(rows,originals):
        f,b = source['feature'],source['base']
        assert row['side']==source['side'] and row['base_known_veto_allowed']==source['元許可']
        assert row['base_known']==b['known'] and row['base_direction_votes']==b['direction_votes'] and row['base_balance']==b['balance']
        expected_reason = 0 if source['元許可'] else 100+b['reason'] if not b['known'] else 200 if b['direction_votes']<2 else 202
        assert row['base_rejection_reason']==expected_reason
        assert row['direction']==('買い' if row['side']>0 else '売り')
        assert row['candidate_price_time_s']==b['candidate_price_time_s']
        assert row['JST']==datetime.fromtimestamp(row['candidate_price_time_s'],timezone(timedelta(hours=9))).isoformat()
        for actual,saved in features.items(): assert row[actual]==f[saved],actual; checked += 1
        expected = None
        if f['eligible'] and f['known']:
            expected = dict(数量非減少=f['minimum_quantity']>=f['initial_quantity'],支持非進行=f['maximum_support_advance']<=0,
                接触二回以上=f['touch_count']>=2,活動比一以上=f['touch_activity_volume']>=f['initial_quantity'])
        assert row['components']==expected
        assert isinstance(row['paper_parent'],int) and row['paper_parent']>=0
    summaries = {}; group_checks = 0
    for symbol in ('TOPIX','NK225'):
        own = [r for r in rows if r['symbol']==symbol]; summaries[symbol]=verify_group(own,diagnosis['商品別'][symbol]); group_checks += 1
        for side in (1,-1): verify_group([r for r in own if r['side']==side],diagnosis['商品側別'][symbol][str(side)]); group_checks += 1
        for session in meta['sessions']: verify_group([r for r in own if r['session']==session],diagnosis['各場'][session][symbol]); group_checks += 1
    assert group_checks==72
    for scene in diagnosis['指定時刻の公開観測']:
        expected = [r for r in rows if r['session']==scene['session'] and r['symbol']==scene['symbol'] and r['JST'][11:19]==scene['指定時計']]
        assert scene['該当公開']==expected
    assert all(diagnosis[k]==0 for k in ('NPZ','原板','原paper','旧金融読取','新金融','勝敗照合','API'))
    proof = dict(全合格=True,範囲='所有299小witnessと独立一読射影を突合し、72商品/側/場groupの16交差・不足型を再集計。大入力未再読。',
        所有witnessSHA256=digest(path),独立射影SHA256=digest(independent_path),レビューsource_SHA256=digest(Path(__file__)),
        source_SHA256=diagnosis['source_SHA256'],全witness=299,突合feature項目数=checked,集計group数=group_checks,商品別の簡潔結果=summaries,
        prepared再読=0,原cache再読=0,NPZ=0,新金融=0,原板=0,API=0,
        留意点=['全対象の同価格接触が最大1回なので2回門が必ず不成立。活動比1の追加だけで成立0となったわけではない。',
            '接触以外三条件を満たす21公開でも同価格接触1回で、固定述語は不成立。2回を1回へ変える金融は未測定。',
            '対象はE01紙上公開299行。全raw更新で同価格反復接触が存在しないことや、板読み全体の無効性は証明していない。',
            '元のpaper_parentは所有projectのorder[2]射影経路を静的確認し型/範囲を点検。独立射影にcidを保存していないため元feedとの別bytes突合は主張しない。',
            '保存されたQmin等の数値とsource契約を検算した。元rawを独立再測定して同じ最小/最大を得た主張ではない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('逆板維持の全299小観測と72group交差の独立検算合格',digest(target))
    print(json.dumps(summaries,ensure_ascii=False))


if __name__=='__main__': main()
