// tailwind.config.js
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Energiafelhő arculat – a nyomtatott matricák palettája
        ink: {
          DEFAULT: "#15233b", // sötétkék szöveg / címek
          soft: "#5b6b85",    // másodlagos szöveg
          muted: "#949eb0",   // halvány szöveg
        },
        brand: {
          blue: "#6699ff",    // felhő-kék
          green: "#04cd99",   // felhő-zöld
          yellow: "#ffcd60",  // felhő-sárga
          action: "#2f62da",  // link / CTA kék
          panel: "#eff3ff",   // világos lila-kék panel
          cream: "#fff6e0",   // krém figyelmeztető pill
          amber: "#b07a13",   // szöveg a krém pillen
          line: "#e2e8f6",    // kártya-keret
          bg: "#f5f7fc",      // oldal háttér
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(21,35,59,0.04), 0 4px 16px rgba(21,35,59,0.06)",
      },
    },
  },
  plugins: [],
};
