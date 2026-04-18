"""Scoreboard: tracks student's current run against three benchmark runs.

The benchmark delays are precomputed once at scenario load (in benchmarks.py).
The student's run is read continuously from the live simulator and extrapolated
to the full analysis period so comparison is apples-to-apples.

"Best so far" tracks the student's best extrapolated delay across all their
attempts in this session (survives reset within the same scenario).
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
from constants import SIM_DURATION


@dataclass
class BenchmarkValues:
    """One benchmark's values: total delay (veh-hr), avg delay/veh (sec)."""
    delay_vehhr: float = 0.0
    avg_sec: float = 0.0
    throughput: float = 0.0


@dataclass
class ScoreBoard:
    """Tracks benchmark + current + best-so-far.

    Benchmarks are fixed after construction. Current updates live. Best-so-far
    updates when current extrapolated delay improves.
    """
    baseline: BenchmarkValues = field(default_factory=BenchmarkValues)
    webster: BenchmarkValues = field(default_factory=BenchmarkValues)
    optimum: BenchmarkValues = field(default_factory=BenchmarkValues)

    current_delay_vehhr: float = 0.0     # extrapolated to SIM_DURATION
    current_avg_sec: float = 0.0
    current_throughput: float = 0.0
    current_raw_delay_vehhr: float = 0.0  # actually measured so far

    best_delay_vehhr: float = float("inf")  # lowest extrapolated delay seen
    best_avg_sec: float = float("inf")

    # Minimum simulated time before we start counting for best-so-far
    # (avoid false-best from a 5-second run with zero delay)
    min_time_for_best: float = 300.0

    # ---- Load-time setup ----
    @classmethod
    def from_benchmarks(cls, bench: Dict[str, Dict[str, float]]) -> "ScoreBoard":
        """Build from the dict returned by benchmarks.compute_all()."""
        sb = cls()
        sb.baseline = BenchmarkValues(
            delay_vehhr=bench["baseline"]["delay_vehhr"],
            avg_sec=bench["baseline"]["avg_sec"],
            throughput=bench["baseline"]["throughput"],
        )
        sb.webster = BenchmarkValues(
            delay_vehhr=bench["webster"]["delay_vehhr"],
            avg_sec=bench["webster"]["avg_sec"],
            throughput=bench["webster"]["throughput"],
        )
        sb.optimum = BenchmarkValues(
            delay_vehhr=bench["optimum"]["delay_vehhr"],
            avg_sec=bench["optimum"]["avg_sec"],
            throughput=bench["optimum"]["throughput"],
        )
        return sb

    # ---- Live update ----
    def reset_current(self) -> None:
        """Clear current-run metrics (called on simulation reset).
        Benchmarks and best-so-far are preserved."""
        self.current_delay_vehhr = 0.0
        self.current_avg_sec = 0.0
        self.current_throughput = 0.0
        self.current_raw_delay_vehhr = 0.0

    def update(self, sim) -> None:
        """Refresh from simulator. Extrapolate current delay to full duration.

        Extrapolation: if the sim has run for t seconds with D veh-sec of delay,
        we estimate the full-duration delay as D * (SIM_DURATION / t).
        """
        t = sim.global_time
        if t < 1.0:
            return

        self.current_raw_delay_vehhr = sim.total_delay / 3600.0
        self.current_throughput = sim.total_throughput
        self.current_avg_sec = (
            sim.total_delay / max(sim.total_throughput, 1e-9)
        )

        # Extrapolate
        scale = SIM_DURATION / t
        self.current_delay_vehhr = self.current_raw_delay_vehhr * scale

        # Update best-so-far (require minimum time to avoid noise)
        if t >= self.min_time_for_best:
            if self.current_delay_vehhr < self.best_delay_vehhr:
                self.best_delay_vehhr = self.current_delay_vehhr
                self.best_avg_sec = self.current_avg_sec

    # ---- Reporting ----
    def ratio_vs_baseline(self) -> float:
        """Current as fraction of baseline. <1 means better."""
        if self.baseline.delay_vehhr <= 1e-9:
            return 1.0
        return self.current_delay_vehhr / self.baseline.delay_vehhr

    def gap_to_optimum(self) -> float:
        """(current - optimum) / (baseline - optimum).
        0 = matched optimum, 1 = at baseline, negative = better than optimum.
        """
        denom = self.baseline.delay_vehhr - self.optimum.delay_vehhr
        if abs(denom) < 1e-9:
            return 0.0
        return (self.current_delay_vehhr - self.optimum.delay_vehhr) / denom

    def percent_improvement_over_baseline(self) -> float:
        """How much better than baseline, as a percentage (positive = better)."""
        if self.baseline.delay_vehhr <= 1e-9:
            return 0.0
        return 100.0 * (1.0 - self.current_delay_vehhr / self.baseline.delay_vehhr)
