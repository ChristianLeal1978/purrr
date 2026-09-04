package io.github.christianlealreyes.purrr.auth

import android.content.Context

/** Client ID de una app Spotify creada gratis en developer.spotify.com (Redirect
 * URI a registrar ahí: `purrr://spotify-callback`) — mismo patrón "traé tu propia
 * app" que Drive/RadioTunes. Sin client secret: el flujo es PKCE puro, ver
 * [SpotifyAuth]. También guarda acá los tokens de sesión (access/refresh/expiry) —
 * mismo nivel de protección que ya usa el escritorio para su `spotify_token.json`
 * (archivo/store privado de la app, sin cifrado adicional). */
class SpotifyAuthConfig(context: Context) {
    private val prefs = context.getSharedPreferences("spotify_auth_config", Context.MODE_PRIVATE)

    fun saveClientId(clientId: String) {
        prefs.edit().putString(KEY_CLIENT_ID, clientId).apply()
    }

    fun loadClientId(): String? = prefs.getString(KEY_CLIENT_ID, null)

    fun saveTokens(accessToken: String, refreshToken: String, expiresAtEpochMs: Long) {
        prefs.edit()
            .putString(KEY_ACCESS_TOKEN, accessToken)
            .putString(KEY_REFRESH_TOKEN, refreshToken)
            .putLong(KEY_EXPIRES_AT, expiresAtEpochMs)
            .apply()
    }

    fun loadAccessToken(): String? = prefs.getString(KEY_ACCESS_TOKEN, null)

    fun loadRefreshToken(): String? = prefs.getString(KEY_REFRESH_TOKEN, null)

    fun loadExpiresAt(): Long = prefs.getLong(KEY_EXPIRES_AT, 0L)

    fun isConnected(): Boolean = loadRefreshToken() != null

    companion object {
        private const val KEY_CLIENT_ID = "client_id"
        private const val KEY_ACCESS_TOKEN = "access_token"
        private const val KEY_REFRESH_TOKEN = "refresh_token"
        private const val KEY_EXPIRES_AT = "expires_at"
    }
}
