"""Torch-native PPO over the batched :class:`MultiAgentDroneEnv` — GPU-resident.

Replaces the lab's SB3-PPO/CPU loop. The whole rollout (obs, actions, advantages) lives on the
GPU and never round-trips to numpy; each of the ``n_drones`` parallel drones is an independent
sample. The actor is the ported :class:`~neural_whoop.policies.tiny_policy.TinyPolicy` (so the
exact tiny network that trains is what deploys to a whoop); a separate small critic estimates
value. GAE handles **time-limit truncation** correctly (bootstrap from the stashed terminal
obs) while **not** bootstrapping crashes — important for a lap-time objective where running out
of clock is not the same as hitting a wall.

This is deliberately a compact, hackable single-file loop (cleanrl-style), not a framework:
the autonomous agent is expected to fork reward/curriculum/algorithm here.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

import torch
from torch import Tensor, nn

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.policies.tiny_policy import TinyPolicy, TinyPolicyConfig


@dataclass
class PPOConfig:
    """PPO + rollout hyperparameters."""

    num_steps: int = 24            # rollout horizon per update (per drone)
    total_steps: int = 30_000_000  # total environment steps (across all drones)
    lr: float = 3e-4
    anneal_lr: bool = True
    # "adam" (default) or "muon" (Newton-Schulz orthogonalized momentum, training/muon.py).
    # Muon wants a ~10-30x higher lr than Adam for the same net.
    optimizer: str = "adam"
    # PufferLib-style "puff" update (idea-import, Flywheel cluster:system-comparison): replaces
    # the epoch/minibatch loop with V-trace-rho/c-clipped GAE recomputed per minibatch from a
    # live importance-ratio buffer + advantage-prioritized SEGMENT sampling (a segment = one
    # drone's num_steps trajectory) with (N*p)^-beta importance correction. replay_ratio plays
    # update_epochs' role (total sample reuse = replay_ratio x batch); target_kl is ignored in
    # this mode (V-trace absorbs staleness instead of early-stopping).
    puff_update: bool = False
    replay_ratio: float = 4.0       # match update_epochs=4 reuse so the delta is vtrace+prio
    vtrace_rho_clip: float = 1.5
    vtrace_c_clip: float = 2.9
    prio_alpha: float = 0.2
    prio_beta0: float = 0.75
    gamma: float = 0.99
    gae_lambda: float = 0.95
    update_epochs: int = 4
    num_minibatches: int = 8
    clip_coef: float = 0.2
    ent_coef: float = 0.0
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    target_kl: float | None = 0.03
    norm_adv: bool = True
    clip_vloss: bool = True
    # Seam-DR curriculum: 0.0 = full DR from step 0 (default / current behavior); >0 ramps the
    # seam DR magnitudes 0->full over this fraction of training (reliability hardening, hop-10).
    dr_curriculum_frac: float = 0.0
    # Policy/critic shape.
    hidden_sizes: tuple[int, ...] = (64, 64)
    activation: str = "tanh"
    init_log_std: float = -0.5
    # Logging / checkpoints (in env steps).
    log_interval: int = 1
    ckpt_interval_updates: int = 50


class ActorCritic(nn.Module):
    """TinyPolicy actor (Gaussian mean) + a small separate critic.

    The actor outputs an unbounded mean; actions are sampled from ``Normal(mean, exp(log_std))``
    and clamped to ``[-1, 1]`` by the env (the deterministic export uses ``clip(mean)``). The
    log-std is state-independent (a learned per-dim scalar), standard for on-policy locomotion.
    """

    def __init__(self, obs_dim: int, act_dim: int, cfg: PPOConfig):
        super().__init__()
        self.actor = TinyPolicy(
            TinyPolicyConfig(obs_dim, act_dim, tuple(cfg.hidden_sizes), cfg.activation, output="none")
        )
        self.log_std = nn.Parameter(torch.ones(act_dim) * cfg.init_log_std)
        act = nn.Tanh if cfg.activation == "tanh" else nn.ReLU
        layers: list[nn.Module] = []
        d = obs_dim
        for h in cfg.hidden_sizes:
            layers += [nn.Linear(d, h), act()]
            d = h
        layers += [nn.Linear(d, 1)]
        self.critic = nn.Sequential(*layers)

    def get_value(self, obs: Tensor) -> Tensor:
        return self.critic(obs).squeeze(-1)

    def get_action_and_value(self, obs: Tensor, action: Tensor | None = None):
        mean = self.actor(obs)
        std = self.log_std.exp().expand_as(mean)
        dist = torch.distributions.Normal(mean, std)
        if action is None:
            action = dist.sample()
        logp = dist.log_prob(action).sum(-1)
        entropy = dist.entropy().sum(-1)
        value = self.critic(obs).squeeze(-1)
        return action, logp, entropy, value


def _layer_init(model: nn.Module) -> None:
    """Orthogonal init (gain sqrt(2) hidden, small final) — the standard PPO init."""
    linears = [m for m in model.modules() if isinstance(m, nn.Linear)]
    for i, m in enumerate(linears):
        gain = 0.01 if i == len(linears) - 1 else (2.0 ** 0.5)
        nn.init.orthogonal_(m.weight, gain)
        nn.init.zeros_(m.bias)


def train_ppo(
    env: MultiAgentDroneEnv,
    cfg: PPOConfig,
    run_dir: str,
    device: torch.device | str = "cuda",
    writer=None,
    log=print,
) -> ActorCritic:
    """Train an :class:`ActorCritic` on ``env`` with PPO; return the trained agent.

    Writes TensorBoard scalars (if ``writer`` given) and periodic checkpoints to ``run_dir``.
    """
    import os

    os.makedirs(run_dir, exist_ok=True)
    dev = torch.device(device)
    N = env.n_drones
    obs_dim, act_dim = env.obs_dim, env.act_dim

    agent = ActorCritic(obs_dim, act_dim, cfg).to(dev)
    _layer_init(agent.actor)
    _layer_init(agent.critic)
    if cfg.optimizer == "muon":
        from neural_whoop.training.muon import Muon

        opt = Muon(agent.parameters(), lr=cfg.lr)
    elif cfg.optimizer == "adam":
        opt = torch.optim.Adam(agent.parameters(), lr=cfg.lr, eps=1e-5)
    else:
        raise ValueError(f"unknown optimizer {cfg.optimizer!r} (expected 'adam' or 'muon')")

    batch = N * cfg.num_steps
    mb_size = max(1, batch // cfg.num_minibatches)
    num_updates = max(1, cfg.total_steps // batch)

    # Rollout storage (GPU).
    obs_buf = torch.zeros(cfg.num_steps, N, obs_dim, device=dev)
    act_buf = torch.zeros(cfg.num_steps, N, act_dim, device=dev)
    logp_buf = torch.zeros(cfg.num_steps, N, device=dev)
    rew_buf = torch.zeros(cfg.num_steps, N, device=dev)
    val_buf = torch.zeros(cfg.num_steps, N, device=dev)
    term_buf = torch.zeros(cfg.num_steps, N, device=dev)
    trunc_buf = torch.zeros(cfg.num_steps, N, device=dev)
    boot_val = torch.zeros(cfg.num_steps, N, device=dev)  # terminal value for truncated steps

    # Episode-return tracking (GPU; materialized only at log time).
    ep_ret = torch.zeros(N, device=dev)
    ep_len = torch.zeros(N, device=dev)
    done_ret_sum = torch.zeros((), device=dev)
    done_len_sum = torch.zeros((), device=dev)
    done_count = torch.zeros((), device=dev)

    next_obs = env.reset_all()
    global_step = 0
    dr_scale = 1.0
    t_start = time.time()

    for update in range(1, num_updates + 1):
        if cfg.anneal_lr:
            frac = 1.0 - (update - 1.0) / num_updates
            for g in opt.param_groups:
                g["lr"] = frac * cfg.lr
        if cfg.dr_curriculum_frac > 0.0:
            dr_scale = min(1.0, global_step / max(1.0, cfg.dr_curriculum_frac * cfg.total_steps))
            env.set_dr_scale(dr_scale)
        # Course-scale curriculum progress (the task decides whether to use it). Linear in training.
        env.set_course_scale(global_step / max(1.0, cfg.total_steps))

        for step in range(cfg.num_steps):
            obs_buf[step] = next_obs
            with torch.no_grad():
                action, logp, _, value = agent.get_action_and_value(next_obs)
            act_buf[step] = action
            logp_buf[step] = logp
            val_buf[step] = value

            next_obs, reward, term, trunc, info = env.step(action)
            global_step += N

            rew_buf[step] = reward
            term_buf[step] = term.float()
            trunc_buf[step] = trunc.float()
            # Bootstrap value for truncated episodes from the true terminal obs.
            if bool(trunc.any()):
                with torch.no_grad():
                    tv = agent.get_value(info["terminal_obs"])
                boot_val[step] = torch.where(trunc, tv, torch.zeros_like(tv))
            else:
                boot_val[step] = 0.0

            # Episode bookkeeping.
            ep_ret += reward
            ep_len += 1.0
            done = term | trunc
            if bool(done.any()):
                done_ret_sum += ep_ret[done].sum()
                done_len_sum += ep_len[done].sum()
                done_count += done.sum()
                ep_ret = torch.where(done, torch.zeros_like(ep_ret), ep_ret)
                ep_len = torch.where(done, torch.zeros_like(ep_len), ep_len)

        # --- GAE (with timeout bootstrap; reset accumulation at any episode boundary) ---
        with torch.no_grad():
            next_value = agent.get_value(next_obs)
            adv = torch.zeros_like(rew_buf)
            lastgae = torch.zeros(N, device=dev)
            for t in reversed(range(cfg.num_steps)):
                nextval = next_value if t == cfg.num_steps - 1 else val_buf[t + 1]
                # boot: 0 on crash, terminal value on truncation, else next-step value.
                boot = torch.where(
                    term_buf[t].bool(), torch.zeros_like(nextval),
                    torch.where(trunc_buf[t].bool(), boot_val[t], nextval),
                )
                done_t = (term_buf[t] + trunc_buf[t]).clamp(max=1.0)
                delta = rew_buf[t] + cfg.gamma * boot - val_buf[t]
                lastgae = delta + cfg.gamma * cfg.gae_lambda * (1.0 - done_t) * lastgae
                adv[t] = lastgae
            returns = adv + val_buf

        if cfg.puff_update:
            # --- PufferLib-style update: V-trace-clipped advantages recomputed per minibatch
            # + advantage-prioritized segment sampling (see PPOConfig.puff_update). ---
            T = cfg.num_steps
            mb_seg = max(1, mb_size // T)
            num_mb = max(1, int(cfg.replay_ratio * batch / (mb_seg * T)))
            beta = cfg.prio_beta0 + (1.0 - cfg.prio_beta0) * cfg.prio_alpha * update / num_updates
            ratio_buf = torch.ones(T, N, device=dev)
            done_all = (term_buf + trunc_buf).clamp(max=1.0)
            # Fold the truncation bootstrap into rewards so the V-trace recurrence only needs
            # the done flag (equivalent to our GAE's boot handling).
            r_eff = rew_buf + cfg.gamma * boot_val * trunc_buf
            approx_kl = torch.zeros((), device=dev)
            pg_loss = v_loss = ent_loss = torch.zeros((), device=dev)
            stop = False
            for _mb in range(num_mb):
                with torch.no_grad():
                    padv = torch.zeros_like(rew_buf)
                    lastgae = torch.zeros(N, device=dev)
                    for t in reversed(range(T)):
                        nextval = next_value if t == T - 1 else val_buf[t + 1]
                        boot = torch.where(term_buf[t].bool(), torch.zeros_like(nextval), nextval)
                        boot = torch.where(trunc_buf[t].bool(), torch.zeros_like(nextval), boot)
                        rho_t = ratio_buf[t].clamp(max=cfg.vtrace_rho_clip)
                        c_t = ratio_buf[t].clamp(max=cfg.vtrace_c_clip)
                        delta = rho_t * r_eff[t] + cfg.gamma * boot - val_buf[t]
                        lastgae = delta + cfg.gamma * cfg.gae_lambda * c_t * (1.0 - done_all[t]) * lastgae
                        padv[t] = lastgae
                    # Prioritized segment draw (segment = one drone's T-step trajectory).
                    w = padv.abs().sum(dim=0).pow(cfg.prio_alpha)
                    w = torch.nan_to_num(w, 0.0, 0.0, 0.0)
                    p = (w + 1e-6) / (w.sum() + 1e-6)
                    seg = torch.multinomial(p, mb_seg, replacement=True)
                    is_w = (N * p[seg]).pow(-beta)  # importance correction, (1, mb_seg) after unsqueeze

                mb_obs = obs_buf[:, seg].reshape(T * mb_seg, obs_dim)
                mb_act = act_buf[:, seg].reshape(T * mb_seg, act_dim)
                _, newlogp, entropy, newval = agent.get_action_and_value(mb_obs, mb_act)
                newlogp = newlogp.view(T, mb_seg)
                newval = newval.view(T, mb_seg)
                logratio = newlogp - logp_buf[:, seg]
                ratio = logratio.exp()
                with torch.no_grad():
                    approx_kl = ((ratio - 1) - logratio).mean()
                    ratio_buf[:, seg] = ratio.detach()

                mb_adv = padv[:, seg]
                if cfg.norm_adv:
                    mb_adv = (mb_adv - mb_adv.mean()) / (mb_adv.std() + 1e-8)
                mb_adv = is_w.unsqueeze(0) * mb_adv
                pg1 = -mb_adv * ratio
                pg2 = -mb_adv * ratio.clamp(1 - cfg.clip_coef, 1 + cfg.clip_coef)
                pg_loss = torch.max(pg1, pg2).mean()

                mb_ret = padv[:, seg] + val_buf[:, seg]
                if cfg.clip_vloss:
                    old_v = val_buf[:, seg]
                    v_unclipped = (newval - mb_ret) ** 2
                    v_clipped = old_v + (newval - old_v).clamp(-cfg.clip_coef, cfg.clip_coef)
                    v_clipped = (v_clipped - mb_ret) ** 2
                    v_loss = 0.5 * torch.max(v_unclipped, v_clipped).mean()
                else:
                    v_loss = 0.5 * ((newval - mb_ret) ** 2).mean()

                ent_loss = entropy.mean()
                loss = pg_loss - cfg.ent_coef * ent_loss + cfg.vf_coef * v_loss

                opt.zero_grad(set_to_none=True)
                loss.backward()
                nn.utils.clip_grad_norm_(agent.parameters(), cfg.max_grad_norm)
                opt.step()
                with torch.no_grad():
                    val_buf[:, seg] = newval.detach()
        else:
            # --- flatten + PPO update ---
            b_obs = obs_buf.reshape(-1, obs_dim)
            b_act = act_buf.reshape(-1, act_dim)
            b_logp = logp_buf.reshape(-1)
            b_adv = adv.reshape(-1)
            b_ret = returns.reshape(-1)
            b_val = val_buf.reshape(-1)

            idx = torch.randperm(batch, device=dev)
            approx_kl = torch.zeros((), device=dev)
            pg_loss = v_loss = ent_loss = torch.zeros((), device=dev)
            stop = False
            for _epoch in range(cfg.update_epochs):
                for start in range(0, batch, mb_size):
                    mb = idx[start:start + mb_size]
                    _, newlogp, entropy, newval = agent.get_action_and_value(b_obs[mb], b_act[mb])
                    logratio = newlogp - b_logp[mb]
                    ratio = logratio.exp()
                    with torch.no_grad():
                        approx_kl = ((ratio - 1) - logratio).mean()

                    mb_adv = b_adv[mb]
                    if cfg.norm_adv:
                        mb_adv = (mb_adv - mb_adv.mean()) / (mb_adv.std() + 1e-8)
                    pg1 = -mb_adv * ratio
                    pg2 = -mb_adv * ratio.clamp(1 - cfg.clip_coef, 1 + cfg.clip_coef)
                    pg_loss = torch.max(pg1, pg2).mean()

                    if cfg.clip_vloss:
                        v_unclipped = (newval - b_ret[mb]) ** 2
                        v_clipped = b_val[mb] + (newval - b_val[mb]).clamp(-cfg.clip_coef, cfg.clip_coef)
                        v_clipped = (v_clipped - b_ret[mb]) ** 2
                        v_loss = 0.5 * torch.max(v_unclipped, v_clipped).mean()
                    else:
                        v_loss = 0.5 * ((newval - b_ret[mb]) ** 2).mean()

                    ent_loss = entropy.mean()
                    loss = pg_loss - cfg.ent_coef * ent_loss + cfg.vf_coef * v_loss

                    opt.zero_grad(set_to_none=True)
                    loss.backward()
                    nn.utils.clip_grad_norm_(agent.parameters(), cfg.max_grad_norm)
                    opt.step()

                if cfg.target_kl is not None and float(approx_kl) > cfg.target_kl:
                    stop = True
                    break

        # --- logging ---
        if update % cfg.log_interval == 0:
            sps = int(global_step / (time.time() - t_start))
            ep_ret_mean = float(done_ret_sum / done_count) if float(done_count) > 0 else float("nan")
            ep_len_mean = float(done_len_sum / done_count) if float(done_count) > 0 else float("nan")
            m = env.task.metrics(env)
            head = f"upd {update}/{num_updates} step {global_step:,} | sps {sps:,} | ep_ret {ep_ret_mean:7.2f}"
            if "best_lap_time" in m:  # racing tasks: lap-time line
                tail = (
                    f" | best_lap {m['best_lap_time']:6.3f}s "
                    f"(oracle {m.get('oracle_lap_time', float('nan')):.3f}s) | "
                    f"laps {m.get('laps_completed_mean', 0):.2f} | "
                    f"compl {m.get('lap_completion_rate', 0):.2f}"
                )
            else:  # other tasks: show their own metrics generically
                tail = "".join(f" | {k} {v:.3f}" for k, v in m.items())
            log(f"{head}{tail} | kl {float(approx_kl):.3f}")
            if writer is not None:
                writer.add_scalar("charts/episodic_return", ep_ret_mean, global_step)
                writer.add_scalar("charts/episodic_length", ep_len_mean, global_step)
                writer.add_scalar("charts/SPS", sps, global_step)
                writer.add_scalar("charts/learning_rate", opt.param_groups[0]["lr"], global_step)
                writer.add_scalar("charts/dr_scale", dr_scale, global_step)
                writer.add_scalar("losses/policy", float(pg_loss), global_step)
                writer.add_scalar("losses/value", float(v_loss), global_step)
                writer.add_scalar("losses/entropy", float(ent_loss), global_step)
                writer.add_scalar("losses/approx_kl", float(approx_kl), global_step)
                for k, v in m.items():
                    writer.add_scalar(f"metrics/{k}", v, global_step)
            done_ret_sum.zero_()
            done_len_sum.zero_()
            done_count.zero_()

        if update % cfg.ckpt_interval_updates == 0 or update == num_updates:
            save_checkpoint(agent, cfg, env, f"{run_dir}/ckpt_{global_step}.pt", global_step)
        if stop and cfg.target_kl is not None:
            pass  # KL early-stop is per-update; continue collecting next rollout

    save_checkpoint(agent, cfg, env, f"{run_dir}/ckpt_final.pt", global_step)
    return agent


def save_checkpoint(agent: ActorCritic, cfg: PPOConfig, env: MultiAgentDroneEnv, path: str, step: int) -> None:
    """Save agent weights + the shapes/config needed to rebuild and evaluate it."""
    torch.save(
        {
            "model": agent.state_dict(),
            "ppo_cfg": asdict(cfg),
            "obs_dim": env.obs_dim,
            "act_dim": env.act_dim,
            "task": env.task.name,
            "global_step": step,
        },
        path,
    )
    with open(path + ".meta.json", "w") as f:
        json.dump({"task": env.task.name, "obs_dim": env.obs_dim, "act_dim": env.act_dim, "step": step}, f)


def load_agent(path: str, device: torch.device | str = "cuda") -> ActorCritic:
    """Rebuild an :class:`ActorCritic` from a checkpoint."""
    ckpt = torch.load(path, map_location=device, weights_only=False)
    cfg = PPOConfig(**ckpt["ppo_cfg"])
    agent = ActorCritic(ckpt["obs_dim"], ckpt["act_dim"], cfg).to(device)
    agent.load_state_dict(ckpt["model"])
    return agent.eval()
