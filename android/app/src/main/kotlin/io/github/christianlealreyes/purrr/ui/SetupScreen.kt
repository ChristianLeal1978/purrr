package io.github.christianlealreyes.purrr.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.christianlealreyes.purrr.cloud.CloudSyncEngine
import io.github.christianlealreyes.purrr.cloud.SupabaseClientProvider
import io.github.christianlealreyes.purrr.cloud.SupabaseConfig
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.providers.builtin.Email
import kotlinx.coroutines.launch

/** Pantalla "Cuenta / Sync" (Fase 6.3 del plan): bootstrap de Supabase (Project URL +
 * anon key, una vez por dispositivo) y login con la misma cuenta Purrr del
 * escritorio (email + contraseña). */
@Composable
fun SetupScreen(syncEngine: CloudSyncEngine) {
    val context = LocalContext.current
    val config = remember { SupabaseConfig(context) }
    var url by remember { mutableStateOf("") }
    var anonKey by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var loggedIn by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        config.load()?.let { (savedUrl, savedKey) -> url = savedUrl; anonKey = savedKey }
        loggedIn = SupabaseClientProvider.get(context)?.auth?.currentSessionOrNull() != null
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("1. Proyecto Supabase")
        OutlinedTextField(value = url, onValueChange = { url = it }, label = { Text("Project URL") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = anonKey, onValueChange = { anonKey = it }, label = { Text("Anon key") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = {
            config.save(url.trim(), anonKey.trim())
            SupabaseClientProvider.reset()
            statusMessage = "Proyecto guardado."
        }) { Text("Guardar proyecto") }

        Text("2. Iniciar sesión")
        OutlinedTextField(value = email, onValueChange = { email = it }, label = { Text("Email") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = password, onValueChange = { password = it }, label = { Text("Contraseña") }, modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                scope.launch {
                    runCatching {
                        val client = SupabaseClientProvider.get(context) ?: error("Falta guardar el proyecto Supabase")
                        client.auth.signInWith(Email) { this.email = email.trim(); this.password = password }
                    }.onSuccess {
                        statusMessage = "Sesión iniciada."
                        loggedIn = true
                        syncEngine.start()
                    }.onFailure { statusMessage = "Error: ${it.message}" }
                }
            }) { Text("Iniciar sesión") }
            Button(onClick = {
                scope.launch {
                    runCatching {
                        val client = SupabaseClientProvider.get(context) ?: error("Falta guardar el proyecto Supabase")
                        client.auth.signUpWith(Email) { this.email = email.trim(); this.password = password }
                    }.onSuccess {
                        statusMessage = "Cuenta creada e iniciada."
                        loggedIn = true
                        syncEngine.start()
                    }.onFailure { statusMessage = "Error: ${it.message}" }
                }
            }) { Text("Crear cuenta") }
        }

        Text(if (loggedIn) "Estado: conectado" else "Estado: sin sesión")
        statusMessage?.let { Text(it) }
    }
}
