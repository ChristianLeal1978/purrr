package io.github.christianlealreyes.purrr

import android.app.Application
import io.github.christianlealreyes.purrr.cloud.CloudSyncEngine

class PurrrApplication : Application() {
    lateinit var syncEngine: CloudSyncEngine
        private set

    override fun onCreate() {
        super.onCreate()
        syncEngine = CloudSyncEngine(this)
        // Idempotente: no hace nada todavía si Supabase no está configurado o no hay
        // sesión — se activa solo cuando la pantalla "Configurar" complete el login.
        syncEngine.start()
    }
}
