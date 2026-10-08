import { createClient } from '@supabase/supabase-js'

declare global {
  interface Window {
    CRM_CONFIG: { supabaseUrl: string; supabaseKey: string }
  }
}

export const supabase = createClient(window.CRM_CONFIG.supabaseUrl, window.CRM_CONFIG.supabaseKey)

/** Las escrituras pasan por el agente: el panel nunca tiene claves de Twilio ni la secreta de Supabase. */
export async function callAgent(phone: string, action: string, body: object = {}) {
  const { data } = await supabase.auth.getSession()
  const res = await fetch(`/crm/conversations/${encodeURIComponent(phone)}/${action}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${data.session?.access_token ?? ''}`,
      'Content-Type': 'application/json',
      // Sin esto, ngrok gratis puede devolver su página de aviso en vez del JSON.
      'ngrok-skip-browser-warning': '1',
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail
    throw new Error(typeof detail === 'string' ? detail : `Error ${res.status}`)
  }
}
