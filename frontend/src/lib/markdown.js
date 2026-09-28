// Minimaler, sicherer Markdown-Renderer für Coach-Antworten (escaped HTML zuerst).
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inline = (s) => s
  .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  .replace(/(^|[^*])\*(?!\s)(.+?)\*/g, '$1<em>$2</em>')
  .replace(/`([^`]+)`/g, '<code class="rounded bg-surface-2 px-1">$1</code>');

export function md(text = '') {
  const lines = esc(text).split('\n');
  let html = '', list = null;
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^#{1,4}\s+(.*)/))) { close(); html += `<p class="mt-2 font-bold">${inline(m[1])}</p>`; }
    else if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { if (list !== 'ul') { close(); html += '<ul class="ml-4 list-disc space-y-0.5">'; list = 'ul'; } html += `<li>${inline(m[1])}</li>`; }
    else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== 'ol') { close(); html += '<ol class="ml-4 list-decimal space-y-0.5">'; list = 'ol'; } html += `<li>${inline(m[1])}</li>`; }
    else if (!line.trim()) { close(); html += '<div class="h-2"></div>'; }
    else { close(); html += `<p>${inline(line)}</p>`; }
  }
  close();
  return html;
}
