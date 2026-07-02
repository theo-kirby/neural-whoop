"""Muon optimizer — Newton-Schulz-orthogonalized momentum SGD.

Ported from PufferLib 4.0 (``pufferlib/muon.py``, MIT, PufferAI) for the PufferLib
idea-import experiments (Flywheel cluster:system-comparison). Muon orthogonalizes the
momentum-averaged gradient of every >=2D weight matrix via a 5-step Newton-Schulz
iteration; 1D params (biases, log_std) fall through to plain momentum SGD. Typical lr is
~10-30x Adam's for the same net (PufferLib's swept drone config uses lr 9.5e-3).
"""

from __future__ import annotations

import torch
from torch import Tensor
from torch.optim.optimizer import Optimizer, ParamsT

__all__ = ["Muon"]

NS_COEFS = [
    (4.0848, -6.8946, 2.9270),
    (3.9505, -6.3029, 2.6377),
    (3.7418, -5.5913, 2.3037),
    (2.8769, -3.1427, 1.2046),
    (2.8366, -3.0525, 1.2012),
]


def zeropower_via_newtonschulz5(G: Tensor, eps: float = 1e-7) -> Tensor:
    x = G.clone()
    if G.size(-2) > G.size(-1):
        x = x.mT
    x = x / torch.clamp(G.norm(dim=(-2, -1)), min=eps)
    for a, b, c in NS_COEFS:
        s = x @ x.mT
        y = c * s
        y.diagonal(dim1=-2, dim2=-1).add_(b)
        y = y @ s
        y.diagonal(dim1=-2, dim2=-1).add_(a)
        x = y @ x
    if G.size(-2) > G.size(-1):
        x = x.mT
    return x.to(G.dtype)


class Muon(Optimizer):
    def __init__(
        self,
        params: ParamsT,
        lr: float = 0.0025,
        weight_decay: float = 0.0,
        momentum: float = 0.9,
        eps: float = 1e-8,
    ) -> None:
        if lr < 0.0:
            raise ValueError(f"Learning rate should be >= 0 but is: {lr}")
        if momentum < 0.0:
            raise ValueError(f"momentum should be >= 0 but is: {momentum}")
        if weight_decay < 0.0:
            raise ValueError(f"weight decay should be >= 0 but is: {weight_decay}")
        defaults = {"lr": lr, "weight_decay": weight_decay, "momentum": momentum, "eps": eps}
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            lr = group["lr"]
            weight_decay = group["weight_decay"]
            momentum = group["momentum"]

            for p in group["params"]:
                if p.grad is None:
                    continue
                grad = p.grad
                state = self.state[p]
                if "momentum_buffer" not in state:
                    state["momentum_buffer"] = torch.zeros_like(grad)
                buf = state["momentum_buffer"]
                buf.mul_(momentum).add_(grad)
                grad = grad.add(buf * momentum)  # Nesterov-style lookahead

                if grad.ndim >= 2:
                    g2 = grad.view(grad.shape[0], -1)
                    g2 = zeropower_via_newtonschulz5(g2)
                    g2 = g2 * max(1, g2.size(-2) / g2.size(-1)) ** 0.5
                    grad = g2.view(p.shape)

                p.mul_(1 - lr * weight_decay)
                p.sub_(lr * grad)

        return loss
