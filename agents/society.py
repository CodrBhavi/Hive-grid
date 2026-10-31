"""Society price coordination and fairness weights."""
class SocietyAgent:
    """Coordinates aggregate loads with public multipliers and fairness weights."""
    def __init__(self) -> None: self.rounds = 0; self.deficits = {}; self.price_multiplier = 1.0
    def observe(self, loads: dict[str,float], cap: float, deficits: dict[str,float] | None = None, step: int = 0) -> None:
        self.loads, self.cap = loads, cap
        self.step=step
        if deficits is not None: self.deficits = dict(deficits)
    def act(self) -> dict:
        if self.rounds < 5:
            total=sum(self.loads.values())
            self.price_multiplier=min(2.0,self.price_multiplier*1.1) if total>self.cap else max(.5,self.price_multiplier*.95)
            self.rounds += 1
        vector=[self.price_multiplier*(1.1 if 18<=((self.step+i)%96)/4<22 else .95) for i in range(48)]
        return {"round": self.rounds, "price_multiplier":self.price_multiplier,"price_multiplier_vector":vector,
                "weights": {k: 1 / (1 + self.deficits.get(k, 0)) for k in self.loads}}
    def explain(self) -> str: return "Adjusted price signals and fairness weights using current society demand."
