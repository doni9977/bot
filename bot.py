"""Mech Royale entrypoint. `mechfight.run` owns the stdin/stdout loop."""
import mechfight as mf
from apex import ApexBrain
from brain import Brain
from params import load as load_params


class Bot:
    name = "doni"

    def __init__(self, hello: mf.Hello):
        p = load_params()
        if p.get("engine_v2", True):
            self.brain = ApexBrain(hello)
        else:
            self.brain = Brain(hello)

    def act(self, obs: mf.Observation) -> mf.Action:
        try:
            return self.brain.act(obs)
        except Exception as exc:
            import sys
            print(f"act error: {exc}", file=sys.stderr, flush=True)
            me = obs.get("self") or {}
            aim = me.get("aim") or [0.0, 0.0]
            return {
                "move": [0.0, 0.0],
                "boost": False,
                "aim": [float(aim[0]), float(aim[1])],
                "fire": [False, False],
            }


mf.run(Bot)
