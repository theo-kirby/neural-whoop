"""TinyPolicy: a deliberately small, export-friendly MLP policy (ported from the lab).

Design intent (read before changing):

- **Tiny.** Small hidden sizes; ``num_parameters()`` keeps the size budget visible. A whoop
  flies its policy on a microcontroller, so growth should be a conscious decision.
- **Quantization-friendly.** Plain ``nn.Linear`` + one simple activation. No layernorm /
  attention / exotic ops that complicate int8 quantization or MCU deployment.
- **Exportable.** ``forward`` is pure tensor-in/tensor-out with no data-dependent control
  flow, so it round-trips cleanly through TorchScript and ONNX.

The PPO actor-critic in ``neural_whoop.training.ppo`` wraps this as the deterministic action
mean (``output="none"``; the squashing/rescale lives in the env's CTBR map and the export
wrapper), so the exact same tiny network is what deploys to hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch
from torch import Tensor, nn


@dataclass
class TinyPolicyConfig:
    """Shape/config for :class:`TinyPolicy`.

    Attributes:
        obs_dim: Observation vector length.
        act_dim: Action vector length.
        hidden_sizes: Hidden widths. Keep these small — this is a *tiny* policy.
        activation: One of ``{"relu", "tanh"}`` (ReLU is the quantization-friendly default).
        output: Output squashing — ``{"tanh", "clip", "none"}``. ``tanh`` bounds actions to
            [-1, 1]; ``none`` returns the raw mean (PPO actor); ``clip`` hard-clamps.
    """

    obs_dim: int = 11
    act_dim: int = 4
    hidden_sizes: tuple[int, ...] = field(default_factory=lambda: (64, 64))
    activation: str = "tanh"
    output: str = "tanh"


_ACTIVATIONS: dict[str, type[nn.Module]] = {"relu": nn.ReLU, "tanh": nn.Tanh}


class TinyPolicy(nn.Module):
    """A small feed-forward policy mapping observations to actions."""

    def __init__(self, config: TinyPolicyConfig | None = None) -> None:
        super().__init__()
        self.config = config or TinyPolicyConfig()
        if self.config.activation not in _ACTIVATIONS:
            raise ValueError(
                f"Unknown activation {self.config.activation!r}; expected one of {sorted(_ACTIVATIONS)}"
            )
        if self.config.output not in ("tanh", "clip", "none"):
            raise ValueError(f"Unknown output {self.config.output!r}; expected 'tanh', 'clip', or 'none'")
        act_cls = _ACTIVATIONS[self.config.activation]

        layers: list[nn.Module] = []
        in_dim = self.config.obs_dim
        for hidden in self.config.hidden_sizes:
            layers.append(nn.Linear(in_dim, hidden))
            layers.append(act_cls())
            in_dim = hidden
        layers.append(nn.Linear(in_dim, self.config.act_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, obs: Tensor) -> Tensor:
        """Map observations ``(batch, obs_dim)`` to actions ``(batch, act_dim)``."""
        out = self.net(obs)
        if self.config.output == "tanh":
            return torch.tanh(out)
        if self.config.output == "clip":
            return torch.clamp(out, -1.0, 1.0)
        return out

    def num_parameters(self) -> int:
        """Total trainable parameters. Keep this small (it's the whole point)."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
