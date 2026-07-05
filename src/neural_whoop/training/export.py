"""Policy export: trained actor -> TorchScript / ONNX, the sim2real deploy path.

The deployable policy is the TinyPolicy actor emitting the deterministic action PPO's eval
uses: the **clipped-Gaussian effective mean** ``E[clip(N(mean, std))]`` with the trained
per-channel std baked in as a constant (see
:func:`~neural_whoop.training.ppo.clipped_gaussian_mean` — deploying the raw clamped mean is
systematically biased on channels trained near a clip bound, the hover_blind thrust-trim
sink). This module lifts the trained actor into a clean, SB3-free, framework-free
``DeployPolicy`` module — pure ``Linear`` + activation + erf/exp — that TorchScripts and
ONNX-exports cleanly and is quantization-ready for a flight controller. On hardware the same
obs-v4 vector is fed in and the CTBR action comes out (rescaled by the
:class:`~neural_whoop.contract.ActionLimits` the env used).
"""

from __future__ import annotations

import torch
from torch import Tensor, nn

from neural_whoop.policies.tiny_policy import TinyPolicy
from neural_whoop.training.ppo import ActorCritic, clipped_gaussian_mean


class DeployPolicy(nn.Module):
    """Trained TinyPolicy actor + the deterministic effective-mean output for deploy."""

    def __init__(self, actor: TinyPolicy, std: Tensor):
        super().__init__()
        self.net = actor.net  # share the trained Linear/activation stack
        self.register_buffer("std", std.detach().clone())

    def forward(self, obs: Tensor) -> Tensor:
        return clipped_gaussian_mean(self.net(obs), self.std)


def build_deploy_policy(agent: ActorCritic) -> DeployPolicy:
    """Extract a :class:`DeployPolicy` from a trained :class:`ActorCritic`."""
    return DeployPolicy(agent.actor, agent.log_std.exp()).eval()


def export_torchscript(policy: DeployPolicy, obs_dim: int, path: str) -> str:
    """TorchScript-trace the deploy policy; verify the trace matches; return ``path``."""
    policy = policy.eval().cpu()
    example = torch.zeros(1, obs_dim)
    traced = torch.jit.trace(policy, example)
    with torch.no_grad():
        sample = torch.randn(16, obs_dim)
        max_diff = (traced(sample) - policy(sample)).abs().max().item()
    if max_diff > 1e-5:
        raise AssertionError(f"TorchScript trace mismatch: {max_diff:.2e}")
    traced.save(path)
    return path


def export_onnx(policy: DeployPolicy, obs_dim: int, path: str, atol: float = 1e-4) -> float:
    """Export the deploy policy to ONNX and validate the round-trip; return max abs diff.

    Requires the ``export`` extra (``onnx``, ``onnxruntime``). Raises if the runtime output
    diverges from torch beyond ``atol``.
    """
    import numpy as np
    import onnxruntime as ort

    policy = policy.eval().cpu()
    example = torch.zeros(1, obs_dim)
    torch.onnx.export(
        policy, example, path,
        input_names=["obs"], output_names=["action"],
        dynamic_axes={"obs": {0: "batch"}, "action": {0: "batch"}},
        opset_version=17,
    )
    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    sample = torch.randn(16, obs_dim)
    with torch.no_grad():
        torch_out = policy(sample).numpy()
    onnx_out = sess.run(None, {"obs": sample.numpy()})[0]
    max_diff = float(np.max(np.abs(torch_out - onnx_out)))
    if max_diff > atol:
        raise AssertionError(f"ONNX round-trip mismatch: {max_diff:.2e} > {atol:.0e}")
    return max_diff
