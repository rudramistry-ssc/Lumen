"""Local FP32 Kokoro acceleration, with the original ONNX engine as fallback.

The supported export builds frame indices by looping over phonemes and appending
each index `duration` times. The equivalent cumulative-sum comparison removes
that sequence loop; the trained weights and voice styles are never changed.
"""
import hashlib
import logging
import os
import sys
from pathlib import Path

SUPPORTED_SHA256 = "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a"
LOG = logging.getLogger(__name__)


def local_runtime():
    # Only the runtime is needed. OpenVINO's optional conversion API initializes
    # telemetry on import; omit that API so local speech has no telemetry path.
    missing = object()
    converter = sys.modules.get("openvino.tools.ovc", missing)
    sys.modules["openvino.tools.ovc"] = None
    try:
        import openvino as ov
    finally:
        if converter is missing:
            sys.modules.pop("openvino.tools.ovc", None)
        else:
            sys.modules["openvino.tools.ovc"] = converter
    return ov


def alignment_graph(durations, output):
    import numpy as np
    from onnx import TensorProto, helper, numpy_helper

    p = "lumen_alignment_"
    constants = [numpy_helper.from_array(np.array(value, dtype=np.int64), p + name)
                 for name, value in (("zero", 0), ("one", 1), ("axis0", [0]), ("axis1", [1]))]
    nodes = [
        helper.make_node("CumSum", [durations, p + "zero"], [p + "ends"]),
        helper.make_node("ReduceSum", [durations, p + "axis0"], [p + "length"], keepdims=0),
        helper.make_node("Range", [p + "zero", p + "length", p + "one"], [p + "frames"]),
        helper.make_node("Unsqueeze", [p + "frames", p + "axis0"], [p + "rows"]),
        helper.make_node("Unsqueeze", [p + "ends", p + "axis1"], [p + "columns"]),
        helper.make_node("GreaterOrEqual", [p + "rows", p + "columns"], [p + "passed"]),
        helper.make_node("Cast", [p + "passed"], [p + "integers"], to=TensorProto.INT64),
        helper.make_node("ReduceSum", [p + "integers", p + "axis0"], [output], keepdims=0),
    ]
    return nodes, constants


def optimized_model(source):
    source = Path(source)
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SUPPORTED_SHA256:
            raise ValueError("Voice export is not the supported Kokoro model")
    target = source.with_name("kokoro-lumen-v1.onnx")
    if target.is_file():
        return target

    import numpy as np
    import onnx
    from onnx import numpy_helper

    model = onnx.load(source)
    nodes, constants = alignment_graph("/Where_1_output_0", "/ConcatFromSequence_output_0")
    rewritten = []
    for node in model.graph.node:
        if node.op_type in {"SplitToSequence", "SequenceEmpty", "Loop"}:
            continue
        if node.op_type == "ConcatFromSequence":
            rewritten.extend(nodes)
        else:
            if node.op_type == "Squeeze" and list(node.output) == ["duration"]:
                # Batch size is fixed at one; make its axis explicit so the
                # accelerator can infer the output rank for variable text length.
                node.input.append("lumen_duration_batch_axis")
            rewritten.append(node)
    del model.graph.node[:]
    model.graph.node.extend(rewritten)
    model.graph.initializer.extend(constants)
    model.graph.initializer.append(numpy_helper.from_array(np.array([0], np.int64), "lumen_duration_batch_axis"))
    onnx.checker.check_model(model)
    temporary = target.with_suffix(".part.onnx")
    onnx.save(model, temporary)
    temporary.replace(target)
    return target


class AcceleratedSession:
    """OpenVINO first; the original ONNX Runtime engine if that ever fails.

    ``original`` is a session or, to save memory, a function that creates one:
    an idle ONNX Runtime copy of the voice costs ~370 MB of RAM, and with working
    acceleration it is never used.
    """

    def __init__(self, compiled, original):
        self.compiled = compiled
        self.original = original

    def _original(self):
        if not hasattr(self.original, "run"):
            self.original = self.original()  # created only when first needed
        return self.original

    def run(self, names, inputs):
        if self.compiled is not None:
            try:
                import numpy as np
                outputs = self.compiled(inputs)
                # OpenVINO owns output buffers; return independent arrays just
                # as ONNX Runtime does, before the next phrase reuses a buffer.
                return [np.array(outputs[port], copy=True) for port in self.compiled.outputs]
            except Exception:
                self.compiled = None
                LOG.warning("Local voice acceleration failed; using the original CPU engine.")
        return self._original().run(names, inputs)


def accelerate(voice, source, fallback=None):
    """Run ``voice`` through OpenVINO. With ``fallback`` (a function creating the
    original session), the original session is released once acceleration works."""
    if os.getenv("LUMEN_SPEECH_ACCELERATION", "auto").lower() == "off":
        return
    try:
        ov = local_runtime()
        model = optimized_model(source)
        compiled = ov.Core().compile_model(str(model), "CPU", {
            "PERFORMANCE_HINT": "LATENCY",
            "INFERENCE_PRECISION_HINT": "f32",
            "INFERENCE_NUM_THREADS": min(4, os.cpu_count() or 2),
        })
        voice.sess = AcceleratedSession(compiled, fallback or voice.sess)
        LOG.info("Local voice acceleration ready (FP32 CPU).")
    except Exception:
        LOG.warning("Local voice acceleration unavailable; using the original CPU engine.")
