package io.github.christianlealreyes.purrr.cloud

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.postgrest.Postgrest
import io.github.jan.supabase.realtime.Realtime

/** Cliente Supabase compartido — equivalente de `cloud/client.py` del escritorio.
 * URL y anon key van incrustados igual que en `purrr/config.py` del escritorio: el
 * anon key no es secreto, todo el acceso queda restringido por Row Level Security
 * (`cloud/schema.sql`) con `auth.uid()`, así que nadie tiene que pegar ni configurar
 * un backend propio.
 * A diferencia del cliente Python (que persiste la sesión a mano en un archivo,
 * ver `_persist_session`/`_restore_session`), el plugin Auth acá guarda y restaura
 * la sesión solo (SettingsSessionManager por defecto, respaldado por
 * SharedPreferences) — no hace falta reimplementar ese mecanismo. */
object SupabaseClientProvider {
    private const val SUPABASE_URL = "https://nlvajcskcnnwnhcslbcj.supabase.co"
    private const val SUPABASE_ANON_KEY =
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5sdmFqY3Nr" +
            "Y25ud25oY3NsYmNqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg0ODMyNTksImV4cCI6MjEwNDA1OTI1" +
            "OX0.PaHa_yz91J_M8Xh0Mhsr0zg1czHdpunRAmwFgKmkK-w"

    @Volatile private var client: SupabaseClient? = null

    fun get(): SupabaseClient =
        client ?: synchronized(this) {
            client ?: createSupabaseClient(supabaseUrl = SUPABASE_URL, supabaseKey = SUPABASE_ANON_KEY) {
                install(Auth)
                install(Postgrest)
                install(Realtime)
            }.also { client = it }
        }
}
