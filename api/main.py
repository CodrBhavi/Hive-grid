"""FastAPI application and deterministic simulation manager."""
from __future__ import annotations
from threading import RLock
from queue import Queue, Empty
from typing import Any
from dataclasses import replace
from functools import wraps
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, RootModel
from profiles import generate_profiles
from world import World
from agents.home import HomeAgent
from agents.society import SocietyAgent
from agents.grid import GridAgent
from metrics import summarize
from shield import project
from market import clear_market
from energy import balance
from messages import PriceSignal, P2POffer, P2PBid, Accept, Reject, encode_message

class StartRequest(BaseModel):
    n_homes: int = Field(default=60, ge=50, le=100)
    seed: int = 7
    policy: str = "teacher"
    scenario: str = "summer"
class StepsRequest(BaseModel): n_steps: int = Field(default=1, ge=1, le=96)
class EventRequest(BaseModel): type: str = "heatwave"; start: int = Field(default=72, ge=0, le=95); end: int = Field(default=88, ge=1, le=96); cap_reduction_pct: float = Field(default=20, ge=0, le=80)
class OverrideRequest(BaseModel): constraint: dict[str, Any] | None = None; text: str | None = None
class ApiResponse(RootModel[Any]):
    """Pydantic response envelope for dynamically shaped API resources."""

