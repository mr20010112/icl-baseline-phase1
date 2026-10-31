#!/usr/bin/env python3
"""Observe the pinned official server, without replacing its CLI or policy logic."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import time


def load_official(name, relative):
    path = Path(os.environ["OPENPI_PROJECT_ROOT"]) / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class InferenceProbe:
    def __init__(self, original_infer, stream):
        self.original_infer = original_infer
        self.stream = stream
        self.selected = None
        self.request_id = 0

    def observe_demo(self, result):
        # Read the official transform's returned value, including its cache path.
        self.selected = [int(i) for i in result["selected_episode"].reshape(-1).tolist()]

    def infer(self, *args, **kwargs):
        self.selected = None
        started = time.perf_counter_ns()
        try:
            result = self.original_infer(*args, **kwargs)
        except BaseException as exc:
            self.record(args, kwargs, started, type(exc).__name__)
            raise
        self.record(args, kwargs, started, None)
        return result

    def record(self, args, kwargs, started, error):
        elapsed_ms = (time.perf_counter_ns() - started) / 1e6
        obs = args[0] if args else kwargs["obs"]
        self.stream.write(json.dumps({"request_id": self.request_id,
                                     "task": str(obs["prompt"]),
                                     "task_index": int(obs["task_index"]),
                                     "demo_episode_indices": self.selected or [],
                                     "error": error,
                                     "latency_ms": elapsed_ms}) + "\n")
        self.stream.flush()  # Before the official websocket sends the response.
        self.request_id += 1


def main():
    official = load_official("contextflow_official_server", "scripts/serve_policy.py")
    from openpi import transforms
    original_create = official.create_policy
    original_transform = transforms.InjectDemoFromCustomDataset.__call__
    with open(os.environ["CONTEXTFLOW_PROBE_LOG"], "x", buffering=1) as stream:
        def create(*args, **kwargs):
            policy = original_create(*args, **kwargs)
            probe = InferenceProbe(policy.infer, stream)

            def observe(transform, *a, **kw):
                result = original_transform(transform, *a, **kw)
                probe.observe_demo(result)
                return result

            transforms.InjectDemoFromCustomDataset.__call__ = observe
            policy.infer = probe.infer
            return policy

        official.create_policy = create
        logging.basicConfig(level=logging.INFO, force=True)
        try:
            official.main(official.tyro.cli(official.Args))
        finally:
            official.create_policy = original_create
            transforms.InjectDemoFromCustomDataset.__call__ = original_transform


if __name__ == "__main__":
    main()
