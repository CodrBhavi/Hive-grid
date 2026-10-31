"""Train HivePolicy from scratch with deterministic teacher imitation."""
import argparse, random
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset
from model import HivePolicy, parameter_count, FEATURES

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument('--data',default='data/teacher.pt'); parser.add_argument('--output',default='artifacts/hive_policy.pt'); parser.add_argument('--epochs',type=int,default=12); parser.add_argument('--batch-size',type=int,default=128); parser.add_argument('--seed',type=int,default=17); parser.add_argument('--smoke',action='store_true'); args=parser.parse_args()
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed); torch.use_deterministic_algorithms(True)
    if not Path(args.data).exists() and args.smoke:
        from collect import sample
        x,r,y=sample(args.seed,512); data={'observations':torch.from_numpy(x),'roles':torch.from_numpy(r),'actions':torch.from_numpy(y)}
    else: data=torch.load(args.data,map_location='cpu',weights_only=True)
    n=min(len(data['roles']),512 if args.smoke else len(data['roles']))
    ds=TensorDataset(data['observations'][:n],data['roles'][:n],data['actions'][:n]); loader=DataLoader(ds,batch_size=16 if args.smoke else args.batch_size,shuffle=True,generator=torch.Generator().manual_seed(args.seed))
    model=HivePolicy(); optimizer=torch.optim.AdamW(model.parameters(),lr=3e-4); epochs=1 if args.smoke else args.epochs
    losses=[]
    for epoch in range(epochs):
        total=0.
        for x,role,y in loader:
            optimizer.zero_grad(set_to_none=True); loss=torch.nn.functional.mse_loss(model(x,role),y); loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),1.0); optimizer.step(); total+=float(loss.detach())
        epoch_mse=total/max(1,len(loader)); losses.append(epoch_mse)
        print(f'epoch {epoch+1}/{epochs}: mse={epoch_mse:.6f}')
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); torch.save({'state_dict':model.state_dict(),'features':FEATURES,'actions':7,'seed':args.seed,'training':{'sample_count':n,'epochs':epochs,'batch_size':16 if args.smoke else args.batch_size,'final_train_mse':losses[-1]}},out)
    print(f'Saved {parameter_count(model):,} parameters to {out}')
if __name__=='__main__': main()
