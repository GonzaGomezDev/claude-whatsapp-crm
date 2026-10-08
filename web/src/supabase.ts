import { createClient } from '@supabase/supabase-js'

declare global {
  interface Window {
    CRM_CONFIG: { supabaseUrl: string; supabaseKey: string }
  }
}

export const supabase = createClient(window.CRM_CONFIG.supabaseUrl, window.CRM_CONFIG.supabaseKey)

/**
 * Lo que necesita secretos o tiene efectos afuera pasa por el agente (Twilio, tomar/devolver/asignar,
 * alta de usuarios, resumen IA). El resto (CRUD de datos) va directo a Supabase, protegido por RLS.
 */
export async function agent<T = unknown>(path: string, body: object = {}): Promise<T> {
  const { data } = await supabase.auth.getSession()
  const res = await fetch(`/crm${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${data.session?.access_token ?? ''}`,
      'Content-Type': 'application/json',
      // Sin esto, ngrok gratis puede devolver su página de aviso en vez del JSON.
      'ngrok-skip-browser-warning': '1',
    },
    body: JSON.stringify(body),
  })
  const json = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = json?.detail
    throw new Error(typeof detail === 'string' ? detail : `Error ${res.status}`)
  }
  return json as T
}

/** Mensaje de error de una consulta de Supabase, o null. */
export function failed(result: { error: { message: string } | null }): string | null {
  return result.error ? result.error.message : null
}
