"""Evaluate learned policy imitation and its closed-loop API behavior."""
import argparse
from pathlib import Path
import torch
from collect import sample
from model import HivePolicy
from api.main import app
from fastapi.testclient import TestClient

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument('--model',default='artifacts/hive_policy.pt'); parser.add_argument('--seed',type=int,default=999); parser.add_argument('--smoke',action='store_true'); args=parser.parse_args()
    model=HivePolicy()
    if Path(args.model).exists():
        data=torch.load(args.model,map_location='cpu',weights_only=True); model.load_state_dict(data['state_dict'])
    elif args.smoke:
        x0,r0,y0=sample(args.seed,128); ox=torch.from_numpy(x0); rr=torch.from_numpy(r0); yy=torch.from_numpy(y0)
        optimizer=torch.optim.AdamW(model.parameters(),lr=3e-4)
        for _ in range(2): optimizer.zero_grad(set_to_none=True); torch.nn.functional.mse_loss(model(ox,rr),yy).backward(); optimizer.step()
    else: raise SystemExit(f'Missing model checkpoint: {args.model}')
    model.eval()
    x,r,y=sample(args.seed,64 if args.smoke else 2048)
    with torch.inference_mode(): prediction=model(torch.from_numpy(x),torch.from_numpy(r))
    mse=torch.mean((prediction-torch.from_numpy(y))**2).item(); client=TestClient(app)
    from api.main import manager
    client.post('/simulation/reset'); client.post('/simulation/start',json={'n_homes':50,'seed':args.seed,'policy':'teacher'}); client.post('/grid/event',json={'type':'heatwave','start':72,'end':88}); client.post('/simulation/run'); teacher=client.get('/metrics').json()
    client.post('/simulation/reset'); client.post('/simulation/start',json={'n_homes':50,'seed':args.seed,'policy':'learned'}); manager.learned_model=model; manager.learned_fallback=False; client.post('/grid/event',json={'type':'heatwave','start':72,'end':88}); client.post('/simulation/run'); learned=client.get('/metrics').json()
    within=learned['peak_reduction_pct'] >= .9*teacher['peak_reduction_pct']; fair=learned['jain_comfort']>=.9; safe=learned['violations']==0
    diagnosis=[]
    if not within: diagnosis.append('peak reduction fell more than 10% below the teacher')
    if not fair: diagnosis.append('comfort Jain index is below 0.9')
    if not safe: diagnosis.append('one or more hard-constraint or balance violations occurred')
    print({'heldout_mse':mse,'teacher_peak_reduction_pct':teacher['peak_reduction_pct'],'learned_peak_reduction_pct':learned['peak_reduction_pct'],'within_10pct_of_teacher':within,'jain_comfort':learned['jain_comfort'],'jain_target_met':fair,'violations':learned['violations'],'safety_target_met':safe,'diagnosis':diagnosis})
if __name__=='__main__': main()
