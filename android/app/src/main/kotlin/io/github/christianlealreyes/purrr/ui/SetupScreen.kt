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
import androidx.compose.ui.unit.dp
import io.github.christianlealreyes.purrr.cloud.CloudSyncEngine
import io.github.christianlealreyes.purrr.cloud.SupabaseClientProvider
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.providers.builtin.Email
import kotlinx.coroutines.launch

/** Pantalla "Cuenta / Sync": login con la misma cuenta Purrr del escritorio (email +
 * contraseña) sobre el backend Supabase compartido, que ya viene incrustado en la
 * app — no hace falta pegar ningún dato de proyecto. */
@Composable
fun SetupScreen(syncEngine: CloudSyncEngine) {
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var loggedIn by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        loggedIn = SupabaseClientProvider.get().auth.currentSessionOrNull() != null
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Iniciar sesión")
        OutlinedTextField(value = email, onValueChange = { email = it }, label = { Text("Email") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = password, onValueChange = { password = it }, label = { Text("Contraseña") }, modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                scope.launch {
                    runCatching {
                        SupabaseClientProvider.get().auth.signInWith(Email) { this.email = email.trim(); this.password = password }
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
                        SupabaseClientProvider.get().auth.signUpWith(Email) { this.email = email.trim(); this.password = password }
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
