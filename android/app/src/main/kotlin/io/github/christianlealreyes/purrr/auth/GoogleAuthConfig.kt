package io.github.christianlealreyes.purrr.auth

import android.content.Context

/** Client ID de tipo "Web application" del mismo proyecto de Google Cloud que ya usa
 * el escritorio (Fase 0) — hace falta como `serverClientId` para Credential Manager,
 * ver `DriveAuth`. No es el client ID "Android" (ese no se pega en ningún lado, solo
 * se registra en la consola con el paquete + huella SHA-1 del APK, ver el plan). */
class GoogleAuthConfig(context: Context) {
    private val prefs = context.getSharedPreferences("google_auth_config", Context.MODE_PRIVATE)

    fun save(webClientId: String) {
        prefs.edit().putString(KEY_WEB_CLIENT_ID, webClientId).apply()
    }

    fun load(): String? = prefs.getString(KEY_WEB_CLIENT_ID, null)

    fun isConfigured(): Boolean = load() != null

    companion object {
        private const val KEY_WEB_CLIENT_ID = "web_client_id"
    }
}
