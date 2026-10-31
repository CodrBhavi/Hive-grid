"""Deterministic synthetic household profiles for HiveGrid."""
from dataclasses import dataclass
import random

@dataclass(frozen=True)
class HomeProfile:
    id: str
    name: str
    archetype: str
    solar_kwp: float
    ac_count: int
    ac_kw: float
    ev_kw: float
    ev_battery_kwh: float
    ev_arrival_step: int
    ev_energy_need_kwh: float
    battery_kwh: float
    battery_efficiency: float
    battery_power_kw: float
    base_load_kw: float
    geyser: bool
    washing_machine: bool
    comfort_weight: float
    cost_weight: float
    flexibility_weight: float
    ev_deadline_step: int
    ev_target_pct: float
    temperature_setpoint_c: float
    temperature_window: tuple[int, int]
    blocked_windows: tuple[tuple[int, int], ...]

def generate_profiles(n: int, seed: int) -> list[HomeProfile]:
    """Generate distinct, repeatable homes; n is restricted to 50–100."""
    if not 50 <= n <= 100:
        raise ValueError("n must be between 50 and 100")
    rng = random.Random(seed)
    archetypes = ("working_couple", "family", "work_from_home", "elderly")
    homes = []
    for i in range(n):
        solar = round(rng.choice([0, 0, 1.5, 2, 3, 4, 5, 6, 7, 8]), 1)
        ev_kw = rng.choice([0, 0, 3.3, 7.4])
        homes.append(HomeProfile(
            id=f"H{i+1:03d}", name=f"Flat {i+1:03d}", archetype=archetypes[i % 4],
            solar_kwp=solar, ac_count=rng.randint(1, 4), ac_kw=round(rng.uniform(.8, 1.5), 2),
            ev_kw=ev_kw, ev_battery_kwh=60.0 if ev_kw else 0.0,
            ev_arrival_step=rng.randint(68, 84), ev_energy_need_kwh=round(rng.uniform(4, 16), 1) if ev_kw else 0.0,
            battery_kwh=rng.choice([0, 0, 5, 10]), battery_efficiency=.92,
            battery_power_kw=3.0, base_load_kw=round(rng.uniform(.35, 1.1), 2),
            geyser=rng.random() < .75, washing_machine=rng.random() < .7,
            comfort_weight=round(rng.uniform(.5, 1.5), 2), cost_weight=round(rng.uniform(.5, 1.5), 2),
            flexibility_weight=round(rng.uniform(.3, 1), 2), ev_deadline_step=32,
            ev_target_pct=.8, temperature_setpoint_c=24.0, temperature_window=(88, 32), blocked_windows=((32, 68),)))
    return homes
