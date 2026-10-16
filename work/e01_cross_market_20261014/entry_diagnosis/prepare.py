"""金融小会計だけから十五活動場と一赤字場を固定し、台帳本文はまだ読まない。"""

import common


def run() -> None:
    """
    機能: B03の全活動十五場とB01のTOPIX唯一赤字場を保存小結果から機械選定する。
    引数: なし。
    返り値: None。対象path/SHA・正しい分母・射影可能列の限界を結果前計画へ保存する。
    """
    path=common.ROOT/'work/e01_cross_market_20261014/engine/finance/結果.json'
    result,sha=common.read_json(path);assert result['全合格'] and result['source開始終端一致']
    targets=[]
    for cid in ('E01_CROSS_B03','E01_CROSS_B01'):
        case=result['results'][cid]
        for row in case['rows']:
            chosen=(row['親数']>0) if cid=='E01_CROSS_B03' else (row['symbol']=='TOPIX' and row['収支']<0)
            if not chosen:continue
            refs=[r for r in case['ledgers'] if r['session']==row['session'] and r['symbol']==row['symbol']]
            assert len(refs)==1
            targets.append(dict(refs[0],case_id=cid,small_row=row))
    assert len(targets)==16 and len({r['path'] for r in targets})==16
    assert sum(r['case_id']=='E01_CROSS_B03' and r['symbol']=='TOPIX' for r in targets)==7
    assert sum(r['case_id']=='E01_CROSS_B03' and r['symbol']=='NK225' for r in targets)==8
    targets.sort(key=lambda r:(r['case_id'],r['symbol'],r['session']))
    common.write('読取計画.json',dict(全合格=True,目的='B03無敗が少数方向票二票に依存するか、B01赤字の反証が残るかを完結実親だけで調べる。',
        result_path=path.relative_to(common.ROOT).as_posix(),result_SHA256=sha,金融源SHA256=result['source_SHA256'],
        source_SHA256=common.sources(),targets=targets,対象台帳数=16,
        選定='B03全活動場TOP7/NK8とB01TOP唯一赤字場。勝敗で親を削除せず、指定場の完結実親を全部射影。',
        予定=dict(新保存台帳各一読=16,入力packet読取=0,旧台帳読取=0,金融再生=0,原板=0,NPZ=0,API=0),
        limitations=['公開両BBOと各実fillの原seq/価格時計は台帳未保存。公開spread/ATR、公開代理時計、実fill行/片側価格を引用し、推定しない。',
            'MAEと費用後極値は保存された完結実親期間の事後診断で、入口/途中ルールへ将来値を流用しない。',
            '場清算から前親netを引く。粗時価MAEはpartial実現を含む親全体の金額で、全玉の単純価格逆行と混同しない。',
            '無敗の十五活動場は全三十三場の勝ちではない。小利確に比べ固定hardBが広いままで損小利大を保証しない。',
            '全GU診断のうち実ordersに対応する公開sourceだけを扱い、場停止後の影親を実績へ含めない。'],
        現在台帳読取=0,現在入力読取=0,金融=0,原板=0,NPZ=0,API=0))
    print('十五活動場と一赤字場の十六台帳読取計画のみ保存、本文読取0',flush=True)


if __name__=='__main__':run()
