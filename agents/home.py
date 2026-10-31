"""Private household scheduling agent."""
from scheduling import schedule_home, schedule_horizon
from profiles import HomeProfile
from scheduling import Schedule
from world import World
class HomeAgent:
    """Schedules one home's private flexible demand."""
    def __init__(self, profile: HomeProfile) -> None: self.profile, self.private_state = profile, {}
    def observe(self, observation: dict) -> None: self.private_state = dict(observation)
    def act(self, step: int, temp: float, solar: float, price: float, stress: bool) -> Schedule: return schedule_home(self.profile, step, temp, solar, price, stress)
    def plan(self, step: int, world: World, ev_remaining_kwh: float, battery_soc_kwh: float, room_temp_c: float, horizon: int = 48) -> list[Schedule]:
        """Return rolling-horizon schedules based only on this home's profile and public world signals."""
        return schedule_horizon(self.profile,step,world,ev_remaining_kwh,battery_soc_kwh,room_temp_c,horizon,
            current_price=self.private_state.get('price'),current_stress=self.private_state.get('stress'),
            price_multiplier=self.private_state.get('society_price_multiplier',1.0))
    def explain(self) -> str: return "Scheduled flexible loads around solar availability and the current peak signal."
