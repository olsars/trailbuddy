export async function requestJson(url, { signal, headers, timeoutMs = 10000 } = {}) {
  const controller = new AbortController()
  let timedOut = false

  function cancel() {
    controller.abort(signal?.reason)
  }

  if (signal?.aborted) cancel()
  else signal?.addEventListener('abort', cancel, { once: true })

  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  try {
    const response = await fetch(url, { headers, signal: controller.signal })
    if (!response.ok) {
      throw new Error(`Backend request failed: ${response.status}`)
    }
    return await response.json()
  } catch (error) {
    if (timedOut && !signal?.aborted) {
      throw new Error('Backend request timed out. Check that the backend is running.', { cause: error })
    }
    throw error
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
  }
}
