"""Core deterministic and API checks for Phase 1."""
from fastapi.testclient import TestClient
from api.main import app, manager
from profiles import generate_profiles
from energy import balance
from market import clear_market
from shield import project
from messages import PriceSignal, encode_message, decode_message
from replay import replay

client=TestClient(app)
def test_profiles_and_determinism():
    assert generate_profiles(60,4)==generate_profiles(60,4)
    assert len({h.name for h in generate_profiles(60,4)})==60
def test_balance_and_market_band():
    assert abs(balance(2,0,1,0,1,1,0,0,0,0,0,1))<1e-9
    trades,_=clear_market([{'home':'a','kwh':1,'price':.05}],[{'home':'b','kwh':1,'price':.2}],.04,.24)
    assert .04 <= trades[0]['price'] <= .24
def test_shield_fuzz():
    h=generate_profiles(50,2)[0]
    import random
    rng=random.Random(88)
    for val in [-1e6,-100,0,100,1e6]+[rng.uniform(-100,100) for _ in range(500)]:
        out,_=project({'ac_kw':val,'ev_kw':val,'battery_charge_kw':val,'battery_discharge_kw':val},h)
        assert 0<=out['ac_kw']<=h.ac_count*h.ac_kw and 0<=out['ev_kw']<=h.ev_kw
        assert 0<=out['battery_charge_kw']<=h.battery_power_kw and 0<=out['battery_discharge_kw']<=h.battery_power_kw
        assert out['battery_charge_kw']==0 or out['battery_discharge_kw']==0
    limited,_=project({'ac_kw':5,'ev_kw':8,'battery_charge_kw':3,'battery_discharge_kw':0},h,step=10,battery_soc_kwh=h.battery_kwh)
    assert limited['battery_charge_kw']==0
def test_protocol_round_trip_and_replay():
    message=PriceSignal('GRID','SOCIETY',2,{'price':.2})
    encoded=encode_message(message)
    assert encode_message(decode_message(encoded))==encoded
    records,inboxes=replay([encoded,encoded])
    assert records==[encoded,encoded] and len(inboxes['SOCIETY'])==2
def test_api_happy_and_errors():
    client.post('/simulation/reset')
    assert client.get('/simulation/state').status_code==409
    assert client.get('/health').json()['status']=='ok'
    demo=client.get('/')
    assert demo.status_code==200 and 'HiveGrid Demo' in demo.text
    assert client.post('/simulation/start',json={'n_homes':50,'seed':3}).status_code==200
    assert client.post('/simulation/step',json={'n_steps':2}).status_code==200
    assert client.get('/homes/H001').status_code==200
    assert client.get('/homes/nope').status_code==404
    assert client.get('/society').status_code==200 and client.get('/grid').status_code==200
    assert client.get('/metrics').status_code==200 and client.get('/timeseries').status_code==200
    assert client.get('/events').status_code==200
    assert client.post('/homes/H002/override',json={'constraint':{'ev_deadline_step':80}}).status_code==200
    assert client.post('/grid/event',json={'type':'heatwave','start':72,'end':88}).status_code==200
    completed=client.post('/simulation/run')
    assert completed.status_code==200
    data=client.get('/timeseries').json()['steps']
    assert all(abs(home['balance_residual_kwh'])<1e-6 for point in data for home in point['homes'])
    metrics=client.get('/metrics').json()
    assert metrics['hard_constraint_violations']==0
    assert metrics['peak_reduction_pct']>0
    response=client.get('/events/stream?limit=1')
    assert response.status_code==200 and response.text.startswith('data: ')

def test_same_seed_repeats():
    outputs=[]
    for _ in range(2):
        client.post('/simulation/reset')
        client.post('/simulation/start',json={'n_homes':50,'seed':19,'scenario':'heatwave'})
        client.post('/grid/event',json={'type':'heatwave','start':72,'end':88})
        client.post('/simulation/run')
        outputs.append((client.get('/metrics').json(),client.get('/timeseries').json()))
    assert outputs[0]==outputs[1]
