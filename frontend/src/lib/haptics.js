// Haptik: iOS Safari unterstützt navigator.vibrate nicht – dort bleibt es stumm, Android vibriert.
export function tap(ms = 10) {
  try { navigator.vibrate?.(ms); } catch {}
}
export function success() { tap([15, 40, 15]); }
export function alarm() { tap([200, 100, 200, 100, 400]); }
