import type { PointerEvent } from 'react'

/**
 * Pointer handler for the `spotlight` utility: writes the pointer position into
 * CSS variables on the element, so the light follows the cursor without re-rendering.
 */
export function onSpotlightMove(event: PointerEvent<HTMLElement>): void {
  if (event.pointerType === 'touch') return
  const element = event.currentTarget
  const rect = element.getBoundingClientRect()
  element.style.setProperty('--spot-x', `${event.clientX - rect.left}px`)
  element.style.setProperty('--spot-y', `${event.clientY - rect.top}px`)
}
