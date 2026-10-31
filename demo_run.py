"""Run a reproducible 60-home heatwave demo; --smoke uses the same pipeline."""
import argparse
from fastapi.testclient import TestClient
from api.main import app, manager

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true', help='Run the full demo with a quick deterministic seed')
    args = parser.parse_args()
    client = TestClient(app)
    client.post('/simulation/start', json={'n_homes':60,'seed':7,'policy':'teacher','scenario':'heatwave'})
    client.post('/grid/event', json={'type':'heatwave','start':72,'end':88,'cap_reduction_pct':20})
    client.post('/simulation/run')
    m=client.get('/metrics').json()
    print(f"Peak reduction: {m['peak_reduction_pct']:.1f}%")
    print(f"Solar self-consumption: {m['solar_self_consumption_pct']:.1f}%")
    print(f"Cost saved: {m['cost_saved_pct']:.1f}%")
    print(f"Jain comfort index: {m['jain_comfort']:.3f}")
    print(f"Violations: {m['violations']}")

if __name__ == '__main__': main()
