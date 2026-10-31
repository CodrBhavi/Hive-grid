"""Reward-weighted on-policy fine-tuning of the HOME policy head."""
import argparse, random
from pathlib import Path
import numpy as np
import torch
from model import HivePolicy, ROLE_HOME, FEATURES
from collect import sample

def reward(actions: torch.Tensor, observations: torch.Tensor) -> torch.Tensor:
    """Compute per-step simulated utility from cost, peak, and comfort terms."""
    bounded=actions.clamp(0,1)
    ac, ev, geyser, other, charge, discharge, comfort = bounded.unbind(-1)
    price=observations[...,4].clamp(0,1); stress=observations[...,5].clamp(0,1); solar=observations[...,3].clamp(0,1)
    import_kw=(.35 + ac*1.5 + ev*2.0 + geyser*.7 + other*.5 + charge*.7 - discharge*.7 - solar*1.5).clamp(min=0)
    cost=import_kw*price
    peak=(import_kw*(.5+stress)).square()
    comfort_penalty=comfort.clamp(min=0).square()
    violation=(torch.relu(-actions)+torch.relu(actions-1)).square().sum(dim=-1)
    return -(cost + .25*peak + .35*comfort_penalty + 3*violation)

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument('--model',default='artifacts/hive_policy.pt'); parser.add_argument('--data',default='data/teacher.pt'); parser.add_argument('--output',default='artifacts/hive_policy_rl.pt'); parser.add_argument('--updates',type=int,default=200); parser.add_argument('--seed',type=int,default=29); parser.add_argument('--smoke',action='store_true'); args=parser.parse_args()
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed); torch.use_deterministic_algorithms(True)
    if Path(args.model).exists():
        saved=torch.load(args.model,map_location='cpu',weights_only=True); model=HivePolicy(); model.load_state_dict(saved['state_dict'])
    elif args.smoke:
        from collect import sample
        x,r,y=sample(args.seed,128); model=HivePolicy(); optimizer=torch.optim.AdamW(model.parameters(),lr=3e-4)
        ox=torch.from_numpy(x); rr=torch.from_numpy(r); yy=torch.from_numpy(y)
        optimizer.zero_grad(set_to_none=True); torch.nn.functional.mse_loss(model(ox,rr),yy).backward(); optimizer.step()
        data={'observations':ox,'roles':rr,'actions':yy}
    else: raise SystemExit(f'Missing trained imitation model: {args.model}; train.py must run first')
    if 'data' not in locals(): data=torch.load(args.data,map_location='cpu',weights_only=True)
    home_mask=data['roles']==ROLE_HOME; observations=data['observations'][home_mask]
    if len(observations)==0: raise SystemExit('Training data has no HOME role samples')
    for parameter in model.parameters(): parameter.requires_grad_(False)
    home_head=model.heads[ROLE_HOME]
    for parameter in home_head.parameters(): parameter.requires_grad_(True)
    optimizer=torch.optim.AdamW(home_head.parameters(),lr=1e-5); updates=2 if args.smoke else args.updates; batch_size=8 if args.smoke else 32
    for update in range(updates):
        indices=torch.randint(len(observations),(batch_size,)); obs=observations[indices]
        with torch.no_grad(): encoded=model.norm(model.encoder(model.input(obs)+model.position[:,:obs.shape[1]]+model.role(torch.full((batch_size,),ROLE_HOME)).unsqueeze(1)).mean(dim=1))
        mean=home_head(encoded); dist=torch.distributions.Normal(mean,torch.full_like(mean,.12)); action=dist.sample(); log_prob=dist.log_prob(action).sum(-1)
        returns=reward(action,obs).mean(dim=1); advantage=(returns-returns.mean()).detach()
        loss=-(log_prob*advantage).mean() + .01*(mean.square().mean())
        optimizer.zero_grad(set_to_none=True); loss.backward(); torch.nn.utils.clip_grad_norm_(home_head.parameters(),.5); optimizer.step()
        if update % max(1,updates//5)==0: print(f'update {update+1}/{updates}: reward={returns.mean().item():.4f} loss={loss.item():.4f}')
    target=Path(args.output); target.parent.mkdir(parents=True,exist_ok=True); torch.save({'state_dict':model.state_dict(),'features':FEATURES,'actions':7,'seed':args.seed,'fine_tuned':'home_reward_policy'},target); print(f'Saved fine-tuned HOME head to {target}')
if __name__=='__main__': main()