class SimulationManager:
    """Thread-safe, resettable one-day simulation state."""
    def __init__(self): self.lock = RLock(); self.started = False; self.reset()
    def reset(self):
        with getattr(self, 'lock', RLock()):
            self.started=False; self.step=0; self.homes=[]; self.world=None; self.logs=[]; self.loads=[]; self.trades=[]; self.home_stats={}; self.running_cost=0.0; self.solar_total=0.0; self.solar_used=0.0; self.overrides={}; self.baseline_loads=[]; self.violations=0; self.negotiation_round=0; self.price_multiplier=1.0; self.fairness_weights={}; self.event_subscribers=set()
    def start(self, req: StartRequest):
        if req.policy not in ('teacher', 'learned'): raise HTTPException(400, detail='policy must be teacher or learned')
        if req.scenario not in ('summer','heatwave'): raise HTTPException(400,detail='scenario must be summer or heatwave')
        with self.lock:
            self.homes=generate_profiles(req.n_homes, req.seed); self.world=World(req.seed); self.step=0; self.logs=[]; self.loads=[]; self.trades=[]; self.home_stats={h.id:{'cost':0.,'baseline_cost':0.,'comfort':0.,'savings':0.,'soc':h.battery_kwh*.5,'baseline_soc':h.battery_kwh*.5,'ev_initial_soc':h.ev_battery_kwh*.5,'ev_remaining':max(h.ev_energy_need_kwh,h.ev_battery_kwh*max(0,h.ev_target_pct-.5)),'baseline_ev_remaining':max(h.ev_energy_need_kwh,h.ev_battery_kwh*max(0,h.ev_target_pct-.5)),'ev_energy_delivered':0.,'baseline_ev_delivered':0.,'ev_energy_used':0.,'room_temp':h.temperature_setpoint_c,'baseline_room_temp':h.temperature_setpoint_c} for h in self.homes}; self.started=True; self.policy=req.policy; self.seed=req.seed; self.learned_model=None; self.learned_fallback=req.policy=='learned'; self.overrides={}; self.baseline_loads=[]; self.solar_total=0.; self.solar_used=0.; self.running_cost=0.; self.trades=[]; self.loads=[]; self.logs=[]; self.violations=0; self.negotiation_round=0; self.price_multiplier=1.0; self.fairness_weights={}
            if req.scenario == 'heatwave': self.world.heatwave=True
            if req.policy == 'learned':
                try:
                    import torch
                    from pathlib import Path
                    from model import HivePolicy
                    rl_path=Path('artifacts/hive_policy_rl.pt')
                    model_path=rl_path if rl_path.exists() else Path('artifacts/hive_policy.pt')
                    if model_path.exists():
                        self.learned_model=HivePolicy(); self.learned_model.load_state_dict(torch.load(model_path,map_location='cpu',weights_only=True)['state_dict']); self.learned_model.eval(); self.learned_fallback=False
                except (ImportError, OSError, RuntimeError, KeyError):
                    self.learned_model=None; self.learned_fallback=True
            return self.state()
    def require(self):
        if not self.started: raise HTTPException(409, detail='Start a simulation first')
    def subscribe_events(self):
        """Register a queue and return it with a consistent event snapshot."""
        subscriber=Queue()
        with self.lock:
            self.event_subscribers.add(subscriber); snapshot=list(self.logs)
        return subscriber,snapshot
    def unsubscribe_events(self, subscriber):
        with self.lock: self.event_subscribers.discard(subscriber)
    def publish_event(self, event):
        """Publish one action log to each active SSE stream."""
        with self.lock:
            for subscriber in tuple(self.event_subscribers): subscriber.put(event)
    def state(self):
        with self.lock:
            net=self.loads[-1]['net_load_kw'] if self.loads else 0.; current=max(0,self.step-1)
            return {'current_step':self.step,'time':f'{self.step//4:02d}:{(self.step%4)*15:02d}','society_net_load_kw':net,'cap_kw':self.world.cap_kw(len(self.homes),current) if self.world else 0.,'grid_price':self.world.price(current) if self.world else 0.,'stress':self.world.is_stress(current,net,len(self.homes)) if self.world else False,'running_cost':self.running_cost}
    def advance(self, count):
        with self.lock:
            self.require(); count=min(count,96-self.step)
        for _ in range(count):
            with self.lock:
                if self.step>=96: break
                self.one_step()
        with self.lock: return self.state()
    def one_step(self):
        s=self.step; temp,cloud,hot=self.world.weather(s); price=self.world.price(s); previous_load=self.loads[-1]['net_load_kw'] if self.loads else 0.; stress=self.world.is_stress(s,previous_load,len(self.homes))
        grid=GridAgent(self.world); grid.observe(s,n_homes=len(self.homes)); societal=SocietyAgent(); coord=HomeAgent
        rows=[]; solar_step=0.; used_step=0.; cost_step=0.; baseline_import=0.; offers=[]; bids=[]; homes_by_id={}; schedules={}; effective_homes={}; logs_by_home={}
        learned_predictions={}
        if self.learned_model is not None:
            try:
                import torch
                sequences=[]
                for profile in self.homes:
                    history=[]
                    for offset in range(48):
                        forecast_step=(s-47+offset)%96; forecast_temp,forecast_cloud,forecast_hot=self.world.weather(forecast_step)
                        forecast_stress=self.world.heatwave and self.world.heat_start<=forecast_step<self.world.heat_end
                        stat=self.home_stats[profile.id]; ev_soc=stat['ev_initial_soc']+stat['ev_energy_delivered']-stat['ev_energy_used']
                        history.append([forecast_step/96,forecast_temp/50,forecast_cloud,self.world.solar_kw(profile.solar_kwp,forecast_step,forecast_cloud)/8,self.world.price(forecast_step)/.3,float(forecast_stress),profile.solar_kwp/8,profile.ac_count/4,profile.ac_kw/2,profile.ev_kw/8,profile.battery_kwh/10,profile.base_load_kw/2,profile.comfort_weight/1.5,profile.cost_weight/1.5,profile.flexibility_weight,profile.ev_energy_need_kwh/20,(stat['room_temp']-profile.temperature_setpoint_c)/10,(stat['soc']/profile.battery_kwh if profile.battery_kwh else 0)])
                    sequences.append(history)
                batch=torch.tensor(sequences,dtype=torch.float32)
                with torch.inference_mode(): predicted=self.learned_model(batch,torch.zeros(len(self.homes),dtype=torch.long)).tolist()
                learned_predictions={h.id:predicted[i] for i,h in enumerate(self.homes)}
            except (RuntimeError, ValueError, TypeError): self.learned_fallback=True
        for h in self.homes:
            effective=replace(h, **self.overrides.get(h.id, {})) if self.overrides.get(h.id) else h
            effective_homes[h.id]=effective
            stat=self.home_stats[h.id]
            if h.ev_kw and effective.ev_deadline_step%96<h.ev_arrival_step and s==h.ev_arrival_step:
                trip=h.ev_energy_need_kwh
                current_soc=max(0,stat['ev_initial_soc']+stat['ev_energy_delivered']-stat['ev_energy_used'])
                stat['ev_energy_used']+=min(trip,current_soc)
                stat['ev_remaining']=max(trip,effective.ev_battery_kwh*effective.ev_target_pct-max(0,current_soc-trip))
                baseline_soc=max(0,stat['ev_initial_soc']+stat['baseline_ev_delivered']-trip)
                stat['baseline_ev_remaining']=max(trip,effective.ev_battery_kwh*effective.ev_target_pct-baseline_soc)
            solar=self.world.solar_kw(h.solar_kwp,s,cloud); home_agent=coord(effective); home_agent.observe({'step':s,'temperature_c':temp,'solar_kw':solar,'price':price,'stress':stress})
            act=home_agent.plan(s,self.world,stat['ev_remaining'],stat['soc'],stat['room_temp'],48)[0]; fallback=self.learned_fallback
            if self.learned_model is not None and h.id in learned_predictions:
                try:
                    prediction=learned_predictions[h.id]
                    candidate={'base_kw':h.base_load_kw,'ac_kw':prediction[0]*6,'ev_kw':prediction[1]*8,'geyser_kw':prediction[2]*1.2,'other_kw':prediction[3],'battery_charge_kw':prediction[4]*3,'battery_discharge_kw':prediction[5]*3,'solar_kw':solar,'comfort_deficit':prediction[6]*10}
                    ev_soc=stat['ev_initial_soc']+stat['ev_energy_delivered']-stat['ev_energy_used']
                    projected_candidate, candidate_corrections=project(candidate,effective,step=s,battery_soc_kwh=stat['soc'],ev_remaining_kwh=stat['ev_remaining'],room_temp_c=stat['room_temp'],outdoor_temp_c=temp,ev_soc_kwh=ev_soc)
                    if any(abs(float(candidate.get(k,0))-float(projected_candidate.get(k,0)))>1.0 for k in candidate):
                        fallback=True
                    else:
                        from scheduling import Schedule
                        act=Schedule(**projected_candidate); fallback=False
                except (RuntimeError, ValueError, TypeError): fallback=True
            ev_soc=stat['ev_initial_soc']+stat['ev_energy_delivered']-stat['ev_energy_used']
            projected, corrections=project(act.__dict__,effective,step=s,battery_soc_kwh=stat['soc'],ev_remaining_kwh=stat['ev_remaining'],room_temp_c=stat['room_temp'],outdoor_temp_c=temp,ev_soc_kwh=ev_soc)
            if self.policy=='learned' and fallback:
                corrections=corrections+['learned policy unavailable or outside safety bounds; teacher fallback']
            demand=projected['base_kw']+projected['ac_kw']+projected['ev_kw']+projected['geyser_kw']+projected['other_kw']
            net=demand+projected['battery_charge_kw']-projected['battery_discharge_kw']-solar
            offer_kwh=max(0,-net)*.25; bid_kwh=max(0,net)*.25
            if offer_kwh>1e-9: offers.append({'home':h.id,'kwh':offer_kwh,'price':.04,'weight':1.0})
            if bid_kwh>1e-9: bids.append({'home':h.id,'kwh':bid_kwh,'price':price,'weight':1/(1+stat['comfort'])})
            row={'home':h.id,'solar_kw':solar,'load_kw':demand,'net_kw':net,'import_kw':max(0,net),'export_kw':max(0,-net),'cost':0.0}; rows.append(row); homes_by_id[h.id]=row; schedules[h.id]=projected
            solar_step+=solar*.25; used_step+=min(solar,demand+projected['battery_charge_kw'])*.25
            bstart,bend=effective.temperature_window; baseline_comfort=(bstart<=s<bend) if bstart<bend else (s>=bstart or s<bend)
            baseline_target=effective.temperature_setpoint_c if baseline_comfort else effective.temperature_setpoint_c+2
            baseline_room=stat['baseline_room_temp']
            baseline_ac=min(effective.ac_count*effective.ac_kw,max(0,(temp-baseline_room)*.015/.7+max(0,baseline_room-baseline_target)*.8))
            stat['baseline_room_temp']=max(16,min(50,baseline_room+.015*(temp-baseline_room)-.7*baseline_ac))
            baseline_charge_kw=min(effective.battery_power_kw,max(0,(effective.battery_kwh-stat['baseline_soc'])/(.25*effective.battery_efficiency))) if effective.battery_kwh and price<=.08 else 0
            stat['baseline_soc']=min(effective.battery_kwh,stat['baseline_soc']+baseline_charge_kw*.25*effective.battery_efficiency)
            deadline=effective.ev_deadline_step%96; ev_due=bool(effective.ev_kw and (s>=effective.ev_arrival_step or s<deadline))
            baseline_ev_kw=min(effective.ev_kw,stat['baseline_ev_remaining']/.25) if ev_due else 0
            flat=int(effective.id[1:]); geyser_baseline=72+flat%8; washer_baseline=72+flat%16
            quiet=any(start<=s<end for start,end in effective.blocked_windows)
            baseline_demand=effective.base_load_kw+baseline_ac+baseline_ev_kw+baseline_charge_kw+(.9 if effective.geyser and s in (geyser_baseline,geyser_baseline+1) else 0)+(.6 if effective.washing_machine and not quiet and washer_baseline<=s<washer_baseline+4 else 0)
            baseline_net=baseline_demand-solar; baseline_cost=(max(0,baseline_net)*price-max(0,-baseline_net)*.04)*.25
            stat['baseline_cost']+=baseline_cost; stat['baseline_ev_remaining']=max(0,stat['baseline_ev_remaining']-baseline_ev_kw*.25); stat['baseline_ev_delivered']+=baseline_ev_kw*.25; baseline_import+=max(0,baseline_net)
            exchanged=[encode_message(PriceSignal('SOCIETY',h.id,0,{'grid_price':price,'cap_kw':self.world.cap_kw(len(self.homes),s),'stress':stress}))]
            if offer_kwh>1e-9: exchanged.append(encode_message(P2POffer(h.id,'SOCIETY',0,{'kwh':offer_kwh,'price':.04})))
            if bid_kwh>1e-9: exchanged.append(encode_message(P2PBid(h.id,'SOCIETY',0,{'kwh':bid_kwh,'price':price})))
            event={'timestamp':f'{s//4:02d}:{s%4*15:02d}','step':s,'role':'HOME','agent_id':h.id,'action':'scheduled household loads','shield_correction':corrections,'explanation':'Shifted flexible load using solar and tariff signals.','messages':exchanged,'policy':'teacher_fallback' if fallback and self.policy=='learned' else self.policy}
            self.logs.append(event); logs_by_home[h.id]=event
        trades,unmatched=clear_market(offers,bids,.04,price); self.trades=[]
        for trade in trades:
            seller=homes_by_id[trade['seller']]; buyer=homes_by_id[trade['buyer']]; kw=trade['kwh']/.25
            seller['net_kw']+=kw; seller['export_kw']=max(0,seller['export_kw']-kw); buyer['net_kw']-=kw; buyer['import_kw']=max(0,buyer['import_kw']-kw)
            seller['p2p_sold_kwh']=seller.get('p2p_sold_kwh',0)+trade['kwh']; buyer['p2p_bought_kwh']=buyer.get('p2p_bought_kwh',0)+trade['kwh']
            seller['p2p_money_earned']=seller.get('p2p_money_earned',0)+trade['kwh']*trade['price']; buyer['p2p_money_paid']=buyer.get('p2p_money_paid',0)+trade['kwh']*trade['price']
            seller['cost']-=trade['kwh']*trade['price']; buyer['cost']+=trade['kwh']*trade['price']; self.solar_used+=trade['kwh']; self.trades.append(trade)
            for home_id in (trade['seller'],trade['buyer']): logs_by_home[home_id]['messages'].append(encode_message(Accept('SOCIETY',home_id,0,{'trade':trade})))
        for offer in unmatched:
            logs_by_home[offer['home']]['messages'].append(encode_message(Reject('SOCIETY',offer['home'],0,{'reason':'no_crossing_bid','remaining_kwh':offer['kwh']})))
        for h in self.homes:
            row=homes_by_id[h.id]; st=self.home_stats[h.id]; action=schedules[h.id]
            row['cost']+=(row['import_kw']*.25*price-row['export_kw']*.25*.04)
            row['balance_residual_kwh']=balance(row['solar_kw']*.25,action['battery_discharge_kw']*.25,row['import_kw']*.25,row.get('p2p_bought_kwh',0),
                action['base_kw']*.25,action['ac_kw']*.25,action['ev_kw']*.25,action['geyser_kw']*.25,action['other_kw']*.25,
                action['battery_charge_kw']*.25,row['export_kw']*.25,row.get('p2p_sold_kwh',0))
            if abs(row['balance_residual_kwh'])>1e-6: self.violations+=1
            st['cost']+=row['cost']; st['savings']=st['baseline_cost']-st['cost']; st['comfort']+=action['comfort_deficit']*.25
            st['soc']=min(h.battery_kwh,max(0,st['soc']+action['battery_charge_kw']*.25*h.battery_efficiency-action['battery_discharge_kw']*.25/h.battery_efficiency))
            delivered=action['ev_kw']*.25; st['ev_remaining']=max(0,st['ev_remaining']-delivered); st['ev_energy_delivered']+=delivered
            deadline=effective_homes[h.id].ev_deadline_step%96
            if h.ev_kw and s==deadline-1 and st['ev_remaining']>1e-6: self.violations+=1
            room=st['room_temp']; st['room_temp']=max(16,min(50,room+.015*(temp-room)-.7*action['ac_kw']))
            effective=effective_homes[h.id]; start,end=effective.temperature_window
            if ((start<=s<end) if start<end else (s>=start or s<end)) and st['room_temp']>effective.temperature_setpoint_c+.1: self.violations+=1
            cost_step+=row['cost']
        net_load=sum(x['net_kw'] for x in rows); imports=sum(x['import_kw'] for x in rows)
        cap=self.world.cap_kw(len(self.homes),s); societal.observe({row['home']:max(0,row['net_kw']) for row in rows},cap,{key:value['comfort'] for key,value in self.home_stats.items()},s)
        negotiation=societal.act()
        while sum(societal.loads.values())>cap and societal.rounds<5: negotiation=societal.act()
        self.negotiation_round=negotiation['round']; self.fairness_weights=negotiation['weights']; self.price_multiplier=negotiation['price_multiplier']
        for event in logs_by_home.values():
            event['messages'].append(encode_message(PriceSignal('SOCIETY',event['agent_id'],negotiation['round'],{'multiplier_vector':negotiation['price_multiplier_vector'],'fairness_weight':self.fairness_weights[event['agent_id']]})))
            self.publish_event(event)
        self.baseline_loads.append(baseline_import)
        self.loads.append({'step':s,'net_load_kw':net_load,'grid_import_kw':imports,'grid_export_kw':sum(x['export_kw'] for x in rows),'losses_kwh':0.0,'cap_kw':self.world.cap_kw(len(self.homes),s),'temperature_c':temp,'heatwave':hot,'p2p_trades':self.trades,'homes':rows})
        self.solar_total+=solar_step; self.solar_used+=used_step; self.running_cost+=cost_step; self.step+=1
    def metrics(self):
        with self.lock:
            self.require(); peak=max((x['grid_import_kw'] for x in self.loads),default=0); baseline=max(self.baseline_loads,default=0)
            costs=[v['cost'] for v in self.home_stats.values()]; savings=[v['baseline_cost'] for v in self.home_stats.values()]
            result=summarize(baseline,peak,self.solar_total,self.solar_used,costs,savings,[v['comfort'] for v in self.home_stats.values()])
            result['per_home_cost']={h.id:self.home_stats[h.id]['cost'] for h in self.homes}; result['per_home_savings']={h.id:self.home_stats[h.id]['savings'] for h in self.homes}
            result['hard_constraint_violations']=self.violations; result['violations']=self.violations; result['comfort_degree_hours']=sum(v['comfort'] for v in self.home_stats.values())
            return result

