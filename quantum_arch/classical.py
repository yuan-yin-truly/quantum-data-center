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

    @classmethod
    def from_catalog(cls, key: str) -> "Device":
        raw = dict(catalog.entry("classical", key))
        raw["locations"] = tuple(raw["locations"])
        return cls(key=key, **raw)

    def rate(self, kind: str) -> float:
        return getattr(self, kind)

    def power_w(self, utilisation: float) -> float:
        u = min(max(utilisation, 0.0), 1.0)
        return self.idle_w + (self.tdp_w - self.idle_w) * u


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


def check_location(device: Device, location: str) -> None:
    if location not in device.locations:
        raise ValueError(f"{device.label} cannot be placed at {location!r}; allowed: {', '.join(device.locations)}")


def decoder_latency_s(decoder_key: str, device: Device, distance: int) -> float:
    raw = catalog.entry("decoders", decoder_key)
    return raw["latency_us_d10"] * 1e-6 * device.latency_factor * distance / 10.0


def size_decoder(required_ops_per_s: float, decoder_key: str, device_key: str, location: str,
                 count: int | None = None, sustained: float = 0.4,
                 distance: int = 10) -> Block:
    """A bank of ``device_key`` devices running ``decoder_key`` at ``required_ops_per_s``.

    ``sustained`` is the fraction of peak throughput a real decoder implementation
    reaches (memory-bound, irregular access). ``count=None`` sizes the bank to
    keep up with the syndrome stream.
    """
    dec = catalog.entry("decoders", decoder_key)
    dev = Device.from_catalog(device_key)
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


def fixed_block(role: str, device_key: str, count: int, location: str, utilisation: float) -> Block:
    dev = Device.from_catalog(device_key)
    check_location(dev, location)
    return Block(role=role, device=dev, count=count, location=location, utilisation=utilisation,
                 power_w=count * dev.power_w(utilisation))


def link_power_w(bits_per_s: float, pj_per_bit: float) -> float:
    return bits_per_s * pj_per_bit * 1e-12
