#!/usr/bin/env python3
"""CPU-only synthetic linear-regression computation; never research evidence."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import random
import sys
import time


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--fail", action="store_true", help="Intentional fault injection")
    parser.add_argument("--missing-metrics", action="store_true", help="Intentional evidence failure")
    parser.add_argument("--sleep", type=float, default=0.0, help="Intentional timeout/stall fixture")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("kind") != "toy":
        parser.error("The example requires config.kind='toy'; it cannot run real research")
    seed = args.seed if args.seed is not None else int(os.environ.get("RESEARCH_SEED", config.get("seed", 7)))
    hyperparameters = config.get("hyperparameters", config)
    n_train = hyperparameters.get("n_train", 64)
    n_test = hyperparameters.get("n_test", 32)
    epochs = hyperparameters.get("epochs", 100)
    learning_rate = hyperparameters.get("learning_rate", 0.05)
    noise_std = hyperparameters.get("noise_std", 0.02)
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (n_train, n_test, epochs)):
        parser.error("n_train, n_test and epochs must be positive integers")
    if (not isinstance(learning_rate, (int, float)) or not math.isfinite(learning_rate)
            or not 0 < learning_rate < 1 or not isinstance(noise_std, (int, float))
            or not math.isfinite(noise_std) or noise_std < 0):
        parser.error("learning_rate must be in (0, 1); noise_std must be finite and nonnegative")
    out_value = os.environ.get("RESEARCH_RUN_DIR")
    if not out_value:
        parser.error("RESEARCH_RUN_DIR must point to the launcher-assigned output directory")
    output = Path(out_value)
    output.mkdir(parents=True, exist_ok=True)
    if args.fail:
        print("Intentional toy failure; no metrics generated", file=sys.stderr, flush=True)
        return 23
    if args.sleep:
        time.sleep(args.sleep)
    rng = random.Random(seed)
    # Independent synthetic train/test samples; the known generating law is y=2x+1+noise.
    def sample(count: int) -> list[tuple[float, float]]:
        rows = []
        for _ in range(count):
            x = rng.uniform(-1.0, 1.0)
            rows.append((x, 2.0 * x + 1.0 + rng.gauss(0.0, noise_std)))
        return rows
    train = sample(n_train)
    test = sample(n_test)
    weight, bias = rng.uniform(-0.1, 0.1), 0.0
    trajectory = []
    for epoch in range(epochs):
        # Full-batch gradient descent, squared-error gradient. All values are scalar CPU floats.
        errors = [(weight * x + bias - y, x) for x, y in train]
        grad_w = 2.0 * sum(error * x for error, x in errors) / n_train
        grad_b = 2.0 * sum(error for error, _ in errors) / n_train
        weight -= learning_rate * grad_w
        bias -= learning_rate * grad_b
        train_mse = sum((weight * x + bias - y) ** 2 for x, y in train) / n_train
        trajectory.append({"epoch": epoch + 1, "train_mse": train_mse})
        write_json(output / "progress.json", {"kind": "toy", "epoch": epoch + 1, "epochs": epochs})
    test_mse = sum((weight * x + bias - y) ** 2 for x, y in test) / n_test
    write_json(output / "trajectory.json", {"kind": "toy", "seed": seed, "points": trajectory})
    write_json(output / "model.json", {"kind": "toy", "weight": weight, "bias": bias, "seed": seed})
    with (output / "predictions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["kind", "split", "x", "target", "prediction"])
        writer.writerows(("toy", "test", x, y, weight * x + bias) for x, y in test)
    if not args.missing_metrics:
        # Metric files contain numeric measurements only; kind/seed are in the run manifest.
        write_json(output / "metrics.json", {"mse": test_mse, "train_mse": train_mse})
    print(json.dumps({"kind": "toy", "seed": seed, "test_mse": test_mse,
                      "warning": "Synthetic engineering smoke test; no scientific claim"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
