"""Feasibility projection for household schedule actions."""
from typing import Any
from profiles import HomeProfile

def project(action: dict[str, Any], home: HomeProfile, step: int | None = None, battery_soc_kwh: float | None = None, ev_remaining_kwh: float | None = None,
            room_temp_c: float | None = None, outdoor_temp_c: float | None = None, ev_soc_kwh: float | None = None) -> tuple[dict[str, Any],list[str]]:
    """Clamp an action to device limits and return corrections."""
    result = dict(action); corrections = []
    ev_limit=home.ev_kw
    if step is not None:
        deadline=home.ev_deadline_step%96
        if not home.ev_kw or not (step>=home.ev_arrival_step or step<deadline): ev_limit=0
    if ev_remaining_kwh is not None: ev_limit=min(ev_limit,max(0,ev_remaining_kwh)/.25)
    if ev_soc_kwh is not None and home.ev_battery_kwh: ev_limit=min(ev_limit,max(0,home.ev_battery_kwh-ev_soc_kwh)/.25)
    charge_limit=home.battery_power_kw if home.battery_kwh else 0
    discharge_limit=home.battery_power_kw if home.battery_kwh else 0
    if battery_soc_kwh is not None:
        charge_limit=min(charge_limit,max(0,home.battery_kwh-battery_soc_kwh)/(.25*home.battery_efficiency))
        discharge_limit=min(discharge_limit,max(0,battery_soc_kwh)*home.battery_efficiency/.25)
    for key, limit in (("ac_kw", home.ac_count * home.ac_kw), ("ev_kw", ev_limit), ("battery_charge_kw", charge_limit), ("battery_discharge_kw", discharge_limit)):
        value = max(0.0, min(float(result.get(key, 0)), limit))
        if value != result.get(key, 0): corrections.append(f"clamped {key}")
        result[key] = value
    if step is not None and room_temp_c is not None and outdoor_temp_c is not None:
        start,end=home.temperature_window
        comfort_active=(start<=step<end) if start<end else (step>=start or step<end)
        if comfort_active:
            required=max(0,(room_temp_c+.015*(outdoor_temp_c-room_temp_c)-home.temperature_setpoint_c)/.7)
            if result['ac_kw']<required:
                result['ac_kw']=min(home.ac_count*home.ac_kw,required)
                corrections.append('raised AC to preserve resident temperature constraint')
    if result["battery_charge_kw"]>0 and result["battery_discharge_kw"]>0:
        overlap=min(result["battery_charge_kw"],result["battery_discharge_kw"])
        result["battery_charge_kw"]-=overlap; result["battery_discharge_kw"]-=overlap
        corrections.append("removed simultaneous battery charge and discharge")
    for key, limit in (("geyser_kw", .9 if home.geyser else 0), ("other_kw", .6 if home.washing_machine else 0)):
        original = float(result.get(key, 0))
        result[key] = max(0.0, min(original, limit))
        if result[key] != original: corrections.append(f"clamped {key}")
    for key in ("comfort_deficit",):
        original = float(result.get(key, 0))
        result[key] = max(0.0, min(original, 10.0))
        if result[key] != original: corrections.append(f"clamped {key}")
    if step is not None and any(start<=step<end for start,end in home.blocked_windows):
        for key in ("geyser_kw","other_kw"):
            if result[key]>0: result[key]=0.; corrections.append(f"blocked {key} during resident quiet window")
    return result, corrections
