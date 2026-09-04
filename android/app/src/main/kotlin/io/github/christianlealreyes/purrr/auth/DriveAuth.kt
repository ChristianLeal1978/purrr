package io.github.christianlealreyes.purrr.auth

import android.util.Base64
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.credentials.CredentialManager
import androidx.credentials.GetCredentialRequest
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.tasks.await
import org.json.JSONObject

private const val DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

data class DriveAuthResult(val email: String?, val accessToken: String)

/** Login de Google + autorización del scope de Drive (Fase 6.3 del plan) — Credential
 * Manager para la identidad, `AuthorizationClient` (Identity API de Google Play
 * Services) para el scope de Drive por separado, siguiendo la guía moderna que
 * reemplaza a `GoogleSignInClient` (deprecado).
 *
 * Deliberadamente SIN `requestOfflineAccess` (que devolvería un refresh token): esa
 * API está pensada para que el intercambio código→token pase por un backend propio
 * que guarde el client secret — Purrr no tiene backend, y la guía oficial de Google
 * desaconseja guardar un refresh token en el dispositivo por eso mismo. En cambio,
 * se vuelve a llamar a `authorize()` cada vez que hace falta un token: si el scope
 * ya fue concedido antes, Play Services lo devuelve solo (sin UI), renovado, desde
 * caché — mismo resultado práctico que un refresh token, sin guardar ningún secreto.
 *
 * Debe instanciarse en `onCreate` de una `ComponentActivity` (antes de que llegue a
 * STARTED) porque registra un `ActivityResultLauncher`.
 */
class DriveAuth(private val activity: ComponentActivity) {
    private val credentialManager = CredentialManager.create(activity)
    private val authorizationClient = Identity.getAuthorizationClient(activity)
    private var pendingResolution: CancellableContinuation<AuthorizationResult>? = null

    private val resolutionLauncher: ActivityResultLauncher<IntentSenderRequest> =
        activity.registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { result ->
            val continuation = pendingResolution
            pendingResolution = null
            if (continuation == null) return@registerForActivityResult
            try {
                continuation.resume(authorizationClient.getAuthorizationResultFromIntent(result.data))
            } catch (e: Exception) {
                continuation.resumeWithException(e)
            }
        }

    /** Pide login + autoriza el scope de Drive — pide consentimiento la primera vez,
     * después es silencioso. `null` si todavía no se configuró el Web client ID
     * (pantalla "Configurar", ver [GoogleAuthConfig]). */
    suspend fun connect(): DriveAuthResult? {
        val webClientId = GoogleAuthConfig(activity).load() ?: return null
        val email = signIn(webClientId)
        val accessToken = authorizeDrive()
        return DriveAuthResult(email, accessToken)
    }

    /** Igual que [connect] pero para cuando ya se conectó antes — solo renueva el
     * access token (silencioso salvo que Google haya revocado el consentimiento). */
    suspend fun refreshAccessToken(): String = authorizeDrive()

    private suspend fun signIn(webClientId: String): String? {
        val option = GetGoogleIdOption.Builder()
            .setFilterByAuthorizedAccounts(false)
            .setServerClientId(webClientId)
            .build()
        val request = GetCredentialRequest.Builder().addCredentialOption(option).build()
        val response = credentialManager.getCredential(activity, request)
        val credential = GoogleIdTokenCredential.createFrom(response.credential.data)
        return decodeEmailFromIdToken(credential.idToken)
    }

    private suspend fun authorizeDrive(): String {
        val request = AuthorizationRequest.builder()
            .setRequestedScopes(listOf(Scope(DRIVE_READONLY_SCOPE)))
            .build()
        val result = authorizationClient.authorize(request).await()
        val resolved = if (result.hasResolution()) {
            val pendingIntent = result.pendingIntent
                ?: error("Sin PendingIntent para resolver la autorización de Drive")
            suspendCancellableCoroutine { cont ->
                pendingResolution = cont
                resolutionLauncher.launch(IntentSenderRequest.Builder(pendingIntent.intentSender).build())
            }
        } else {
            result
        }
        return resolved.accessToken ?: error("Google no devolvió un access token para Drive")
    }
}

/** El ID token es un JWT — decodificamos el payload nosotros mismos (sin librería
 * extra) para leer el claim "email", sin depender de qué propiedades expone la
 * versión instalada de `GoogleIdTokenCredential`. */
private fun decodeEmailFromIdToken(idToken: String): String? {
    val parts = idToken.split(".")
    if (parts.size < 2) return null
    return try {
        val payload = Base64.decode(parts[1], Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        val json = JSONObject(String(payload, Charsets.UTF_8))
        if (json.has("email")) json.getString("email") else null
    } catch (e: Exception) {
        null
    }
}