manager=SimulationManager(); app=FastAPI(title='HiveGrid API',version='1.0.0'); app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
def synchronized(function):
    """Serialize API reads or mutations against simulator stepping."""
    @wraps(function)
    def wrapped(*args,**kwargs):
        with manager.lock: return function(*args,**kwargs)
    return wrapped
def need(): manager.require()
@app.exception_handler(HTTPException)
async def errors(_, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status_code,content={'error':'request_error','detail':exc.detail})
@app.exception_handler(Exception)
async def unexpected_errors(_, exc):
    from fastapi.responses import JSONResponse
    if isinstance(exc, HTTPException): return await errors(_, exc)
    return JSONResponse(status_code=500,content={'error':'internal_error','detail':str(exc)})
@app.exception_handler(RequestValidationError)
async def invalid_requests(_, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422,content={'error':'validation_error','detail':jsonable_encoder(exc.errors())})
@app.get('/health',response_model=ApiResponse)
def health(): return {'status':'ok'}
@app.get('/',include_in_schema=False)
def demo_frontend(): return FileResponse(Path(__file__).resolve().parents[1]/'frontend'/'index.html',media_type='text/html')
@app.post('/simulation/start',response_model=ApiResponse)
def start(req:StartRequest): return manager.start(req)
@app.post('/simulation/reset',response_model=ApiResponse)
def reset(): manager.reset(); return {'status':'reset'}
@app.post('/simulation/step',response_model=ApiResponse)
def step(req:StepsRequest): return manager.advance(req.n_steps)
@app.post('/simulation/run',response_model=ApiResponse)
def run(): manager.require(); manager.advance(96-manager.step); return {'state':manager.state(),'metrics':manager.metrics()}
@app.get('/simulation/state',response_model=ApiResponse)
def state(): need(); return manager.state()
@app.get('/homes',response_model=ApiResponse)
def homes():
    with manager.lock:
        need(); return [{'profile':h.__dict__,'schedule':manager.loads[-1]['homes'][i] if manager.loads else None,'battery_soc_kwh':manager.home_stats[h.id]['soc'],'ev_soc_pct':min(1,max(0,(manager.home_stats[h.id]['ev_initial_soc']+manager.home_stats[h.id]['ev_energy_delivered']-manager.home_stats[h.id]['ev_energy_used'])/h.ev_battery_kwh)) if h.ev_battery_kwh else 0,'ev_remaining_kwh':manager.home_stats[h.id]['ev_remaining'],'comfort_deficit':manager.home_stats[h.id]['comfort'],'today_cost':manager.home_stats[h.id]['cost'],'today_savings':manager.home_stats[h.id]['savings']} for i,h in enumerate(manager.homes)]
