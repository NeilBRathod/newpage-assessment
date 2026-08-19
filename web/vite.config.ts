import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: Number(process.env.VITE_PORT ?? 5173),
    // Without this Vite quietly takes the next free port when 5173 is busy,
    // which then fails CORS against the API's allowlist — a confusing failure
    // several steps removed from its cause. Better to refuse to start.
    strictPort: true,
  },
});
