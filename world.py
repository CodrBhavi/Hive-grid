"""Nagpur-like deterministic weather and tariffs."""
import math, random
from dataclasses import dataclass, field

@dataclass
class World:
    seed: int
    heatwave: bool = False
    heat_start: int = 72
    heat_end: int = 84
    cap_reduction_pct: float = 20.0
    day_of_year: int = 130
    _cloud_cache: dict[int,float] = field(default_factory=dict,init=False,repr=False)
    def weather(self, step: int) -> tuple[float, float, bool]:
        rng = random.Random(self.seed * 1000 + step)
        annual = math.cos(2*math.pi*(self.day_of_year-130)/365)
        mean_temperature = 34 + 5*annual
        hour = (step % 96)/4
        diurnal = 3.2*math.cos(2*math.pi*(hour-14)/24)
        temp = mean_temperature + diurnal + (3 if self.heatwave and self.heat_start <= step < self.heat_end else 0) + rng.uniform(-1.2, 1.2)
        cloud = self._cloud_cache.get(step)
        if cloud is None:
            start=max(self._cloud_cache,default=-1)+1
            cloud=self._cloud_cache.get(start-1,.55)
            for index in range(start,step+1):
                cloud_rng = random.Random(self.seed * 1000 + index + 71)
                cloud = max(.05, min(1, .55 + .78 * (cloud - .55) + cloud_rng.uniform(-.12, .12)))
                self._cloud_cache[index]=cloud
        return temp, cloud, temp >= 43
    def solar_kw(self, kwp: float, step: int, cloud: float, day_of_year: int | None = None) -> float:
        hour = (step % 96) / 4
        day = self.day_of_year if day_of_year is None else day_of_year
        latitude=math.radians(21.15); declination=math.radians(23.45)*math.sin(2*math.pi*(284+day)/365)
        hour_angle=math.radians(15*(hour-12))
        daylight=max(0.0,math.sin(latitude)*math.sin(declination)+math.cos(latitude)*math.cos(declination)*math.cos(hour_angle))
        return kwp * daylight * (1 - .65 * cloud)
    def price(self, step: int) -> float:
        h = (step % 96) / 4
        return .08 if 10 <= h < 16 else (.24 if 18 <= h < 22 else .14)
    def is_stress(self, step: int, net_load_kw: float = 0.0, n_homes: int = 1) -> bool:
        """Detect a manual heatwave event, a hot evening, or cap exceedance."""
        hour=(step%96)/4; temp,_,_=self.weather(step)
        base_cap=n_homes*2.7
        return bool((self.heatwave and self.heat_start<=step<self.heat_end) or (temp>=43 and 18<=hour<22) or net_load_kw>base_cap)
    def cap_kw(self, n: int, step: int) -> float:
        cap = n * 2.7
        temp,_,_=self.weather(step); hour=(step%96)/4
        event=(self.heatwave and self.heat_start<=step<self.heat_end) or (temp>=43 and 18<=hour<22)
        return cap * (1 - self.cap_reduction_pct / 100) if event else cap
