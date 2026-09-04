package io.github.christianlealreyes.purrr.mood

import io.github.christianlealreyes.purrr.data.entities.TrackEntity
import io.github.christianlealreyes.purrr.data.entities.TrackMoodEntity

private const val DEFAULT_LIMIT = 50

/** Arma una cola de reproducción a partir de canciones semilla, usando la
 * cercanía en el espacio de ánimo de 4 dimensiones — espejo de
 * `mood/queue_builder.py:build_mood_queue` del escritorio. Vacío si ninguna
 * semilla tiene todavía un vector sincronizado. El resultado se le pasa tal cual
 * a `PlaybackCoordinator.playQueue` — como esa función ya ignora tracks sin
 * `localPath` (Fase 6.4), una canción con ánimo sincronizado pero nunca cacheada
 * en este dispositivo simplemente no suena, mismo comportamiento que ya existe en
 * Biblioteca/Playlists, no es un caso especial nuevo. */
fun buildMoodQueue(
    seedTrackRefs: List<String>,
    moods: List<TrackMoodEntity>,
    tracks: List<TrackEntity>,
    limit: Int = DEFAULT_LIMIT,
): List<TrackEntity> {
    val moodByRef = moods.associateBy { it.trackRef }
    val trackByRef = tracks.associateBy { it.trackRef }

    val seedVectors = seedTrackRefs.mapNotNull { moodByRef[it]?.toMoodVector() }
    if (seedVectors.isEmpty()) return emptyList()
    val centroid = MoodVector.average(seedVectors)

    val seedItems = seedTrackRefs.mapNotNull { trackByRef[it] }

    val seedRefSet = seedTrackRefs.toSet()
    val candidates = moods.filter { it.trackRef !in seedRefSet }
        .sortedBy { centroid.distanceTo(it.toMoodVector()) }
        .mapNotNull { trackByRef[it.trackRef] }
        .take(limit)

    return seedItems + candidates
}

private fun TrackMoodEntity.toMoodVector() = MoodVector(happy, sad, relaxed, aggressive)
