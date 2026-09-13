# Site

Landing page for the marketplace (Vite + Three.js), deployed to GitHub Pages.

## Development

```bash
cd site
npm install
npm run dev       # http://127.0.0.1:5173
npm run build     # production build → site/dist/
```

Pushes to `main` deploy `site/dist/` to GitHub Pages automatically
(Settings → Pages → Source: "GitHub Actions" on first setup).
