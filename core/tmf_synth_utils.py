# core/tmf_synth_utils.py
# Compatibility layer to keep older imports working.
# New code should import from core.synth_utils.

from .synth_utils import call_gpt_json, embed_texts

__all__ = ["call_gpt_json", "embed_texts"]
