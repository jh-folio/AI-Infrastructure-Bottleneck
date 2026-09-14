"""Single versioned calculation entrypoint; never executes code from research data."""
from engines import d3_1_0
from engines.d3_1_0 import VERSION, ENGINE, WEIGHTS, AXES, CORE, compare
from pathlib import Path
import hashlib

REGISTRY = {'d3-1.0': d3_1_0}

def calculate(inputs):
    return REGISTRY[ENGINE].calculate(inputs)

def replay(inputs, result, artifacts):
    engine=REGISTRY.get(result['engine_version'])
    if engine is None:
        raise ValueError('Historical engine not bundled; retain artifacts for reviewed migration')
    path=Path(engine.__file__)
    expected=artifacts.get('engines/'+path.name,{})
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected.get('sha256'):
        raise ValueError('Bundled historical engine hash differs from stored artifact')
    return engine.calculate(inputs)
