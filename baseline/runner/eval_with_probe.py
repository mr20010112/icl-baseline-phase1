#!/usr/bin/env python3
"""Python 3.8 compatible observer around official main_incontext.eval_libero."""
import json
import logging
import os

try:
    from .serve_with_probe import load_official
except ImportError:  # Direct script entry in the official client interpreter.
    from serve_with_probe import load_official


class TrialObserver(logging.Handler):
    def __init__(self, args, stream):
        super().__init__()
        self.args = args
        self.stream = stream
        self.state = None
        self.active = False
        self.errors = []

    def reset(self, task, episode):
        self.active = False
        self.state = dict(task=task, episode=episode, steps=0, steps_attempted=0,
                          failure_step=None, request_ids=[])

    def step(self, original, *args, **kwargs):
        if not self.active:
            return original(*args, **kwargs)
        self.state["steps_attempted"] += 1
        try:
            result = original(*args, **kwargs)
        except Exception:
            self.state["failure_step"] = self.state["steps_attempted"]
            raise
        self.state["steps"] += 1
        return result

    def emit(self, record):
        # Observe official log events; never manufacture a success decision.
        message = record.getMessage()
        if message.startswith("Starting episode "):
            self.active = True
        elif message.startswith("Caught exception:") and self.state is not None:
            self.state["exception"] = message
            if self.state["failure_step"] is None:
                self.state["failure_step"] = self.state["steps_attempted"] + 1
        elif message in ("Success: True", "Success: False"):
            self.active = False
            row = dict(self.state)
            row["success"] = message == "Success: True"
            row["failure_step"] = None if row["success"] else (
                row["failure_step"] or row["steps_attempted"])
            row["settling_steps"] = min(row["steps"], self.args.num_steps_wait)
            row["policy_steps"] = row["steps"] - row["settling_steps"]
            self.stream.write(json.dumps(row) + "\n")
            self.stream.flush()


def main():
    official = load_official("contextflow_official_client", "examples/libero/main_incontext.py")
    logging.basicConfig(level=logging.INFO)
    args = official.tyro.cli(official.Args)
    original_env = official._get_libero_env
    client_class = official._websocket_client_policy.WebsocketClientPolicy
    original_infer = client_class.infer
    with open(os.environ["CONTEXTFLOW_TRIAL_LOG"], "x", buffering=1) as stream, \
            open(os.environ["CONTEXTFLOW_PROBE_LOG"]) as requests:
        requests.seek(0, 2)  # Only requests made by this sequential client process.
        observer = TrialObserver(args, stream)

        def get_env(*a, **kw):
            env, task = original_env(*a, **kw)
            original_reset, original_step = env.reset, env.step
            episode = 0

            def reset(*a, **kw):
                nonlocal episode
                observer.reset(task, episode)
                episode += 1
                return original_reset(*a, **kw)

            def step(*a, **kw):
                return observer.step(original_step, *a, **kw)

            env.reset, env.step = reset, step
            return env, task

        def infer(client, *a, **kw):
            try:
                result = original_infer(client, *a, **kw)
            except BaseException:
                observe_request(a, kw)
                raise
            observe_request(a, kw)
            return result

        def observe_request(a, kw):
            # Server flushes its observation before sending this unchanged result.
            try:
                row = json.loads(requests.readline())
                obs = a[0] if a else kw["obs"]
                if row["task"] != str(obs["prompt"]):
                    raise ValueError("Probe task mismatch")
                observer.state["request_ids"].append(row["request_id"])
            except Exception as exc:
                # Do not turn observation errors into official rollout exceptions.
                observer.errors.append(str(exc))

        official._get_libero_env = get_env
        client_class.infer = infer
        logging.getLogger().addHandler(observer)
        try:
            official.eval_libero(args)
        finally:
            logging.getLogger().removeHandler(observer)
            official._get_libero_env = original_env
            client_class.infer = original_infer
        if observer.errors:
            raise RuntimeError("Invalid trial observations: " + repr(observer.errors))


if __name__ == "__main__":
    main()
