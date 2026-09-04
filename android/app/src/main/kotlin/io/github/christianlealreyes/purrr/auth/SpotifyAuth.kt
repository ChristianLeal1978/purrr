package io.github.christianlealreyes.purrr.auth

import android.content.Context
import android.net.Uri
import android.util.Base64
import androidx.browser.customtabs.CustomTabsIntent
import java.security.MessageDigest
import java.security.SecureRandom
import java.time.Instant
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request

private const val REDIRECT_URI = "purrr://spotify-callback"
private const val AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
private const val TOKEN_URL = "https://accounts.spotify.com/api/token"
private const val SCOPES = "user-read-playback-state user-modify-playback-state"

/** Login de Spotify vía PKCE puro (sin client secret) — implementado a mano en vez
 * de sumar `com.spotify.android:auth` (Fase 7 del plan: su forma de código actual
 * no se pudo confirmar del todo). Custom Tabs para el navegador, un intent-filter
 * de `purrr://spotify-callback` en `MainActivity` para el redirect, OkHttp para el
 * intercambio código→token — mismo endpoint que ya usa `spotipy` en el
 * escritorio, sin ningún SDK. */
class SpotifyAuth(private val context: Context) {
    private val config = SpotifyAuthConfig(context)
    private val client = OkHttpClient()
    private val json = Json { ignoreUnknownKeys = true }
    private var pendingContinuation: CancellableContinuation<String>? = null

    fun isConfigured(): Boolean = config.loadClientId() != null
    fun isConnected(): Boolean = config.isConnected()

    /** Abre Custom Tabs para el login y suspende hasta que
     * [handleRedirect] resuelva el resultado — llamar desde
     * `MainActivity.onNewIntent`. */
    suspend fun connect(): Boolean {
        val clientId = config.loadClientId() ?: return false
        val verifier = randomCodeVerifier()
        val challenge = codeChallenge(verifier)
        val code = suspendCancellableCoroutine<String> { cont ->
            pendingContinuation = cont
            CustomTabsIntent.Builder().build().launchUrl(context, buildAuthorizeUrl(clientId, challenge))
        }
        exchangeCodeForTokens(clientId, code, verifier)
        return true
    }

    /** Llamar con la `Intent.data` recibida en `onNewIntent`/`onCreate`. Devuelve
     * `true` si esta URI era el redirect de Spotify (haya tenido éxito o no). */
    fun handleRedirect(uri: Uri): Boolean {
        if (uri.scheme != "purrr" || uri.host != "spotify-callback") return false
        val continuation = pendingContinuation ?: return true
        pendingContinuation = null
        val code = uri.getQueryParameter("code")
        if (code != null) {
            continuation.resume(code)
        } else {
            val error = uri.getQueryParameter("error") ?: "login cancelado"
            continuation.resumeWithException(IllegalStateException("Spotify: $error"))
        }
        return true
    }

    /** Access token vigente — lo renueva solo si ya venció. */
    suspend fun getAccessToken(): String {
        val current = config.loadAccessToken()
        val expiresAt = config.loadExpiresAt()
        if (current != null && Instant.now().toEpochMilli() < expiresAt - 30_000) return current
        return refreshAccessToken()
    }

    private suspend fun refreshAccessToken(): String {
        val clientId = config.loadClientId() ?: error("Falta configurar el Client ID de Spotify")
        val refreshToken = config.loadRefreshToken() ?: error("No hay sesión de Spotify — conectá primero")
        val body = FormBody.Builder()
            .add("grant_type", "refresh_token")
            .add("refresh_token", refreshToken)
            .add("client_id", clientId)
            .build()
        val response = postForm(body)
        config.saveTokens(response.accessToken, response.refreshToken ?: refreshToken, expiresAtEpochMs(response.expiresIn))
        return response.accessToken
    }

    private suspend fun exchangeCodeForTokens(clientId: String, code: String, verifier: String) {
        val body = FormBody.Builder()
            .add("grant_type", "authorization_code")
            .add("code", code)
            .add("redirect_uri", REDIRECT_URI)
            .add("client_id", clientId)
            .add("code_verifier", verifier)
            .build()
        val response = postForm(body)
        val refreshToken = response.refreshToken ?: error("Spotify no devolvió un refresh_token")
        config.saveTokens(response.accessToken, refreshToken, expiresAtEpochMs(response.expiresIn))
    }

    private suspend fun postForm(body: FormBody): TokenResponse = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(TOKEN_URL).post(body).build()
        client.newCall(request).execute().use { response ->
            val text = response.body?.string()
            if (!response.isSuccessful) error("Spotify token endpoint devolvió ${response.code}: $text")
            json.decodeFromString<TokenResponse>(text ?: error("Spotify no devolvió cuerpo en la respuesta"))
        }
    }

    private fun buildAuthorizeUrl(clientId: String, challenge: String): Uri =
        Uri.parse(AUTHORIZE_URL).buildUpon()
            .appendQueryParameter("client_id", clientId)
            .appendQueryParameter("response_type", "code")
            .appendQueryParameter("redirect_uri", REDIRECT_URI)
            .appendQueryParameter("code_challenge_method", "S256")
            .appendQueryParameter("code_challenge", challenge)
            .appendQueryParameter("scope", SCOPES)
            .build()
}

private fun expiresAtEpochMs(expiresInSeconds: Long): Long = Instant.now().plusSeconds(expiresInSeconds).toEpochMilli()

private fun randomCodeVerifier(): String {
    val bytes = ByteArray(64)
    SecureRandom().nextBytes(bytes)
    return Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
}

private fun codeChallenge(verifier: String): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray(Charsets.US_ASCII))
    return Base64.encodeToString(digest, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
}

@Serializable
private data class TokenResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String? = null,
    @SerialName("expires_in") val expiresIn: Long,
)
