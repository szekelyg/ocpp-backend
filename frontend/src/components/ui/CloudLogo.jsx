// Energiafelhő "felhő" logó – három lekerekített sáv, mint a matricán.
export default function CloudLogo({ size = 28 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect x="10" y="4" width="16" height="6" rx="3" fill="#ffcd60" />
      <rect x="4" y="13" width="22" height="6" rx="3" fill="#6699ff" />
      <rect x="9" y="22" width="13" height="6" rx="3" fill="#04cd99" />
    </svg>
  );
}
