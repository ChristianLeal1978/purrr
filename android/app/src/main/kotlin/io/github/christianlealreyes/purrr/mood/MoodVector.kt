package io.github.christianlealreyes.purrr.mood

/** Espejo de `MoodVector` en `mood/analyzer.py` del escritorio — sin la parte de
 * análisis, que no existe en Android (ver el plan, Fase 7.3: Android solo lee
 * vectores ya calculados por sync, nunca los calcula). */
data class MoodVector(
    val happy: Float,
    val sad: Float,
    val relaxed: Float,
    val aggressive: Float,
) {
    /** Distancia euclídea al cuadrado — alcanza para ordenar por cercanía
     * ([MoodQueueBuilder]), no hace falta la raíz cuadrada. */
    fun distanceTo(other: MoodVector): Float {
        val dHappy = happy - other.happy
        val dSad = sad - other.sad
        val dRelaxed = relaxed - other.relaxed
        val dAggressive = aggressive - other.aggressive
        return dHappy * dHappy + dSad * dSad + dRelaxed * dRelaxed + dAggressive * dAggressive
    }

    companion object {
        fun average(vectors: List<MoodVector>): MoodVector {
            require(vectors.isNotEmpty()) { "average() necesita al menos un vector" }
            val n = vectors.size
            return MoodVector(
                happy = vectors.sumOf { it.happy.toDouble() }.toFloat() / n,
                sad = vectors.sumOf { it.sad.toDouble() }.toFloat() / n,
                relaxed = vectors.sumOf { it.relaxed.toDouble() }.toFloat() / n,
                aggressive = vectors.sumOf { it.aggressive.toDouble() }.toFloat() / n,
            )
        }
    }
}
