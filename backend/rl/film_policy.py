"""
FiLM (Feature-wise Linear Modulation, Perez et al. 2017) team-conditioning
for the shared auction policy.

WHY: one network expresses all ten franchises. Concatenating the team's
identity features flat into the observation makes them just N more numbers
among many, with no structural reason for them to change how the OTHER
features are processed -- and the first shared-policy run duly collapsed,
with nine of ten teams converging on near-identical squad shapes.

FiLM gives team identity an architecturally privileged role instead: the
identity block runs through a small network producing a scale (gamma) and
shift (beta) that modulate the hidden representation of the SITUATIONAL
features. The team profile gates how the network reads the situation
rather than sitting beside it.

LAYOUT CONTRACT: the team-identity block is the LAST N_TEAM_FEATURES
entries of the observation; everything before is situational. The slicing
below is negative-indexed, so adding situational features is safe, but the
team block must stay last -- see build_observation in auction_mdp.py.
"""

from __future__ import annotations

import gymnasium as gym
import torch
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from torch import nn

N_TEAM_FEATURES = 8


class FiLMFeaturesExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space: gym.Space, features_dim: int = 64, team_hidden_dim: int = 16):
        super().__init__(observation_space, features_dim)
        obs_dim = observation_space.shape[0]
        situational_dim = obs_dim - N_TEAM_FEATURES

        self.situational_proj = nn.Linear(situational_dim, features_dim)
        self.team_encoder = nn.Sequential(
            nn.Linear(N_TEAM_FEATURES, team_hidden_dim),
            nn.ReLU(),
            nn.Linear(team_hidden_dim, 2 * features_dim),  # gamma and beta, concatenated
        )
        self.activation = nn.ReLU()

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        situational = observations[:, :-N_TEAM_FEATURES]
        team = observations[:, -N_TEAM_FEATURES:]

        h = self.situational_proj(situational)
        gamma, beta = self.team_encoder(team).chunk(2, dim=-1)
        # Centre gamma at 1.0 so a zero-init team_encoder starts as the
        # identity transform rather than wiping out h.
        modulated = (1.0 + gamma) * h + beta
        return self.activation(modulated)
