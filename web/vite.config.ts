import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import thermalLab from '../thermal_lab/vite-plugin.mjs';

export default defineConfig({
  plugins: [react(), thermalLab()],
  // Relative asset paths, so the build works on GitHub Pages under /<repo>/ and from disk.
  base: './',
  // The page renders the team's markdown from ../docs.
  server: { fs: { allow: ['..'] } },
});
