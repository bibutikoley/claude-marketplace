import { defineConfig } from 'vite';

// The strict Content-Security-Policy shared by every delivery mechanism. It's
// intentionally narrow: no inline scripts, no external origins, and no network
// calls at all (`connect-src 'none'`). The page ships zero runtime fetches.
const csp = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'none'",
  "media-src 'none'",
  "object-src 'none'",
  "frame-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ');

// HTTP security headers applied by `vite preview` (and, via public/_headers, by
// Netlify-style static hosts). `frame-ancestors` (clickjacking) can only be
// enforced as an HTTP header, never from a <meta> tag, so it lives here rather
// than in the meta policy below.
const securityHeaders = {
  'Content-Security-Policy': `${csp}; frame-ancestors 'none'`,
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
};

export default defineConfig({
  // GitHub Pages project sites are served under /<repo-name>/, not from the
  // root. Set this to your exact repo name so the built asset URLs resolve.
  // (For a user site — a repo named <user>.github.io — use base: '/' instead.)
  base: '/claude-marketplace/',
  server: {
    // Bind the dev server to loopback only. The Vite dev server enables HMR, so
    // it must never be reachable over the network. Override deliberately with
    // `npm run dev -- --host 0.0.0.0` if you need LAN access for device testing.
    host: '127.0.0.1',
    strictPort: true,
  },
  preview: {
    headers: securityHeaders,
  },
  plugins: [
    {
      // Inject the CSP <meta> tag ONLY into production builds. In dev, the Vite
      // client needs an inline preamble and an HMR WebSocket, both of which a
      // strict CSP would block — so the dev server stays CSP-free and the policy
      // is delivered by the preview/host HTTP headers instead. This keeps
      // `npm run dev` working while dist/ still ships a strict CSP on hosts that
      // can't set response headers.
      name: 'inject-csp-meta',
      apply: 'build',
      transformIndexHtml() {
        return [
          {
            tag: 'meta',
            attrs: { 'http-equiv': 'Content-Security-Policy', content: csp },
            injectTo: 'head-prepend',
          },
        ];
      },
    },
  ],
});
