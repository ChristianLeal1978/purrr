package io.github.christianlealreyes.purrr.cloud

import android.content.Context

/** Bootstrap del proyecto Supabase (Project URL + anon key) — igual que
 * `cloud/config.py` del escritorio: no es una credencial secreta, solo "a qué
 * backend hablarle". Guardado en SharedPreferences (equivalente Android de un
 * archivo de config chico en `~/.config/purrr/` — no hace falta más para esto). */
class SupabaseConfig(context: Context) {
    private val prefs = context.getSharedPreferences("supabase_config", Context.MODE_PRIVATE)

    fun save(url: String, anonKey: String) {
        prefs.edit().putString(KEY_URL, url).putString(KEY_ANON_KEY, anonKey).apply()
    }

    fun load(): Pair<String, String>? {
        val url = prefs.getString(KEY_URL, null)
        val anonKey = prefs.getString(KEY_ANON_KEY, null)
        return if (url != null && anonKey != null) url to anonKey else null
    }

    fun isConfigured(): Boolean = load() != null

    companion object {
        private const val KEY_URL = "url"
        private const val KEY_ANON_KEY = "anon_key"
    }
}
