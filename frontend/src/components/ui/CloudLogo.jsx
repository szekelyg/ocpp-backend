// Energiafelhő "felhő" logó – három lekerekített sáv.
//
// A geometria és a színek az arculati SVG-ből valók, változatlanul. Csak a
// viewBox van rávágva a rajzra: az eredeti fájl 600×400-as vászna aszimmetrikus
// margóval veszi körbe, amitől ikonméretben félrecsúszna és apró lenne.
export default function CloudLogo({ size = 28 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="158.27 60 283.46 280"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect x="327.65" y="60" width="114.07" height="65.68" rx="32.84" ry="32.84" fill="#f7d17e" />
      <rect x="158.27" y="167.16" width="283.46" height="65.68" rx="32.84" ry="32.84" fill="#779cf8" />
      <rect x="158.27" y="274.32" width="200.49" height="65.68" rx="32.84" ry="32.84" fill="#64cba1" />
    </svg>
  );
}
