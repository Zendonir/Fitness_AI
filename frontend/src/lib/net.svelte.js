export const net = $state({ online: typeof navigator === 'undefined' ? true : navigator.onLine, pending: 0 });
