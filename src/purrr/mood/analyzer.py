"""Análisis de ánimo de un track local con essentia-tensorflow — función pura, sin
threading ni GTK (eso lo maneja `mood/controller.py`), para poder probarla sola.

Verificado de punta a punta contra audio real antes de escribir esto (no es una
integración a ciegas contra la documentación): decodificar → embedding
Discogs-EffNet → 4 clasificadores binarios (happy/sad/relaxed/aggressive) da un
vector de ánimo coherente en un par de segundos por canción.

Dos detalles de la API que NO son obvios por la documentación y hay que respetar:
1. El nombre del nodo de salida de `TensorflowPredict2D` no es fijo entre modelos —
   hay que leerlo de `schema.outputs[0].name` en el `.json` de cada cabezal.
2. El orden de las clases tampoco es fijo: para "happy" es `['happy','non_happy']`
   pero para "sad" es `['non_sad','sad']` (¡al revés!). Hardcodear un índice fijo
   daría probabilidades invertidas para algunos ánimos, sin ningún error visible.
"""

from dataclasses import dataclass
from pathlib import Path

from purrr.mood import models

_SAMPLE_RATE = 16000


@dataclass(frozen=True)
class MoodVector:
    happy: float
    sad: float
    relaxed: float
    aggressive: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.happy, self.sad, self.relaxed, self.aggressive)

    def distance_to(self, other: "MoodVector") -> float:
        """Distancia euclídea al cuadrado — alcanza para ordenar por cercanía
        (`mood/queue_builder.py`), no hace falta la raíz cuadrada."""
        return sum((a - b) ** 2 for a, b in zip(self.as_tuple(), other.as_tuple()))

    @staticmethod
    def average(vectors: list["MoodVector"]) -> "MoodVector":
        n = len(vectors)
        return MoodVector(
            happy=sum(v.happy for v in vectors) / n,
            sad=sum(v.sad for v in vectors) / n,
            relaxed=sum(v.relaxed for v in vectors) / n,
            aggressive=sum(v.aggressive for v in vectors) / n,
        )


def analyze_track(local_path: Path) -> MoodVector:
    """Decodifica el audio y corre los 5 modelos (embedding + 4 cabezales). Pesado en
    CPU (~1-15s según la duración) — llamar siempre desde un hilo de fondo."""
    # Import perezoso: essentia-tensorflow carga TensorFlow completo, no tiene
    # sentido pagar ese costo al arrancar Purrr si el usuario nunca usa este modo.
    import essentia.standard as es

    audio = es.MonoLoader(filename=str(local_path), sampleRate=_SAMPLE_RATE)()
    embeddings = es.TensorflowPredictEffnetDiscogs(
        graphFilename=str(models.embedding_path()), output="PartitionedCall:1"
    )(audio)

    values = {}
    for mood in models.MOODS:
        meta = models.load_head_metadata(mood)
        output_name = meta["schema"]["outputs"][0]["name"]
        predictor = es.TensorflowPredict2D(graphFilename=str(models.head_pb_path(mood)), output=output_name)
        activations = predictor(embeddings)
        class_index = meta["classes"].index(mood)
        values[mood] = float(activations.mean(axis=0)[class_index])

    return MoodVector(**values)
