import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  kit: {
    adapter: adapter({ fallback: 'index.html', strict: false }),
    serviceWorker: { register: false },
    alias: { $components: 'src/lib/components' }
  }
};

export default config;
