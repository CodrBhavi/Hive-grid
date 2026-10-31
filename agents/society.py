"""Society price coordination and fairness weights."""
class SocietyAgent:
    """Coordinates aggregate loads with public multipliers and fairness weights."""
    def __init__(self) -> None: self.rounds = 0; self.deficits = {}; self.price_multiplier = 1.0
    def observe(self, loads: dict[str,float], cap: float, deficits: dict[str,float] | None = None, step: int = 0) -> None:
        self.loads, self.cap = loads, cap
        self.step=step
        if deficits is not None: self.deficits = dict(deficits)
    def act(self, learned_actions: dict[str, list[float]] | None = None) -> dict:
        if self.rounds < 5:
            total=sum(self.loads.values())
            rule_multiplier=min(2.0,self.price_multiplier*1.1) if total>self.cap else max(.5,self.price_multiplier*.95)
            if learned_actions:
                learned_multiplier=sum(min(1.5,max(.5,action[0])) for action in learned_actions.values())/len(learned_actions)
                self.price_multiplier=min(2.0,max(.5,.5*rule_multiplier+.5*learned_multiplier))
            else: self.price_multiplier=rule_multiplier
            self.rounds += 1
        vector=[self.price_multiplier*(1.1 if 18<=((self.step+i)%96)/4<22 else .95) for i in range(48)]
        weights={}
        for home,load in self.loads.items():
            weight=1/(1+self.deficits.get(home,0))
            if learned_actions and home in learned_actions:
                weight*=min(1.5,max(.5,learned_actions[home][1]))
            weights[home]=weight
        return {"round": self.rounds, "price_multiplier":self.price_multiplier,"price_multiplier_vector":vector,
                "weights": weights}
    def explain(self) -> str: return "Adjusted price signals and fairness weights using current society demand."
