"""根の仕様文章から作る入口状態の独立純参照。入口③の取消後再取得禁止と①②の再取得許容を分ける。"""

from dataclasses import dataclass,field
import math


@dataclass(frozen=True)
class Observation:
    """
    機能: 人工の一原行に必要な確定L・両BBO・現在情報を保持する。
    引数: row/bucket/confirmed(int)、high/low/bid/ask(float)、資格(bool)、方向配列(tuple) は当時観測。
    返り値: Observation は不変の人工。paper方向や未来の価格を持たない。
    """
    row:int
    bucket:int
    confirmed:int
    high:float
    low:float
    bid:float
    ask:float
    normal:bool=True
    volume_known:bool=True
    price_known:bool=True
    volume_gate:tuple[bool,bool]=(True,False)
    price_gate:tuple[bool,bool]=(True,False)
    interval_known:bool=True
    new_up:int=0
    new_down:int=0


@dataclass
class Probe:
    """
    機能: 認定行に固定した突破BBOと最初の反対更新を別段階で保持する。
    引数: row(int)、bid/ask(float) は突破観測。
    返り値: Probe は人工の未公開状態。現在値で過去基準を上書きしない。
    """
    row:int
    bid:float
    ask:float
    opposed:Observation|None=None
    opposed_lower:int=0


@dataclass
class Episode:
    """
    機能: 同じbucket/L/sideで各入口の公開消費と未公開probeを分ける。
    引数: side/bucket/serial(int)、level(float) は側と人工episodeの水準。
    返り値: Episode は実busy/FAKの採否とは独立の構造状態。
    """
    side:int
    bucket:int
    serial:int
    level:float
    seen_break:bool=False
    used:set[int]=field(default_factory=set)
    probes:dict[int,Probe]=field(default_factory=dict)


