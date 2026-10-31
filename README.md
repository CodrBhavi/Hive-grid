# HiveGrid

**Problem statement**

Build a multi-agent energy system for a housing society. Every home has an energy agent that knows resident preferences such as EV charging deadlines and bedroom temperature limits. A society agent coordinates homes, and a grid agent sends prices and demand-response signals. The system schedules flexible loads, trades surplus solar, and responds to grid stress while respecting household constraints.

**Why this matters**

Rooftop solar, home batteries, EVs and smart ACs are spreading through Indian housing societies. Uncoordinated charging and cooling can create hot-evening peaks while daytime solar is wasted or sold cheaply. Coordination can make these distributed resources more useful to residents and the grid.

**Expected impact**

Use distributed solar, storage and flexible demand to reduce peak demand and household energy costs without compromising resident constraints.

---

# HiveGrid simulation backend

## Plan and assumptions

1. Generate seeded, diverse profiles for 50–100 flats.
2. Simulate a 96-step day in 15-minute increments.
3. Use deterministic synthetic Nagpur summer weather and time-of-use tariffs.
4. Schedule household AC, EV, geyser, laundry and stationary batteries with rules.
5. Clamp device actions through a feasibility shield before accounting.
6. Coordinate homes with a society price signal and fairness weights.
7. Clear peer energy with an ascending-offer/descending-bid midpoint auction.
8. Track import/export, costs, solar use, peaks, comfort and savings.
9. Expose resettable simulation controls and chart/action-log endpoints through FastAPI.
10. Keep the teacher as a safety fallback while offering an optional learned HOME policy.

Assumptions: power values are average kW over each 15-minute interval and converted to kWh for energy balances and costs. EV energy need is a daily charging request; room comfort uses a simple thermal model and a nightly constraint window. Battery and EV models are approximate.

## Setup

```powershell
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000/` for the small interactive demo. Start the heatwave run, advance four 15-minute intervals at a time, or run the full day. OpenAPI docs are at `http://127.0.0.1:8000/docs`.

Run the terminal demo with `python demo_run.py --smoke`; run checks with `pytest`.

## Learned policy

The shared four-layer, 144-wide transformer has separate HOME, SOCIETY and GRID heads, all used by the learned simulation mode. The HOME head proposes household schedules; the SOCIETY head advises its price multiplier and fairness weights; the GRID head advises price, stress and response-cap signals. These signals feed the next household schedules. Rule-based checks remain as safety bounds and teacher fallback. The committed `artifacts/hive_policy.pt` checkpoint was initialized randomly and trained for four epochs on 5,000 seeded teacher examples. On a separate 512-example synthetic seed, held-out MSE was 0.00793 for HOME, 0.00249 for SOCIETY and 0.00973 for GRID. [A preview of three full training examples](teacher_dataset_preview.json) includes all 48 observations and each role's target action. Regenerate the exact training dataset with `python collect.py --samples 5000 --seed 11 --output data/teacher.pt`. In a seeded 50-home heatwave run, the three learned agents completed all 96 intervals with zero EV deadline, comfort, or energy-balance violations. This is one deterministic simulator result; it does not establish generalization beyond these synthetic scenarios. Home teacher schedules use a rolling 48-step horizon. The browser demo lets you choose the learned policy or teacher baseline. To retrain from scratch with a larger dataset, collect 100,000 teacher samples and train with:

```powershell
python collect.py --samples 100000 --seed 11 --output data/teacher.pt
python train.py --data data/teacher.pt --epochs 12 --output artifacts/hive_policy.pt
python eval.py --model artifacts/hive_policy.pt
```

The scripts support `--smoke`. Start the API with `policy=learned` to select the trained HOME head. Missing or invalid model weights and actions that need large safety corrections fall back to the teacher and are flagged in event logs. The HOME head always passes through `shield.py`. Live simulation uses the deterministic Society and Grid agents.

For a DAgger round, collect rollouts with the imitation checkpoint, relabel with the teacher, then retrain:

```powershell
python collect.py --samples 10000 --seed 29 --dagger-model artifacts/hive_policy.pt --dagger-rounds 1 --output data/dagger1.pt
python train.py --data data/dagger1.pt --epochs 4 --output artifacts/hive_policy_dagger1.pt
```

Repeat with the new checkpoint and `--append` for a second round. These use stateful synthetic household transitions rather than full multi-home negotiation rollouts.

## Message replay and reward fine-tuning

Protocol messages use canonical JSONL with type, sender, receiver, round and payload. Action logs include price signals, offers, bids and market accept/reject records. Use `python replay.py --smoke` for a sample or provide exported message JSONL with `--input` and `--output`.

Fine-tune the HOME head with the deterministic reward proxy:

```powershell
python rl_finetune.py --model artifacts/hive_policy.pt --data data/teacher.pt --updates 200 --output artifacts/hive_policy_rl.pt
python eval.py --model artifacts/hive_policy_rl.pt
```

The API prefers `artifacts/hive_policy_rl.pt` when present, otherwise it loads `artifacts/hive_policy.pt`.

## API examples

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/simulation/start -H 'Content-Type: application/json' -d '{"n_homes":60,"seed":7,"policy":"teacher","scenario":"summer"}'
curl -X POST http://127.0.0.1:8000/simulation/reset
curl -X POST http://127.0.0.1:8000/simulation/step -H 'Content-Type: application/json' -d '{"n_steps":4}'
curl -X POST http://127.0.0.1:8000/simulation/run
curl http://127.0.0.1:8000/simulation/state
curl http://127.0.0.1:8000/homes
curl http://127.0.0.1:8000/homes/H001
curl http://127.0.0.1:8000/society
curl http://127.0.0.1:8000/grid
curl -X POST http://127.0.0.1:8000/grid/event -H 'Content-Type: application/json' -d '{"type":"heatwave","start":72,"end":88,"cap_reduction_pct":20}'
curl http://127.0.0.1:8000/metrics
curl http://127.0.0.1:8000/timeseries
curl http://127.0.0.1:8000/events
curl -N http://127.0.0.1:8000/events/stream
curl -X POST http://127.0.0.1:8000/homes/H002/override -H 'Content-Type: application/json' -d '{"constraint":{"ev_deadline_step":80}}'
```

## Expected results and limitations

The demo displays peak reduction, solar self-consumption, cost saved, comfort fairness, hard-constraint violations, a load/cap chart, and household state. For the seeded heatwave run, peak reduction should be positive and hard-constraint violations should be zero.

This is a hackathon-scale simulator. Battery, thermal and EV models are simplified; the baseline is a deterministic no-coordination approximation; fairness rounds broadcast multiplier signals without fully rescheduling every home after each round; and only the HOME learned head is used live. RL uses a compact reward proxy rather than a full multi-day society environment. Training speed and learned-policy targets require verification on a machine with PyTorch installed.
