package io.github.christianlealreyes.purrr.cloud

import android.content.Context
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.postgrest.Postgrest
import io.github.jan.supabase.realtime.Realtime

/** Cliente Supabase compartido — equivalente de `cloud/client.py` del escritorio.
 * A diferencia del cliente Python (que persiste la sesión a mano en un archivo,
 * ver `_persist_session`/`_restore_session`), el plugin Auth acá guarda y restaura
 * la sesión solo (SettingsSessionManager por defecto, respaldado por
 * SharedPreferences) — no hace falta reimplementar ese mecanismo. */
object SupabaseClientProvider {
    @Volatile private var client: SupabaseClient? = null

    /** Null si todavía no se pegó Project URL + anon key (pantalla "Configurar"). */
    fun get(context: Context): SupabaseClient? {
        client?.let { return it }
        val (url, anonKey) = SupabaseConfig(context).load() ?: return null
        return synchronized(this) {
            client ?: createSupabaseClient(supabaseUrl = url, supabaseKey = anonKey) {
                install(Auth)
                install(Postgrest)
                install(Realtime)
            }.also { client = it }
        }
    }

    /** Forzar recrear el cliente en la próxima llamada a [get] — usar tras cambiar
     * de proyecto Supabase (nueva URL/anon key). */
    fun reset() {
        client = null
    }
}
