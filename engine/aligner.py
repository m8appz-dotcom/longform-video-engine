#!/usr/bin/env python3
"""Alignment a nivel de palabra (misma interfaz mock/real).
- MockAligner: even-split deterministico (para el camino offline/tests).
- WhisperXAligner: forced alignment real sobre el audio de TTS (produccion).
get_aligner() elige por PROVIDER_MODE. La precision palabra-a-palabra es el insumo del caption.
- ElevenLabsAligner: usa los timestamps por caracter que ElevenLabs devuelve (sin whisperX/torch).
"""
import os, json

PER_WORD = float(os.environ.get("REEL_WORD_SECONDS", "0.30"))

def _even_split(words, per_word=PER_WORD, tail=0.4):
    out = [{"i": i, "word": w, "start_ms": int(i*per_word*1000), "end_ms": int((i+1)*per_word*1000)}
           for i, w in enumerate(words)]
    return {"words": out, "duration_ms": int((len(words)*per_word + tail)*1000)}

class MockAligner:
    mode = "mock"
    def align(self, audio_path, words):
        return _even_split(words)

class WhisperXAligner:
    mode = "real"
    def __init__(self):
        self.model_size = os.environ.get("WHISPERX_MODEL", "base")
        self.device = os.environ.get("WHISPERX_DEVICE", "cpu")
        self.compute = os.environ.get("WHISPERX_COMPUTE", "int8")
        self.language = os.environ.get("WHISPERX_LANG", "es")
    def align(self, audio_path, words=None):
        try:
            import whisperx
        except ImportError:
            raise RuntimeError("whisperx no instalado: pip install whisperx (requiere torch). "
                               "Es el modulo de alignment real; alimenta el caption palabra-a-palabra.")
        model = whisperx.load_model(self.model_size, self.device, compute_type=self.compute, language=self.language)
        audio = whisperx.load_audio(audio_path)
        result = model.transcribe(audio, language=self.language)
        amodel, meta = whisperx.load_align_model(language_code=self.language, device=self.device)
        aligned = whisperx.align(result["segments"], amodel, meta, audio, self.device)
        out = []; i = 0; last = 0
        for seg in aligned.get("segments", []):
            for wd in seg.get("words", []):
                if wd.get("start") is None:
                    continue
                s = int(wd["start"]*1000); e = int(wd.get("end", wd["start"]+0.2)*1000)
                out.append({"i": i, "word": wd["word"].strip(), "start_ms": s, "end_ms": max(e, s+1)})
                i += 1; last = max(last, e)
        if not out:
            raise RuntimeError("whisperX no devolvio palabras alineadas")
        return {"words": out, "duration_ms": last + 200}

class ElevenLabsAligner:
    """Lee el sidecar de timestamps por caracter que deja la TTS de ElevenLabs y agrupa en palabras. Sin torch."""
    mode = "real"
    def align(self, audio_path, words=None):
        side = os.path.splitext(audio_path)[0] + ".align.json"
        if not os.path.exists(side):
            raise RuntimeError("falta %s: corre la TTS de ElevenLabs con with-timestamps (providers.tts_voiceover ya lo hace)." % side)
        al = json.load(open(side, encoding="utf-8"))
        chars = al.get("characters") or []
        st = al.get("character_start_times_seconds") or []
        en = al.get("character_end_times_seconds") or []
        out = []; i = 0; cur = ""; cs = None; ce = None
        for c, s, e in zip(chars, st, en):
            if c is None or c.strip() == "":
                if cur:
                    out.append({"i": i, "word": cur, "start_ms": int(cs*1000), "end_ms": max(int(ce*1000), int(cs*1000)+1)})
                    i += 1; cur = ""; cs = None; ce = None
            else:
                if cs is None: cs = s
                cur += c; ce = e
        if cur:
            out.append({"i": i, "word": cur, "start_ms": int(cs*1000), "end_ms": max(int(ce*1000), int(cs*1000)+1)})
        if not out:
            raise RuntimeError("alineacion de ElevenLabs vacia en %s" % side)
        dur = int(max(en)*1000) + 150 if en else out[-1]["end_ms"]
        return {"words": out, "duration_ms": dur}

def get_aligner():
    mode = os.environ.get("PROVIDER_MODE", "mock").lower()
    if mode != "real":
        return MockAligner()
    if os.environ.get("ALIGNER", "elevenlabs").lower() == "whisperx":
        return WhisperXAligner()
    return ElevenLabsAligner()
