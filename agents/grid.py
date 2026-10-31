"""Grid tariff, cap and demand response agent."""
from world import World
class GridAgent:
    """Publishes public grid signals without reading home state."""
    def __init__(self, world: World) -> None: self.world = world
    def observe(self, step: int, net_load: float = 0, n_homes: int = 1) -> None: self.step, self.net_load, self.n_homes = step, net_load, n_homes
    def act(self, learned_action: list[float] | None = None) -> dict[str, float | bool]:
        rule_price=self.world.price(self.step); rule_cap=self.world.cap_kw(self.n_homes,self.step)
        stress=self.world.is_stress(self.step,self.net_load,self.n_homes); price=rule_price; cap=rule_cap
        if learned_action is not None:
            proposed_price=min(.3,max(0.,learned_action[0])*.3)
            price=min(.24,max(.08,.5*rule_price+.5*proposed_price))
            stress=stress or learned_action[1]>=.75
            response_factor=min(1.,max(.75,learned_action[2]))
            cap=rule_cap*response_factor
        return {"price":price,"cap_kw":cap,"stress":stress}
    def explain(self) -> str: return "Published the time-of-use tariff and the active society cap signal."
