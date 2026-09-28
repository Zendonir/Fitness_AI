<script>
  import { page } from '$app/state';
</script>
<div class="flex min-h-dvh flex-col items-center justify-center px-6 text-center">
  <p class="text-5xl font-black text-accent">{page.status}</p>
  <p class="mt-2 text-muted">{page.status === 404 ? 'Seite nicht gefunden' : page.error?.message}</p>
  <a href="/" class="btn-primary mt-6">Zur Startseite</a>
</div>
