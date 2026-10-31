"""Deterministic double auction for peer solar sharing."""
def clear_market(offers: list[dict], bids: list[dict], feed_in: float, grid_tariff: float) -> tuple[list[dict],list[dict]]:
    """Match offer and bid records, returning trades and unmatched offers."""
    sellers = sorted((dict(x) for x in offers), key=lambda x: (x['price'], x['home']))
    buyers = sorted((dict(x) for x in bids), key=lambda x: (-x['price'], x['home']))
    trades = []
    for seller in sellers:
        eligible = [b for b in buyers if b['kwh'] > 1e-9 and b['price'] >= seller['price']]
        supply = seller['kwh']
        while supply > 1e-9 and eligible:
            total_demand = sum(b['kwh'] for b in eligible)
            allocation = min(supply, total_demand)
            total_weight = sum(max(0.0, float(b.get('weight', 1.0))) for b in eligible)
            if total_weight <= 0: total_weight = float(len(eligible))
            distributed = 0.0
            for index, buyer in enumerate(eligible):
                weight = max(0.0, float(buyer.get('weight', 1.0))) or (1.0 if total_weight == len(eligible) else 0.0)
                amount = min(buyer['kwh'], allocation-distributed) if index == len(eligible)-1 else min(buyer['kwh'], allocation*weight/total_weight)
                if amount <= 1e-9: continue
                clear_price = max(feed_in, min(grid_tariff, (seller['price']+buyer['price'])/2))
                trades.append({'seller':seller['home'],'buyer':buyer['home'],'kwh':amount,'price':clear_price})
                buyer['kwh']-=amount; supply-=amount; distributed+=amount
            eligible=[b for b in eligible if b['kwh']>1e-9]
            if distributed<=1e-9: break
    unmatched=[{'home':seller['home'],'kwh':seller['kwh'],'price':seller['price']} for seller in sellers if seller['kwh']>1e-9]
    return trades, unmatched
