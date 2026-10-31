"""Rule-based rolling horizon household scheduling."""
from dataclasses import dataclass
from profiles import HomeProfile
from world import World

@dataclass
class Schedule:
    base_kw: float
    ac_kw: float
    ev_kw: float
    geyser_kw: float
    other_kw: float
    battery_charge_kw: float
    battery_discharge_kw: float
    solar_kw: float
    comfort_deficit: float

def schedule_home(home: HomeProfile, step: int, temp: float, solar_kw: float, price: float, stress: bool,
                  ev_remaining_kwh: float | None = None, room_temp_c: float | None = None,
                  battery_soc_kwh: float | None = None, pre_cool: bool = False) -> Schedule:
    """Choose feasible loads with peak avoidance and solar-first charging."""
    hour = (step % 96) / 4
    room = temp if room_temp_c is None else room_temp_c
    start, end = home.temperature_window
    comfort_active = (start <= step < end) if start < end else (step >= start or step < end)
    target = home.temperature_setpoint_c
    if pre_cool: target-=1
    if stress and 18 <= hour < 22 and not comfort_active: target += 2
    thermal_hold = max(0, temp-room) * .015/.7
    thermostat = max(0, room-target) * .8
    ac = min(home.ac_count * home.ac_kw, max(thermal_hold + thermostat, 0))
    flat=int(home.id[1:])
    deadline = home.ev_deadline_step % 96
    ev_window = home.ev_kw and (step >= home.ev_arrival_step or step < deadline)
    ev = min(home.ev_kw, (ev_remaining_kwh / .25) if ev_remaining_kwh is not None else home.ev_kw) if ev_window and not (stress and 18 <= hour < 22) else 0
    if step<deadline and step%4==flat%4: ev=0
    if 22 <= hour < 24 and int(home.id[1:])%4 != (step-88)%4: ev=0
    blocked = any(start <= step < end for start, end in home.blocked_windows)
    geyser_start=40+flat%24; washer_start=20+flat%8
    geyser = .9 if home.geyser and step in (geyser_start,geyser_start+1) else 0
    other = .6 if home.washing_machine and not blocked and washer_start<=step<washer_start+4 else 0
    demand = home.base_load_kw + ac + ev + geyser + other
    soc = home.battery_kwh * .5 if battery_soc_kwh is None else battery_soc_kwh
    charge_room_kw = max(0, (home.battery_kwh - soc) / (.25 * home.battery_efficiency)) if home.battery_kwh else 0
    discharge_room_kw = max(0, soc * home.battery_efficiency / .25) if home.battery_kwh else 0
    staggered_cheap_slot = price<=.08 and step in (40+flat%12,52+flat%12)
    charging_opportunity = max(0, solar_kw-demand) + (home.battery_power_kw if staggered_cheap_slot else 0)
    charge = min(home.battery_power_kw, charge_room_kw, charging_opportunity) if home.battery_kwh else 0
    discharge = min(home.battery_power_kw, discharge_room_kw, max(0, demand - solar_kw)) if home.battery_kwh and 18 <= hour < 22 else 0
    comfort = max(0,room-home.temperature_setpoint_c) if comfort_active else 0.0
    return Schedule(home.base_load_kw, ac, ev, geyser, other, charge, discharge, solar_kw, comfort)

def schedule_horizon(home: HomeProfile, start_step: int, world: World, ev_remaining_kwh: float,
                     battery_soc_kwh: float, room_temp_c: float, horizon: int = 48) -> list[Schedule]:
    """Roll the household teacher through a deterministic 48-step look-ahead."""
    schedules=[]; ev_left=ev_remaining_kwh; soc=battery_soc_kwh; room=room_temp_c
    for offset in range(max(1,min(48,horizon))):
        step=(start_step+offset)%96; temp,cloud,_=world.weather(step); solar=world.solar_kw(home.solar_kwp,step,cloud)
        stress=world.is_stress(step)
        group=int(home.id[1:])%3; hour=step/4
        pre_cool=bool(world.heatwave and world.heat_start-12<=step<world.heat_start and 15+group<=hour<16+group and solar>home.base_load_kw+home.ac_count*home.ac_kw)
        action=schedule_home(home,step,temp,solar,world.price(step),stress,ev_left,room,soc,pre_cool)
        schedules.append(action); ev_left=max(0,ev_left-action.ev_kw*.25)
        soc=min(home.battery_kwh,max(0,soc+action.battery_charge_kw*.25*home.battery_efficiency-action.battery_discharge_kw*.25/home.battery_efficiency))
        room=max(16,min(50,room+.015*(temp-room)-.7*action.ac_kw))
    return schedules
