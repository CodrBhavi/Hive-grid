"""Grid tariff, cap and demand response agent."""
from world import World
class GridAgent:
    """Publishes public grid signals without reading home state."""
    def __init__(self, world: World) -> None: self.world = world
    def observe(self, step: int, net_load: float = 0, n_homes: int = 1) -> None: self.step, self.net_load, self.n_homes = step, net_load, n_homes
    def act(self) -> dict[str, float | bool]: return {"price": self.world.price(self.step), "cap_kw": self.world.cap_kw(self.n_homes, self.step), "stress": self.world.is_stress(self.step,self.net_load,self.n_homes)}
    def explain(self) -> str: return "Published the time-of-use tariff and the active society cap signal."
