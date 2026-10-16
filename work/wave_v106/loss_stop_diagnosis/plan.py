"""初回同数量・同sourceの旧勝ち赤字化を、二例だけ結果前に固定する。"""

import common


def prepare() -> None:
    """
    機能: 完成小metadataから指定条件の最大失勝二例と四台帳を固定する。
    引数: なし。新旧結果及び入力目録の小JSONだけを読む。
    返り値: None。実台帳・inputpacket・原板・金融の読取はしない。
    """
    paths={kind:common.ROOT/f'work/wave_v106/{folder}/finance/結果.json'
        for kind,folder in (('new','e01_size_loss_anchor'),('old','e01_size_goal_anchor'))}
    values={};sha={}
    for kind,path in paths.items():values[kind],sha[path.relative_to(common.ROOT).as_posix()]=common.small(path)
    fixed_path=common.ROOT/'work/wave_v106/e01_size_loss_anchor/金融事前固定.json'
    fixed,digest=common.small(fixed_path);sha[fixed_path.relative_to(common.ROOT).as_posix()]=digest
    new,old=values['new'],values['old'];assert new['全合格'] and old['全合格'] and fixed['全合格']
    config=next(c for c in new['configs'] if c['mode']=='CONFIRM' and c['profit_ticks']==1)
    cid=config['id'];baseline=config['baseline_id'];assert baseline in old['results']
    before={(v['session'],v['symbol']):v for v in old['初回受理と費用後目標境界'][baseline]}
    after={(v['session'],v['symbol']):v for v in new['初回受理と費用後目標境界'][cid]}
    selected=[]
    for symbol in ('TOPIX','NK225'):
        candidates=[]
        for value in new['各場寄与'][cid]:
            if value['symbol']!=symbol:continue
            key=value['session'],symbol
            oldfirst=before[key]['実政策初回新規'];newfirst=after[key]['実政策初回新規']
            if oldfirst is None or newfirst is None:continue
            fields=('row','source_row','paper_parent','quantity','price','raw_seq')
            if any(oldfirst[f]!=newfirst[f] for f in fields):continue
            for parent in value['元勝ち親が赤字化']:
                if parent['parent']==oldfirst['paper_parent'] and parent['old_net']>0>parent['new_net']:
                    candidates.append(dict(session=key[0],symbol=symbol,parent=parent['parent'],
                        old_net=parent['old_net'],new_net=parent['new_net'],差=parent['old_net']-parent['new_net'],
                        first=oldfirst,old_boundary=before[key],new_boundary=after[key]))
        assert candidates,('指定資格を満たす初回親が無い',symbol)
        chosen=sorted(candidates,key=lambda v:(-v['差'],v['session'],v['parent']))[0]
        for kind,identifier in (('new',cid),('old',baseline)):
            matches=[r for r in values[kind]['results'][identifier]['ledgers']
                if r['session']==chosen['session'] and r['symbol']==symbol]
            assert len(matches)==1;chosen[kind+'_ledger']=matches[0]
        chosen['候補数']=len(candidates);selected.append(chosen)
    packets={v['session']:fixed['input_cache'][v['session']] for v in selected}
    assert 1<=len(packets)<=2
    common.write('二例の初回同数量回復勝ちを調べる固定計画.json',dict(全合格=True,
        条件=cid,比較元=baseline,選定='CONFIRM_P1、初回実親・同数量・同sourceの旧黒字→新赤字。oldnet-newnet最大、同点は場名/parent順。',
        selected=selected,input_packets=packets,metadata_SHA256=sha,source_SHA256=common.sources(),
        読取予定=dict(対象台帳=4,対象input=len(packets),他全33=0,原板=0,NPZ=0,金融再生=0,API=0),
        目的='初期spread・注文別料と小往復が比例線を破り、旧実会計の回復利益を失ったかを時刻と気配で確認する。',
        数式資格='初回実親、過去損益0、損失判断まで部分返済無し、アンカーqと実q一致の場合のみ、初期清算気配からの必要逆行/順行幅を計算。',
        限界=['選定は事後診断の代表例で、勝率の分母でも未来の入口判定でもない。',
            '時刻は価格代理時計。板の厚さ/補充/真の受信時刻を推定しない。',
            '旧実利益だけを比較し、新しい救済取引や未見利益のcounterfactualは作らない。'],
        台帳読取=0,input読取=0,授権後のみ診断=True))
    print('最大失勝の二例を小metadataだけから固定。根レビュー/診断授権待ち。',flush=True)


if __name__=='__main__':prepare()
