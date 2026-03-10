"""processing — signal processing algorithms for ZenFlow Verity."""

from processing.ppi_processor import compute_ppi_metrics, process_window, PPIMetrics
from processing.rsa_analyzer import compute_rsa, RSAResult
from processing.coherence_scorer import compute_coherence, CoherenceResult
from processing.artifact_handler import filter_ppi_stream, detect_artifact

__all__ = [
    "compute_ppi_metrics", "process_window", "PPIMetrics",
    "compute_rsa", "RSAResult",
    "compute_coherence", "CoherenceResult",
    "filter_ppi_stream", "detect_artifact",
]