@app.get('/homes/{home_id}',response_model=ApiResponse)
def home(home_id:str):
    need(); result=next((x for x in homes() if x['profile']['id']==home_id),None)
    if result is None: raise HTTPException(404,detail='Home not found')
    return result
@app.get('/society',response_model=ApiResponse)
def society():
    with manager.lock:
        need(); return {'peak_kw':max((x['grid_import_kw'] for x in manager.loads),default=0),'cap_kw':manager.state()['cap_kw'],'negotiation_round':getattr(manager,'negotiation_round',0),'price_multiplier':getattr(manager,'price_multiplier',1.0),'p2p_trades_this_step':manager.trades,'fairness_weights':getattr(manager,'fairness_weights',{})}
@app.get('/grid',response_model=ApiResponse)
@synchronized
def grid(): need(); return {'temperature_c':manager.world.weather(max(0,manager.step-1))[0],'price':manager.state()['grid_price'],'cap_kw':manager.state()['cap_kw'],'stress':manager.state()['stress'],'heatwave_event':manager.world.heatwave}
@app.post('/grid/event',response_model=ApiResponse)
@synchronized
def grid_event(req:EventRequest):
    need()
    if req.type!='heatwave' or req.end<=req.start: raise HTTPException(400,detail='Expected heatwave with end after start')
    manager.world.heatwave=True; manager.world.heat_start=req.start; manager.world.heat_end=req.end; manager.world.cap_reduction_pct=req.cap_reduction_pct
    event={'timestamp':manager.state()['time'],'step':manager.step,'role':'GRID','agent_id':'GRID','action':'heatwave demand-response event','shield_correction':[],'explanation':f'Activated heatwave stress from step {req.start} through {req.end-1} with a {req.cap_reduction_pct:g}% cap reduction.','messages':[encode_message(PriceSignal('GRID','SOCIETY',manager.negotiation_round,{'event':'heatwave','start':req.start,'end':req.end,'cap_reduction_pct':req.cap_reduction_pct}))]}; manager.logs.append(event); manager.publish_event(event)
    return grid()