class Reference:
    """
    機能: 三入口を正常観測ごとに進め、最大一回の公開を独立に認定する。
    引数: tick(float)、reanchor_modes(tuple[bool,bool,bool]) は観測呼値とモード別再取得の可否。
    返り値: Reference は人工モデル。根裁定では①②のみ再取得可、③はepisode終了。
    """

    def __init__(self,tick:float,reanchor_modes:tuple[bool,bool,bool]=(True,True,False)):
        """
        機能: 二方向を別episodeとして初期化する。
        引数: tick(float)、reanchor_modes(tuple[bool,bool,bool]) は呼値とモード別再取得の可否。
        返り値: None。価格予測・金融を実行しない。
        """
        assert math.isfinite(tick) and tick>0
        self.tick=tick
        assert len(reanchor_modes)==3
        self.reanchor_modes=reanchor_modes
        self.episodes={}
        self.serial={1:0,-1:0}
        self.blocked_probes={1:set(),-1:set()}
        self.events=[]

    def new_episode(self,side:int,p:Observation,level:float) -> Episode:
        """
        機能: 新bucket又はL反対側の戻りで構造episodeを新しくする。
        引数: side(int)、p(Observation)、level(float) は側・当行・既知L。
        返り値: Episode は未消費の新状態。返済だけでは呼ばない。
        """
        self.serial[side]+=1
        self.blocked_probes[side].clear()
        value=Episode(side,p.bucket,self.serial[side],level)
        self.episodes[side]=value
        return value

    def cancel_probe(self,episode:Episode,mode:int) -> None:
        """
        機能: 未公開probeだけを取り消し、公開済みの消費を保持する。
        引数: episode(Episode)、mode(int) は側の状態と入口。
        返り値: None。FAKや実親を持たないため取消対象にしない。
        """
        existed=mode in episode.probes
        episode.probes.pop(mode,None)
        if existed and not self.reanchor_modes[mode]:
            self.blocked_probes[episode.side].add(mode)

    def observe(self,p:Observation) -> list[dict]:
        """
        機能: 当時までの既知L・BBO・票を使い、三入口の初公開だけを返す。
        引数: p(Observation) は人工現在行。
        返り値: list[dict] は当行候補。実約定・勝ち・再参加成功ではない。
        """
        new=[]
        for direction,side in enumerate((1,-1)):
            level=p.high if side>0 else p.low
            episode=self.episodes.get(side)
            if episode is None or episode.bucket!=p.bucket:
                episode=self.new_episode(side,p,level)
            if not (math.isfinite(level) and p.confirmed<p.row and p.normal):
                for mode in range(3):
                    if mode not in episode.used:
                        self.cancel_probe(episode,mode)
                continue
            assert math.isclose(level,episode.level,rel_tol=0.,abs_tol=0.),'同bucketの接触前Lは不変'
            returned=(p.bid<=level and p.ask<=level) if side>0 else (p.bid>=level and p.ask>=level)
            if returned and episode.seen_break:
                episode=self.new_episode(side,p,level)
            beyond=(p.bid>level and p.ask>level) if side>0 else (p.bid<level and p.ask<level)
            episode.seen_break=episode.seen_break or beyond
            for mode in range(3):
                if mode in episode.used or mode in self.blocked_probes[side]:
                    continue
                if not p.volume_known or (mode and not p.price_known):
                    self.cancel_probe(episode,mode)
                    continue
                probe=episode.probes.get(mode)
                if probe is None:
                    if beyond:
                        episode.probes[mode]=Probe(p.row,p.bid,p.ask)
                    continue
                assert probe.row<p.row
                if mode==2:
                    if side*(p.bid-probe.bid)<-self.tick or side*(p.ask-probe.ask)<-self.tick:
                        self.cancel_probe(episode,mode)
                        continue
                    activity=p.new_down if side>0 else p.new_up
                    if probe.opposed is None and p.interval_known and activity>=1:
                        probe.opposed=p
                        probe.opposed_lower=activity
                    opposite=probe.opposed
                    progressed=bool(opposite is not None and opposite.row<p.row and side*(p.bid-opposite.bid)>=2*self.tick and side*(p.ask-opposite.ask)>=2*self.tick)
                else:
                    opposite=None
                    progressed=side*(p.bid-probe.bid)>=self.tick and side*(p.ask-probe.ask)>=self.tick
                qualification=p.volume_gate[direction] and (mode==0 or p.price_gate[direction])
                if progressed and qualification:
                    event=dict(row=p.row,mode=mode,side=side,episode=(side,episode.bucket,episode.serial),
                        bucket=p.bucket,level=level,break_row=probe.row,b0=probe.bid,a0=probe.ask,
                        opposite_row=opposite.row if opposite is not None else -1,
                        bp=opposite.bid if opposite is not None else None,ap=opposite.ask if opposite is not None else None,
                        confirmed=p.confirmed,opposite_lower=probe.opposed_lower if mode==2 else 0)
                    episode.used.add(mode)
                    self.events.append(event)
                    new.append(event)
        return new


def mirror(p:Observation,center:float=1000.) -> Observation:
    """
    機能: 人工の高安/BBO/買売資格/反対票を対称に変換する。
    引数: p(Observation)、center(float) は一人工観測と鏡像定数。
    返り値: Observation は売り側の対称人工。価格順序を崩さない。
    """
    return Observation(p.row,p.bucket,p.confirmed,center-p.low,center-p.high,center-p.ask,center-p.bid,
        p.normal,p.volume_known,p.price_known,(p.volume_gate[1],p.volume_gate[0]),(p.price_gate[1],p.price_gate[0]),
        p.interval_known,p.new_down,p.new_up)


def run(points:list[Observation],tick:float,reanchor_modes:tuple[bool,bool,bool]=(True,True,False)) -> tuple[list[dict],Reference]:
    """
    機能: 独立人工の接頭を逐次進め、公開と消費状態を得る。
    引数: points(list[Observation])、tick(float)、reanchor_modes(tuple[bool,bool,bool]) は素材とモード別取消境界。
    返り値: tuple[list[dict],Reference] は公開列と人工状態。owner実装は呼ばない。
    """
    value=Reference(tick,reanchor_modes)
    for p in points:
        value.observe(p)
    return value.events,value
