import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
)

/** Las escrituras pasan por el agente: el panel nunca tiene claves de Twilio ni service_role. */
export async function callAgent(phone: string, action: string, body: object = {}) {
  const { data } = await supabase.auth.getSession()
  const res = await fetch(
    `${import.meta.env.VITE_AGENT_URL}/crm/conversations/${encodeURIComponent(phone)}/${action}`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${data.session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
        // Sin esto, ngrok gratis devuelve su página de aviso en vez del JSON.
        'ngrok-skip-browser-warning': '1',
      },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail
    throw new Error(typeof detail === 'string' ? detail : `Error ${res.status}`)
  }
}
