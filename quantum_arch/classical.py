"""Classical CPUs, GPUs, FPGAs and ASICs next to the quantum processor.

Three jobs: decode error-correction syndromes in real time, run the classical
half of hybrid algorithms, and host the control stack. Devices are sized by
throughput, powered linearly between idle and TDP, and, when placed on a cold
stage, their dissipation is returned to the cryostat model as a heat load.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import catalog


@dataclass(frozen=True)
class Device:
    """One catalog device. ``tdp_w`` / ``idle_w`` are MODULE-level power (boundary 1)."""
    key: str
    label: str
    kind: str
    tdp_w: float
    idle_w: float
    int_ops: float
    fp64_flops: float
    fp16_flops: float
    latency_factor: float
    locations: tuple[str, ...]
    #: Complete-server power / module power at rated maximum (boundary 2); 1.0 = not modelled.
    system_overhead_ratio: float = 1.0
    hbm_stacks: int = 0
    hbm_w_per_stack: float = 0.0
    hbm_tbps: float = 0.0
    vintage: str = ""
    scenario: str = ""
    source: str = ""

    @classmethod
    def from_catalog(cls, key: str, profile: str | None = None) -> "Device":
        key = resolve_key(key, profile)
        raw = dict(catalog.entry("classical", key))
        raw["locations"] = tuple(raw["locations"])
        return cls(key=key, **raw)

    @property
    def hbm_power_w(self) -> float:
        return self.hbm_stacks * self.hbm_w_per_stack

    def system_power_w(self, utilisation: float) -> float:
        """Complete-server power (boundary 2) at ``utilisation``: module power x system overhead ratio."""
        return self.power_w(utilisation) * self.system_overhead_ratio

    def rate(self, kind: str) -> float:
        return getattr(self, kind)

    def power_w(self, utilisation: float) -> float:
        u = min(max(utilisation, 0.0), 1.0)
        return self.idle_w + (self.tdp_w - self.idle_w) * u


#: scenario suffix per hardware profile (the unsuffixed catalog key is the base scenario)
_SCENARIO_SUFFIX = {"mid2030s_low": "_low", "mid2030s_high": "_high"}


def profile_family(profile: str | None) -> str:
    """Catalog family of a profile: ``today``, ``projected`` or ``mid2030s`` (any scenario)."""
    if profile is None:
        return "mid2030s"
    return "mid2030s" if profile.startswith("mid2030s") else profile


def resolve_key(key: str, profile: str | None = None) -> str:
    """Resolve ``auto:<role>`` and scenario variants of a device key for a hardware profile.

    ``auto:cpu|gpu|fpga|asic_rt|asic_4k`` picks the profile's default device. A 2035 key
    without a scenario suffix (``gpu_2035``) maps to its ``_low`` / ``_high`` variant when the
    profile is ``mid2030s_low`` / ``mid2030s_high`` and the variant exists.
    """
    if key.startswith("auto:"):
        defaults = catalog.load("classical")["_profile_defaults"]
        key = defaults[profile_family(profile) if profile_family(profile) in defaults else "mid2030s"][key[5:]]
    suffix = _SCENARIO_SUFFIX.get(profile or "")
    if suffix and not key.endswith(("_low", "_high")) and f"{key}{suffix}" in catalog.keys("classical"):
        return f"{key}{suffix}"
    return key


@dataclass
class Block:
    role: str
    device: Device
    count: int
    location: str
    utilisation: float
    power_w: float
    detail: str = ""
    keeps_up: bool = True
    latency_s: float = 0.0

    @property
    def name(self) -> str:
        return f"{self.role}: {self.count} x {self.device.label}"

    @property
    def server_overhead_w(self) -> float:
        """Extra power of the complete server around the modules (boundary 2 minus boundary 1)."""
        return self.power_w * (self.device.system_overhead_ratio - 1.0)


def check_location(device: Device, location: str) -> None:
    if location not in device.locations:
        raise ValueError(f"{device.label} cannot be placed at {location!r}; allowed: {', '.join(device.locations)}")


def decoder_latency_s(decoder_key: str, device: Device, distance: int) -> float:
    raw = catalog.entry("decoders", decoder_key)
    return raw["latency_us_d10"] * 1e-6 * device.latency_factor * distance / 10.0


def size_decoder(required_ops_per_s: float, decoder_key: str, device_key: str, location: str,
                 count: int | None = None, sustained: float = 0.4,
                 distance: int = 10, profile: str | None = None) -> Block:
    """A bank of ``device_key`` devices running ``decoder_key`` at ``required_ops_per_s``.

    ``sustained`` is the fraction of peak throughput a real decoder implementation
    reaches (memory-bound, irregular access). ``count=None`` sizes the bank to
    keep up with the syndrome stream.
    """
    dec = catalog.entry("decoders", decoder_key)
    dev = Device.from_catalog(device_key, profile)
    check_location(dev, location)
    rate = dev.rate(dec["ops_kind"])
    if rate <= 0:
        raise ValueError(f"{dev.label} has no {dec['ops_kind']} throughput for {dec['label']}")
    per_device = rate * sustained
    needed = max(1, math.ceil(required_ops_per_s / per_device)) if required_ops_per_s > 0 else 1
    n = needed if count is None else count
    util = required_ops_per_s / (n * per_device) if n else math.inf
    return Block(role="decoder", device=dev, count=n, location=location, utilisation=min(util, 1.0),
                 power_w=n * dev.power_w(util),
                 detail=f"{dec['label']}, {required_ops_per_s:.2e} op/s needed, {per_device:.2e} op/s each",
                 keeps_up=util <= 1.0 + 1e-9,
                 latency_s=decoder_latency_s(decoder_key, dev, distance))


def fixed_block(role: str, device_key: str, count: int, location: str, utilisation: float,
                profile: str | None = None) -> Block:
    dev = Device.from_catalog(device_key, profile)
    check_location(dev, location)
    return Block(role=role, device=dev, count=count, location=location, utilisation=utilisation,
                 power_w=count * dev.power_w(utilisation))


def link_power_w(bits_per_s: float, pj_per_bit: float) -> float:
    return bits_per_s * pj_per_bit * 1e-12
