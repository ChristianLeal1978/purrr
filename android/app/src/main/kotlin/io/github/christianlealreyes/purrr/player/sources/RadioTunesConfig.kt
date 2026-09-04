package io.github.christianlealreyes.purrr.player.sources

import android.content.Context

/** Listen Key de RadioTunes (cuenta Premium AudioAddict) — se copia a mano desde
 * la cuenta del usuario (Player Settings → Hardware Player), mismo patrón que
 * `GoogleAuthConfig`/`SupabaseConfig`: sin OAuth, Purrr nunca maneja la
 * contraseña real de la cuenta. */
class RadioTunesConfig(context: Context) {
    private val prefs = context.getSharedPreferences("radiotunes_config", Context.MODE_PRIVATE)

    fun saveListenKey(listenKey: String) {
        prefs.edit().putString(KEY_LISTEN_KEY, listenKey).apply()
    }

    fun loadListenKey(): String? = prefs.getString(KEY_LISTEN_KEY, null)

    fun isConfigured(): Boolean = loadListenKey() != null

    companion object {
        private const val KEY_LISTEN_KEY = "listen_key"
    }
}
