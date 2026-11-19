"""Check the duration rewrite and recovery without voice downloads or a GPU."""
import sys
import subprocess
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import pytest
from onnx import TensorProto, helper

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from speech_acceleration import AcceleratedSession, alignment_graph, optimized_model


def test_runtime_loads_without_the_optional_conversion_telemetry():
    backend = str(Path(__file__).resolve().parents[2] / "backend")
    code = ("import sys; sys.path.insert(0, " + repr(backend) + "); "
            "from speech_acceleration import local_runtime; "
            "assert local_runtime().Core; "
            "assert 'openvino_telemetry' not in sys.modules; "
            "assert 'openvino.tools.ovc' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


def test_alignment_matches_repeated_indices_including_zero_durations():
    nodes, constants = alignment_graph("durations", "indices")
    graph = helper.make_graph(nodes, "alignment", [helper.make_tensor_value_info("durations", TensorProto.INT64, [None])],
                              [helper.make_tensor_value_info("indices", TensorProto.INT64, [None])], constants)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)], ir_version=10)
    onnx.checker.check_model(model)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    session = ort.InferenceSession(model.SerializeToString(), sess_options=options, providers=["CPUExecutionProvider"])
    random = np.random.default_rng(42)
    cases = [np.array([1]), np.array([0, 0, 0]), np.array([0, 2, 0, 3, 1, 0])]
    cases += [random.integers(0, 30, size=size) for size in (3, 12, 64, 128, 510)]
    for durations in cases:
        actual = session.run(None, {"durations": durations.astype(np.int64)})[0]
        np.testing.assert_array_equal(actual, np.repeat(np.arange(len(durations)), durations))


def test_unknown_model_is_never_rewritten(tmp_path):
    source = tmp_path / "custom.onnx"
    source.write_bytes(b"a different model")
    with pytest.raises(ValueError, match="not the supported"):
        optimized_model(source)
    assert source.read_bytes() == b"a different model"
    assert not (tmp_path / "kokoro-lumen-v1.onnx").exists()


def test_accelerator_failure_retries_original_engine_and_disables_acceleration():
    class Broken:
        def __call__(self, inputs):
            raise RuntimeError("unsupported shape")

    class Original:
        def run(self, names, inputs):
            return [inputs["tokens"]]

    session = AcceleratedSession(Broken(), Original())
    assert session.run(None, {"tokens": [1, 2]}) == [[1, 2]]
    assert session.compiled is None
    assert session.run(None, {"tokens": [3]}) == [[3]]


def test_original_engine_is_only_created_if_acceleration_fails():
    created = []

    class Original:
        def run(self, names, inputs):
            return ["original"]

    def factory():
        created.append(1)
        return Original()

    class Working:
        outputs = ["audio"]
        def __call__(self, inputs):
            return {"audio": np.zeros(2, np.float32)}

    session = AcceleratedSession(Working(), factory)
    session.run(None, {})
    assert created == []  # ~370 MB of RAM not spent while acceleration works

    class Broken:
        def __call__(self, inputs):
            raise RuntimeError("driver problem")

    session = AcceleratedSession(Broken(), factory)
    assert session.run(None, {}) == ["original"]
    assert session.run(None, {}) == ["original"]
    assert created == [1]  # created once, on first need


def test_accelerator_returns_owned_output_buffers():
    class Compiled:
        outputs = ["audio"]
        def __init__(self):
            self.audio = np.array([0.1, 0.2], np.float32)
        def __call__(self, inputs):
            return {"audio": self.audio}

    compiled = Compiled()
    session = AcceleratedSession(compiled, None)
    audio = session.run(None, {})[0]
    compiled.audio[:] = 0
    np.testing.assert_allclose(audio, [0.1, 0.2])
