// Vite settings: Vite runs the app while you develop (with instant reloads) and bundles it for the live website.
// The two plugins add React support and Tailwind CSS. Port 5173 is fixed, because the API and Supabase are told
// to trust exactly http://localhost:5173 during development.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true },
  build: {
    rollupOptions: {
      output: {
        // Put the big libraries in their own files. They rarely change, so browsers can keep them cached
        // between updates of our own code, and the first visit downloads several smaller files in parallel.
        manualChunks: {
          react: ["react", "react-dom"],
          supabase: ["@supabase/supabase-js"],
          markdown: ["react-markdown", "remark-gfm"],
        },
      },
    },
  },
});
