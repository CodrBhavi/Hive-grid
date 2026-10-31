"""Energy balance helpers."""
def balance(solar: float, discharge: float, grid_import: float, p2p_buy: float,
            base: float, ac: float, ev: float, geyser: float, other: float,
            charge: float, grid_export: float, p2p_sell: float) -> float:
    """Return left minus right side of the explicit energy balance in kWh."""
    return solar + discharge + grid_import + p2p_buy - base - ac - ev - geyser - other - charge - grid_export - p2p_sell
