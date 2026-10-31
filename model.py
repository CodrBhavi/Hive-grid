"""Role-conditioned transformer policy trained from scratch on teacher data."""
from __future__ import annotations
import torch
from torch import nn

FEATURES = 18
ROLE_HOME, ROLE_SOCIETY, ROLE_GRID = 0, 1, 2
ROLE_NAMES = {"HOME": ROLE_HOME, "SOCIETY": ROLE_SOCIETY, "GRID": ROLE_GRID}
ACTION_DIMS = 7

class HivePolicy(nn.Module):
    """Four-layer shared transformer encoder with role-specific action heads."""
    def __init__(self, feature_count: int = FEATURES, width: int = 144, layers: int = 4):
        super().__init__()
        self.input = nn.Linear(feature_count, width)
        self.position = nn.Parameter(torch.zeros(1, 48, width))
        self.role = nn.Embedding(3, width)
        block = nn.TransformerEncoderLayer(width, 4, width * 4, dropout=0.0, batch_first=True, norm_first=True, activation="gelu")
        self.encoder = nn.TransformerEncoder(block, layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(width)
        self.heads = nn.ModuleList([nn.Sequential(nn.Linear(width, width), nn.GELU(), nn.Linear(width, ACTION_DIMS)) for _ in range(3)])
    def forward(self, observations: torch.Tensor, role_ids: torch.Tensor) -> torch.Tensor:
        """Map [batch, 48, features] observations to role-specific actions."""
        x = self.input(observations) + self.position[:, :observations.shape[1]] + self.role(role_ids).unsqueeze(1)
        pooled = self.norm(self.encoder(x).mean(dim=1))
        all_actions = torch.stack([head(pooled) for head in self.heads], dim=1)
        return all_actions[torch.arange(len(role_ids), device=role_ids.device), role_ids]

def parameter_count(model: nn.Module) -> int:
    """Count trainable parameters."""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
