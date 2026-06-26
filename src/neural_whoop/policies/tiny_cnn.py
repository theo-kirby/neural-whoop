"""TinyCNNExtractor: a small, export-friendly conv stack for camera-only tasks (ported).

Design intent mirrors :mod:`tiny_policy`: small (a few-channel conv tower + one linear
projection, concatenated with proprioception), quantization-friendly (plain Conv2d/Linear +
ReLU, no batchnorm/attention), and exportable (pure tensor-in/tensor-out, no data-dependent
control flow). Used by the deferred camera-only follow tasks (DiffAero depth render on
Blackwell); primary training stays render-free via the perception oracle.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn


@dataclass
class TinyCNNConfig:
    """Shape/config for :class:`TinyCNNExtractor`."""

    in_channels: int = 1   # depth by default (DiffAero depth render); 3 for RGB
    img_size: int = 48
    proprio_dim: int = 8
    conv_channels: tuple[int, ...] = (8, 16, 16)
    feature_dim: int = 64


class TinyCNNExtractor(nn.Module):
    """Conv tower over the image + concat proprio -> a compact feature vector.

    ``forward(image, proprio)`` -> features of size ``feature_dim + proprio_dim``. ``image``
    is a float tensor in [0, 1], shape ``(B, C, H, W)``; ``proprio`` is ``(B, proprio_dim)``.
    """

    def __init__(self, config: TinyCNNConfig | None = None) -> None:
        super().__init__()
        self.config = config or TinyCNNConfig()
        cfg = self.config

        layers: list[nn.Module] = []
        c_in = cfg.in_channels
        for i, c_out in enumerate(cfg.conv_channels):
            k = 4 if i == 0 else 3
            layers.append(nn.Conv2d(c_in, c_out, kernel_size=k, stride=2, padding=1))
            layers.append(nn.ReLU())
            c_in = c_out
        self.conv = nn.Sequential(*layers)

        with torch.no_grad():
            dummy = torch.zeros(1, cfg.in_channels, cfg.img_size, cfg.img_size)
            conv_out = self.conv(dummy).flatten(1).shape[1]
        self.proj = nn.Sequential(nn.Linear(conv_out, cfg.feature_dim), nn.ReLU())
        self.features_dim = cfg.feature_dim + cfg.proprio_dim

    def forward(self, image: Tensor, proprio: Tensor) -> Tensor:
        x = self.conv(image).flatten(1)
        x = self.proj(x)
        return torch.cat([x, proprio], dim=1)

    def num_parameters(self) -> int:
        """Total trainable parameter count (kept visible for the size budget)."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