@app.get('/metrics',response_model=ApiResponse)
def metrics(): return manager.metrics()
@app.get('/timeseries',response_model=ApiResponse)
def timeseries():
    with manager.lock: need(); return {'steps':list(manager.loads)}
@app.get('/events',response_model=ApiResponse)
def events():
    with manager.lock: need(); return {'events':list(manager.logs)}
@app.get('/events/stream')
def stream(limit: int | None = Query(default=None, ge=1)):
    need()
    import asyncio, json
    async def generate():
        subscriber,snapshot=manager.subscribe_events()
        try:
            for event in snapshot[:limit] if limit is not None else snapshot: yield 'data: '+json.dumps(event)+'\n\n'
            if limit is not None: return
            while True:
                try: event=await asyncio.to_thread(subscriber.get,True,15)
                except Empty: yield ': keepalive\n\n'; continue
                yield 'data: '+json.dumps(event)+'\n\n'
        finally: manager.unsubscribe_events(subscriber)
    return StreamingResponse(generate(),media_type='text/event-stream')
@app.post('/homes/{home_id}/override',response_model=ApiResponse)
@synchronized
def override(home_id:str,req:OverrideRequest):
    need(); h=next((x for x in manager.homes if x.id==home_id),None)
    if h is None: raise HTTPException(404,detail='Home not found')
    constraint=req.constraint or {}
    if req.text and not constraint:
        import re
        text=req.text.lower(); found=re.search(r'(\d+(?:\.\d+)?)\s*(?:c|°)',text)
        constraint={'temperature_setpoint_c':float(found.group(1))} if found else {}
        if not constraint: raise HTTPException(400,detail='Could not parse text; send a structured constraint object')
    allowed={'ev_deadline_step','ev_target_pct','temperature_setpoint_c','temperature_window','blocked_windows'}
    unknown=set(constraint)-allowed
    if unknown: raise HTTPException(400,detail=f'Unsupported constraint fields: {sorted(unknown)}')
    if 'ev_deadline_step' in constraint and (not isinstance(constraint['ev_deadline_step'],int) or not 0<=constraint['ev_deadline_step']<96): raise HTTPException(400,detail='EV deadline must be an integer in [0, 95]')
    if 'ev_target_pct' in constraint and not 0<=float(constraint['ev_target_pct'])<=1: raise HTTPException(400,detail='EV target must be in [0, 1]')
    if ('ev_deadline_step' in constraint or 'ev_target_pct' in constraint) and not h.ev_kw: raise HTTPException(400,detail='This home has no EV to apply EV charging constraints to')
    if 'temperature_setpoint_c' in constraint and not 18<=float(constraint['temperature_setpoint_c'])<=30: raise HTTPException(400,detail='Temperature setpoint must be in [18, 30] C')
    if 'temperature_window' in constraint:
        window=constraint['temperature_window']
        if not isinstance(window,(tuple,list)) or len(window)!=2 or not all(isinstance(v,int) and 0<=v<96 for v in window) or window[0]==window[1]: raise HTTPException(400,detail='temperature_window must be two distinct steps in [0, 95]')
        constraint['temperature_window']=tuple(window)
    if 'blocked_windows' in constraint:
        windows=constraint['blocked_windows']
        if not isinstance(windows,list) or any(not isinstance(w,list) or len(w)!=2 or not all(isinstance(v,int) for v in w) or not 0<=w[0]<w[1]<=96 for w in windows): raise HTTPException(400,detail='blocked_windows must be [[start_step, end_step], ...] within [0, 96]')
        constraint['blocked_windows']=tuple(tuple(w) for w in windows)
    updated={**manager.overrides.get(home_id,{}),**constraint}
    deadline=updated.get('ev_deadline_step',h.ev_deadline_step)
    if 'temperature_setpoint_c' in constraint:
        target=updated['temperature_setpoint_c']; start,end=updated.get('temperature_window',h.temperature_window); current=manager.step%96
        active=(start<=current<end) if start<end else (current>=start or current<end)
        if active:
            room=manager.home_stats[home_id]['room_temp']; outdoor=manager.world.weather(current)[0]
            required=max(0,(room+.015*(outdoor-room)-target)/.7)
            if required>h.ac_count*h.ac_kw+1e-6: raise HTTPException(400,detail=f'Temperature constraint infeasible for the next step: needs {required:.2f} kW AC but this home has {h.ac_count*h.ac_kw:.2f} kW')
    if h.ev_kw and 'ev_target_pct' in constraint:
        target_energy=h.ev_battery_kwh*float(constraint['ev_target_pct'])
        delivered=manager.home_stats[home_id]['ev_energy_delivered']
        remaining=max(0,target_energy-(manager.home_stats[home_id]['ev_initial_soc']+delivered-manager.home_stats[home_id]['ev_energy_used']))
        deadline=updated.get('ev_deadline_step',h.ev_deadline_step)%96
        flat=int(h.id[1:]); steps=sum(1 for step in range(manager.step,96) if (step>=h.ev_arrival_step or step<deadline) and not (step<deadline and step%4==flat%4))
        possible=steps*.25*h.ev_kw
        if remaining>possible+1e-6: raise HTTPException(400,detail=f'EV target infeasible in this day: needs {remaining:.1f} kWh with at most {possible:.1f} kWh available')
        manager.home_stats[home_id]['ev_remaining']=remaining; manager.home_stats[home_id]['baseline_ev_remaining']=remaining
    if h.ev_kw and 'ev_deadline_step' in constraint:
        rem=manager.home_stats[home_id]['ev_remaining']; deadline=deadline%96
        flat=int(h.id[1:]); available_steps=sum(1 for step in range(manager.step,min(96,deadline if manager.step<deadline else 96)) if (step>=h.ev_arrival_step or step<deadline) and not (step<deadline and step%4==flat%4))
        available=available_steps*.25*h.ev_kw
        if rem>available+1e-6: raise HTTPException(400,detail=f'EV deadline infeasible: {rem:.1f} kWh remain but at most {available:.1f} kWh can be charged')
    manager.overrides[home_id]=updated
    event={'timestamp':manager.state()['time'],'step':manager.step,'role':'HOME','agent_id':home_id,'action':'resident override','shield_correction':[],'explanation':f'Applied structured resident override: {constraint}','messages':[]}; manager.logs.append(event); manager.publish_event(event)
    return {'home_id':home_id,'constraint':{**constraint,**({'blocked_windows':[list(w) for w in constraint['blocked_windows']]} if 'blocked_windows' in constraint else {})},'status':'accepted'}
