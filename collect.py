"""Collect deterministic observation/action pairs from rule-based teachers."""
import argparse
from pathlib import Path
import numpy as np
import torch
from model import FEATURES, ROLE_HOME, ROLE_SOCIETY, ROLE_GRID, HivePolicy
from profiles import generate_profiles
from scheduling import schedule_home
from world import World
from shield import project

def sample(seed: int, count: int, policy_model: HivePolicy | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate 48-step home sequences and role-labelled teacher actions."""
    rng = np.random.default_rng(seed); profiles = generate_profiles(60, seed); world = World(seed); world.heat_start=72; world.heat_end=88
    weather=[world.weather(step) for step in range(96)]
    solar_table={home.solar_kwp:[world.solar_kw(home.solar_kwp,step,weather[step][1]) for step in range(96)] for home in profiles}
    obs = np.zeros((count, 48, FEATURES), dtype=np.float32); acts = np.zeros((count, 7), dtype=np.float32); roles = np.zeros(count, dtype=np.int64)
    for i in range(count):
        world.heatwave=i%5==0
        home = profiles[int(rng.integers(len(profiles)))]; start = int(rng.integers(0, 96)); temp_bias = float(rng.uniform(-2, 5))
        role = i % 3; roles[i] = role
        if role == ROLE_HOME:
            room=world.weather(start)[0]+temp_bias; soc=home.battery_kwh*.5; ev_left=max(home.ev_energy_need_kwh,home.ev_battery_kwh*max(0,home.ev_target_pct-.5))
            for j in range(48):
                s=(start+j)%96; temp,cloud,heat=weather[s]
                if world.heatwave and 72<=s<88: temp+=3; heat=temp>=43
                solar=solar_table[home.solar_kwp][s]; price=world.price(s); stress=bool(world.heatwave and 72<=s<88)
                feature=[s/96,(temp+temp_bias)/50,cloud,solar/8,price/.3,float(stress),home.solar_kwp/8,home.ac_count/4,home.ac_kw/2,home.ev_kw/8,home.battery_kwh/10,home.base_load_kw/2,home.comfort_weight/1.5,home.cost_weight/1.5,home.flexibility_weight,home.ev_energy_need_kwh/20,(room-home.temperature_setpoint_c)/10,(soc/home.battery_kwh if home.battery_kwh else 0)]
                obs[i,j]=feature
                group=int(home.id[1:])%3; hour=s/4
                pre_cool=bool(world.heatwave and world.heat_start-12<=s<world.heat_start and 15+group<=hour<16+group and solar>home.base_load_kw+home.ac_count*home.ac_kw)
                sched=schedule_home(home,s,temp+temp_bias,solar,price,stress,ev_left,room,soc,pre_cool)
                chosen=sched
                if policy_model is not None:
                    with torch.inference_mode(): raw=policy_model(torch.tensor([[feature]*48]),torch.tensor([ROLE_HOME])).squeeze(0).tolist()
                    candidate={'base_kw':home.base_load_kw,'ac_kw':raw[0]*6,'ev_kw':raw[1]*8,'geyser_kw':raw[2]*1.2,'other_kw':raw[3],'battery_charge_kw':raw[4]*3,'battery_discharge_kw':raw[5]*3,'solar_kw':solar,'comfort_deficit':raw[6]*10}
                    safe,_=project(candidate,home,step=s,battery_soc_kwh=soc,ev_remaining_kwh=ev_left,room_temp_c=room,outdoor_temp_c=temp+temp_bias)
                    from scheduling import Schedule
                    chosen=Schedule(**safe)
                acts[i]=[sched.ac_kw/6,sched.ev_kw/8,sched.geyser_kw/1.2,sched.other_kw/1,sched.battery_charge_kw/3,sched.battery_discharge_kw/3,sched.comfort_deficit/10]
                room=max(16,min(50,room+.015*(temp+temp_bias-room)-.7*chosen.ac_kw)); soc=min(home.battery_kwh,max(0,soc+chosen.battery_charge_kw*.25*home.battery_efficiency-chosen.battery_discharge_kw*.25/home.battery_efficiency)); ev_left=max(0,ev_left-chosen.ev_kw*.25)
        else:
            for j in range(48):
                s=(start+j)%96; temp,cloud,heat=weather[s]
                if world.heatwave and 72<=s<88: temp+=3; heat=temp>=43
                price=world.price(s); stress=float(heat or (world.heatwave and 72<=s<88))
                obs[i,j]=[s/96,temp/50,cloud,solar_table[home.solar_kwp][s]/8,price/.3,stress,home.solar_kwp/8,home.ac_count/4,home.ac_kw/2,home.ev_kw/8,home.battery_kwh/10,home.base_load_kw/2,home.comfort_weight/1.5,home.cost_weight/1.5,home.flexibility_weight,home.ev_energy_need_kwh/20,0,0]
                if role==ROLE_SOCIETY: acts[i]=[min(1.5,max(.5,1+stress*.25)),home.flexibility_weight,0,0,0,0,0]
                else: acts[i]=[price/.3,stress,.8 if stress else 1,0,0,0,0]
    return obs, roles, acts

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument('--samples',type=int,default=100000); parser.add_argument('--seed',type=int,default=11); parser.add_argument('--output',default='data/teacher.pt'); parser.add_argument('--dagger-model'); parser.add_argument('--dagger-rounds',type=int,choices=(0,1,2),default=0); parser.add_argument('--append',action='store_true'); parser.add_argument('--smoke',action='store_true'); args=parser.parse_args()
    if args.dagger_rounds and not args.dagger_model: parser.error('--dagger-model is required when --dagger-rounds is nonzero')
    count=512 if args.smoke else args.samples; path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    if args.dagger_rounds:
        checkpoint=torch.load(args.dagger_model,map_location='cpu',weights_only=True); policy=HivePolicy(); policy.load_state_dict(checkpoint['state_dict']); policy.eval()
        chunks=[sample(args.seed+round_index,count//args.dagger_rounds,policy) for round_index in range(args.dagger_rounds)]
        obs=np.concatenate([part[0] for part in chunks]); roles=np.concatenate([part[1] for part in chunks]); acts=np.concatenate([part[2] for part in chunks])
    else: obs,roles,acts=sample(args.seed,count)
    new_data={'observations':torch.from_numpy(obs),'roles':torch.from_numpy(roles),'actions':torch.from_numpy(acts),'seed':args.seed,'dagger_rounds':args.dagger_rounds}
    if args.append and path.exists():
        old=torch.load(path,map_location='cpu',weights_only=True)
        for key in ('observations','roles','actions'): new_data[key]=torch.cat((old[key],new_data[key]))
    torch.save(new_data,path); print(f'Wrote {len(roles)} samples to {path}; DAgger rounds={args.dagger_rounds}')
if __name__=='__main__': main()
